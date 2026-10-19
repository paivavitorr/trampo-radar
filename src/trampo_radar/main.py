"""Ponto de entrada FastAPI + Scheduler diário + Bot Interativo do Telegram."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from trampo_radar.config import get_settings
from trampo_radar.dependencies import get_job_repository
from trampo_radar.exceptions import DomainError
from trampo_radar.routers import health, jobs
from trampo_radar.services.ai_resume import AIResumeService
from trampo_radar.services.email_reader import EmailReaderService
from trampo_radar.services.linkedin import LinkedInService
from trampo_radar.services.notifier import SmtpDigestService, TelegramService
from trampo_radar.services.pipeline import JobPipelineService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _scheduled_scan_job() -> None:
    """Callback executado diariamente pelo APScheduler."""
    settings = get_settings()
    yaml_cfg = settings.load_yaml_config()
    repo = get_job_repository()
    pipeline = JobPipelineService(
        settings=settings,
        yaml_cfg=yaml_cfg,
        repo=repo,
        email_reader=EmailReaderService(settings=settings, email_cfg=yaml_cfg.email),
        linkedin_service=LinkedInService(
            requests_per_second=yaml_cfg.rate_limit.requests_per_second,
            proxy_urls=yaml_cfg.proxy.urls,
            proxy_enabled=yaml_cfg.proxy.enabled,
        ),
        telegram_service=TelegramService(
            bot_token=yaml_cfg.telegram.bot_token,
            chat_id=yaml_cfg.telegram.chat_id,
        ),
        smtp_service=SmtpDigestService(
            settings=settings,
            enabled=yaml_cfg.smtp_digest.enabled,
        ),
    )
    await pipeline.run_daily_scan()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Gerencia o ciclo de vida do Scheduler diário e do Bot interativo do Telegram."""
    settings = get_settings()
    yaml_cfg = settings.load_yaml_config()
    repo = get_job_repository()

    scheduler = AsyncIOScheduler()
    if yaml_cfg.schedule.enabled:
        scheduler.add_job(
            _scheduled_scan_job,
            CronTrigger(
                hour=yaml_cfg.schedule.daily_hour,
                minute=yaml_cfg.schedule.daily_minute,
            ),
            id="daily_job_scan",
            replace_existing=True,
        )
        scheduler.start()
        logger.info(
            "Scheduler diário configurado para %02d:%02d.",
            yaml_cfg.schedule.daily_hour,
            yaml_cfg.schedule.daily_minute,
        )

    stop_event = asyncio.Event()
    bot_task: asyncio.Task[None] | None = None

    tg_service = TelegramService(
        bot_token=yaml_cfg.telegram.bot_token,
        chat_id=yaml_cfg.telegram.chat_id,
    )
    if yaml_cfg.telegram.enabled and tg_service.is_configured():
        li_service = LinkedInService(
            requests_per_second=yaml_cfg.rate_limit.requests_per_second,
            proxy_urls=yaml_cfg.proxy.urls,
            proxy_enabled=yaml_cfg.proxy.enabled,
        )
        ai_service = AIResumeService(ai_cfg=yaml_cfg.ai, profile=yaml_cfg.profile)
        bot_task = asyncio.create_task(
            tg_service.run_interactive_bot(
                stop_event=stop_event,
                repo=repo,
                linkedin_service=li_service,
                ai_service=ai_service,
                profile=yaml_cfg.profile,
            )
        )

    if yaml_cfg.schedule.run_on_startup:
        asyncio.create_task(_scheduled_scan_job())

    try:
        yield
    finally:
        stop_event.set()
        if bot_task is not None:
            bot_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await bot_task
        if scheduler.running:
            scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    """Factory da aplicação FastAPI."""
    app = FastAPI(
        title="TrampoRadar API",
        description=(
            "Caçador diário de vagas via E-mail (IMAP) + LinkedIn Scraper "
            "com filtragem inteligente, notificações Telegram/Email e adaptação de currículo em PDF via IA."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message},
        )

    app.include_router(health.router)
    app.include_router(jobs.router)
    return app


app = create_app()
