"""
Job Radar — Scraper de vagas DevOps
Fontes validadas localmente: LinkedIn, Vagas.com, Programathor

Fontes removidas (bloqueiam IPs de CI/container):
  - Indeed    → 403 em todos os IPs de datacenter
  - Catho     → 404 em container
  - Gupy      → carrega vagas via JavaScript (sem API pública)
  - InfoJobs  → API retorna 404
"""

import hashlib
import json
import logging
import random
import re
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
    "Analista de Infraestrutura",
    "SRE",
    "Engenheiro DevOps",
    "DevOps Pleno",
    "DevOps Junior",
    "Analista de Infraestrutura Junior",
    "Analista de Infraestrutura Pleno",
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
        "Accept-Encoding": "gzip, deflate",
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
    """API pública guest do LinkedIn — validada: retorna ~10 vagas por query."""
    jobs: list[Job] = []
    url = (
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        f"?keywords={quote_plus(query)}"
        f"&location={quote_plus(location + ', Brasil')}"
        "&f_TPR=r604800"  # últimos 7 dias
        "&start=0"
    )

    log.info("[LinkedIn] query=%r location=%r", query, location)
    resp = _safe_get(url)
    if not resp:
        return jobs

    soup = BeautifulSoup(resp.text, "html.parser")
    for card in soup.select("li"):
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


# ─── Vagas.com ────────────────────────────────────────────────────────────────

def scrape_vagas_com(query: str, location: str = "") -> list[Job]:
    """
    Vagas.com — validada: 18 vagas sem filtro de cidade, 1 com cidade.
    Usa busca nacional e o scorer filtra localização depois.
    """
    jobs: list[Job] = []
    slug_query = query.lower().replace(" ", "-")

    # Busca nacional primeiro (mais resultados), depois com cidade
    urls = [f"https://www.vagas.com.br/vagas-de-{slug_query}"]
    if location:
        slug_loc = location.lower().replace(" ", "-")
        urls.append(f"https://www.vagas.com.br/vagas-de-{slug_query}-em-{slug_loc}")

    for url in urls:
        log.info("[Vagas.com] %s", url)
        resp = _safe_get(url)
        if not resp:
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("li.vaga")

        for card in cards[:20]:
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
                    title=title_el.get_text(separator=" ", strip=True),
                    company=company_el.get_text(separator=" ", strip=True) if company_el else "N/A",
                    location=loc_el.get_text(separator=" ", strip=True) if loc_el else location,
                    url=href,
                    source="Vagas.com",
                    description=desc,
                    published_at=date_el.get_text(strip=True) if date_el else "",
                ))
                _sleep(1.5, 3.0)
            except Exception as e:
                log.warning("[Vagas.com] Erro ao processar card: %s", e)

        log.info("[Vagas.com] %d vagas encontradas em %s", len(jobs), url)
        if jobs:
            break  # se achou na busca nacional, não precisa buscar por cidade

    return jobs


def _fetch_vagas_description(url: str) -> str:
    _sleep(1.0, 2.5)
    resp = _safe_get(url)
    if not resp:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    desc_el = soup.select_one(".job-description, #job-description, .descricao")
    return desc_el.get_text(separator=" ", strip=True)[:3000] if desc_el else ""


# ─── Programathor ─────────────────────────────────────────────────────────────

