"""Rota de healthcheck e status da configuração."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from trampo_radar.config import AppYamlConfig
from trampo_radar.dependencies import (
    get_ai_resume_service,
    get_email_reader_service,
    get_telegram_service,
    get_yaml_config,
)
from trampo_radar.services.ai_resume import AIResumeService
from trampo_radar.services.email_reader import EmailReaderService
from trampo_radar.services.notifier import TelegramService

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    email_imap_configured: bool
    linkedin_scraper_enabled: bool
    telegram_configured: bool
    ai_configured: bool
    daily_schedule: str


@router.get("/health", response_model=HealthResponse)
async def health_check(
    yaml_cfg: AppYamlConfig = Depends(get_yaml_config),
    email_reader: EmailReaderService = Depends(get_email_reader_service),
    telegram_service: TelegramService = Depends(get_telegram_service),
    ai_service: AIResumeService = Depends(get_ai_resume_service),
) -> HealthResponse:
    """Retorna o status operacional do serviço e das integrações."""
    sched = f"{yaml_cfg.schedule.daily_hour:02d}:{yaml_cfg.schedule.daily_minute:02d}"
    return HealthResponse(
        status="ok",
        email_imap_configured=email_reader.is_configured(),
        linkedin_scraper_enabled=yaml_cfg.linkedin.enabled,
        telegram_configured=telegram_service.is_configured(),
        ai_configured=ai_service.is_configured(),
        daily_schedule=sched if yaml_cfg.schedule.enabled else "disabled",
    )
