"""Injeção de dependências compartilhadas para rotas FastAPI."""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends

from trampo_radar.config import AppYamlConfig, Settings, get_settings
from trampo_radar.repositories.dedup import JobRepository
from trampo_radar.services.ai_resume import AIResumeService
from trampo_radar.services.email_reader import EmailReaderService
from trampo_radar.services.linkedin import LinkedInService
from trampo_radar.services.notifier import SmtpDigestService, TelegramService
from trampo_radar.services.pipeline import JobPipelineService


@lru_cache
def get_job_repository() -> JobRepository:
    """Instância singleton do repositório de deduplicação e cache de vagas."""
    settings = get_settings()
    return JobRepository(settings.data_dir)


def get_yaml_config(settings: Settings = Depends(get_settings)) -> AppYamlConfig:
    """Carrega a configuração atualizada do arquivo config.yaml."""
    return settings.load_yaml_config()


def get_linkedin_service(
    yaml_cfg: AppYamlConfig = Depends(get_yaml_config),
) -> LinkedInService:
    return LinkedInService(
        requests_per_second=yaml_cfg.rate_limit.requests_per_second,
        proxy_urls=yaml_cfg.proxy.urls,
        proxy_enabled=yaml_cfg.proxy.enabled,
    )


def get_email_reader_service(
    settings: Settings = Depends(get_settings),
    yaml_cfg: AppYamlConfig = Depends(get_yaml_config),
) -> EmailReaderService:
    return EmailReaderService(settings=settings, email_cfg=yaml_cfg.email)


def get_ai_resume_service(
    yaml_cfg: AppYamlConfig = Depends(get_yaml_config),
) -> AIResumeService:
    return AIResumeService(ai_cfg=yaml_cfg.ai, profile=yaml_cfg.profile)


def get_telegram_service(
    yaml_cfg: AppYamlConfig = Depends(get_yaml_config),
) -> TelegramService:
    return TelegramService(
        bot_token=yaml_cfg.telegram.bot_token,
        chat_id=yaml_cfg.telegram.chat_id,
    )


def get_smtp_service(
    settings: Settings = Depends(get_settings),
    yaml_cfg: AppYamlConfig = Depends(get_yaml_config),
) -> SmtpDigestService:
    return SmtpDigestService(
        settings=settings,
        enabled=yaml_cfg.smtp_digest.enabled,
    )


def get_pipeline_service(
    settings: Settings = Depends(get_settings),
    yaml_cfg: AppYamlConfig = Depends(get_yaml_config),
    repo: JobRepository = Depends(get_job_repository),
    email_reader: EmailReaderService = Depends(get_email_reader_service),
    linkedin_service: LinkedInService = Depends(get_linkedin_service),
    telegram_service: TelegramService = Depends(get_telegram_service),
    smtp_service: SmtpDigestService = Depends(get_smtp_service),
) -> JobPipelineService:
    return JobPipelineService(
        settings=settings,
        yaml_cfg=yaml_cfg,
        repo=repo,
        email_reader=email_reader,
        linkedin_service=linkedin_service,
        telegram_service=telegram_service,
        smtp_service=smtp_service,
    )
