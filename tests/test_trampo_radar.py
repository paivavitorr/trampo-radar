"""Testes unitários e de integração: filtros, LinkedIn, e-mail, IA, PDF, pipeline e API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from trampo_radar.config import (
    AIConfig,
    AppYamlConfig,
    ContactConfig,
    EmailConfig,
    FilterConfig,
    ProfileConfig,
    Settings,
)
from trampo_radar.dependencies import (
    get_ai_resume_service,
    get_job_repository,
    get_linkedin_service,
    get_pipeline_service,
    get_yaml_config,
)
from trampo_radar.main import create_app
from trampo_radar.models.job import Job, JobSource
from trampo_radar.repositories.dedup import JobRepository
from trampo_radar.schemas.job import (
    GeneratedResume,
    ResumeEducation,
    ResumeExperience,
    ResumeLanguage,
    ResumeProject,
)
from trampo_radar.services.ai_resume import (
    AIResumeService,
    _clean_json_fence,
    build_messages,
    truncate_text,
)
from trampo_radar.services.email_reader import (
    EmailReaderService,
    decode_mime_words,
    extract_email_bodies,
    is_job_alert_email,
    parse_jobs_from_email_content,
    unwrap_tracking_url,
)
from trampo_radar.services.job_filter import filter_jobs, should_keep_job
from trampo_radar.services.linkedin import (
    LinkedInService,
    extract_linkedin_job_id,
    parse_job_detail_html,
    parse_jobs_html,
    parse_posted_date,
    post_time_to_ftpr,
)
from trampo_radar.services.notifier import (
    SmtpDigestService,
    TelegramService,
    extract_job_id_from_telegram_message,
    format_job_notification,
)
from trampo_radar.services.pdf_renderer import render_resume_pdf
from trampo_radar.services.pipeline import JobPipelineService


def test_filter_jobs_keywords_and_regex() -> None:
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    jobs = [
        Job(
            id="1",
            title="Backend Python Pleno",
            company="TechCorp",
            location="Remote, Brazil",
            description="Desenvolvimento com FastAPI, PostgreSQL e Docker.",
            posted_at=now - timedelta(days=1),
        ),
        Job(
            id="2",
            title="Senior Java Architect",
            company="BigBank",
            location="São Paulo",
            description="Spring Boot e microserviços.",
            posted_at=now - timedelta(days=1),
        ),
        Job(
            id="3",
            title="Python Developer",
            company="SpamCompany",
            location="Remote",
            description="FastAPI e Django.",
            posted_at=now - timedelta(days=10),
        ),
    ]

    cfg = FilterConfig(
        include_keywords=["python", r"/\b(fastapi|django)\b/"],
        exclude_keywords=["java"],
        exclude_companies=["SpamCompany"],
        include_locations=["Remote"],
        min_description_length=10,
        max_job_age_days=5,
    )

    filtered = filter_jobs(jobs, cfg, now=now)
    assert len(filtered) == 1
    assert filtered[0].id == "1"


def test_should_keep_job_age_and_company_filters() -> None:
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    old_job = Job(
        id="99",
        title="Rust Developer",
        company="GoodCo",
        location="Brazil",
        description="Axum e Tokio",
        posted_at=now - timedelta(days=10),
    )
    cfg = FilterConfig(include_companies=["GoodCo"], max_job_age_days=3)
    assert not should_keep_job(old_job, cfg, now=now)
    assert not should_keep_job(old_job, FilterConfig(exclude_locations=["Brazil"]), now=now)
    assert not should_keep_job(old_job, FilterConfig(min_description_length=500), now=now)


def test_linkedin_id_and_date_parsing() -> None:
    assert (
        extract_linkedin_job_id(
            "https://www.linkedin.com/jobs/view/python-developer-at-acme-4464493957?trk=123"
        )
        == "4464493957"
    )
    assert (
        extract_linkedin_job_id("https://www.linkedin.com/comm/jobs/view/4371654421/")
        == "4371654421"
    )
    assert extract_linkedin_job_id("") == ""
    assert post_time_to_ftpr("day") == "r86400"
    assert post_time_to_ftpr("week") == "r604800"
    assert post_time_to_ftpr("month") == "r2592000"
    assert post_time_to_ftpr("invalid") == ""

    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    assert parse_posted_date("2026-10-15", now) == datetime(2026, 10, 15, 0, 0, tzinfo=UTC)
    assert parse_posted_date("3 days ago", now) == now - timedelta(days=3)
    assert parse_posted_date("2 weeks ago", now) == now - timedelta(weeks=2)
    assert parse_posted_date("1 month ago", now) == now - timedelta(days=30)
    assert parse_posted_date("1 year ago", now) == now - timedelta(days=365)
    assert parse_posted_date("hoje", now) == now
    assert parse_posted_date("ontem", now) == now - timedelta(days=1)
    assert parse_posted_date("", now) is None


def test_parse_linkedin_search_and_detail_html() -> None:
    search_html = """
    <ul>
      <li data-entity-urn="urn:li:jobPosting:4123456789">
        <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/rust-dev-4123456789?refId=abc"></a>
        <h3 class="base-search-card__title">Rust Backend Engineer</h3>
        <h4 class="base-search-card__subtitle">Ferris Labs</h4>
        <span class="job-search-card__location">Brazil (Remote)</span>
        <time class="job-search-card__listdate" datetime="2026-10-18">1 day ago</time>
      </li>
    </ul>
    """
    jobs = parse_jobs_html(search_html)
    assert len(jobs) == 1
    assert jobs[0].id == "4123456789"
    assert jobs[0].title == "Rust Backend Engineer"
    assert jobs[0].company == "Ferris Labs"

    fallback_html = """
    <div>
      <a href="https://www.linkedin.com/jobs/view/555111222"><h3>Fallback Engineer</h3></a>
    </div>
    """
    fb_jobs = parse_jobs_html(fallback_html)
    assert len(fb_jobs) == 1
    assert fb_jobs[0].id == "555111222"

    detail_html = """
    <h1 class="top-card-layout__title">Rust Engineer</h1>
    <a class="topcard__org-name-link">Ferris</a>
    <span class="topcard__flavor--bullet">Remote</span>
    <div class="description__text--rich">Experiência com Rust, Axum, Tokio e SQLx.</div>
    <ul>
      <li class="description__job-criteria-item">
        <h3 class="description__job-criteria-subheader">Seniority level</h3>
        <span class="description__job-criteria-text">Mid-Senior level</span>
      </li>
      <li class="description__job-criteria-item">
        <h3 class="description__job-criteria-subheader">Employment type</h3>
        <span class="description__job-criteria-text">Full-time</span>
      </li>
      <li class="description__job-criteria-item">
        <h3 class="description__job-criteria-subheader">Job function</h3>
        <span class="description__job-criteria-text">Engineering</span>
      </li>
      <li class="description__job-criteria-item">
        <h3 class="description__job-criteria-subheader">Industries</h3>
        <span class="description__job-criteria-text">Software</span>
      </li>
    </ul>
    """
    empty_job = Job(id="4123456789", title="")
    parse_job_detail_html(detail_html, empty_job)
    assert empty_job.title == "Rust Engineer"
    assert empty_job.company == "Ferris"
    assert empty_job.location == "Remote"
    assert "Axum" in empty_job.description
    assert empty_job.seniority_level == "Mid-Senior level"
    assert empty_job.employment_type == "Full-time"
    assert empty_job.job_function == "Engineering"
    assert empty_job.industries == "Software"


def test_parse_jobs_from_email_content_and_mime() -> None:
    email_html = """
    <html>
      <body>
        <table>
          <tr>
            <td>
              <a href="https://www.linkedin.com/comm/jobs/view/9876543210?trackingId=xyz">
                Desenvolvedor Python / FastAPI
              </a>
              <div>Acme Cloud · Remoto, Brasil</div>
            </td>
          </tr>
          <tr>
            <td>
              <a href="https://empresa.gupy.io/jobs/11223344?utm_source=email">
                Engenheiro de Software Backend
              </a>
              <div>EmpresaX - São Paulo</div>
            </td>
          </tr>
          <tr>
            <td>
              <a href="https://www.linkedin.com/help">Unsubscribe</a>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """
    text_body = "Veja também: https://www.linkedin.com/jobs/view/777666555"
    jobs = parse_jobs_from_email_content(email_html, text_body=text_body, subject="Alerta")
    assert len(jobs) == 3
    by_id = {j.id: j for j in jobs}
    assert "9876543210" in by_id
    assert by_id["9876543210"].title == "Desenvolvedor Python / FastAPI"
    assert by_id["9876543210"].company == "Acme Cloud"
    assert by_id["9876543210"].source == JobSource.EMAIL
    assert "777666555" in by_id

    assert is_job_alert_email("jobalerts-noreply@linkedin.com", "News", EmailConfig())
    assert is_job_alert_email("rh@empresa.com", "Nova vaga Python", EmailConfig())
    assert not is_job_alert_email("promo@loja.com", "Cupom de desconto", EmailConfig())
    assert (
        unwrap_tracking_url(
            "https://click.mail.com/?url=https%3A%2F%2Fwww.linkedin.com%2Fjobs%2Fview%2F123"
        )
        == "https://www.linkedin.com/jobs/view/123"
    )
    assert decode_mime_words("=?utf-8?q?Alerta_de_Vagas?=") == "Alerta de Vagas"

    msg = EmailMessage()
    msg["Subject"] = "Vagas do dia"
    msg["From"] = "jobalerts-noreply@linkedin.com"
    msg.set_content("Texto puro")
    msg.add_alternative("<p>HTML</p>", subtype="html")
    html_part, txt_part = extract_email_bodies(msg)
    assert "<p>HTML</p>" in html_part
    assert "Texto puro" in txt_part


def test_dedup_repository_persistence(tmp_path: Path) -> None:
    repo = JobRepository(tmp_path)
    j1 = Job(id="101", title="Dev Python", company="A", source=JobSource.EMAIL)
    j2 = Job(id="102", title="Dev Rust", company="B", source=JobSource.LINKEDIN_SCRAPER)

    assert len(repo.filter_new([j1, j2, j1])) == 2
    repo.mark_seen("101")
    repo.save_jobs([j1, j2])

    repo2 = JobRepository(tmp_path)
    assert repo2.is_seen("101")
    assert not repo2.is_seen("102")
    assert len(repo2.filter_new([j1, j2])) == 1
    cached = repo2.get_job("101")
    assert cached is not None
    assert cached.title == "Dev Python"


def test_telegram_formatting_and_pdf_rendering() -> None:
    job = Job(
        id="555666777",
        title="Engenheiro Python & Rust <Senior>",
        company="Paiva Tech",
        location="Remoto",
        url="https://www.linkedin.com/jobs/view/555666777",
        description="Vaga excelente com FastAPI e Axum.",
        seniority_level="Pleno/Sênior",
        source=JobSource.EMAIL,
    )
    html_msg = format_job_notification(job)
    assert "<b>💼 Engenheiro Python &amp; Rust &lt;Senior&gt;</b>" in html_msg
    assert "[ID: 555666777]" in html_msg

    assert extract_job_id_from_telegram_message({"text": html_msg}) == "555666777"
    assert (
        extract_job_id_from_telegram_message(
            {
                "text": "Ver vaga",
                "entities": [
                    {
                        "type": "text_link",
                        "url": "https://www.linkedin.com/jobs/view/python-dev-123456789",
                    }
                ],
            }
        )
        == "123456789"
    )

    profile = ProfileConfig(
        name="Vitor Paiva",
        job_title="Software Engineer",
        contact=ContactConfig(
            email="vitor@example.com",
            github="github.com/vitor",
        ),
    )
    resume = GeneratedResume(
        resumo="Engenheiro focado em Python (FastAPI) e Rust (Axum).",
        habilidades=["Python", "FastAPI", "Rust", "PostgreSQL"],
        experiencia=[
            ResumeExperience(
                cargo="Backend Developer",
                empresa="SaaS Co",
                periodo="2024 - Atual",
                descricao=["Construção de APIs assíncronas de alta performance."],
            )
        ],
        projetos=[
            ResumeProject(
                nome="TrampoRadar",
                link="https://github.com/vitor/trampo-radar",
                descricao="Automação de vagas.",
            )
        ],
        formacao=[
            ResumeEducation(
                curso="Ciência da Computação",
                instituicao="Universidade",
                periodo="2022 - 2026",
            )
        ],
        idiomas=[ResumeLanguage(idioma="Português", nivel="Nativo")],
    )
    pdf_bytes = render_resume_pdf(profile, resume)
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500

    sys_msg, usr_msg = build_messages([job], profile)
    assert "REGRAS OBRIGATORIAS" in sys_msg
    assert "555666777" in usr_msg
    assert _clean_json_fence('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert truncate_text("abcdef", 3) == "abc..."


@pytest.mark.asyncio
async def test_pipeline_and_fastapi_endpoints(tmp_path: Path) -> None:
    repo = JobRepository(tmp_path)
    sample_job = Job(
        id="777888",
        title="FastAPI Specialist",
        company="AsyncCorp",
        location="Remote",
        url="https://www.linkedin.com/jobs/view/777888",
        description="FastAPI + Pydantic V2",
        source=JobSource.EMAIL,
    )
    repo.save_job(sample_job)

    settings = Settings(data_dir=tmp_path)
    yaml_cfg = AppYamlConfig()
    yaml_cfg.schedule.enabled = False
    yaml_cfg.telegram.enabled = False

    email_reader = EmailReaderService(settings=settings, email_cfg=yaml_cfg.email)
    linkedin_svc = LinkedInService(requests_per_second=10.0)
    linkedin_svc.search_keyword = AsyncMock(  # type: ignore[method-assign]
        return_value=[
            Job(
                id="888999",
                title="Python Backend Developer",
                company="CloudCo",
                location="Brazil",
                description="FastAPI async services",
            )
        ]
    )
    linkedin_svc.fetch_detail = AsyncMock(return_value=True)  # type: ignore[method-assign]

    tg_svc = TelegramService(bot_token="", chat_id=0)
    smtp_svc = SmtpDigestService(settings=settings, enabled=False)

    pipeline = JobPipelineService(
        settings=settings,
        yaml_cfg=yaml_cfg,
        repo=repo,
        email_reader=email_reader,
        linkedin_service=linkedin_svc,
        telegram_service=tg_svc,
        smtp_service=smtp_svc,
    )

    ai_svc = AIResumeService(
        ai_cfg=AIConfig(enable=True, api_token="test-key"),
        profile=yaml_cfg.profile,
    )
    ai_svc.generate_resumes = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "777888": GeneratedResume(
                resumo="Resumo adaptado para FastAPI Specialist.",
                habilidades=["Python", "FastAPI"],
            )
        }
    )

    app = create_app()
    app.dependency_overrides[get_job_repository] = lambda: repo
    app.dependency_overrides[get_yaml_config] = lambda: yaml_cfg
    app.dependency_overrides[get_pipeline_service] = lambda: pipeline
    app.dependency_overrides[get_ai_resume_service] = lambda: ai_svc
    app.dependency_overrides[get_linkedin_service] = lambda: linkedin_svc

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health_resp = await client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json()["status"] == "ok"

        scan_resp = await client.post("/jobs/scan")
        assert scan_resp.status_code == 200
        scan_data = scan_resp.json()
        assert scan_data["linkedin_candidates"] == 1
        assert scan_data["relevant_after_filter"] == 1

        jobs_resp = await client.get("/jobs")
        assert jobs_resp.status_code == 200
        assert len(jobs_resp.json()) == 2

        detail_resp = await client.get("/jobs/777888")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["title"] == "FastAPI Specialist"

        resume_resp = await client.post("/jobs/777888/resume")
        assert resume_resp.status_code == 200
        assert resume_resp.headers["content-type"] == "application/pdf"
        assert resume_resp.content.startswith(b"%PDF")

        not_found_resp = await client.get("/jobs/nao_existe")
        assert not_found_resp.status_code == 404


@pytest.mark.asyncio
async def test_ai_resume_service_http_mock() -> None:
    ai_cfg = AIConfig(enable=True, api_token="fake-key", model="test-model")
    profile = ProfileConfig(name="Vitor", skills=["Python"])
    service = AIResumeService(ai_cfg=ai_cfg, profile=profile)
    job = Job(id="123", title="Dev Python", description="FastAPI")

    mock_json = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": '{"123": {"resumo": "Dev Python Senior", "habilidades": ["Python"]}}'
                },
            }
        ]
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: mock_json
        mock_post.return_value = mock_resp

        resumes = await service.generate_resumes([job])
        assert "123" in resumes
        assert resumes["123"].resumo == "Dev Python Senior"
