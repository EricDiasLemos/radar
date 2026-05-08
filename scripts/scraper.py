"""
Job Radar — Scraper de vagas DevOps
Fontes validadas:
  - LinkedIn     (HTML — guest API pública)
  - Vagas.com    (HTML — busca nacional)
  - Programathor (RSS feed /jobs.rss)
  - Gupy         (API JSON portal.api.gupy.io)

Fontes removidas (sem feed/API pública acessível):
  - Indeed    → 403 em IPs de datacenter
  - Catho     → 404 em sitemap/robots, sem RSS
  - InfoJobs  → robots.txt sem sitemap, sem RSS
"""

import hashlib
import json
import logging
import random
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

# Cache do RSS do Programathor (uma chamada por execução)
_PROGRAMATHOR_CACHE: Optional[list[dict]] = None
_PROGRAMATHOR_FETCHED: bool = False

# Cache de descrições (URL → texto): evita re-fetch de vagas já conhecidas.
# Populado por run_scraper antes do loop principal.
_DESCRIPTION_CACHE: dict[str, str] = {}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
JOBS_FILE = DATA_DIR / "jobs.json"
BLACKLIST_FILE = DATA_DIR / "blacklist.json"

SEARCH_QUERIES = [
    # DevOps
    "DevOps",
    "DevOps Engineer",
    "Engenheiro DevOps",
    "DevOps Pleno",
    "DevOps Junior",
    # SRE / Infra
    "SRE",
    "Analista Infraestrutura Linux",
    "Analista de Infraestrutura",
    "Analista de Infraestrutura Junior",
    "Analista de Infraestrutura Pleno",
    # Cloud
    "Cloud Engineer",
    "Engenheiro Cloud",
    "Analista Cloud",
    "Cloud Junior",
    "AWS Engineer",
    "GCP Engineer",
    "Cloud Computing",
    "Computação em Nuvem",
    "Administrador Cloud",
    "Cloud Operations",
]

LOCATIONS = [
    "Belo Horizonte",  # cobre Grande BH (Contagem, Betim) na busca do LinkedIn
    "Minas Gerais",    # captura MG inteiro
    "Remoto",
]
# Quantas localizações usar no LinkedIn (BH + MG já cobrem Contagem)
LINKEDIN_LOCATIONS_LIMIT = 2

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
    contact_email: Optional[str] = None

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
            "contact_email": self.contact_email,
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
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # 1ª passada: extrai metadados e URLs novas (sem fetch ainda)
    cards_data: list[dict] = []
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
            cards_data.append({
                "title": title_el.get_text(strip=True),
                "company": company_el.get_text(strip=True) if company_el else "N/A",
                "location": loc_el.get_text(strip=True) if loc_el else location,
                "url": href,
                "published_at": date_el.get("datetime", "") if date_el else "",
            })
        except Exception as e:
            log.warning("[LinkedIn] Erro ao processar card: %s", e)

    # 2ª passada: fetch paralelo das descrições (com cache)
    urls = [c["url"] for c in cards_data]
    descriptions = _fetch_descriptions_parallel(urls, _fetch_linkedin_description)

    jobs = [
        Job(
            title=c["title"],
            company=c["company"],
            location=c["location"],
            url=c["url"],
            source="LinkedIn",
            description=descriptions.get(c["url"], ""),
            published_at=c["published_at"],
        )
        for c in cards_data
    ]
    log.info("[LinkedIn] %d vagas encontradas", len(jobs))
    return jobs


def _fetch_linkedin_description(url: str) -> str:
    """Fetch direto (sem sleep — paralelização cuida do throttling natural)."""
    if url in _DESCRIPTION_CACHE:
        return _DESCRIPTION_CACHE[url]
    resp = _safe_get(url)
    if not resp:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    desc_el = soup.select_one(".show-more-less-html__markup, .description__text")
    text = desc_el.get_text(separator=" ", strip=True)[:3000] if desc_el else ""
    _DESCRIPTION_CACHE[url] = text
    return text


