"""
Job Radar — Geração de carta de apresentação via Groq (gratuito)
Modelo: llama-3.3-70b-versatile (substituto do 3.1-70b descontinuado)
"""

import json
import logging
import os

from groq import Groq

log = logging.getLogger(__name__)

# Perfil do candidato — base factual usada nos prompts.
# Mantenha fiel ao currículo: o modelo não deve inventar experiência.
CANDIDATE_PROFILE = """Eric Dias Lemos — DevOps / Platform Engineer, 3 anos de experiência.
Engenharia da Computação concluída (Centro Universitário Una, 2026). Belo Horizonte/MG.

Atuação atual — Método Telecom (desde mar/2025), DevOps | Cloud & Infraestrutura:
- Construiu do zero uma plataforma interna (IDP) com Gitea, Jenkins, Docker Registry,
  Trivy, Gitleaks e SonarQube — DevSecOps embutido em cada commit, stack open source.
- Sustenta hospedagem, confiabilidade e CI/CD de 30+ sistemas em produção;
  4 servidores e 25+ máquinas Linux monitoradas.
- Observabilidade com Zabbix, Prometheus, Grafana e Loki: dashboards, alertas
  multi-canal e abertura automática de chamados.
- Pipelines Jenkins containerizado em EC2 e Kubernetes (K3s), testes em múltiplos
  níveis e Blue-Green Deployment com zero downtime. Provisionamento com Terraform.
- Ambiente híbrido GCP + AWS + VMware, com migração de sistemas e FinOps.
- Exporters em Python integrando APIs de SBCs de telefonia ao Prometheus.
- Redes e segurança: Fortigate, WireGuard, MikroTik, segmentação e troubleshooting.

MUG Solutions (desde mar/2026), Cloud Engineer | DevOps — responsável pela infraestrutura:
- Reconstruiu a infra como código (Terraform + Ansible) — ambiente 100% reprodutível.
- Conduziu avaliação multi-cloud e migrou a stack de GCP para AWS reaproveitando
  100% da camada Ansible — migração sem retrabalho.
- CI/CD com GitHub Actions e deploy blue-green (Next.js + Supabase).
- Análise de custo/capacidade que reduziu gasto de nuvem.

Antes: Analista de Redes Jr (Century) e Assistente de NOC (Kater) — Zabbix, Grafana,
MikroTik, Huawei, OLT, VLAN, troubleshooting camada 2/3. Militar do Exército (Comunicações).

Stack: Python, Docker, Kubernetes/K3s, Terraform, Ansible, Jenkins, GitHub Actions,
Prometheus, Grafana, Loki, Zabbix, AWS (EC2, EBS, IAM, Elastic IP), GCP (Compute Engine,
Cloud Run), VMware, Nginx, Cloudflare, Fortigate, WireGuard, FastAPI, Flask, N8N.

Certificações: AWS Cloud Practitioner (curso), Google DevOps Essentials,
Cisco NDG Linux Essentials, Networking Basics. Cursando Google Cloud Associate
Cloud Engineer."""

SYSTEM_PROMPT = """Você escreve cartas de apresentação em nome de Eric Dias Lemos.

PERFIL DO CANDIDATO (use só o que está aqui, nunca invente experiência):
""" + CANDIDATE_PROFILE + """

Regras obrigatórias:
- Tom direto e técnico, sem exageros ou adjetivos vazios
- Máximo 4 parágrafos curtos (não mais de 5 linhas cada)
- Não começar com "Prezados" ou frases genéricas
- Destacar 2-3 pontos do perfil que casam com a vaga, preferindo
  resultados concretos (ex: plataforma interna para 30+ sistemas,
  migração GCP→AWS sem retrabalho, blue-green com zero downtime)
- Nunca citar tecnologia ou experiência que não esteja no perfil acima
- Finalizar com disponibilidade para entrevista
- Escrever em português brasileiro formal-técnico"""

GROQ_MODEL = "llama-3.3-70b-versatile"


