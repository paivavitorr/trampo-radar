"""Serviço de filtragem de relevância de vagas."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from trampo_radar.config import FilterConfig
from trampo_radar.models.job import Job


def filter_jobs(jobs: list[Job], cfg: FilterConfig, now: datetime | None = None) -> list[Job]:
    """Filtra a lista de vagas mantendo apenas as que atendem todos os critérios."""
    ref_now = now or datetime.now(UTC)
    return [job for job in jobs if should_keep_job(job, cfg, ref_now)]


def should_keep_job(job: Job, cfg: FilterConfig, now: datetime | None = None) -> bool:
    """Verifica se uma única vaga passa em todos os filtros configurados."""
    ref_now = now or datetime.now(UTC)
    title_lower = job.title.lower()
    desc_lower = job.description.lower()
    company_lower = job.company.lower()
    location_lower = job.location.lower()
    combined = f"{title_lower} {desc_lower}"

    for kw in cfg.exclude_keywords:
        if kw and kw.lower() in combined:
            return False

    for comp in cfg.exclude_companies:
        if comp and comp.lower() in company_lower:
            return False

    for loc in cfg.exclude_locations:
        if loc and loc.lower() in location_lower:
            return False

    if cfg.include_companies:
        matched_comp = any(comp.lower() in company_lower for comp in cfg.include_companies if comp)
        if not matched_comp:
            return False

    if cfg.include_locations:
        matched_loc = any(loc.lower() in location_lower for loc in cfg.include_locations if loc)
        if not matched_loc:
            return False

    if cfg.min_description_length > 0 and len(job.description) < cfg.min_description_length:
        return False

    if cfg.max_job_age_days > 0 and job.posted_at is not None:
        posted_utc = (
            job.posted_at
            if job.posted_at.tzinfo is not None
            else job.posted_at.replace(tzinfo=UTC)
        )
        age_days = int((ref_now - posted_utc).total_seconds() // 86400)
        if age_days > cfg.max_job_age_days:
            return False

    for pattern in cfg.include_keywords:
        if not pattern:
            continue
        if _is_regex(pattern):
            raw_regex = pattern[1:-1]
            try:
                if not re.search(raw_regex, combined, flags=re.IGNORECASE):
                    return False
            except re.error:
                continue
        elif pattern.lower() not in combined:
            return False

    return True


def _is_regex(pattern: str) -> bool:
    return len(pattern) >= 2 and pattern.startswith("/") and pattern.endswith("/")
