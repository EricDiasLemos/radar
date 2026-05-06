"""
Job Radar — Geração de carta de apresentação via Claude API
"""

import logging
import os

import anthropic

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
- Finalizar com disponibilidade para entrevista e link do GitHub implícito
- Escrever em português brasileiro formal-técnico"""


def generate_cover_letter(job: dict) -> str:
    """Gera carta personalizada para a vaga. Retorna texto da carta."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY não configurada")

    client = anthropic.Anthropic(api_key=api_key)

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

    log.info("Gerando carta para: %s @ %s", title, company)

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    letter = message.content[0].text.strip()
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
    skills = ", ".join(job.get("skills_match", ["Docker", "Linux", "Python"])[:3])
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