def generate_cover_letter(job: dict) -> str:
    """Gera carta personalizada para a vaga. Retorna texto da carta."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY não configurada")

    client = Groq(api_key=api_key)

    title = job.get("title", "")
    company = job.get("company", "")
    description = job.get("description", "")[:1500]
    skills_match = job.get("skills_match", [])
    skills_gap = job.get("skills_gap", [])

    user_prompt = f"""Vaga: {title} na {company}

Descrição da vaga (resumida):
{description}

Skills da vaga que Eric possui: {', '.join(skills_match[:10]) if skills_match else 'DevOps, Linux, Docker'}
Skills da vaga que Eric não possui: {', '.join(skills_gap[:5]) if skills_gap else 'nenhuma relevante'}

Escreva uma carta de apresentação personalizada e objetiva para Eric se candidatar \
a esta vaga. Foque nas skills coincidentes e no valor que ele pode agregar à empresa."""

    log.info("Gerando carta para: %s @ %s (Groq/%s)", title, company, GROQ_MODEL)

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        max_tokens=600,
        temperature=0.7,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    letter = response.choices[0].message.content.strip()
    log.info("Carta gerada: %d caracteres", len(letter))
    return letter


def generate_letter_batch(jobs: list[dict]) -> dict[str, str]:
    """Gera cartas para múltiplas vagas. Retorna dict {job_id: carta}."""
    results: dict[str, str] = {}
    for job in jobs:
        job_id = job.get("id", "")
        try:
            letter = generate_cover_letter(job)
            results[job_id] = letter
        except Exception as e:
            log.error("Falha ao gerar carta para %s: %s", job_id, e)
            results[job_id] = _fallback_letter(job)
    return results


def _fallback_letter(job: dict) -> str:
    title = job.get("title", "DevOps Engineer")
    company = job.get("company", "empresa")
    # dict.get(key, default) só retorna default se a chave não existir.
    # Se for lista vazia [], retorna [] e o join vira "". Trata os dois casos.
    skills_list = job.get("skills_match") or ["Docker", "Linux", "Python"]
    skills = ", ".join(skills_list[:3])
    return f"""Prezados da {company},

Tenho interesse na vaga de {title} e acredito que minha experiência em {skills} \
se alinha diretamente com as necessidades descritas.

Atuo há mais de 3 anos em ambientes de infraestrutura Linux com foco em \
automação, monitoramento (Prometheus/Grafana) e containerização com Docker e Kubernetes. \
Já implementei pipelines CI/CD com GitHub Actions e Jenkins em ambientes produtivos.

Estou disponível para uma conversa técnica quando for conveniente para a equipe.

Atenciosamente,
Eric Dias Lemos
ericdias0603@gmail.com"""


# ─── Abordagem de recruiters (LinkedIn) ───────────────────────────────────────
# Duas peças por recrutador:
#   invite_note — vai no convite de conexão. O LinkedIn corta em 300 caracteres.
#   message     — mandada depois que ele aceita; aí cabe um pouco mais.

INVITE_LIMIT = 300

RECRUITER_SYSTEM_PROMPT = """Você escreve a abordagem de LinkedIn de Eric Dias Lemos \
para recrutadores que publicaram vagas de DevOps/Cloud/Platform.

PERFIL (use só o que está aqui, nunca invente experiência):
""" + CANDIDATE_PROFILE + """

Devolva JSON com duas chaves:
- "convite": nota do convite de conexão. NO MÁXIMO 280 caracteres. Cite a vaga
  e uma prova concreta do perfil. Termine sem pergunta longa.
- "mensagem": mensagem para depois que o convite for aceito, até 70 palavras.
  Retome a vaga, dê 2 resultados concretos que casam com ela e termine com uma
  pergunta simples e de baixo atrito (ex: "posso te mandar meu currículo?").

Regras: tom cordial e direto, como uma pessoa real escreveria; português
brasileiro informal-profissional; nada de "Prezado(a)" ou jargão corporativo;
nenhuma tecnologia ou resultado fora do perfil."""


def _fit(text: str, limit: int) -> str:
    """Corta no limite sem quebrar palavra, preferindo fim de frase."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    corte = text[:limit]
    fim = max(corte.rfind(". "), corte.rfind("! "), corte.rfind("? "))
    if fim >= limit * 0.6:
        return corte[:fim + 1].strip()
    return corte[:corte.rfind(" ")].rstrip(" ,;:") + "…"


