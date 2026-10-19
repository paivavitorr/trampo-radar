"""Rotas para listagem de vagas, disparo de varredura manual e geração de currículo em PDF."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from trampo_radar.config import AppYamlConfig
from trampo_radar.dependencies import (
    get_ai_resume_service,
    get_job_repository,
    get_linkedin_service,
    get_pipeline_service,
    get_yaml_config,
)
from trampo_radar.exceptions import NotFoundError
from trampo_radar.models.job import Job
from trampo_radar.repositories.dedup import JobRepository
from trampo_radar.schemas.job import JobResponse, ScanReportResponse
from trampo_radar.services.ai_resume import AIResumeService
from trampo_radar.services.linkedin import LinkedInService
from trampo_radar.services.pdf_renderer import render_resume_pdf
from trampo_radar.services.pipeline import JobPipelineService

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    repo: JobRepository = Depends(get_job_repository),
) -> list[JobResponse]:
    """Lista as vagas relevantes salvas no cache local."""
    jobs = repo.list_jobs(limit=limit)
    return [JobResponse.model_validate(j) for j in jobs]


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_detail(
    job_id: str,
    repo: JobRepository = Depends(get_job_repository),
) -> JobResponse:
    """Busca uma vaga específica pelo ID."""
    job = repo.get_job(job_id)
    if not job:
        raise NotFoundError(f"Vaga {job_id} não encontrada no cache.")
    return JobResponse.model_validate(job)


@router.post("/scan", response_model=ScanReportResponse)
async def trigger_scan(
    pipeline: JobPipelineService = Depends(get_pipeline_service),
) -> ScanReportResponse:
    """Dispara imediatamente a varredura de E-mail (IMAP) + LinkedIn e envia notificações."""
    return await pipeline.run_daily_scan()


@router.post("/{job_id}/resume")
async def generate_job_resume_pdf(
    job_id: str,
    repo: JobRepository = Depends(get_job_repository),
    linkedin_service: LinkedInService = Depends(get_linkedin_service),
    ai_service: AIResumeService = Depends(get_ai_resume_service),
    yaml_cfg: AppYamlConfig = Depends(get_yaml_config),
) -> Response:
    """Adapta o currículo do perfil para a vaga via IA e retorna o arquivo PDF."""
    job = repo.get_job(job_id)
    if job is None:
        if not job_id.isdigit():
            raise NotFoundError(f"Vaga {job_id} não encontrada.")
        job = Job(id=job_id, title=f"Vaga {job_id}")

    if not job.description:
        await linkedin_service.fetch_detail(job)
        repo.save_job(job)

    resumes = await ai_service.generate_resumes([job])
    resume = resumes[job.id]
    pdf_bytes = render_resume_pdf(yaml_cfg.profile, resume)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="curriculo_{job.id}.pdf"',
        },
    )
