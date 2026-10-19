"""Notificadores (Telegram HTML + Bot Interativo /resume + Digest SMTP por E-mail)."""

from __future__ import annotations

import asyncio
import html
import logging
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import httpx

from trampo_radar.config import ProfileConfig, Settings
from trampo_radar.models.job import Job, JobSource
from trampo_radar.repositories.dedup import JobRepository
from trampo_radar.services.ai_resume import AIResumeService
from trampo_radar.services.linkedin import LinkedInService, extract_linkedin_job_id
from trampo_radar.services.pdf_renderer import render_resume_pdf

logger = logging.getLogger(__name__)

_RE_JOB_ID_TAG = re.compile(r"\[ID:\s*([A-Za-z0-9_]+)\]")


def format_job_notification(job: Job) -> str:
    """Formata uma vaga em HTML para envio no Telegram."""
    lines: list[str] = []
    source_badge = "📧 E-mail" if job.source == JobSource.EMAIL else "🔎 LinkedIn"

    lines.append(f"<b>💼 {html.escape(job.title)}</b>")
    if job.company:
        lines.append(f"🏢 <b>{html.escape(job.company)}</b>")

    loc_parts = [p for p in (job.location, job.posted_date, source_badge) if p]
    if loc_parts:
        lines.append("📍 " + " • ".join(html.escape(p) for p in loc_parts))

    meta = [p for p in (job.seniority_level, job.employment_type) if p]
    if meta:
        lines.append(f"📊 <i>{html.escape(' | '.join(meta))}</i>")

    if job.description:
        desc = job.description[:400] + ("..." if len(job.description) > 400 else "")
        lines.append(f"\n{html.escape(desc)}")

    if job.url:
        lines.append(f'\n🔗 <a href="{html.escape(job.url, quote=True)}">Ver vaga</a>')

    lines.append(f"<code>[ID: {html.escape(job.id)}]</code>")
    return "\n".join(lines)


def extract_job_id_from_telegram_message(msg: dict[str, Any]) -> str:
    """Extrai o ID da vaga a partir da mensagem respondida no Telegram."""
    if not msg:
        return ""

    text = str(msg.get("text", ""))
    # 1) Procura tag explícita [ID: xxx] (suporta tanto LinkedIn quanto Gupy/Indeed do e-mail)
    tag_match = _RE_JOB_ID_TAG.search(text)
    if tag_match:
        return tag_match.group(1)

    # 2) Entidades text_link ou url
    entities = msg.get("entities", [])
    if isinstance(entities, list):
        for ent in entities:
            if not isinstance(ent, dict):
                continue
            if ent.get("type") == "text_link" and ent.get("url"):
                job_id = extract_linkedin_job_id(str(ent["url"]))
                if job_id:
                    return job_id
            if ent.get("type") == "url":
                offset = int(ent.get("offset", 0))
                length = int(ent.get("length", 0))
                if offset >= 0 and length > 0 and offset + length <= len(text):
                    job_id = extract_linkedin_job_id(text[offset : offset + length])
                    if job_id:
                        return job_id

    # 3) Fallback regex no texto
    return extract_linkedin_job_id(text)


