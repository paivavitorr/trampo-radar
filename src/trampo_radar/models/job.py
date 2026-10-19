"""Modelos de domínio para vagas e currículos."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class JobSource(StrEnum):
    """Origem da vaga capturada."""

    EMAIL = "email"
    LINKEDIN_SCRAPER = "linkedin_scraper"


@dataclass
class Job:
    """Entidade de domínio representando uma vaga de emprego."""

    id: str
    title: str
    company: str = ""
    location: str = ""
    url: str = ""
    posted_date: str = ""
    posted_at: datetime | None = None
    description: str = ""
    seniority_level: str = ""
    employment_type: str = ""
    job_function: str = ""
    industries: str = ""
    source: JobSource = JobSource.LINKEDIN_SCRAPER
    scraped_at: datetime = field(default_factory=lambda: datetime.now(UTC))
