"""
Job Radar — Envio de candidaturas por email (Gmail SMTP)
"""

import json
import logging
import os
import smtplib
from datetime import datetime, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
SENT_FILE = DATA_DIR / "sent.json"
ASSETS_DIR = Path(__file__).parent.parent / "assets"
RESUME_PATH = ASSETS_DIR / "curriculo.pdf"

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
CANDIDATE_EMAIL = os.environ.get("CANDIDATE_EMAIL", "ericdias0603@gmail.com")


def load_sent_history() -> dict:
    if SENT_FILE.exists():
        with open(SENT_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"sent": []}


def save_sent_history(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(SENT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def already_applied_to_company(company: str, sent_history: dict) -> bool:
    """Verifica se já candidatou na empresa nos últimos 7 dias."""
    company_lower = company.lower().strip()
    now = datetime.now(timezone.utc)
    for record in sent_history.get("sent", []):
        if record.get("company", "").lower().strip() == company_lower:
            sent_at_str = record.get("sent_at", "")
            if sent_at_str:
                try:
                    sent_at = datetime.fromisoformat(sent_at_str.replace("Z", "+00:00"))
                    delta = (now - sent_at).days
                    if delta < 7:
                        log.info("Já candidatou em %s há %d dias — pulando", company, delta)
                        return True
                except ValueError:
                    pass
    return False


def build_email(job: dict, cover_letter: str) -> MIMEMultipart:
    msg = MIMEMultipart()
    msg["From"] = GMAIL_USER

    contact_email = job.get("contact_email")
    if contact_email:
        # Envia direto para o recrutador, cópia para o candidato
        msg["To"] = contact_email
        msg["Cc"] = CANDIDATE_EMAIL
        msg["Subject"] = f"Candidatura — {job['title']} | Eric Dias Lemos"
        body = cover_letter  # email profissional: só a carta
        log.info("Destino: recrutador <%s> (cc: %s)", contact_email, CANDIDATE_EMAIL)
    else:
        # Sem email de contato: envia para o próprio candidato revisar
        msg["To"] = CANDIDATE_EMAIL
        msg["Subject"] = f"[Job Radar] {job['title']} @ {job.get('company', '')} | Score {job.get('score', 0)}/100"
        body = f"""{cover_letter}

---
Vaga:   {job.get('url', '')}
Fonte:  {job.get('source', '')}
Score:  {job.get('score', 0)}/100 ({job.get('fit_level', '').upper()} FIT)
Skills: {', '.join(job.get('skills_match', []))}
"""
        log.info("Destino: candidato <%s> (sem email de contato na vaga)", CANDIDATE_EMAIL)

    msg.attach(MIMEText(body, "plain", "utf-8"))

    if RESUME_PATH.exists():
        with open(RESUME_PATH, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename="curriculo_eric_devops.pdf",
        )
        msg.attach(part)
        log.info("Currículo anexado")
    else:
        log.warning(
            "⚠️  Currículo não encontrado em %s — email enviado SEM anexo!\n"
            "    Para anexar: faça commit do arquivo assets/curriculo.pdf no repo.",
            RESUME_PATH,
        )

    return msg


def send_application(job: dict, cover_letter: str) -> bool:
    """Envia email de candidatura. Retorna True se bem-sucedido."""
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        log.error("Credenciais Gmail não configuradas (GMAIL_USER / GMAIL_APP_PASSWORD)")
        return False

    sent_history = load_sent_history()

    if already_applied_to_company(job.get("company", ""), sent_history):
        return False

    msg = build_email(job, cover_letter)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        log.info("Email enviado para: %s @ %s", job.get("title"), job.get("company"))
    except smtplib.SMTPException as e:
        log.error("Falha ao enviar email: %s", e)
        return False

    # Registra envio
    record = {
        "job_id": job.get("id"),
        "title": job.get("title"),
        "company": job.get("company"),
        "source": job.get("source"),
        "url": job.get("url"),
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "score": job.get("score"),
    }
    sent_history.setdefault("sent", []).append(record)
    save_sent_history(sent_history)

    return True


def send_batch(jobs: list[dict], letters: dict[str, str]) -> list[str]:
    """Envia candidaturas em lote. Retorna lista de job_ids enviados."""
    sent_ids: list[str] = []
    for job in jobs:
        job_id = job.get("id", "")
        letter = letters.get(job_id, "")
        if not letter:
            log.warning("Sem carta para job %s — pulando", job_id)
            continue
        if send_application(job, letter):
            sent_ids.append(job_id)
    log.info("Candidaturas enviadas: %d/%d", len(sent_ids), len(jobs))
    return sent_ids
