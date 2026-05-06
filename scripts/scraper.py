"""
Job Radar — Scraper de vagas DevOps
Fontes: LinkedIn Jobs, Gupy, Vagas.com, Catho
(Indeed removido — bloqueia IPs de datacenter/CI com 403)
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
from urllib.parse import quote_plus

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
    "DevOps",
    "DevOps Engineer",
    "Analista Infraestrutura Linux",
    "SRE",
    "Engenheiro DevOps",
    "DevOps Pleno",
    "DevOps Junior",
]

LOCATIONS = [
    "Belo Horizonte",
    "Contagem",
    "Minas Gerais",
    "Remoto",
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


def _get_headers(extra: dict = None) -> dict:
    h = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    if extra:
        h.update(extra)
    return h


def _sleep(min_s: float = 2.0, max_s: float = 5.0) -> None:
    time.sleep(random.uniform(min_s, max_s))


def _safe_get(url: str, timeout: int = 20, extra_headers: dict = None, **kwargs) -> Optional[requests.Response]:
    try:
        resp = requests.get(url, headers=_get_headers(extra_headers), timeout=timeout, **kwargs)
        if resp.status_code == 200:
            return resp
        log.warning("HTTP %s ao buscar %s", resp.status_code, url)
        return None
    except requests.RequestException as e:
        log.error("Erro ao buscar %s: %s", url, e)
        return None


# ─── LinkedIn ─────────────────────────────────────────────────────────────────

def scrape_linkedin(query: str, location: str) -> list[Job]:
    jobs: list[Job] = []
    url = (
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        f"?keywords={quote_plus(query)}"
        f"&location={quote_plus(location + ', Brasil')}"
        "&f_TPR=r604800"
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
            _sleep(1.5, 3.0)
        except Exception as e:
            log.warning("[LinkedIn] Erro ao processar card: %s", e)

    log.info("[LinkedIn] %d vagas encontradas", len(jobs))
    return jobs


def _fetch_linkedin_description(url: str) -> str:
    _sleep(1.0, 2.5)
    resp = _safe_get(url)
    if not resp:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    desc_el = soup.select_one(".show-more-less-html__markup, .description__text")
    return desc_el.get_text(separator=" ", strip=True)[:3000] if desc_el else ""


# ─── Gupy ─────────────────────────────────────────────────────────────────────

def scrape_gupy(query: str) -> list[Job]:
    """Scraping da página de busca do Gupy com extração via __NEXT_DATA__."""
    jobs: list[Job] = []

    url = f"https://portal.gupy.io/job-search/term/{quote_plus(query)}"
    log.info("[Gupy] query=%r", query)

    resp = _safe_get(url, extra_headers={
        "Accept": "text/html,application/xhtml+xml",
        "Referer": "https://portal.gupy.io/",
    })
    if not resp:
        return jobs

    soup = BeautifulSoup(resp.text, "html.parser")
    script = soup.find("script", {"id": "__NEXT_DATA__"})

    if script and script.string:
        try:
            next_data = json.loads(script.string)
            # Navega pela estrutura do Next.js para achar a lista de vagas
            queries = (
                next_data.get("props", {})
                .get("pageProps", {})
                .get("dehydratedState", {})
                .get("queries", [])
            )
            job_list = []
            for q in queries:
                data = q.get("state", {}).get("data", {})
                if isinstance(data, dict) and "data" in data:
                    job_list = data["data"]
                    break
                if isinstance(data, list):
                    job_list = data
                    break

            for item in job_list[:20]:
                job_id = item.get("id", "")
                city = item.get("city", "")
                state = item.get("state", "")
                location = f"{city}, {state}".strip(", ") or "Brasil"
                workplace = item.get("workplaceType", "")
                if workplace == "remote":
                    location = "Remoto"
                elif workplace == "hybrid":
                    location = f"Híbrido — {location}"

                company = item.get("company", {})
                company_name = company.get("name", "N/A") if isinstance(company, dict) else str(company)

                jobs.append(Job(
                    title=item.get("name", ""),
                    company=company_name,
                    location=location,
                    url=f"https://portal.gupy.io/job/{job_id}" if job_id else "",
                    source="Gupy",
                    description=str(item.get("description", ""))[:3000],
                    published_at=item.get("publishedDate", ""),
                ))
        except Exception as e:
            log.warning("[Gupy] Erro ao extrair __NEXT_DATA__: %s", e)

    if not jobs:
        # Fallback: tenta extrair cards do HTML diretamente
        cards = soup.select("article, [data-testid='job-card'], .job-card")
        for card in cards[:20]:
            try:
                title_el = card.select_one("h2, h3, [data-testid='job-name']")
                company_el = card.select_one("[data-testid='company-name'], .company-name")
                loc_el = card.select_one("[data-testid='job-location'], .location")
                link_el = card.select_one("a")

                if not title_el or not link_el:
                    continue

                href = link_el.get("href", "")
                if href.startswith("/"):
                    href = "https://portal.gupy.io" + href

                jobs.append(Job(
                    title=title_el.get_text(strip=True),
                    company=company_el.get_text(strip=True) if company_el else "N/A",
                    location=loc_el.get_text(strip=True) if loc_el else "Brasil",
                    url=href,
                    source="Gupy",
                ))
            except Exception as e:
                log.warning("[Gupy HTML] Erro: %s", e)

    log.info("[Gupy] %d vagas encontradas", len(jobs))
    _sleep(2.0, 4.0)
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
    _sleep(1.0, 2.5)
    resp = _safe_get(url)
    if not resp:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    desc_el = soup.select_one(".job-description, #job-description, .descricao")
    return desc_el.get_text(separator=" ", strip=True)[:3000] if desc_el else ""


# ─── Catho ────────────────────────────────────────────────────────────────────

def scrape_catho(query: str, location: str) -> list[Job]:
    """Catho via página de busca."""
    jobs: list[Job] = []
    url = f"https://www.catho.com.br/vagas/?q={quote_plus(query)}&where={quote_plus(location)}"

    log.info("[Catho] query=%r location=%r", query, location)
    resp = _safe_get(url)
    if not resp:
        return jobs

    soup = BeautifulSoup(resp.text, "html.parser")

    # Tenta extrair do JSON embutido
    for script in soup.find_all("script", type="application/json"):
        try:
            data = json.loads(script.string or "")
            job_list = None

            # Estrutura pode variar — procura lista de vagas
            if isinstance(data, dict):
                job_list = (
                    data.get("jobs")
                    or data.get("vacancies")
                    or data.get("results")
                )
            if job_list and isinstance(job_list, list):
                for item in job_list[:15]:
                    title = item.get("title") or item.get("name") or item.get("jobTitle", "")
                    company = item.get("company") or item.get("companyName", "N/A")
                    if isinstance(company, dict):
                        company = company.get("name", "N/A")
                    job_url = item.get("url") or item.get("link") or item.get("applyUrl", "")
                    if not job_url.startswith("http"):
                        job_url = "https://www.catho.com.br" + job_url

                    if title:
                        jobs.append(Job(
                            title=title,
                            company=str(company),
                            location=item.get("location") or item.get("city") or location,
                            url=job_url,
                            source="Catho",
                            salary=str(item.get("salary") or item.get("wage", "")),
                            published_at=str(item.get("publishedAt") or item.get("date", "")),
                        ))
                if jobs:
                    break
        except (json.JSONDecodeError, AttributeError):
            continue

    # Fallback: HTML scraping
    if not jobs:
        selectors = [
            "article.sc-",
            "[data-testid='job-card']",
            ".job-list-item",
            "li[class*='JobCard']",
        ]
        for sel in selectors:
            cards = soup.select(sel)
            if cards:
                for card in cards[:15]:
                    try:
                        title_el = card.select_one("h2, h3, [class*='title'], [class*='Title']")
                        company_el = card.select_one("[class*='company'], [class*='Company']")
                        link_el = card.select_one("a")
                        if not title_el or not link_el:
                            continue
                        href = link_el.get("href", "")
                        if href.startswith("/"):
                            href = "https://www.catho.com.br" + href
                        jobs.append(Job(
                            title=title_el.get_text(strip=True),
                            company=company_el.get_text(strip=True) if company_el else "N/A",
                            location=location,
                            url=href,
                            source="Catho",
                        ))
                    except Exception:
                        continue
                break

    log.info("[Catho] %d vagas encontradas", len(jobs))
    _sleep(2.0, 4.0)
    return jobs


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
    seen_signatures: set[str] = set()
    for j in existing.get("jobs", []):
        seen_signatures.add(_job_signature(j["title"], j["company"]))

    new_jobs: list[Job] = []

    for query in SEARCH_QUERIES:
        for location in LOCATIONS[:3]:
            for fn, needs_location in [
                (scrape_linkedin, True),
                (scrape_vagas_com, True),
                (scrape_catho, True),
            ]:
                try:
                    batch = fn(query, location) if needs_location else fn(query)
                    for job in batch:
                        if _is_new(job, existing_ids, seen_signatures):
                            new_jobs.append(job)
                            existing_ids.add(job.id)
                            seen_signatures.add(_job_signature(job.title, job.company))
                except Exception as e:
                    log.error("[%s] Falha: %s", fn.__name__, e)

            _sleep(2.0, 4.0)

        # Gupy — não filtra por localização, retorna nacional
        try:
            for job in scrape_gupy(query):
                if _is_new(job, existing_ids, seen_signatures):
                    new_jobs.append(job)
                    existing_ids.add(job.id)
                    seen_signatures.add(_job_signature(job.title, job.company))
        except Exception as e:
            log.error("[Gupy] Falha: %s", e)

    log.info("Total de vagas novas encontradas: %d", len(new_jobs))
    return new_jobs


def _is_new(job: Job, existing_ids: set, seen_sigs: set) -> bool:
    if job.id in existing_ids:
        return False
    if _job_signature(job.title, job.company) in seen_sigs:
        log.debug("Duplicata cross-fonte: %s @ %s", job.title, job.company)
        return False
    return True


def _job_signature(title: str, company: str) -> str:
    return hashlib.md5(
        f"{title.lower().strip()}|{company.lower().strip()}".encode()
    ).hexdigest()


if __name__ == "__main__":
    jobs = run_scraper()
    log.info("Scraper finalizado: %d vagas novas", len(jobs))
