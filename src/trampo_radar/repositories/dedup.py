"""Repositório de deduplicação (seen.json) e cache local de vagas."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from trampo_radar.models.job import Job, JobSource


class JobRepository:
    """Gerencia deduplicação (seen.json) e histórico local de vagas."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._seen_file = data_dir / "seen.json"
        self._cache_file = data_dir / "jobs_cache.json"
        self._lock = threading.Lock()
        self._seen: dict[str, bool] = {}
        self._jobs: dict[str, Job] = {}
        self._ensure_dir()
        self._load()

    def _ensure_dir(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        if self._seen_file.exists():
            try:
                raw = json.loads(self._seen_file.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._seen = {str(k): bool(v) for k, v in raw.items()}
            except (OSError, json.JSONDecodeError):
                self._seen = {}

        if self._cache_file.exists():
            try:
                raw_jobs = json.loads(self._cache_file.read_text(encoding="utf-8"))
                if isinstance(raw_jobs, dict):
                    for job_id, payload in raw_jobs.items():
                        if isinstance(payload, dict):
                            self._jobs[str(job_id)] = self._dict_to_job(payload)
            except (OSError, json.JSONDecodeError):
                self._jobs = {}

    def _save_seen(self) -> None:
        self._ensure_dir()
        content = json.dumps(self._seen, indent=2, ensure_ascii=False)
        self._seen_file.write_text(content, encoding="utf-8")

    def _save_cache(self) -> None:
        self._ensure_dir()
        serializable = {jid: self._job_to_dict(job) for jid, job in self._jobs.items()}
        content = json.dumps(serializable, indent=2, ensure_ascii=False)
        self._cache_file.write_text(content, encoding="utf-8")

    @staticmethod
    def _job_to_dict(job: Job) -> dict[str, Any]:
        data = asdict(job)
        data["source"] = job.source.value
        data["posted_at"] = job.posted_at.isoformat() if job.posted_at else None
        data["scraped_at"] = job.scraped_at.isoformat()
        return data

    @staticmethod
    def _dict_to_job(data: dict[str, Any]) -> Job:
        posted_at_raw = data.get("posted_at")
        posted_at = datetime.fromisoformat(posted_at_raw) if posted_at_raw else None
        scraped_at_raw = data.get("scraped_at")
        scraped_at = (
            datetime.fromisoformat(scraped_at_raw)
            if scraped_at_raw
            else datetime.now().astimezone()
        )
        source_raw = data.get("source", JobSource.LINKEDIN_SCRAPER.value)
        try:
            source = JobSource(source_raw)
        except ValueError:
            source = JobSource.LINKEDIN_SCRAPER

        return Job(
            id=str(data.get("id", "")),
            title=str(data.get("title", "")),
            company=str(data.get("company", "")),
            location=str(data.get("location", "")),
            url=str(data.get("url", "")),
            posted_date=str(data.get("posted_date", "")),
            posted_at=posted_at,
            description=str(data.get("description", "")),
            seniority_level=str(data.get("seniority_level", "")),
            employment_type=str(data.get("employment_type", "")),
            job_function=str(data.get("job_function", "")),
            industries=str(data.get("industries", "")),
            source=source,
            scraped_at=scraped_at,
        )

    def is_seen(self, job_id: str) -> bool:
        """Verifica se uma vaga já foi processada."""
        with self._lock:
            return self._seen.get(job_id, False)

    def mark_seen(self, job_id: str) -> None:
        """Marca uma vaga como vista e persiste em seen.json."""
        with self._lock:
            self._seen[job_id] = True
            self._save_seen()

    def filter_new(self, jobs: list[Job]) -> list[Job]:
        """Retorna apenas vagas inéditas (também deduplicando o próprio lote)."""
        seen_in_batch: set[str] = set()
        new_jobs: list[Job] = []
        with self._lock:
            for job in jobs:
                if not job.id or job.id in seen_in_batch:
                    continue
                if not self._seen.get(job.id, False):
                    seen_in_batch.add(job.id)
                    new_jobs.append(job)
        return new_jobs

    def save_job(self, job: Job) -> None:
        """Salva ou atualiza os detalhes da vaga no cache local."""
        with self._lock:
            self._jobs[job.id] = job
            self._save_cache()

    def save_jobs(self, jobs: list[Job]) -> None:
        """Salva um lote de vagas no cache local."""
        with self._lock:
            for job in jobs:
                if job.id:
                    self._jobs[job.id] = job
            self._save_cache()

    def get_job(self, job_id: str) -> Job | None:
        """Busca uma vaga pelo ID no cache local."""
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 100) -> list[Job]:
        """Lista as vagas salvas ordenadas da mais recente para a mais antiga."""
        with self._lock:
            items = list(self._jobs.values())
        items.sort(key=lambda j: j.scraped_at, reverse=True)
        return items[:limit]