class TelegramService:
    """Cliente da API de Bot do Telegram e loop interativo para o comando /resume."""

    def __init__(self, bot_token: str, chat_id: int) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._offset = 0

    def is_configured(self) -> bool:
        return bool(self._token and self._chat_id != 0)

    @property
    def chat_id(self) -> int:
        return self._chat_id

    async def send_text(self, text: str, reply_to: int = 0) -> None:
        await self._send_message(text=text, parse_mode="", reply_to=reply_to)

    async def send_html(self, text: str, reply_to: int = 0) -> None:
        await self._send_message(text=text, parse_mode="HTML", reply_to=reply_to)

    async def _send_message(self, text: str, parse_mode: str, reply_to: int) -> None:
        endpoint = f"https://api.telegram.org/bot{self._token}/sendMessage"
        data: dict[str, Any] = {
            "chat_id": str(self._chat_id),
            "text": text,
        }
        if parse_mode:
            data["parse_mode"] = parse_mode
        if reply_to:
            data["reply_to_message_id"] = str(reply_to)

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(endpoint, data=data)
            resp.raise_for_status()

    async def send_chat_action(self, action: str = "upload_document") -> None:
        endpoint = f"https://api.telegram.org/bot{self._token}/sendChatAction"
        data = {"chat_id": str(self._chat_id), "action": action}
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(endpoint, data=data)

    async def send_document(self, filename: str, content: bytes, caption: str = "") -> None:
        endpoint = f"https://api.telegram.org/bot{self._token}/sendDocument"
        data = {"chat_id": str(self._chat_id)}
        if caption:
            data["caption"] = caption
        files = {"document": (filename, content, "application/pdf")}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(endpoint, data=data, files=files)
            resp.raise_for_status()

    async def get_updates(self, timeout: int = 30) -> list[dict[str, Any]]:
        endpoint = f"https://api.telegram.org/bot{self._token}/getUpdates"
        params = {"offset": self._offset, "timeout": timeout}
        async with httpx.AsyncClient(timeout=float(timeout + 15)) as client:
            resp = await client.get(endpoint, params=params)
            resp.raise_for_status()
            payload = resp.json()
            if not payload.get("ok"):
                return []
            result = payload.get("result", [])
            return result if isinstance(result, list) else []

    async def run_interactive_bot(
        self,
        stop_event: asyncio.Event,
        repo: JobRepository,
        linkedin_service: LinkedInService,
        ai_service: AIResumeService,
        profile: ProfileConfig,
    ) -> None:
        """Loop de long-polling que escuta o comando /resume em reply a uma vaga."""
        if not self.is_configured():
            return

        logger.info("Bot interativo do Telegram ativo (responda uma vaga com /resume).")
        while not stop_event.is_set():
            try:
                updates = await self.get_updates(timeout=25)
                for upd in updates:
                    upd_id = int(upd.get("update_id", 0))
                    if upd_id < self._offset:
                        continue
                    self._offset = upd_id + 1
                    await self._handle_update(upd, repo, linkedin_service, ai_service, profile)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Erro no long-polling do Telegram: %s", exc)
                await asyncio.sleep(5.0)

    async def _handle_update(
        self,
        upd: dict[str, Any],
        repo: JobRepository,
        linkedin_service: LinkedInService,
        ai_service: AIResumeService,
        profile: ProfileConfig,
    ) -> None:
        msg = upd.get("message")
        if not isinstance(msg, dict):
            return
        chat = msg.get("chat", {})
        if not isinstance(chat, dict) or int(chat.get("id", 0)) != self._chat_id:
            return

        text = str(msg.get("text", "")).strip().lower()
        if not (text == "/resume" or text.startswith("/resume ")):
            return

        msg_id = int(msg.get("message_id", 0))
        reply_to = msg.get("reply_to_message")
        if not isinstance(reply_to, dict):
            await self.send_text(
                "Use /resume como resposta (reply) a uma vaga para gerar o currículo dela.",
                reply_to=msg_id,
            )
            return

        job_id = extract_job_id_from_telegram_message(reply_to)
        if not job_id:
            await self.send_text(
                "Não encontrei o ID da vaga na mensagem respondida. Responda a uma notificação de vaga.",
                reply_to=msg_id,
            )
            return

        if not ai_service.is_configured():
            await self.send_text(
                "A IA não está configurada. Defina AI_API_KEY no .env e ai.enable=true no config.yaml.",
                reply_to=msg_id,
            )
            return

        await self.send_chat_action("upload_document")
        await self.send_text(
            f"Gerando currículo adaptado para a vaga ({job_id})...", reply_to=msg_id
        )

        job = repo.get_job(job_id) or Job(id=job_id, title=f"Vaga {job_id}")
        if not job.description:
            await linkedin_service.fetch_detail(job)
            repo.save_job(job)

        try:
            resumes = await ai_service.generate_resumes([job])
            resume = resumes[job.id]
            pdf_bytes = render_resume_pdf(profile, resume)
            await self.send_document(
                filename=f"curriculo_{job.id}.pdf",
                content=pdf_bytes,
                caption=f"Currículo adaptado para: {job.title}",
            )
        except Exception as exc:
            logger.error("Erro ao gerar currículo para vaga %s: %s", job_id, exc)
            await self.send_text(f"Erro ao gerar currículo: {exc}", reply_to=msg_id)


class SmtpDigestService:
    """Envia um resumo diário (Digest) em HTML por e-mail via SMTP."""

    def __init__(self, settings: Settings, enabled: bool = False) -> None:
        self._settings = settings
        self._enabled = enabled

    def is_configured(self) -> bool:
        return bool(
            self._enabled
            and self._settings.smtp_host
            and self._settings.smtp_user
            and self._settings.smtp_password
            and (self._settings.smtp_to or self._settings.smtp_user)
        )

    async def send_digest(self, jobs: list[Job]) -> bool:
        if not self.is_configured() or not jobs:
            return False
        return await asyncio.to_thread(self._sync_send_digest, jobs)

    def _sync_send_digest(self, jobs: list[Job]) -> bool:
        recipient = self._settings.smtp_to or self._settings.smtp_user
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"💼 TrampoRadar: {len(jobs)} novas vagas encontradas hoje"
        msg["From"] = self._settings.smtp_user
        msg["To"] = recipient

        cards_html: list[str] = []
        for job in jobs:
            badge = "E-mail" if job.source == JobSource.EMAIL else "LinkedIn"
            desc = html.escape(
                job.description[:350] + "..." if len(job.description) > 350 else job.description
            )
            cards_html.append(
                f"""
                <div style="border:1px solid #e2e8f0;border-radius:8px;padding:16px;margin-bottom:14px;font-family:sans-serif;">
                    <h3 style="margin:0 0 6px 0;color:#1e293b;">{html.escape(job.title)}</h3>
                    <p style="margin:0 0 6px 0;color:#475569;">
                        <strong>{html.escape(job.company or "Empresa não informada")}</strong>
                        • {html.escape(job.location or "Remoto/Não informado")}
                        • <span style="color:#2563eb;">[{badge}]</span>
                    </p>
                    <p style="font-size:13px;color:#334155;line-height:1.4;">{desc}</p>
                    <a href="{html.escape(job.url, quote=True)}" style="color:#2563eb;font-weight:bold;text-decoration:none;">
                        Ver vaga →
                    </a>
                </div>
                """
            )

        body_html = f"""
        <html>
            <body style="max-width:680px;margin:0 auto;padding:20px;">
                <h2 style="font-family:sans-serif;color:#0f172a;">Resumo Diário de Vagas ({len(jobs)})</h2>
                {"".join(cards_html)}
            </body>
        </html>
        """
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        try:
            with smtplib.SMTP(
                self._settings.smtp_host, self._settings.smtp_port, timeout=30
            ) as server:
                server.starttls()
                server.login(self._settings.smtp_user, self._settings.smtp_password)
                server.sendmail(self._settings.smtp_user, [recipient], msg.as_string())
            return True
        except Exception as exc:
            logger.error("Falha ao enviar digest SMTP: %s", exc)
            return False
