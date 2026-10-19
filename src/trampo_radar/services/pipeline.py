"""Orquestrador diário do pipeline: E-mail (IMAP) + LinkedIn -> Dedup -> Detalhes -> Filtro -> Envio."""

from __future__ import annotations

import asyncio
import logging

from trampo_radar.config import AppYamlConfig, Settings
from trampo_radar.models.job import Job
from trampo_radar.repositories.dedup import JobRepository
from trampo_radar.schemas.job import JobResponse, ScanReportResponse
from trampo_radar.services.email_reader import EmailReaderService
from trampo_radar.services.job_filter import filter_jobs
from trampo_radar.services.linkedin import LinkedInService
from trampo_radar.services.notifier import (
    SmtpDigestService,
    TelegramService,
    format_job_notification,
)

logger = logging.getLogger(__name__)


class JobPipelineService:
    """Executa o fluxo completo de coleta, deduplicação, enriquecimento, filtro e envio."""

    def __init__(
        self,
        settings: Settings,
        yaml_cfg: AppYamlConfig,
        repo: JobRepository,
        email_reader: EmailReaderService,
        linkedin_service: LinkedInService,
        telegram_service: TelegramService,
        smtp_service: SmtpDigestService,
    ) -> None:
        self._settings = settings
        self._cfg = yaml_cfg
        self._repo = repo
        self._email_reader = email_reader
        self._linkedin = linkedin_service
        self._telegram = telegram_service
        self._smtp = smtp_service

    async def run_daily_scan(self) -> ScanReportResponse:
        """Executa uma rodada completa de busca nos e-mails e no LinkedIn."""
        logger.info("Iniciando varredura de vagas (E-mail + LinkedIn)...")

        # 1) Coleta vagas do E-mail (IMAP)
        email_jobs: list[Job] = []
        if self._cfg.email.enabled:
            email_jobs = await self._email_reader.fetch_jobs_from_inbox()
            logger.info("Vagas extraídas de alertas de e-mail: %d", len(email_jobs))

        # 2) Coleta vagas via Scraper do LinkedIn
        linkedin_jobs: list[Job] = []
        if self._cfg.linkedin.enabled:
            for kw in self._cfg.linkedin.keywords:
                found = await self._linkedin.search_keyword(
                    keyword=kw,
                    location=self._cfg.linkedin.location,
                    max_results=self._cfg.linkedin.max_results,
                    post_time=self._cfg.linkedin.post_time,
                )
                logger.info("Busca LinkedIn keyword='%s': %d encontradas", kw, len(found))
                linkedin_jobs.extend(found)

        # 3) Deduplicação (prioriza vagas do e-mail + adiciona do LinkedIn)
        all_candidates = email_jobs + linkedin_jobs
        new_candidates = self._repo.filter_new(all_candidates)
        max_limit = max(self._cfg.linkedin.max_results * 2, 30)
        if len(new_candidates) > max_limit:
            new_candidates = new_candidates[:max_limit]

        logger.info("Candidatas inéditas após deduplicação: %d", len(new_candidates))

        # 4) Enriquecimento de detalhes (busca descrição completa no LinkedIn / URL)
        for job in new_candidates:
            await self._linkedin.fetch_detail(job)

        # 5) Aplica filtros de relevância
        relevant = filter_jobs(new_candidates, self._cfg.filters)
        logger.info(
            "Vagas relevantes após filtragem: %d (de %d inéditas)",
            len(relevant),
            len(new_candidates),
        )

        # Salva vagas relevantes no cache local (para API e comando /resume)
        self._repo.save_jobs(relevant)

        # 6) Notificação no Telegram
        notified_tg = False
        if self._cfg.telegram.enabled and self._telegram.is_configured():
            try:
                if not relevant:
                    await self._telegram.send_text("Nenhuma vaga nova hoje.")
                else:
                    await self._telegram.send_text(f"Encontradas {len(relevant)} vagas novas:")
                    for job in relevant:
                        msg = format_job_notification(job)
                        await self._telegram.send_html(msg)
                        self._repo.mark_seen(job.id)
                        await asyncio.sleep(1.0)
                notified_tg = True
            except Exception as exc:
                logger.error("Erro ao enviar notificações para o Telegram: %s", exc)
        else:
            # Mesmo sem Telegram configurado, marca como vistas para não repetir infinitamente
            for job in relevant:
                self._repo.mark_seen(job.id)

        # 7) Notificação via E-mail Digest (opcional)
        notified_email = False
        if self._cfg.smtp_digest.enabled and relevant:
            notified_email = await self._smtp.send_digest(relevant)

        return ScanReportResponse(
            email_candidates=len(email_jobs),
            linkedin_candidates=len(linkedin_jobs),
            new_after_dedup=len(new_candidates),
            relevant_after_filter=len(relevant),
            notified_telegram=notified_tg,
            notified_email=notified_email,
            jobs=[JobResponse.model_validate(j) for j in relevant],
        )
