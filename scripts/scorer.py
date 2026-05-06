"""
Job Radar — Sistema de scoring de vagas
Score 0–100 calculado com base em skills, localização, nível e keywords.
"""

import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

# ─── Perfil do candidato ──────────────────────────────────────────────────────

CANDIDATE_SKILLS = {
    # Core (valem +3)
    "python", "docker", "linux", "prometheus", "grafana",
    # Extras (valem +2)
    "zabbix", "loki", "kubernetes", "k3s", "jenkins", "terraform",
    "gcp", "aws", "wireguard", "mikrotik", "fortigate", "vmware",
    "n8n", "flask", "rest", "api", "github actions", "ci/cd",
    "ansible", "nginx", "bash", "shell", "git", "elk",
    "alertmanager", "grafana loki", "datadog",
}

CORE_SKILLS = {"python", "docker", "linux", "prometheus", "grafana"}

POSITIVE_KEYWORDS = {
    "observabilidade", "observability", "sre", "monitoramento", "monitoring",
    "infraestrutura", "infrastructure", "automação", "automation",
    "telecom", "plataforma", "platform", "devops", "devsecops",
    "cloud", "on-premise", "on premise", "noc",
}

NEGATIVE_KEYWORDS = {
    "arquiteto", "architect", "manager", "diretor", "director",
    "cto", "vp de", "head de", "mobile", "ios", "android",
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


def score_job(job_dict: dict) -> ScoreResult:
    text = _full_text(job_dict)
    text_lower = text.lower()

    # ── Rejeição automática ─────────────────────────────────────────────────
    for pattern in SENIOR_PATTERNS:
        if re.search(pattern, text_lower):
            return ScoreResult(
                total=0, skills=0, location=0, level=0,
                keywords=0, salary=0,
                skills_match=[], skills_gap=[],
                fit_level="baixo", rejected=True,
                rejection_reason=f"Padrão sênior detectado: {pattern}",
            )

    for kw in NEGATIVE_KEYWORDS:
        if kw in text_lower:
            return ScoreResult(
                total=0, skills=0, location=0, level=0,
                keywords=0, salary=0,
                skills_match=[], skills_gap=[],
                fit_level="baixo", rejected=True,
                rejection_reason=f"Keyword negativa: {kw}",
            )

    # ── Skills match (cap 40) ───────────────────────────────────────────────
    skills_found = []
    skills_missing = []
    for skill in CANDIDATE_SKILLS:
        pattern = r"\b" + re.escape(skill) + r"\b"
        if re.search(pattern, text_lower):
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
    if re.search(r"\bj[uú]nior\b|\bjr\b", text_lower):
        level_score = 20
    elif re.search(r"\bpleno\b|\bpl\b\s+(?:devops|engenheiro|analista)", text_lower):
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
            # Ainda salva com score 0 e status arquivado
            job["score"] = 0
            job["score_breakdown"] = {}
            job["skills_match"] = []
            job["skills_gap"] = []
            job["fit_level"] = "baixo"
            job["status"] = "arquivada"
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
