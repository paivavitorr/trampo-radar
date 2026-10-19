"""Cliente e parser assíncrono do LinkedIn."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from trampo_radar.models.job import Job, JobSource

logger = logging.getLogger(__name__)

_RE_DAYS_AGO = re.compile(r"(\d+)\s*\+?\s*(?:days?\s*ago|dias?\s*atr[aá]s)", re.IGNORECASE)
_RE_WEEKS_AGO = re.compile(r"(\d+)\s*\+?\s*(?:weeks?\s*ago|semanas?\s*atr[aá]s)", re.IGNORECASE)
_RE_MONTHS_AGO = re.compile(
    r"(\d+)\s*\+?\s*(?:months?\s*ago|m[eê]s(?:es)?\s*atr[aá]s)", re.IGNORECASE
)
_RE_YEARS_AGO = re.compile(r"(\d+)\s*\+?\s*(?:years?\s*ago|anos?\s*atr[aá]s)", re.IGNORECASE)
_RE_LINKEDIN_JOB_ID = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(?:[^/?#]*?-)?(\d+)")


def linkedin_headers() -> dict[str, str]:
    """Retorna cabeçalhos que simulam um navegador real."""
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
        "Referer": "https://www.linkedin.com/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
    }


def post_time_to_ftpr(post_time: str) -> str:
    """Converte 'day' | 'week' | 'month' no parâmetro f_TPR do LinkedIn."""
    mapping = {
        "day": "r86400",
        "week": "r604800",
        "month": "r2592000",
    }
    return mapping.get(post_time.strip().lower(), "")


def extract_linkedin_job_id(url: str) -> str:
    """Extrai o ID numérico da vaga a partir de uma URL do LinkedIn."""
    if not url:
        return ""

    match = _RE_LINKEDIN_JOB_ID.search(url)
    if match:
        return match.group(1)

    clean = url.split("?", 1)[0].rstrip("/")
    parts = clean.split("/")
    if not parts:
        return ""

    last_segment = parts[-1]
    slug_parts = last_segment.split("-")
    candidate = slug_parts[-1] if slug_parts else ""
    return candidate if candidate.isdigit() else ""


def parse_posted_date(text: str, now: datetime | None = None) -> datetime | None:
    """Converte datas absolutas (YYYY-MM-DD) ou relativas ('3 days ago', 'hoje') para datetime."""
    ref_now = now or datetime.now(UTC)
    clean = text.strip()
    if not clean:
        return None

    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(clean, fmt).replace(tzinfo=UTC)
            return dt
        except ValueError:
            pass

    lower = clean.lower()
    if any(tok in lower for tok in ("hoje", "today", "agora", "just now")):
        return ref_now
    if any(tok in lower for tok in ("ontem", "yesterday")):
        return ref_now - timedelta(days=1)

    if m := _RE_DAYS_AGO.search(lower):
        return ref_now - timedelta(days=int(m.group(1)))
    if m := _RE_WEEKS_AGO.search(lower):
        return ref_now - timedelta(weeks=int(m.group(1)))
    if m := _RE_MONTHS_AGO.search(lower):
        return ref_now - timedelta(days=int(m.group(1)) * 30)
    if m := _RE_YEARS_AGO.search(lower):
        return ref_now - timedelta(days=int(m.group(1)) * 365)

    return None


def parse_jobs_html(html: str, now: datetime | None = None) -> list[Job]:
    """Parseia o HTML de busca do LinkedIn e retorna uma lista de objetos Job."""
    ref_now = now or datetime.now(UTC)
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[Job] = []

    cards = soup.select("[data-entity-urn]")
    for card in cards:
        job = _parse_job_card(card, ref_now)
        if job.id:
            jobs.append(job)

    if not jobs:
        for link_tag in soup.select("a[href*='/jobs/view/']"):
            href = str(link_tag.get("href", "")).strip()
            title_el = link_tag.select_one(".base-search-card__title, h3, h4")
            title = title_el.get_text(strip=True) if title_el else link_tag.get_text(strip=True)
            job_id = extract_linkedin_job_id(href)
            if job_id and title:
                jobs.append(
                    Job(
                        id=job_id,
                        title=title,
                        url=href.split("?", 1)[0],
                        source=JobSource.LINKEDIN_SCRAPER,
                        scraped_at=ref_now,
                    )
                )

    return jobs


def _parse_job_card(card: Tag, now: datetime) -> Job:
    title_el = card.select_one(".base-search-card__title") or card.select_one("h3")
    title = title_el.get_text(strip=True) if title_el else ""

    company_el = card.select_one(".base-search-card__subtitle") or card.select_one("h4")
    company = company_el.get_text(strip=True) if company_el else ""

    location_el = card.select_one(".job-search-card__location")
    location = location_el.get_text(strip=True) if location_el else ""

    link_el = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
    href = str(link_el.get("href", "")).strip() if link_el else ""

    time_el = card.select_one("time[class*='job-search-card__listdate']")
    posted_date = time_el.get_text(strip=True) if time_el else ""
    posted_at: datetime | None = None
    if time_el and time_el.get("datetime"):
        posted_at = parse_posted_date(str(time_el.get("datetime")), now)
    if posted_at is None and posted_date:
        posted_at = parse_posted_date(posted_date, now)

    desc_el = card.select_one(".artdeco-entity-snippet__subtitle-link, .search-entity-description")
    description = desc_el.get_text(strip=True) if desc_el else ""

    job_id = extract_linkedin_job_id(href)
    if not job_id:
        urn = str(card.get("data-entity-urn", ""))
        if urn.split(":")[-1].isdigit():
            job_id = urn.split(":")[-1]

    clean_url = (
        href.split("?", 1)[0]
        if href
        else (f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else "")
    )

    return Job(
        id=job_id,
        title=title,
        company=company,
        location=location,
        url=clean_url,
        posted_date=posted_date,
        posted_at=posted_at,
        description=description,
        source=JobSource.LINKEDIN_SCRAPER,
        scraped_at=now,
    )


def parse_job_detail_html(html: str, job: Job) -> None:
    """Extrai descrição completa e metadados da página de detalhe do LinkedIn."""
    soup = BeautifulSoup(html, "html.parser")

    if not job.title:
        title_el = soup.select_one(".top-card-layout__title, h1, h2")
        if title_el:
            job.title = title_el.get_text(strip=True)

    if not job.company:
        comp_el = soup.select_one(".topcard__org-name-link, .topcard__flavor")
        if comp_el:
            job.company = comp_el.get_text(strip=True)

    if not job.location:
        loc_el = soup.select_one(".topcard__flavor--bullet")
        if loc_el:
            job.location = loc_el.get_text(strip=True)

    desc_el = soup.select_one(".description__text--rich, .show-more-less-html__markup")
    if desc_el:
        job.description = desc_el.get_text(separator="\n", strip=True)

    for item in soup.select(".description__job-criteria-item"):
        header_el = item.select_one(".description__job-criteria-subheader")
        val_el = item.select_one(".description__job-criteria-text")
        if not header_el or not val_el:
            continue
        criteria = header_el.get_text(strip=True).lower()
        value = val_el.get_text(strip=True)
        if criteria == "seniority level":
            job.seniority_level = value
        elif criteria == "employment type":
            job.employment_type = value
        elif criteria == "job function":
            job.job_function = value
        elif criteria == "industries":
            job.industries = value


class AsyncRateLimiter:
    """Rate limiter assíncrono simples baseado em intervalo mínimo."""

    def __init__(self, requests_per_second: float) -> None:
        self._min_interval = 1.0 / max(requests_per_second, 0.05)
        self._last_call = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_call = time.monotonic()


class LinkedInService:
    """Cliente HTTP assíncrono com rate limit, retry e rotação de proxy para o LinkedIn."""

    def __init__(
        self,
        requests_per_second: float = 0.5,
        proxy_urls: list[str] | None = None,
        proxy_enabled: bool = False,
    ) -> None:
        self._limiter = AsyncRateLimiter(requests_per_second)
        self._proxies = proxy_urls if (proxy_enabled and proxy_urls) else []
        self._proxy_idx = 0

    def _next_proxy(self) -> str | None:
        if not self._proxies:
            return None
        proxy = self._proxies[self._proxy_idx % len(self._proxies)]
        self._proxy_idx += 1
        return proxy

    async def _get_text(self, url: str, retries: int = 3) -> str:
        last_err: Exception | None = None
        for attempt in range(retries):
            await self._limiter.wait()
            proxy = self._next_proxy()
            try:
                async with httpx.AsyncClient(
                    headers=linkedin_headers(),
                    timeout=15.0,
                    follow_redirects=True,
                    proxy=proxy,
                ) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        return resp.text
                    if resp.status_code in (429, 500, 502, 503, 504):
                        await asyncio.sleep(2.0 * (attempt + 1))
                        continue
                    resp.raise_for_status()
            except httpx.HTTPError as exc:
                last_err = exc
                await asyncio.sleep(2.0 * (attempt + 1))

        raise RuntimeError(f"Falha ao requisitar {url}: {last_err}")

    async def search_keyword(
        self,
        keyword: str,
        location: str,
        max_results: int = 25,
        post_time: str = "day",
    ) -> list[Job]:
        """Busca vagas públicas no LinkedIn para uma palavra-chave e localização."""
        all_jobs: list[Job] = []
        ftpr = post_time_to_ftpr(post_time)

        for start in range(0, max_results, 25):
            search_url = (
                "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                f"?keywords={quote_plus(keyword)}&location={quote_plus(location)}&start={start}"
            )
            if ftpr:
                search_url += f"&f_TPR={ftpr}"

            try:
                html = await self._get_text(search_url)
            except Exception as exc:
                logger.warning("Busca LinkedIn falhou para keyword=%s: %s", keyword, exc)
                break

            batch = parse_jobs_html(html)
            if not batch:
                break
            all_jobs.extend(batch)

        return all_jobs[:max_results]

    async def fetch_detail(self, job: Job) -> bool:
        """Popula a descrição e os critérios de uma vaga do LinkedIn (ou página genérica)."""
        if not job.id:
            return False

        # Vaga do LinkedIn (ID numérico)
        clean_id = job.id.split("?", 1)[0]
        if clean_id.isdigit():
            detail_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{clean_id}"
            try:
                html = await self._get_text(detail_url)
                parse_job_detail_html(html, job)
                if not job.url:
                    job.url = f"https://www.linkedin.com/jobs/view/{clean_id}"
                return True
            except Exception as exc:
                logger.warning("Falha ao buscar detalhe LinkedIn id=%s: %s", clean_id, exc)
                return False

        # Vaga externa vinda do e-mail (ex: Gupy, Indeed, etc.) se tiver URL
        if job.url and urlparse(job.url).scheme in ("http", "https") and not job.description:
            try:
                html = await self._get_text(job.url, retries=1)
                soup = BeautifulSoup(html, "html.parser")
                for tag in soup(["script", "style", "nav", "header", "footer"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)
                job.description = text[:3000]
                return True
            except Exception as exc:
                logger.debug("Não foi possível enriquecer URL externa %s: %s", job.url, exc)
                return False

        return False
