"""
Job Radar — Diretório de recruiters

Agrega as pessoas que publicaram as vagas (extraídas pelo scraper a partir do
bloco público '.message-the-recruiter' do LinkedIn) num diretório acumulado.

Diferente das vagas — que expiram em 24h — um recruiter é um contato de valor
duradouro: fica no diretório para sempre e vai acumulando as vagas que publicou.
"""

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from scorer import classify_title  # type: ignore
except ImportError:
    from scripts.scorer import classify_title  # type: ignore

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
RECRUITERS_FILE = DATA_DIR / "recruiters.json"

# Máximo de vagas guardadas por recruiter (as mais recentes primeiro)
MAX_JOBS_PER_RECRUITER = 20

# Score minimo da vaga para o recruiter entrar no diretorio.
# Evita guardar quem so publica vagas fora do perfil (ex: Depto Pessoal),
# o que geraria mensagens de conexao sem sentido.
MIN_JOB_SCORE = 60

# Janela para inferir o recruiter de uma vaga a partir da empresa.
# Se já conhecemos alguém que publicou por aquela empresa nos últimos N dias,
# associamos as novas vagas dela a esse contato. Recrutador troca de emprego,
# então um contato muito antigo deixa de valer.
INFER_WINDOW_DAYS = 90

# ─── Classificação ────────────────────────────────────────────────────────────

# Headline indica que a pessoa trabalha com recrutamento
_RECRUITER_RE = re.compile(
    r"recruit|talent\s*acquisition|\btalent\b|head\s*hunt|headhunt|"
    r"\br&s\b|\brh\b|recursos\s+humanos|people\s*(&|and)?\s*culture|"
    r"sele[cç][aã]o|\bhiring\b|\bstaffing\b|people\s*ops|\btech\s*rec",
    re.IGNORECASE,
)

# Pistas de país no headline (vagas 'remote worldwide' trazem gente de fora)
_COUNTRY_HINTS = [
    ("US", re.compile(r"\bU\.?S\.?A?\b|United States|Canada", re.I)),
    ("IN", re.compile(r"\bIndia\b|Bangalore|Hyderabad|Noida|Pune", re.I)),
    ("UK", re.compile(r"\bUK\b|United Kingdom|London\b", re.I)),
    ("PT", re.compile(r"\bPortugal\b|Lisboa|Lisbon", re.I)),
]


def classify_recruiter(name, headline, profile_url, job_location=""):
    """
    Deriva metadados do recruiter. Nada é descartado aqui — a classificação
    serve só para o dashboard poder filtrar depois.
    """
    headline = headline or ""
    is_recruiter = bool(_RECRUITER_RE.search(headline))

    # O subdomínio do perfil indica o país (br.linkedin.com, in.linkedin.com...).
    # 'www' é neutro, então cai para as pistas de headline / localização da vaga.
    country = ""
    m = re.match(r"https?://([a-z]{2})\.linkedin\.com", profile_url or "", re.I)
    if m and m.group(1).lower() != "ww":
        country = m.group(1).upper()
    if not country:
        for code, rx in _COUNTRY_HINTS:
            if rx.search(headline):
                country = code
                break
    if not country and re.search(r"brasil|brazil|\bmg\b|\bsp\b|\brj\b", job_location or "", re.I):
        country = "BR"

    return {"is_recruiter": is_recruiter, "country": country or "?"}


def recruiter_id(profile_url):
    """ID estável baseado na URL do perfil (normalizada)."""
    norm = profile_url.lower().rstrip("/")
    norm = re.sub(r"^https?://([a-z]{2}\.|www\.)?linkedin\.com", "", norm)
    norm = re.sub(r"/(pt|en|es)$", "", norm)  # sufixo de idioma
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


# ─── Persistência ─────────────────────────────────────────────────────────────