def _fetch_descriptions_parallel(urls: list[str], fetcher, max_workers: int = 4) -> dict[str, str]:
    """
    Busca descrições em paralelo com ThreadPool. URLs já em cache retornam imediato.
    """
    if not urls:
        return {}
    results: dict[str, str] = {}
    # Separa cached de novos pra evitar criar threads desnecessárias
    new_urls = [u for u in urls if u not in _DESCRIPTION_CACHE]
    for u in urls:
        if u in _DESCRIPTION_CACHE:
            results[u] = _DESCRIPTION_CACHE[u]
    if new_urls:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for url, desc in zip(new_urls, ex.map(fetcher, new_urls)):
                results[url] = desc
    return results


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

        cards_data: list[dict] = []
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

                cards_data.append({
                    "title": title_el.get_text(separator=" ", strip=True),
                    "company": company_el.get_text(separator=" ", strip=True) if company_el else "N/A",
                    "location": loc_el.get_text(separator=" ", strip=True) if loc_el else location,
                    "url": href,
                    "published_at": date_el.get_text(strip=True) if date_el else "",
                })
            except Exception as e:
                log.warning("[Vagas.com] Erro ao processar card: %s", e)

        # Fetch paralelo das descrições (com cache)
        descriptions = _fetch_descriptions_parallel(
            [c["url"] for c in cards_data], _fetch_vagas_description
        )
        for c in cards_data:
            jobs.append(Job(
                title=c["title"],
                company=c["company"],
                location=c["location"],
                url=c["url"],
                source="Vagas.com",
                description=descriptions.get(c["url"], ""),
                published_at=c["published_at"],
            ))

        log.info("[Vagas.com] %d vagas encontradas em %s", len(jobs), url)
        if jobs:
            break  # se achou na busca nacional, não precisa buscar por cidade

    return jobs


def _fetch_vagas_description(url: str) -> str:
    """Fetch direto (sem sleep — paralelização limita concorrência)."""
    if url in _DESCRIPTION_CACHE:
        return _DESCRIPTION_CACHE[url]
    resp = _safe_get(url)
    if not resp:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    desc_el = soup.select_one(".job-description, #job-description, .descricao")
    text = desc_el.get_text(separator=" ", strip=True)[:3000] if desc_el else ""
    _DESCRIPTION_CACHE[url] = text
    return text


# ─── Programathor ─────────────────────────────────────────────────────────────

