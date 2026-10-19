"""Schemas Pydantic V2 para API e geração de currículos via IA."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from trampo_radar.models.job import JobSource


class JobResponse(BaseModel):
    """Schema de resposta de uma vaga na API."""

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
    scraped_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ScanReportResponse(BaseModel):
    """Resultado de uma execução do pipeline de varredura."""

    email_candidates: int = 0
    linkedin_candidates: int = 0
    new_after_dedup: int = 0
    relevant_after_filter: int = 0
    notified_telegram: bool = False
    notified_email: bool = False
    jobs: list[JobResponse] = Field(default_factory=list)


class ResumeExperience(BaseModel):
    """Item de experiência retornado pela IA."""

    cargo: str = ""
    empresa: str = ""
    periodo: str = ""
    descricao: list[str] = Field(default_factory=list)


class ResumeProject(BaseModel):
    """Item de projeto retornado pela IA."""

    nome: str = ""
    link: str = ""
    descricao: str = ""


class ResumeEducation(BaseModel):
    """Item de formação retornado pela IA."""

    curso: str = ""
    instituicao: str = ""
    periodo: str = ""


class ResumeLanguage(BaseModel):
    """Item de idioma retornado pela IA."""

    idioma: str = ""
    nivel: str = ""


class GeneratedResume(BaseModel):
    """Estrutura de currículo adaptado devolvida pela IA."""

    resumo: str = ""
    habilidades: list[str] = Field(default_factory=list)
    experiencia: list[ResumeExperience] = Field(default_factory=list)
    projetos: list[ResumeProject] = Field(default_factory=list)
    formacao: list[ResumeEducation] = Field(default_factory=list)
    idiomas: list[ResumeLanguage] = Field(default_factory=list)
    observacoes: str = ""
