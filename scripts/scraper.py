"""
Job Radar — Scraper de vagas DevOps
Fontes: Indeed, LinkedIn Jobs, Gupy, Vagas.com
"""

import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
JOBS_FILE = DATA_DIR / "jobs.json"

SEARCH_QUERIES = [
    "DevOps Engineer",
    "Analista Infraestrutura Linux",
    "SRE Site Reliability",
    "Engenheiro DevOps",
    "DevOps Pleno",
    "DevOps Junior",
]

LOCATIONS = [
    "Belo Horizonte",
    "Contagem",
    "Minas Gerais",
    "Remoto",
    "Home Office",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    source: str
    description: str = ""
    salary: str = ""
    published_at: str = ""
    found_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    score: int = 0
    score_breakdown: dict = field(default_factory=dict)
    skills_match: list = field(default_factory=list)
    skills_gap: list = field(default_factory=list)
    fit_level: str = "baixo"
    status: str = "nova"
    applied_at: Optional[str] = None
    cover_letter: Optional[str] = None

    @property
    def id(self) -> str:
        raw = f"{self.url}{self.title}{self.company}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "salary": self.salary,
            "description": self.description,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "found_at": self.found_at,
            "score": self.score,
            "score_breakdown": self.score_breakdown,
            "skills_match": self.skills_match,
            "skills_gap": self.skills_gap,
            "fit_level": self.fit_level,
            "status": self.status,
            "applied_at": self.applied_at,
            "cover_letter": self.cover_letter,
        }


def _get_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }


def _sleep(min_s: float = 2.0, max_s: float = 5.0) -> None:
    t = random.uniform(min_s, max_s)
    log.debug("Aguardando %.1fs", t)
    time.sleep(t)


def _safe_get(url: str, timeout: int = 15, **kwargs) -> Optional[requests.Response]:
    try:
        resp = requests.get(url, headers=_get_headers(), timeout=timeout, **kwargs)
        if resp.status_code == 200:
            return resp
        log.warning("HTTP %s ao buscar %s", resp.status_code, url)
        return None
    except requests.RequestException as e:
        log.error("Erro ao buscar %s: %s", url, e)
        return None


# ─── Indeed ───────────────────────────────────────────────────────────────────

def scrape_indeed(query: str, location: str) -> list[Job]:
    jobs: list[Job] = []
    base = "https://br.indeed.com/jobs"
    params = {"q": query, "l": location, "sort": "date"}
    url = f"{base}?q={requests.utils.quote(query)}&l={requests.utils.quote(location)}&sort=date"

    log.info("[Indeed] query=%r location=%r", query, location)
    resp = _safe_get(url)
    if not resp:
        return jobs

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select("div.job_seen_beacon, div.tapItem")

    for card in cards[:15]:
        try:
            title_el = card.select_one("h2.jobTitle span, h2.jobTitle a")
            company_el = card.select_one("[data-testid='company-name'], .companyName")
            loc_el = card.select_one("[data-testid='text-location'], .companyLocation")
            salary_el = card.select_one("[data-testid='attribute_snippet_testid'], .salary-snippet-container")
            link_el = card.select_one("h2.jobTitle a")
            date_el = card.select_one("[data-testid='myJobsStateDate'], .date")

            if not title_el or not link_el:
                continue

            href = link_el.get("href", "")
            if href.startswith("/"):
                href = "https://br.indeed.com" + href

            # Busca descrição completa na página da vaga
            desc = _fetch_indeed_description(href)

            jobs.append(Job(
                title=title_el.get_text(strip=True),
                company=company_el.get_text(strip=True) if company_el else "N/A",
                location=loc_el.get_text(strip=True) if loc_el else location,
                salary=salary_el.get_text(strip=True) if salary_el else "",
                url=href,
                source="Indeed",
                description=desc,
                published_at=date_el.get_text(strip=True) if date_el else "",
            ))
            _sleep(1.5, 3.0)
        except Exception as e:
            log.warning("[Indeed] Erro ao processar card: %s", e)

    log.info("[Indeed] %d vagas encontradas", len(jobs))
    return jobs