def _fetch_programathor_rss() -> list[dict]:
    """
    Busca o feed RSS do Programathor uma única vez por execução.
    O endpoint /jobs.rss retorna XML público com title/link/description/pubDate
    e geralmente não é bloqueado por IPs de datacenter (GitHub Actions).
    """
    global _PROGRAMATHOR_CACHE, _PROGRAMATHOR_FETCHED
    if _PROGRAMATHOR_FETCHED:
        return _PROGRAMATHOR_CACHE or []

    _PROGRAMATHOR_FETCHED = True
    url = "https://programathor.com.br/jobs.rss"
    log.info("[Programathor] Buscando RSS feed: %s", url)

    resp = _safe_get(url, extra_headers={"Accept": "application/rss+xml, application/xml, text/xml"})
    if not resp:
        log.warning("[Programathor] RSS indisponível")
        _PROGRAMATHOR_CACHE = []
        return []

    items: list[dict] = []
    try:
        root = ET.fromstring(resp.text)
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip().split("?")[0]
            desc = (item.findtext("description") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()

            # Limpa marcadores tipo "Vaga:" e hashtags do título
            title = re.sub(r"^Vaga:\s*", "", title)
            title = re.sub(r"\s*#\S+", "", title).strip()

            if not title or not link:
                continue

            items.append({
                "title": title,
                "link": link,
                "description": desc[:3000],
                "pub_date": pub,
            })
    except ET.ParseError as e:
        log.error("[Programathor] Falha ao parsear RSS: %s", e)
        _PROGRAMATHOR_CACHE = []
        return []

    log.info("[Programathor] %d vagas no RSS", len(items))
    _PROGRAMATHOR_CACHE = items
    return items


def scrape_programathor(query: str) -> list[Job]:
    """
    Programathor — usa RSS feed (/jobs.rss) ao invés de scraping HTML.
    O feed lista todas as vagas ativas. Como é uma fonte única,
    retornamos todas as vagas na primeira chamada e [] nas subsequentes
    (o scorer filtra relevância depois).
    """
    items = _fetch_programathor_rss()
    if not items:
        return []

    # Snapshot + clear: na primeira chamada retorna todas as vagas;
    # nas subsequentes (outras queries) o cache fica vazio e retorna [].
    snapshot = list(items)
    items.clear()

    jobs: list[Job] = []
    for it in snapshot:
        title = it["title"]
        link = it["link"]
        desc = it["description"]

        # Localização: tenta detectar no texto
        full_text = f"{title} {desc}".lower()
        location = "N/A"
        if "remoto" in full_text or "100% remote" in full_text or "home office" in full_text:
            location = "Remoto"
        elif "híbrido" in full_text or "hibrido" in full_text:
            location = "Híbrido"

        # Salário, se mencionado
        salary = ""
        sal_match = re.search(r"R\$\s*[\d.,]+", desc)
        if sal_match:
            salary = sal_match.group(0)

        jobs.append(Job(
            title=title,
            company="N/A",  # RSS não traz empresa de forma estruturada
            location=location,
            url=link,
            source="Programathor",
            description=desc,
            salary=salary,
            published_at=it.get("pub_date", ""),
        ))

    log.info("[Programathor] %d vagas convertidas em Jobs", len(jobs))
    return jobs


# ─── Gupy ─────────────────────────────────────────────────────────────────────

def scrape_gupy(query: str, limit: int = 30) -> list[Job]:
    """
    Gupy — API JSON pública agregadora (portal.api.gupy.io).
    Retorna vagas de TODAS as empresas que usam Gupy como ATS.
    """
    jobs: list[Job] = []
    url = (
        "https://portal.api.gupy.io/api/job"
        f"?name={quote_plus(query)}&limit={limit}"
    )

    log.info("[Gupy] query=%r", query)
    resp = _safe_get(url, extra_headers={"Accept": "application/json"})
    if not resp:
        return jobs

    try:
        data = resp.json()
    except ValueError as e:
        log.error("[Gupy] Resposta não-JSON: %s", e)
        return jobs

    # API retorna {"data": [...]} ou lista direta dependendo do endpoint
    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        log.warning("[Gupy] Formato inesperado: %s", type(items).__name__)
        return jobs

    for it in items:
        try:
            title = (it.get("name") or "").strip()
            company = (it.get("careerPageName") or "N/A").strip()
            description = (it.get("description") or "").strip()[:3000]
            job_url = (it.get("jobUrl") or "").strip()
            city = (it.get("city") or "").strip()
            state = (it.get("state") or "").strip()
            workplace = (it.get("workplaceType") or "").lower()
            is_remote = bool(it.get("isRemoteWork"))
            published = (it.get("publishedDate") or "").strip()

            if not title or not job_url:
                continue

            # Localização: prioriza flag remoto, senão monta cidade/estado
            if is_remote or workplace == "remote":
                location = "Remoto"
            elif workplace == "hybrid":
                location = f"Híbrido — {city}/{state}".strip(" —/")
            else:
                location = f"{city}/{state}".strip("/")
                if not location:
                    location = "N/A"

            jobs.append(Job(
                title=title,
                company=company,
                location=location,
                url=job_url,
                source="Gupy",
                description=description,
                published_at=published,
            ))
        except Exception as e:
            log.warning("[Gupy] Erro ao processar item: %s", e)

    log.info("[Gupy] %d vagas encontradas", len(jobs))
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


def load_blacklist() -> set[str]:
    """
    Carrega IDs de vagas excluídas permanentemente pelo dashboard.
    Vagas com esses IDs nunca mais entram no banco mesmo se re-encontradas.
    """
    if not BLACKLIST_FILE.exists():
        return set()
    try:
        with open(BLACKLIST_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("ids", []))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Falha ao ler blacklist: %s", e)
        return set()


def run_scraper() -> list[Job]:
    existing = load_existing_jobs()
    existing_jobs = existing.get("jobs", [])
    existing_ids = {j["id"] for j in existing_jobs}
    blacklist_ids = load_blacklist()
    log.info("Blacklist carregada: %d IDs banidos", len(blacklist_ids))
    seen_signatures: set[str] = set()
    for j in existing_jobs:
        seen_signatures.add(_job_signature(j["title"], j["company"]))

    # Popula cache de descrições com vagas que já temos no banco.
    # Evita re-fetch quando a mesma URL aparece nesta execução.
    for j in existing_jobs:
        url = j.get("url", "")
        desc = j.get("description", "")
        if url and desc:
            _DESCRIPTION_CACHE[url] = desc
    log.info("Cache de descrições pré-carregado com %d entradas", len(_DESCRIPTION_CACHE))

    new_jobs: list[Job] = []

    rejected_by_blacklist = 0

    for query in SEARCH_QUERIES:
        # LinkedIn — só BH + MG (Contagem é coberto por BH/MG)
        for location in LOCATIONS[:LINKEDIN_LOCATIONS_LIMIT]:
            try:
                for job in scrape_linkedin(query, location):
                    if _is_new(job, existing_ids, seen_signatures, blacklist_ids):
                        new_jobs.append(job)
                        _register(job, existing_ids, seen_signatures)
                    elif job.id in blacklist_ids:
                        rejected_by_blacklist += 1
            except Exception as e:
                log.error("[LinkedIn] Falha em query=%r: %s", query, e)
            _sleep(0.5, 1.5)

        # Vagas.com — busca nacional (mais resultados)
        try:
            for job in scrape_vagas_com(query):
                if _is_new(job, existing_ids, seen_signatures, blacklist_ids):
                    new_jobs.append(job)
                    _register(job, existing_ids, seen_signatures)
                elif job.id in blacklist_ids:
                    rejected_by_blacklist += 1
        except Exception as e:
            log.error("[Vagas.com] Falha em query=%r: %s", query, e)

        # Programathor — RSS feed (1 chamada total por execução)
        try:
            for job in scrape_programathor(query):
                if _is_new(job, existing_ids, seen_signatures, blacklist_ids):
                    new_jobs.append(job)
                    _register(job, existing_ids, seen_signatures)
                elif job.id in blacklist_ids:
                    rejected_by_blacklist += 1
        except Exception as e:
            log.error("[Programathor] Falha em query=%r: %s", query, e)

        # Gupy — API JSON agregada
        try:
            for job in scrape_gupy(query):
                if _is_new(job, existing_ids, seen_signatures, blacklist_ids):
                    new_jobs.append(job)
                    _register(job, existing_ids, seen_signatures)
                elif job.id in blacklist_ids:
                    rejected_by_blacklist += 1
        except Exception as e:
            log.error("[Gupy] Falha em query=%r: %s", query, e)

        _sleep(1.0, 2.0)

    log.info("Total de vagas novas encontradas: %d (rejeitadas por blacklist: %d)",
             len(new_jobs), rejected_by_blacklist)
    return new_jobs


def _is_new(job: Job, existing_ids: set, seen_sigs: set, blacklist_ids: set = None) -> bool:
    if blacklist_ids and job.id in blacklist_ids:
        return False
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