def _best_job(recruiter: dict) -> dict:
    jobs = recruiter.get("jobs") or []
    diretas = [j for j in jobs if not j.get("inferred")] or jobs
    return max(diretas, key=lambda j: j.get("score", 0)) if diretas else {}


def generate_recruiter_outreach(recruiter: dict) -> dict:
    """Gera {'invite_note', 'message'} via Groq para um recruiter."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY não configurada")

    best = _best_job(recruiter)
    jobs = recruiter.get("jobs") or []
    first_name = (recruiter.get("name") or "").split()[0] if recruiter.get("name") else ""
    outras = len(jobs) - 1

    user_prompt = f"""Recrutador: {recruiter.get('name', '')} (primeiro nome: {first_name})
Cargo dele: {recruiter.get('headline', 'não informado')}

Vaga que ele publicou: {best.get('title', 'vaga de tecnologia')}
Empresa: {best.get('company', 'não informada')}
{f'Ele também tem outras {outras} vaga(s) da área abertas.' if outras > 0 else ''}

Escreva o JSON com "convite" e "mensagem"."""

    client = Groq(api_key=api_key)
    log.info("Gerando abordagem para recruiter: %s (Groq/%s)", recruiter.get("name"), GROQ_MODEL)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        max_tokens=400,
        temperature=0.7,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": RECRUITER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    data = json.loads(response.choices[0].message.content)
    invite = _fit(data.get("convite", ""), INVITE_LIMIT)
    message = (data.get("mensagem") or "").strip()
    if not invite or not message:
        raise ValueError(f"resposta incompleta da Groq: {list(data)}")
    return {"invite_note": invite, "message": message}


def generate_recruiter_messages(recruiters: list[dict], limit: int = 15) -> int:
    """
    Preenche invite_note e message de quem ainda não tem, começando pelos de
    maior prioridade. `limit` protege a cota da API.
    """
    pendentes = [r for r in recruiters
                 if r.get("jobs") and not (r.get("invite_note") and r.get("message"))]
    pendentes.sort(key=lambda r: r.get("priority", 0), reverse=True)

    geradas = 0
    for rec in pendentes[:limit]:
        try:
            rec.update(generate_recruiter_outreach(rec))
            rec["outreach_source"] = "groq"
        except Exception as e:
            log.error("Falha ao gerar abordagem para %s: %s: %s",
                      rec.get("name"), type(e).__name__, e)
            rec.update(_fallback_outreach(rec))
            rec["outreach_source"] = "fallback"
        geradas += 1
    return geradas


def _fallback_outreach(recruiter: dict) -> dict:
    """Textos padrão quando a Groq falha. O convite respeita os 300 caracteres."""
    best = _best_job(recruiter)
    first_name = (recruiter.get("name") or "").split()[0] if recruiter.get("name") else ""
    oi = f"Oi {first_name}" if first_name else "Oi"
    vaga = best.get("title", "a vaga de DevOps")
    empresa = best.get("company", "")
    onde = f" na {empresa}" if empresa and empresa != "N/A" else ""

    invite = _fit(
        f"{oi}! Vi sua vaga de {vaga}{onde}. Sou DevOps há 3 anos e hoje cuido "
        f"do CI/CD e da observabilidade de 30+ sistemas em produção. "
        f"Gostaria de me conectar.",
        INVITE_LIMIT,
    )
    message = (
        f"{oi}, obrigado por aceitar!\n\n"
        f"Sobre a vaga de {vaga}{onde}: construí do zero uma plataforma interna "
        f"(Jenkins, SonarQube, Trivy) que sustenta 30+ sistemas em produção, e "
        f"conduzi uma migração GCP → AWS com Terraform e Ansible sem retrabalho.\n\n"
        f"Posso te enviar meu currículo?"
    )
    return {"invite_note": invite, "message": message}
