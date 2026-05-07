"""
Job Radar — Orquestrador principal
Executado pelo GitHub Actions (daily-scan.yml)
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from scraper import run_scraper, load_existing_jobs, save_jobs
from scorer import apply_scores, compute_stats
from letter_gen import generate_letter_batch
from mailer import send_batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
JOBS_FILE = DATA_DIR / "jobs.json"


def run_daily_scan(auto_apply: bool = True) -> None:
    log.info("=== Job Radar — Daily Scan iniciado ===")

    # 1. Carrega vagas existentes
    existing_data = load_existing_jobs()
    existing_jobs: list[dict] = existing_data.get("jobs", [])
    log.info("Vagas existentes no banco: %d", len(existing_jobs))

    # 2. Scraper — busca novas vagas
    new_raw_jobs = run_scraper()
    new_jobs_dicts = [j.to_dict() for j in new_raw_jobs]

    # 3. Scoring das novas vagas
    scored_new = apply_scores(new_jobs_dicts)
    log.info("Novas vagas após scoring: %d", len(scored_new))

    # 4. Mescla com banco existente
    all_jobs = existing_jobs + scored_new

    # 5. Auto-candidatura:
    #    - Alto fit (score >= 70): sempre
    #    - Médio fit (score >= 50) COM email de contato: envia direto ao recrutador
    if auto_apply:
        alto_fit = [
            j for j in scored_new
            if j.get("status") == "nova" and (
                j.get("fit_level") == "alto"
                or (j.get("fit_level") == "medio" and j.get("contact_email"))
            )
        ]
        email_vagas = [j for j in alto_fit if j.get("contact_email")]
        sem_email   = [j for j in alto_fit if not j.get("contact_email")]
        log.info("Vagas para auto-candidatura: %d total (%d com email direto, %d sem)",
                 len(alto_fit), len(email_vagas), len(sem_email))

        if alto_fit:
            letters = generate_letter_batch(alto_fit)
            sent_ids = send_batch(alto_fit, letters)

            # Atualiza status e carta no banco
            sent_set = set(sent_ids)
            for job in all_jobs:
                if job["id"] in sent_set:
                    job["status"] = "enviada"
                    job["applied_at"] = datetime.now(timezone.utc).isoformat()
                    job["cover_letter"] = letters.get(job["id"], "")
            log.info("Candidaturas automáticas enviadas: %d", len(sent_ids))

    # 6. Salva dados atualizados
    stats = compute_stats(all_jobs)
    output = {
        "jobs": all_jobs,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
    }
    save_jobs(output)

    log.info("=== Daily Scan concluído — Stats: %s ===", stats)


def apply_single_job(job_id: str) -> None:
    """Candidatura manual para um job_id específico (workflow manual-apply)."""
    log.info("=== Candidatura manual: job_id=%s ===", job_id)

    data = load_existing_jobs()
    jobs = data.get("jobs", [])

    target = next((j for j in jobs if j.get("id") == job_id), None)
    if not target:
        log.error("Job não encontrado: %s", job_id)
        sys.exit(1)

    if target.get("status") == "enviada":
        log.warning("Candidatura já enviada para este job")
        return

    letters = generate_letter_batch([target])
    sent_ids = send_batch([target], letters)

    if job_id in sent_ids:
        for job in jobs:
            if job["id"] == job_id:
                job["status"] = "enviada"
                job["applied_at"] = datetime.now(timezone.utc).isoformat()
                job["cover_letter"] = letters.get(job_id, "")
                break
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        data["stats"] = compute_stats(jobs)
        save_jobs(data)
        log.info("Candidatura manual concluída para: %s @ %s",
                 target.get("title"), target.get("company"))
    else:
        log.error("Falha ao enviar candidatura para job_id=%s", job_id)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Radar CLI")
    sub = parser.add_subparsers(dest="command")

    scan_parser = sub.add_parser("scan", help="Executar busca diária")
    scan_parser.add_argument("--no-auto-apply", action="store_true",
                             help="Desabilita auto-candidatura")

    apply_parser = sub.add_parser("apply", help="Candidatura manual")
    apply_parser.add_argument("job_id", help="ID da vaga")

    args = parser.parse_args()

    if args.command == "scan":
        run_daily_scan(auto_apply=not args.no_auto_apply)
    elif args.command == "apply":
        apply_single_job(args.job_id)
    else:
        parser.print_help()
        sys.exit(1)
