"""
Job Radar — Geração de carta de apresentação via Groq (gratuito)
Modelo: llama-3.3-70b-versatile (substituto do 3.1-70b descontinuado)
"""

import logging
import os

from groq import Groq

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Você é um assistente especializado em escrever cartas de apresentação \
para Eric Dias Lemos, Engenheiro DevOps com experiência em Python, Docker, Linux, \
Prometheus, Grafana, Kubernetes, Terraform, AWS e GCP.

Regras obrigatórias:
- Tom direto e técnico, sem exageros ou adjetivos vazios
- Máximo 4 parágrafos curtos (não mais de 5 linhas cada)
- Não começar com "Prezados" ou frases genéricas
- Destacar sempre 2-3 skills técnicas que coincidem com a vaga
- Não mencionar habilidades que Eric não possui
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


# ─── Mensagem de conexão para recruiters (LinkedIn DM) ────────────────────────

RECRUITER_SYSTEM_PROMPT = """Você escreve mensagens curtas de conexão no LinkedIn \
em nome de Eric Dias Lemos, Engenheiro DevOps (Python, Docker, Linux, Kubernetes, \
Terraform, AWS, GCP, Prometheus, Grafana).

Regras obrigatórias:
- No MÁXIMO 60 palavras (é uma DM de LinkedIn, não uma carta)
- Tom cordial e direto, como uma pessoa real escreveria
- Citar a vaga específica que o recrutador publicou
- Mencionar no máximo 3 skills que casam com a vaga
- Terminar com uma pergunta simples e de baixo atrito
- Nada de "Prezado(a)", "venho por meio desta" ou jargão corporativo
- Português brasileiro, informal-profissional
- Devolver SOMENTE o texto da mensagem, sem assunto nem assinatura"""


def generate_recruiter_message(recruiter: dict) -> str:
    """
    Gera a mensagem de conexão para um recruiter, citando a vaga de maior
    score que ele publicou. Retorna o texto pronto para copiar no LinkedIn.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY não configurada")

    jobs = recruiter.get("jobs") or []
    best = max(jobs, key=lambda j: j.get("score", 0)) if jobs else {}

    first_name = (recruiter.get("name") or "").split()[0] if recruiter.get("name") else ""
    outras = len(jobs) - 1

    user_prompt = f"""Recrutador: {recruiter.get('name', '')} ({first_name})
Cargo dele: {recruiter.get('headline', 'não informado')}

Vaga que ele publicou: {best.get('title', 'vaga de tecnologia')}
Empresa: {best.get('company', 'não informada')}
Score de aderência ao perfil do Eric: {best.get('score', 0)}/100
{f'Ele também publicou outras {outras} vaga(s) que batem com o perfil.' if outras > 0 else ''}

Escreva a mensagem de conexão do Eric para esse recrutador."""

    client = Groq(api_key=api_key)
    log.info("Gerando mensagem para recruiter: %s (Groq/%s)",
             recruiter.get("name"), GROQ_MODEL)

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        max_tokens=220,
        temperature=0.7,
        messages=[
            {"role": "system", "content": RECRUITER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    msg = response.choices[0].message.content.strip()
    log.info("Mensagem gerada: %d caracteres", len(msg))
    return msg


def generate_recruiter_messages(recruiters: list[dict], limit: int = 15) -> int:
    """
    Preenche o campo 'message' dos recruiters que ainda não têm uma.
    Prioriza quem publicou vagas de maior score. `limit` protege a cota da API.
    Retorna quantas mensagens foram geradas.
    """
    pendentes = [r for r in recruiters if not r.get("message") and r.get("jobs")]
    pendentes.sort(
        key=lambda r: max((j.get("score", 0) for j in r["jobs"]), default=0),
        reverse=True,
    )

    geradas = 0
    for rec in pendentes[:limit]:
        try:
            rec["message"] = generate_recruiter_message(rec)
            geradas += 1
        except Exception as e:
            log.error("Falha ao gerar mensagem para %s: %s", rec.get("name"), e)
            rec["message"] = _fallback_recruiter_message(rec)
            geradas += 1
    return geradas


def _fallback_recruiter_message(recruiter: dict) -> str:
    """Mensagem padrão usada quando a API do Groq falha."""
    jobs = recruiter.get("jobs") or []
    best = max(jobs, key=lambda j: j.get("score", 0)) if jobs else {}
    first_name = (recruiter.get("name") or "").split()[0] if recruiter.get("name") else ""
    saudacao = f"Oi {first_name}, tudo bem?" if first_name else "Oi, tudo bem?"
    vaga = best.get("title", "a vaga de infraestrutura")
    empresa = best.get("company", "")
    onde = f" na {empresa}" if empresa and empresa != "N/A" else ""

    return (
        f"{saudacao}\n\n"
        f"Vi que você publicou a vaga de {vaga}{onde}. "
        f"Sou Engenheiro DevOps e trabalho com Linux, Docker, Kubernetes e AWS/GCP, "
        f"então o perfil bateu bastante com o que faço.\n\n"
        f"Posso te enviar meu currículo?"
    )
