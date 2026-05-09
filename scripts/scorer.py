"""
Job Radar — Sistema de scoring de vagas
Score 0–100 calculado com base em skills, localização, nível e keywords.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

# ─── Perfil do candidato ──────────────────────────────────────────────────────

CANDIDATE_SKILLS = {
    # Core (valem +3)
    "python", "docker", "linux", "prometheus", "grafana",
    # Cloud — AWS (valem +2)
    "aws", "ec2", "s3", "rds", "lambda", "cloudwatch", "cloudformation",
    "eks", "ecs", "iam", "vpc", "route53",
    # Cloud — GCP (valem +2)
    "gcp", "google cloud", "gke", "cloud run", "bigquery", "cloud storage",
    # Cloud — Azure (valem +2)
    "azure", "aks", "azure devops",
    # IaC / Orquestração (valem +2)
    "terraform", "ansible", "kubernetes", "helm", "argocd", "pulumi",
    # CI/CD (valem +2)
    "github actions", "ci/cd", "jenkins", "gitlab ci", "circleci",
    # Observabilidade (valem +2)
    "zabbix", "datadog", "loki", "alertmanager", "grafana loki", "elk",
    "newrelic", "dynatrace",
    # Infra / Rede (valem +2)
    "nginx", "bash", "shell", "git", "rest", "api",
    "k3s", "wireguard", "mikrotik", "fortigate", "vmware",
    "n8n", "flask",
}

CORE_SKILLS = {"python", "docker", "linux", "prometheus", "grafana"}

POSITIVE_KEYWORDS = {
    # Área
    "observabilidade", "observability", "sre", "monitoramento", "monitoring",
    "infraestrutura", "infrastructure", "automação", "automation",
    "telecom", "plataforma", "platform", "devops", "devsecops",
    "on-premise", "on premise", "noc",
    # Cloud genérico
    "cloud", "nuvem", "cloud computing", "computação em nuvem",
    "cloud native", "multicloud", "multi-cloud", "hybrid cloud",
    "cloud operations", "cloudops", "finops",
    "migração para nuvem", "cloud migration",
    # Cargos alvo
    "analista de infraestrutura", "engenheiro de infraestrutura",
    "engenheiro cloud", "analista cloud", "cloud engineer",
    "suporte linux", "administrador linux", "linux admin",
    "administrador cloud", "cloud administrator",
}

NEGATIVE_KEYWORDS = {
    "arquiteto", "architect", "manager", "diretor", "director",
    "cto", "vp de", "head de", "ios developer", "android developer",
    "mobile developer", "mobile engineer",
    "data scientist", "machine learning", "ml engineer",
}

SENIOR_PATTERNS = [
    r"\bs[eê]nior\b",
    r"\bsr\b\.?\s+(?:devops|engenheiro|analista)",
    r"\b8\+?\s*anos\b",
    r"\b10\+?\s*anos\b",
    r"\.net\s+s[eê]nior",
    r"java\s+s[eê]nior",
]

LOCATION_KEYWORDS_BH = {"belo horizonte", "bh", "contagem", "betim", "minas gerais", "mg"}
LOCATION_KEYWORDS_REMOTE = {"remoto", "remote", "home office", "híbrido", "hibrido", "trabalho remoto"}

SALARY_PATTERN = re.compile(r"r\$\s*([\d.,]+)", re.IGNORECASE)

# ─── Regex pré-compilados (evita re-compilar por job) ────────────────────────
_SENIOR_RE = [re.compile(p) for p in SENIOR_PATTERNS]
_NEGATIVE_RE = [(kw, re.compile(r"\b" + re.escape(kw) + r"\b")) for kw in NEGATIVE_KEYWORDS]
_SKILL_RE = [(skill, re.compile(r"\b" + re.escape(skill) + r"\b")) for skill in CANDIDATE_SKILLS]
_LEVEL_JR_RE = re.compile(r"\bj[uú]nior\b|\bjr\b")
_LEVEL_PL_RE = re.compile(r"\bpleno\b|\bpl\b\s+(?:devops|engenheiro|analista)")


def is_obviously_rejected(text: str) -> bool:
    """
    Verifica rápido se um texto (geralmente só o título) bate em padrões de
    rejeição automática (sênior / palavra-chave negativa).
    Usado pelo scraper para pular fetch de descrições de vagas que serão
    descartadas de qualquer jeito. Evita ~30-40% das requisições.
    """
    text_lower = text.lower()
    for rx in _SENIOR_RE:
        if rx.search(text_lower):
            return True
    for _, rx in _NEGATIVE_RE:
        if rx.search(text_lower):
            return True
    return False

# ─── Extração de email de contato ─────────────────────────────────────────────
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_SKIP_EMAIL_LOCALS = {
    "noreply", "no-reply", "support", "contato", "info", "contact",
    "jobs", "vagas", "careers", "rh", "recrutamento", "selecao",
    "cadastro", "candidatos", "aplicacao", "apply",
}

def extract_contact_email(text: str) -> Optional[str]:
    """Retorna o primeiro email de contato humano encontrado no texto."""
    for match in _EMAIL_RE.finditer(text):
        email = match.group(0).lower()
        local = email.split("@")[0].rstrip(".")
        if local not in _SKIP_EMAIL_LOCALS and len(local) > 2:
            return email
    return None


@dataclass
class ScoreResult:
    total: int
    skills: int
    location: int
    level: int
    keywords: int
    salary: int
    skills_match: list[str]
    skills_gap: list[str]
    fit_level: str
    rejected: bool
    rejection_reason: str = ""
    contact_email: Optional[str] = None


def score_job(job_dict: dict) -> ScoreResult:
    text = _full_text(job_dict)
    text_lower = text.lower()

    # ── Email de contato ────────────────────────────────────────────────────
    contact_email = extract_contact_email(text)

    # ── Rejeição automática ─────────────────────────────────────────────────
    for rx in _SENIOR_RE:
        if rx.search(text_lower):
            return ScoreResult(
                total=0, skills=0, location=0, level=0,
                keywords=0, salary=0,
                skills_match=[], skills_gap=[],
                fit_level="baixo", rejected=True,
                rejection_reason=f"Padrão sênior detectado: {rx.pattern}",
                contact_email=contact_email,
            )

    for kw, rx in _NEGATIVE_RE:
        if rx.search(text_lower):
            return ScoreResult(
                total=0, skills=0, location=0, level=0,
                keywords=0, salary=0,
                skills_match=[], skills_gap=[],
                fit_level="baixo", rejected=True,
                rejection_reason=f"Keyword negativa: {kw}",
                contact_email=contact_email,
            )

    # ── Skills match (cap 40) ───────────────────────────────────────────────
    skills_found = []
    skills_missing = []
    for skill, rx in _SKILL_RE:
        if rx.search(text_lower):
            skills_found.append(skill)
        else:
            skills_missing.append(skill)

    skills_score = 0
    for skill in skills_found:
        skills_score += 3 if skill in CORE_SKILLS else 2
    skills_score = min(skills_score, 40)

    # ── Localização (20) ────────────────────────────────────────────────────
    loc_text = (job_dict.get("location", "") + " " + job_dict.get("description", "")).lower()
    location_score = 0
    if any(kw in loc_text for kw in LOCATION_KEYWORDS_REMOTE):
        location_score = 20
    elif any(kw in loc_text for kw in LOCATION_KEYWORDS_BH):
        location_score = 20
    # outra cidade presencial = 0

    # ── Nível (20) ──────────────────────────────────────────────────────────
    level_score = 10  # padrão: sem menção
    if _LEVEL_JR_RE.search(text_lower):
        level_score = 20
    elif _LEVEL_PL_RE.search(text_lower):
        level_score = 15
    # sênior já foi rejeitado acima

    # ── Keywords positivas (cap 10) ─────────────────────────────────────────
    kw_score = 0
    for kw in POSITIVE_KEYWORDS:
        if kw in text_lower:
            kw_score += 2
    kw_score = min(kw_score, 10)

    # ── Salário (10) ────────────────────────────────────────────────────────
    salary_score = 5  # não informado
    salary_text = job_dict.get("salary", "")
    if salary_text:
        values = [_parse_salary(v) for v in SALARY_PATTERN.findall(salary_text)]
        values = [v for v in values if v > 0]
        if values:
            max_val = max(values)
            if max_val >= 4000:
                salary_score = 10
            elif max_val >= 2000:
                salary_score = 5
            else:
                salary_score = 0

    total = skills_score + location_score + level_score + kw_score + salary_score
    total = min(total, 100)

    if total >= 70:
        fit_level = "alto"
    elif total >= 50:
        fit_level = "medio"
    else:
        fit_level = "baixo"

    if contact_email:
        log.info("Email de contato detectado: %s → %s", contact_email, job_dict.get("title", ""))

    return ScoreResult(
        total=total,
        skills=skills_score,
        location=location_score,
        level=level_score,
        keywords=kw_score,
        salary=salary_score,
        skills_match=sorted(skills_found),
        skills_gap=sorted(skills_missing),
        fit_level=fit_level,
        rejected=False,
        contact_email=contact_email,
    )


def apply_scores(jobs: list[dict]) -> list[dict]:
    scored = []
    rejected = 0
    for job in jobs:
        result = score_job(job)
        if result.rejected:
            log.info("REJEITADO [%s]: %s @ %s — %s",
                     result.rejection_reason, job.get("title"), job.get("company"), job.get("url"))
            rejected += 1
            job["score"] = 0
            job["score_breakdown"] = {}
            job["skills_match"] = []
            job["skills_gap"] = []
            job["fit_level"] = "baixo"
            job["status"] = "arquivada"
            job["contact_email"] = result.contact_email
        else:
            log.info("Score %d [%s] — %s @ %s",
                     result.total, result.fit_level, job.get("title"), job.get("company"))
            job["score"] = result.total
            job["score_breakdown"] = {
                "skills": result.skills,
                "location": result.location,
                "level": result.level,
                "keywords": result.keywords,
                "salary": result.salary,
            }
            job["skills_match"] = result.skills_match
            job["skills_gap"] = result.skills_gap
            job["fit_level"] = result.fit_level
            job["contact_email"] = result.contact_email
            if job.get("status") == "nova":
                pass  # mantém "nova"
        scored.append(job)

    log.info("Scoring concluído: %d processadas, %d rejeitadas", len(scored), rejected)
    return scored


def compute_stats(jobs: list[dict]) -> dict:
    total = len(jobs)
    alto = sum(1 for j in jobs if j.get("fit_level") == "alto" and j.get("status") != "arquivada")
    medio = sum(1 for j in jobs if j.get("fit_level") == "medio" and j.get("status") != "arquivada")
    baixo = sum(1 for j in jobs if j.get("fit_level") == "baixo" or j.get("status") == "arquivada")
    enviadas = sum(1 for j in jobs if j.get("status") == "enviada")
    return {
        "total": total,
        "alto_fit": alto,
        "medio_fit": medio,
        "baixo_fit": baixo,
        "enviadas": enviadas,
    }


def _full_text(job: dict) -> str:
    return " ".join([
        job.get("title", ""),
        job.get("company", ""),
        job.get("description", ""),
        job.get("location", ""),
    ])


def _parse_salary(raw: str) -> float:
    try:
        return float(raw.replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0