def load_recruiters():
    if RECRUITERS_FILE.exists():
        try:
            with open(RECRUITERS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Falha ao ler recruiters.json: %s", e)
    return {"recruiters": [], "last_updated": ""}


def save_recruiters(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(RECRUITERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("recruiters.json salvo com %d recruiters", len(data.get("recruiters", [])))


# ─── Agregação ────────────────────────────────────────────────────────────────

def merge_jobs_into_directory(jobs):
    """
    Junta os recruiters presentes em `jobs` ao diretório existente.
    Recruiter já conhecido tem a vaga anexada e o last_seen atualizado.
    Retorna o diretório completo (pronto para salvar).
    """
    data = load_recruiters()
    by_id = {r["id"]: r for r in data.get("recruiters", [])}
    podados = _prune_directory(by_id)
    if podados:
        log.info("Diretorio: %d recruiters removidos pelos criterios atuais", podados)
    now = datetime.now(timezone.utc).isoformat()

    novos, atualizados, ignoradas = 0, 0, 0

    for job in jobs:
        rec = job.get("recruiter")
        if not rec or not rec.get("profile_url"):
            continue
        # Ignora vagas irrelevantes para o perfil — nao adianta guardar o
        # contato de quem so publica coisa fora da area.
        if not _job_qualifies(job):
            ignoradas += 1
            continue

        rid = recruiter_id(rec["profile_url"])
        meta = classify_recruiter(
            rec.get("name", ""), rec.get("headline", ""),
            rec["profile_url"], job.get("location", ""),
        )

        job_ref = {
            "id": job.get("id"),
            "title": job.get("title"),
            "company": job.get("company"),
            "url": job.get("url"),
            "score": job.get("score", 0),
            "fit_level": job.get("fit_level", "baixo"),
            "found_at": job.get("found_at", now),
        }

        entry = by_id.get(rid)
        if entry is None:
            by_id[rid] = {
                "id": rid,
                "name": rec.get("name", ""),
                "profile_url": rec["profile_url"],
                "headline": rec.get("headline", ""),
                "is_recruiter": meta["is_recruiter"],
                "country": meta["country"],
                "companies": [job.get("company")] if job.get("company") else [],
                "jobs": [job_ref],
                "first_seen": now,
                "last_seen": now,
                "message": None,
            }
            novos += 1
            continue

        # Já existe: atualiza dados mais recentes e anexa a vaga
        entry["last_seen"] = now
        if rec.get("headline"):
            entry["headline"] = rec["headline"]
            entry["is_recruiter"] = meta["is_recruiter"]
        if meta["country"] != "?":
            entry["country"] = meta["country"]

        comp = job.get("company")
        if comp and comp not in entry.setdefault("companies", []):
            entry["companies"].append(comp)

        existing_ids = {j.get("id") for j in entry.setdefault("jobs", [])}
        if job_ref["id"] not in existing_ids:
            entry["jobs"].insert(0, job_ref)
            entry["jobs"] = entry["jobs"][:MAX_JOBS_PER_RECRUITER]
        atualizados += 1

    # 2a passada: vagas sem recruiter herdam o contato ja conhecido da empresa.
    # Cobre o caso comum de a empresa publicar varias vagas e so uma expor
    # quem publicou.
    inferidas = _infer_by_company(jobs, by_id, now)

    for r in by_id.values():
        r["priority"] = compute_priority(r)

    recruiters = sorted(
        by_id.values(),
        key=lambda r: (r.get("priority", 0), r.get("last_seen", "")),
        reverse=True,
    )
    log.info("Diretorio de recruiters: %d novos, %d atualizados, %d no total "
             "(%d vagas ignoradas por score < %d, %d inferidas via empresa)",
             novos, atualizados, len(recruiters), ignoradas, MIN_JOB_SCORE, inferidas)

    return {"recruiters": recruiters, "last_updated": now}



def _company_key(name):
    """Normaliza o nome da empresa para casar variacoes de escrita."""
    if not name or name == "N/A":
        return ""
    k = name.lower().strip()
    k = re.sub(r"[^\w\s]", " ", k)
    # remove sufixos societarios que variam entre anuncios
    k = re.sub(r"\b(ltda|s\s*a|sa|me|eireli|epp|inc|llc|co|group|brasil|brazil)\b", " ", k)
    return re.sub(r"\s+", " ", k).strip()


def _infer_by_company(jobs, by_id, now):
    """
    Liga vagas sem recruiter ao contato ja conhecido da mesma empresa.

    A vaga entra na lista do recruiter marcada com inferred=True, para o
    dashboard deixar claro que o contato veio da empresa e nao daquela vaga.
    Retorna quantas vagas foram inferidas.
    """
    limite = datetime.now(timezone.utc) - timedelta(days=INFER_WINDOW_DAYS)

    # empresa -> recruiter mais recente que publicou por ela
    por_empresa = {}
    for r in by_id.values():
        try:
            visto = datetime.fromisoformat((r.get("last_seen") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if visto < limite:
            continue
        for comp in r.get("companies", []):
            key = _company_key(comp)
            if not key:
                continue
            atual = por_empresa.get(key)
            if atual is None or visto > atual[1]:
                por_empresa[key] = (r, visto)

    inferidas = 0
    for job in jobs:
        if job.get("recruiter"):
            continue  # ja tem contato proprio
        if not _job_qualifies(job):
            continue
        key = _company_key(job.get("company", ""))
        if not key or key not in por_empresa:
            continue

        entry = por_empresa[key][0]
        if job.get("id") in {j.get("id") for j in entry.get("jobs", [])}:
            continue

        entry["jobs"].insert(0, {
            "id": job.get("id"),
            "title": job.get("title"),
            "company": job.get("company"),
            "url": job.get("url"),
            "score": job.get("score", 0),
            "fit_level": job.get("fit_level", "baixo"),
            "found_at": job.get("found_at", now),
            "inferred": True,
        })
        entry["jobs"] = entry["jobs"][:MAX_JOBS_PER_RECRUITER]
        entry["last_seen"] = now
        inferidas += 1

    return inferidas


def compute_priority(r) -> int:
    """
    0-100: por onde começar a abordagem.
      +25 é recrutador de fato (não o gestor que postou a própria vaga)
      +15 perfil no Brasil
      até +32 volume de vagas da área publicadas (8 por vaga, até 4)
      até +15 aderência da melhor vaga (60 -> 0, 100 -> 15)
      até +13 recência (7 dias: 13, 30 dias: 6)
    """
    jobs = r.get("jobs") or []
    pts = 0
    if r.get("is_recruiter"):
        pts += 25
    if r.get("country") == "BR":
        pts += 15
    pts += min(len(jobs), 4) * 8
    best = max((j.get("score", 0) for j in jobs), default=0)
    pts += max(0, min(15, round((best - MIN_JOB_SCORE) * 15 / (100 - MIN_JOB_SCORE))))
    try:
        visto = datetime.fromisoformat((r.get("last_seen") or "").replace("Z", "+00:00"))
        dias = (datetime.now(timezone.utc) - visto).days
        pts += 13 if dias <= 7 else (6 if dias <= 30 else 0)
    except ValueError:
        pass
    return min(pts, 100)


def _job_qualifies(job) -> bool:
    """Só vaga da área e com aderência mínima liga um recruiter ao diretório."""
    return (job.get("score", 0) >= MIN_JOB_SCORE
            and classify_title(job.get("title", "")) == "core")


def _prune_directory(by_id) -> int:
    """
    Reaplica os critérios atuais a quem já está no diretório. Endurecer o
    filtro (ex.: score 40 -> 60) passa a valer também para o histórico.
    Retorna quantos recruiters saíram.
    """
    removidos = 0
    for rid in list(by_id):
        r = by_id[rid]
        r["jobs"] = [j for j in r.get("jobs", []) if _job_qualifies(j)]
        if not r["jobs"]:
            del by_id[rid]
            removidos += 1
    return removidos


def compute_recruiter_stats(data):
    recs = data.get("recruiters", [])
    return {
        "total": len(recs),
        "tech_recruiters": sum(1 for r in recs if r.get("is_recruiter")),
        "brasil": sum(1 for r in recs if r.get("country") == "BR"),
        "com_mensagem": sum(1 for r in recs if r.get("message")),
        "com_convite": sum(1 for r in recs if r.get("invite_note")),
        "prioridade_alta": sum(1 for r in recs if r.get("priority", 0) >= 70),
    }