def scrape_programathor(query: str) -> list[Job]:
    """
    Programathor — validada: retorna cards no HTML.
    Foco em tech/remote — scorer filtra relevância para DevOps.
    """
    jobs: list[Job] = []
    url = f"https://programathor.com.br/jobs?filters%5Bpesquisa%5D={quote_plus(query)}"

    log.info("[Programathor] query=%r", query)
    resp = _safe_get(url)
    if not resp:
        return jobs

    soup = BeautifulSoup(resp.text, "html.parser")
    links = soup.select("a[href*='/jobs/']")

    seen_hrefs = set()
    for link in links[:20]:
        try:
            href = link.get("href", "")
            if not href or href in seen_hrefs or "/jobs/" not in href:
                continue
            seen_hrefs.add(href)

            if not href.startswith("http"):
                href = "https://programathor.com.br" + href

            # Extrai dados do card
            text = link.get_text(" ", strip=True)
            lines = [l.strip() for l in text.split("\n") if l.strip()]

            title = lines[0] if lines else ""
            # Remove badge "NOVA" do título se presente
            title = title.replace("NOVA", "").strip()

            if not title or len(title) < 5:
                continue

            # Tenta extrair empresa e localização do texto do card
            company = "N/A"
            location = "Remoto"
            salary = ""

            full_text = " ".join(lines)
            if "Remoto" in full_text:
                location = "Remoto"
            elif "Híbrido" in full_text or "Hibrido" in full_text:
                location = "Híbrido"

            sal_match = re.search(r"R\$\s*[\d.,]+", full_text)
            if sal_match:
                salary = sal_match.group(0)

            desc = _fetch_programathor_description(href)

            jobs.append(Job(
                title=title,
                company=company,
                location=location,
                url=href,
                source="Programathor",
                description=desc,
                salary=salary,
            ))
            _sleep(1.0, 2.5)
        except Exception as e:
            log.warning("[Programathor] Erro ao processar link: %s", e)

    log.info("[Programathor] %d vagas encontradas", len(jobs))
    return jobs


def _fetch_programathor_description(url: str) -> str:
    _sleep(1.0, 2.0)
    resp = _safe_get(url)
    if not resp:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    desc_el = soup.select_one(
        ".job-description, .description, [class*='description'], "
        "[class*='content'], article section, .job-content"
    )
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
    seen_signatures: set[str] = set()
    for j in existing.get("jobs", []):
        seen_signatures.add(_job_signature(j["title"], j["company"]))

    new_jobs: list[Job] = []

    for query in SEARCH_QUERIES:
        # LinkedIn — por localização
        for location in LOCATIONS[:3]:
            try:
                for job in scrape_linkedin(query, location):
                    if _is_new(job, existing_ids, seen_signatures):
                        new_jobs.append(job)
                        _register(job, existing_ids, seen_signatures)
            except Exception as e:
                log.error("[LinkedIn] Falha em query=%r: %s", query, e)
            _sleep(3.0, 5.0)

        # Vagas.com — busca nacional (mais resultados)
        try:
            for job in scrape_vagas_com(query):
                if _is_new(job, existing_ids, seen_signatures):
                    new_jobs.append(job)
                    _register(job, existing_ids, seen_signatures)
        except Exception as e:
            log.error("[Vagas.com] Falha em query=%r: %s", query, e)

        # Programathor — busca por query
        try:
            for job in scrape_programathor(query):
                if _is_new(job, existing_ids, seen_signatures):
                    new_jobs.append(job)
                    _register(job, existing_ids, seen_signatures)
        except Exception as e:
            log.error("[Programathor] Falha em query=%r: %s", query, e)

        _sleep(3.0, 6.0)

    log.info("Total de vagas novas encontradas: %d", len(new_jobs))
    return new_jobs


def _is_new(job: Job, existing_ids: set, seen_sigs: set) -> bool:
    if job.id in existing_ids:
        return False
    if _job_signature(job.title, job.company) in seen_sigs:
        log.debug("Duplicata cross-fonte: %s @ %s", job.title, job.company)
        return False
    return True


def _register(job: Job, existing_ids: set, seen_sigs: set) -> None:
    existing_ids.add(job.id)
    seen_sigs.add(_job_signature(job.title, job.company))


def _job_signature(title: str, company: str) -> str:
    norm = lambda s: re.sub(r"\s+", "", s.lower().strip())
    return hashlib.md5(f"{norm(title)}|{norm(company)}".encode()).hexdigest()


if __name__ == "__main__":
    jobs = run_scraper()
    log.info("Scraper finalizado: %d vagas novas", len(jobs))
