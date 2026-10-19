"""Leitor e extrator de vagas a partir de alertas recebidos por E-mail (IMAP)."""

from __future__ import annotations

import asyncio
import email
import hashlib
import imaplib
import logging
import re
from datetime import UTC, datetime, timedelta
from email.header import decode_header
from email.message import Message
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

from trampo_radar.config import EmailConfig, Settings
from trampo_radar.models.job import Job, JobSource
from trampo_radar.services.linkedin import extract_linkedin_job_id

logger = logging.getLogger(__name__)

_JOB_PLATFORMS_RE = re.compile(
    r"(linkedin\.com/(?:comm/)?jobs/view/|"
    r"gupy\.io/jobs/|"
    r"gupy\.com\.br/jobs/|"
    r"indeed\.com/viewjob|"
    r"indeed\.com/rc/clk|"
    r"glassdoor\.com\.(?:br/)?job-listing|"
    r"programathor\.com\.br/jobs/|"
    r"trampos\.co/oportunidades/)",
    re.IGNORECASE,
)

_IGNORED_LINK_TEXTS = {
    "unsubscribe",
    "cancelar inscrição",
    "cancelar inscricao",
    "gerenciar alertas",
    "manage alerts",
    "ver todas as vagas",
    "see all jobs",
    "ajuda",
    "help",
    "privacidade",
    "privacy",
}


def decode_mime_words(raw: str | None) -> str:
    """Decodifica cabeçalhos MIME (Subject, From) com segurança."""
    if not raw:
        return ""
    parts = decode_header(raw)
    decoded: list[str] = []
    for content, charset in parts:
        if isinstance(content, bytes):
            enc = charset or "utf-8"
            try:
                decoded.append(content.decode(enc, errors="replace"))
            except LookupError:
                decoded.append(content.decode("utf-8", errors="replace"))
        else:
            decoded.append(str(content))
    return "".join(decoded).strip()


def extract_email_bodies(msg: Message) -> tuple[str, str]:
    """Extrai o corpo (html, plain_text) de uma mensagem MIME."""
    html_parts: list[str] = []
    text_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                continue
            payload = part.get_payload(decode=True)
            if not isinstance(payload, bytes):
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset, errors="replace")
            except LookupError:
                text = payload.decode("utf-8", errors="replace")

            if content_type == "text/html":
                html_parts.append(text)
            elif content_type == "text/plain":
                text_parts.append(text)
    else:
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_parts.append(text)
            else:
                text_parts.append(text)

    return "\n".join(html_parts), "\n".join(text_parts)


def unwrap_tracking_url(raw_url: str) -> str:
    """Desembrulha links de redirecionamento de e-mail se houver parâmetro url/u/q."""
    parsed = urlparse(raw_url)
    qs = parse_qs(parsed.query)
    for key in ("url", "u", "q", "target"):
        if key in qs and qs[key]:
            candidate = unquote(qs[key][0])
            if candidate.startswith(("http://", "https://")):
                return candidate
    return raw_url


