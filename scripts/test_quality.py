"""
Testes de qualidade dos dados: portao de cargo, diretorio de recruiters,
convite de conexao e dedup contra vagas arquivadas.
Rodar: python scripts/test_quality.py   (sem rede, sem API)
"""
import json
import logging
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
logging.disable(logging.INFO)

import letter_gen
import recruiters
import scraper
from scorer import classify_title, score_job

FALHAS = []


def check(nome, cond, detalhe=""):
    print(("  ok    " if cond else "  FALHA ") + nome + (f"  ({detalhe})" if detalhe and not cond else ""))
    if not cond:
        FALHAS.append(nome)


print("[portao de cargo]")
casos = {
    "DevOps Engineer": "core",
    "Analista de Devsecops": "core",
    "Platform Engineer (Kubernetes) - Remote Work": "core",
    "Azure Cloud Engineer": "core",
    "Analista de Infraestrutura Pleno": "core",
    "Analista de Sistemas e Aplicacoes ( Linux )": "core",
    "Analista de Redes": "adjacent",
    "Plataforma de Dados": "adjacent",
    "Staff Software Engineer - Backend Java": "senior",
    "Analista de Infraestrutura Sr": "senior",
    "Cyber Security Junior": "adjacent",
    "Data Engineer (AWS)": "off",
    "Desenvolvedor Fullstack Node e React": "off",
    "Engenheiro Civil Especialista - Infraestrutura Rodoviaria": "off",
    "Analista Fiscal": "off",
    "Analista de Sistemas": "off",
}
for titulo, esperado in casos.items():
    got = classify_title(titulo)
    check(f"{titulo!r} -> {esperado}", got == esperado, f"veio {got}")

print("[score_job]")
base = {"company": "Acme", "location": "Remoto",
        "description": "AWS Docker Kubernetes Terraform Python Linux Prometheus Grafana CI/CD"}
r = score_job(dict(base, title="Staff Software Engineer - Backend Java"))
check("backend java com stack DevOps na descricao e rejeitada", r.rejected)
r = score_job(dict(base, title="Analista de DevSecOps"))
check("devsecops aceita e ganha bonus de cargo", (not r.rejected) and r.title_bonus == 10)
r = score_job(dict(base, title="Analista de Redes - Selecao em Andamento"))
check("carreira vizinha (redes) e rejeitada", r.rejected)
r = score_job(dict(base, title="Analista de Infraestrutura - Jr"))
check("infraestrutura jr aceita", not r.rejected)

print("[diretorio de recruiters]")
tmp = Path(tempfile.mkdtemp())
recruiters.RECRUITERS_FILE = tmp / "recruiters.json"
now = datetime.now(timezone.utc).isoformat()
velho = {"id": "old", "name": "Antigo", "profile_url": "https://br.linkedin.com/in/antigo",
         "headline": "Tech Recruiter", "is_recruiter": True, "country": "BR", "companies": ["X"],
         "jobs": [{"id": "v0", "title": "Especialista de Desenvolvimento I", "score": 46}],
         "first_seen": now, "last_seen": now, "message": None}
recruiters.save_recruiters({"recruiters": [velho], "last_updated": now})


def vaga(i, titulo, score, rec=None, empresa="Dexian"):
    return {"id": i, "title": titulo, "company": empresa, "url": "u" + i, "score": score,
            "fit_level": "alto", "location": "Remoto", "found_at": now, "recruiter": rec}


ana = {"name": "Ana Souza", "profile_url": "https://br.linkedin.com/in/ana-souza/pt",
       "headline": "Tech Recruiter | Talent Acquisition"}
d = recruiters.merge_jobs_into_directory([
    vaga("a", "DevOps Engineer", 72, ana),
    vaga("b", "Desenvolvedor Fullstack", 80, {"name": "Bia", "profile_url": "https://br.linkedin.com/in/bia",
                                              "headline": "Recruiter"}),
    vaga("c", "SRE Pleno", 66),                       # sem recruiter -> inferida pela empresa
    vaga("d", "Cloud Engineer", 50),                  # abaixo do score minimo
])
nomes = {x["name"]: x for x in d["recruiters"]}
check("recruiter antigo (score 46) podado pelo criterio atual", "Antigo" not in nomes)
check("recruiter de vaga fora da area nao entra", "Bia" not in nomes)
check("recruiter de vaga DevOps entra", "Ana Souza" in nomes)
ana_d = nomes.get("Ana Souza", {})
check("vaga sem recruiter da mesma empresa foi inferida",
      any(j.get("inferred") for j in ana_d.get("jobs", [])))
check("vaga com score < 60 nao foi associada",
      all(j["id"] != "d" for j in ana_d.get("jobs", [])))
check("prioridade calculada", ana_d.get("priority", 0) >= 70, f"prioridade={ana_d.get('priority')}")

print("[convite de conexao]")
longo = {"name": "Maria Aparecida da Silva", "headline": "Recruiter",
         "jobs": [{"title": "Engenheiro(a) de Plataforma Cloud Pleno com foco em Kubernetes e Observabilidade "
                            "para squad de pagamentos", "company": "Uma Empresa de Nome Bastante Comprido S.A.",
                   "score": 80}]}
fb = letter_gen._fallback_outreach(longo)
check("convite do fallback cabe em 300 caracteres", len(fb["invite_note"]) <= 300,
      f"{len(fb['invite_note'])} chars")
check("mensagem de follow-up gerada", len(fb["message"]) > 50)
check("_fit respeita o limite", len(letter_gen._fit("palavra " * 80, 300)) <= 300)

print("[dedup contra arquivadas]")
scraper.DATA_DIR = tmp
(tmp / "archive.json").write_text(json.dumps({"jobs": [{"id": "x1", "title": "DevOps", "company": "Y"}]}),
                                  encoding="utf-8")
arq = scraper._load_archived_jobs()
check("archive.json lido para o dedup", [j["id"] for j in arq] == ["x1"])

print()
if FALHAS:
    print(f"{len(FALHAS)} falha(s): {FALHAS}")
    sys.exit(1)
print("todos os testes passaram")