def _fetch_indeed_description(url: str) -> str:
    _sleep(1.0, 2.5)
    resp = _safe_get(url)
    if not resp:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    desc_el = soup.select_one("#jobDescriptionText, .jobsearch-jobDescriptionText")
    return desc_el.get_text(separator=" ", strip=True)[:3000] if desc_el else ""


# ─── LinkedIn ─────────────────────────────────────────────────────────────────

def scrape_linkedin(query: str, location: str) -> list[Job]:
    jobs: list[Job] = []
    # LinkedIn Jobs API pública (sem autenticação)
    url = (
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        f"?keywords={requests.utils.quote(query)}"
        f"&location={requests.utils.quote(location + ', Brasil')}"
        "&f_TPR=r86400"  # últimas 24h
        "&start=0"
    )

    log.info("[LinkedIn] query=%r location=%r", query, location)
    resp = _safe_get(url)
    if not resp:
        return jobs

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select("li")

    for card in cards[:15]:
        try:
            title_el = card.select_one(".base-search-card__title, h3")
            company_el = card.select_one(".base-search-card__subtitle, h4")
            loc_el = card.select_one(".job-search-card__location")
            link_el = card.select_one("a.base-card__full-link, a")
            date_el = card.select_one("time")

            if not title_el or not link_el:
                continue

            href = link_el.get("href", "").split("?")[0]
            desc = _fetch_linkedin_description(href)

            jobs.append(Job(
                title=title_el.get_text(strip=True),
                company=company_el.get_text(strip=True) if company_el else "N/A",
                location=loc_el.get_text(strip=True) if loc_el else location,
                url=href,
                source="LinkedIn",
                description=desc,
                published_at=date_el.get("datetime", "") if date_el else "",
            ))
            _sleep(2.0, 4.0)
        except Exception as e:
            log.warning("[LinkedIn] Erro ao processar card: %s", e)

    log.info("[LinkedIn] %d vagas encontradas", len(jobs))
    return jobs


def _fetch_linkedin_description(url: str) -> str:
    _sleep(1.5, 3.0)
    resp = _safe_get(url)
    if not resp:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    desc_el = soup.select_one(".show-more-less-html__markup, .description__text")
    return desc_el.get_text(separator=" ", strip=True)[:3000] if desc_el else ""


# ─── Gupy ─────────────────────────────────────────────────────────────────────

def scrape_gupy(query: str) -> list[Job]:
    jobs: list[Job] = []
    url = f"https://portal.gupy.io/api/job?name={requests.utils.quote(query)}&limit=20"

    log.info("[Gupy] query=%r", query)
    resp = _safe_get(url)
    if not resp:
        return jobs

    try:
        data = resp.json()
        items = data.get("data", [])
    except Exception:
        log.warning("[Gupy] Resposta não é JSON válido")
        return jobs

    for item in items[:15]:
        try:
            job_id = item.get("id", "")
            job_url = f"https://portal.gupy.io/job/{job_id}" if job_id else item.get("jobUrl", "")
            city = item.get("city", "")
            state = item.get("state", "")
            location = f"{city}, {state}".strip(", ")
            workplace = item.get("workplaceType", "")
            if workplace == "remote":
                location = "Remoto"
            elif workplace == "hybrid":
                location = f"Híbrido — {location}"

            jobs.append(Job(
                title=item.get("name", ""),
                company=item.get("company", {}).get("name", "N/A"),
                location=location,
                url=job_url,
                source="Gupy",
                description=item.get("description", "")[:3000],
                published_at=item.get("publishedDate", ""),
            ))
            _sleep(0.5, 1.5)
        except Exception as e:
            log.warning("[Gupy] Erro ao processar item: %s", e)

    log.info("[Gupy] %d vagas encontradas", len(jobs))
    return jobs


# ─── Vagas.com ────────────────────────────────────────────────────────────────

