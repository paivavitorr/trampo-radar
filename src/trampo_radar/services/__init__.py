"""Exportação dos serviços da aplicação."""

from __future__ import annotations

from trampo_radar.services.ai_resume import AIResumeService
from trampo_radar.services.email_reader import EmailReaderService
from trampo_radar.services.job_filter import filter_jobs, should_keep_job
from trampo_radar.services.linkedin import LinkedInService
from trampo_radar.services.notifier import SmtpDigestService, TelegramService
from trampo_radar.services.pdf_renderer import render_resume_pdf
from trampo_radar.services.pipeline import JobPipelineService

__all__ = [
    "AIResumeService",
    "EmailReaderService",
    "JobPipelineService",
    "LinkedInService",
    "SmtpDigestService",
    "TelegramService",
    "filter_jobs",
    "render_resume_pdf",
    "should_keep_job",
]