def parse_jobs_from_email_content(
    html_body: str,
    text_body: str = "",
    subject: str = "",
    now: datetime | None = None,
) -> list[Job]:
    """Extrai vagas contidas no HTML ou texto de um e-mail de alerta de vagas."""
    ref_now = now or datetime.now(UTC)
    jobs_by_id: dict[str, Job] = {}

    if html_body:
        soup = BeautifulSoup(html_body, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            raw_href = str(a_tag.get("href", "")).strip()
            if not raw_href.startswith(("http://", "https://")):
                continue

            href = unwrap_tracking_url(raw_href)
            link_text = " ".join(a_tag.get_text(" ", strip=True).split())
            if link_text.lower() in _IGNORED_LINK_TEXTS:
                continue

            # 1) Vaga do LinkedIn dentro do e-mail
            li_id = extract_linkedin_job_id(href)
            if li_id:
                existing = jobs_by_id.get(li_id)
                company, location = _extract_card_context(a_tag, link_text)
                title = link_text or (existing.title if existing else f"Vaga LinkedIn #{li_id}")
                if existing is None or (len(title) > len(existing.title) and link_text):
                    jobs_by_id[li_id] = Job(
                        id=li_id,
                        title=title,
                        company=company or (existing.company if existing else ""),
                        location=location or (existing.location if existing else ""),
                        url=f"https://www.linkedin.com/jobs/view/{li_id}",
                        posted_date="Via E-mail",
                        posted_at=ref_now,
                        source=JobSource.EMAIL,
                        scraped_at=ref_now,
                    )
                continue

            # 2) Vaga de outras plataformas conhecidas (Gupy, Indeed, Glassdoor, etc.)
            if _JOB_PLATFORMS_RE.search(href) and len(link_text) >= 4:
                clean_url = href.split("?", 1)[0]
                ext_id = "mail_" + hashlib.sha1(clean_url.encode("utf-8")).hexdigest()[:12]
                company, location = _extract_card_context(a_tag, link_text)
                if ext_id not in jobs_by_id:
                    jobs_by_id[ext_id] = Job(
                        id=ext_id,
                        title=link_text,
                        company=company,
                        location=location,
                        url=clean_url,
                        posted_date="Via E-mail",
                        posted_at=ref_now,
                        source=JobSource.EMAIL,
                        scraped_at=ref_now,
                    )

    # 3) Fallback em texto puro se houver links diretos do LinkedIn
    if text_body:
        for match in re.finditer(r"https?://[^\s\"<>]+", text_body):
            url = unwrap_tracking_url(match.group(0))
            li_id = extract_linkedin_job_id(url)
            if li_id and li_id not in jobs_by_id:
                jobs_by_id[li_id] = Job(
                    id=li_id,
                    title=subject or f"Vaga LinkedIn #{li_id}",
                    url=f"https://www.linkedin.com/jobs/view/{li_id}",
                    posted_date="Via E-mail",
                    posted_at=ref_now,
                    source=JobSource.EMAIL,
                    scraped_at=ref_now,
                )

    return list(jobs_by_id.values())


def _extract_card_context(a_tag: object, title_text: str) -> tuple[str, str]:
    """Tenta inferir empresa e localização a partir do bloco pai da tag <a> no e-mail."""
    from bs4 import Tag

    if not isinstance(a_tag, Tag):
        return "", ""

    container = a_tag.find_parent(["td", "li", "div", "tr"])
    if not container:
        return "", ""

    lines = [
        line.strip()
        for line in container.get_text(separator="\n", strip=True).splitlines()
        if line.strip() and line.strip() != title_text
    ]
    if not lines:
        return "", ""

    # Muitas newsletters (LinkedIn/Gupy) colocam "Empresa · Localização" ou linhas separadas
    first = lines[0]
    if "·" in first:
        parts = [p.strip() for p in first.split("·", 1)]
        return parts[0], parts[1] if len(parts) > 1 else ""
    if " - " in first:
        parts = [p.strip() for p in first.split(" - ", 1)]
        return parts[0], parts[1] if len(parts) > 1 else ""

    company = first
    location = lines[1] if len(lines) > 1 else ""
    return company[:100], location[:100]


def is_job_alert_email(sender: str, subject: str, cfg: EmailConfig) -> bool:
    """Verifica se o remetente ou assunto corresponde a um alerta de vaga."""
    sender_lower = sender.lower()
    subject_lower = subject.lower()

    if any(domain.lower() in sender_lower for domain in cfg.sender_filters if domain):
        return True
    return any(kw.lower() in subject_lower for kw in cfg.subject_keywords if kw)


class EmailReaderService:
    """Serviço assíncrono para ler e-mails via IMAP e extrair vagas novas."""

    def __init__(self, settings: Settings, email_cfg: EmailConfig) -> None:
        self._settings = settings
        self._cfg = email_cfg

    def is_configured(self) -> bool:
        """Retorna True se o IMAP está habilitado e possui credenciais."""
        return bool(
            self._cfg.enabled
            and self._settings.imap_host
            and self._settings.imap_user
            and self._settings.imap_password
        )

    async def fetch_jobs_from_inbox(self) -> list[Job]:
        """Conecta ao servidor IMAP em thread separada e retorna as vagas extraídas."""
        if not self.is_configured():
            logger.info("Leitor de e-mail IMAP não configurado ou desabilitado; pulando.")
            return []

        return await asyncio.to_thread(self._sync_fetch_jobs)

    def _sync_fetch_jobs(self) -> list[Job]:
        since_date = (datetime.now(UTC) - timedelta(days=self._cfg.lookback_days)).strftime(
            "%d-%b-%Y"
        )
        criteria = (
            f'(UNSEEN SINCE "{since_date}")'
            if self._cfg.unseen_only
            else f'(SINCE "{since_date}")'
        )

        collected: dict[str, Job] = {}
        try:
            with imaplib.IMAP4_SSL(self._settings.imap_host, self._settings.imap_port) as mail:
                mail.login(self._settings.imap_user, self._settings.imap_password)
                mail.select(self._cfg.folder, readonly=True)

                status, data = mail.search(None, criteria)
                if status != "OK" or not data or not data[0]:
                    return []

                msg_ids = data[0].split()
                logger.info("E-mails encontrados na busca IMAP: %d", len(msg_ids))

                for num in msg_ids:
                    res_status, msg_data = mail.fetch(num, "(RFC822)")
                    if res_status != "OK" or not msg_data:
                        continue
                    for item in msg_data:
                        if not isinstance(item, tuple) or len(item) < 2:
                            continue
                        raw_bytes = item[1]
                        if not isinstance(raw_bytes, bytes):
                            continue
                        msg = email.message_from_bytes(raw_bytes)
                        sender = decode_mime_words(msg.get("From"))
                        subject = decode_mime_words(msg.get("Subject"))

                        if not is_job_alert_email(sender, subject, self._cfg):
                            continue

                        html_body, text_body = extract_email_bodies(msg)
                        jobs = parse_jobs_from_email_content(html_body, text_body, subject)
                        for job in jobs:
                            collected[job.id] = job
        except Exception as exc:
            logger.error("Erro ao ler caixa de entrada IMAP: %s", exc)

        return list(collected.values())