def scrape_vagas_com(query: str, location: str) -> list[Job]:
    jobs: list[Job] = []
    slug_query = query.lower().replace(" ", "-")
    slug_loc = location.lower().replace(" ", "-")
    url = f"https://www.vagas.com.br/vagas-de-{slug_query}-em-{slug_loc}"

    log.info("[Vagas.com] query=%r location=%r", query, location)
    resp = _safe_get(url)
    if not resp:
        return jobs

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select("li.vaga")

    for card in cards[:15]:
        try:
            title_el = card.select_one("h2.cargo a, .vaga-title")
            company_el = card.select_one(".empresa, span.nome-empresa")
            loc_el = card.select_one(".vaga-local, .localidade")
            date_el = card.select_one(".data-publicacao, time")
            link_el = card.select_one("h2.cargo a, a.link-detalhes-vaga")

            if not title_el or not link_el:
                continue

            href = link_el.get("href", "")
            if href.startswith("/"):
                href = "https://www.vagas.com.br" + href

            desc = _fetch_vagas_description(href)

            jobs.append(Job(
                title=title_el.get_text(strip=True),
                company=company_el.get_text(strip=True) if company_el else "N/A",
                location=loc_el.get_text(strip=True) if loc_el else location,
                url=href,
                source="Vagas.com",
                description=desc,
                published_at=date_el.get_text(strip=True) if date_el else "",
            ))
            _sleep(2.0, 4.0)
        except Exception as e:
            log.warning("[Vagas.com] Erro ao processar card: %s", e)

    log.info("[Vagas.com] %d vagas encontradas", len(jobs))
    return jobs


def _fetch_vagas_description(url: str) -> str:
    _sleep(1.5, 3.0)
    resp = _safe_get(url)
    if not resp:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    desc_el = soup.select_one(".job-description, #job-description, .descricao")
    return desc_el.get_text(separator=" ", strip=True)[:3000] if desc_el else ""


# ─── Orquestração ─────────────────────────────────────────────────────────────

def load_existing_jobs() -> dict:
    if JOBS_FILE.exists():
        with open(JOBS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"jobs": [], "last_updated": "", "stats": {}}


def save_jobs(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("jobs.json salvo com %d vagas", len(data["jobs"]))


def run_scraper() -> list[Job]:
    existing = load_existing_jobs()
    existing_ids = {j["id"] for j in existing.get("jobs", [])}

    # Deduplicação cross-source: normaliza título+empresa
    seen_signatures: set[str] = set()
    for j in existing.get("jobs", []):
        sig = _job_signature(j["title"], j["company"])
        seen_signatures.add(sig)

    new_jobs: list[Job] = []

    scrapers = [
        ("Indeed", lambda q, l: scrape_indeed(q, l)),
        ("LinkedIn", lambda q, l: scrape_linkedin(q, l)),
        ("Gupy", lambda q, _: scrape_gupy(q)),
        ("Vagas.com", lambda q, l: scrape_vagas_com(q, l)),
    ]

    for query in SEARCH_QUERIES:
        for source, fn in scrapers:
            for location in LOCATIONS[:3]:  # Limita localidades por query/fonte
                try:
                    batch = fn(query, location)
                    for job in batch:
                        sig = _job_signature(job.title, job.company)
                        if job.id not in existing_ids and sig not in seen_signatures:
                            new_jobs.append(job)
                            existing_ids.add(job.id)
                            seen_signatures.add(sig)
                        else:
                            log.debug("Duplicata ignorada: %s @ %s", job.title, job.company)
                    _sleep(3.0, 6.0)
                except Exception as e:
                    log.error("[%s] Falha no scraper: %s", source, e)
                    continue

    log.info("Total de vagas novas encontradas: %d", len(new_jobs))
    return new_jobs


def _job_signature(title: str, company: str) -> str:
    normalized = f"{title.lower().strip()}|{company.lower().strip()}"
    return hashlib.md5(normalized.encode()).hexdigest()


if __name__ == "__main__":
    jobs = run_scraper()
    log.info("Scraper finalizado: %d vagas novas", len(jobs))
