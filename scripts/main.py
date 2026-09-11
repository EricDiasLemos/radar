"""
Job Radar — Orquestrador principal
Executado pelo GitHub Actions (daily-scan.yml)
"""

import argparse
import json
import logging
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from scraper import (
    run_scraper, load_existing_jobs, save_jobs, load_blacklist,
    verify_job_open, get_seen_in_search, deadline_passed, page_logo,
)
from scorer import apply_scores, compute_stats, classify_title
from letter_gen import generate_letter_batch, generate_recruiter_messages
from mailer import send_batch, SEND_SELF_NOTIFICATIONS
from recruiters import (
    merge_jobs_into_directory, save_recruiters, compute_recruiter_stats,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
JOBS_FILE = DATA_DIR / "jobs.json"
ARCHIVE_FILE = DATA_DIR / "archive.json"

# A vaga fica no banco enquanto estiver aberta — idade não importa:
#  - reapareceu na busca nos últimos SEEN_FRESH_DAYS -> aberta, sem visitar
#  - senão, o scan visita a página (até VERIFY_LIMIT) -> fechou? arquiva
#  - prazo de candidatura informado pela vaga passou  -> arquiva
#  - sem nenhuma confirmação há MAX_AGE_DAYS          -> arquiva (segurança)
# Resposta incerta (429, erro de rede) nunca remove a vaga.
SEEN_FRESH_DAYS = 3
VERIFY_LIMIT = 80
MAX_AGE_DAYS = 60


def run_daily_scan(auto_apply: bool = True) -> None:
    log.info("=== Job Radar — Daily Scan iniciado ===")

    # 1. Carrega vagas existentes
    existing_data = load_existing_jobs()
    existing_jobs: list[dict] = existing_data.get("jobs", [])
    log.info("Vagas existentes no banco: %d", len(existing_jobs))

    # 2. Scraper — busca novas vagas
    new_raw_jobs = run_scraper()
    new_jobs_dicts = [j.to_dict() for j in new_raw_jobs]

    # Vaga já conhecida que reapareceu na busca continua aberta.
    agora = datetime.now(timezone.utc).isoformat()
    vistas = get_seen_in_search()
    for j in existing_jobs:
        if j.get("id") in vistas:
            j["last_seen_at"] = agora
    if vistas:
        log.info("Vagas do banco que reapareceram na busca: %d", len(vistas))

    # 3. Scoring das novas vagas
    scored_new = apply_scores(new_jobs_dicts)
    # Rejeitadas (cargo fora da área, nível acima, keyword negativa) não
    # entram no banco: só poluíam o dashboard e o diretório de recruiters.
    rejeitadas = [j for j in scored_new if j.get("rejected")]
    scored_new = [j for j in scored_new if not j.get("rejected")]
    log.info("Novas vagas após scoring: %d aceitas, %d descartadas",
             len(scored_new), len(rejeitadas))
    for j in scored_new:
        j.setdefault("last_seen_at", agora)

    # Limpeza retroativa: vagas que entraram antes do portão de cargo.
    # Candidaturas enviadas/aprovadas ficam — são decisão do usuário.
    antes = len(existing_jobs)
    existing_jobs = [
        j for j in existing_jobs
        if j.get("status") in ("enviada", "aprovada")
        or classify_title(j.get("title", "")) == "core"
    ]
    if antes != len(existing_jobs):
        log.info("Limpeza de cargo fora da área: %d vagas antigas removidas",
                 antes - len(existing_jobs))

    # 4. Mescla com banco existente
    all_jobs = existing_jobs + scored_new

    # 5. Auto-candidatura:
    #    - Alto fit (score >= 70 ou 60 se big tech): sempre
    #    - Médio fit COM email de contato: envia direto ao recrutador
    #    - Big Tech médio fit (sem email): também candidata — não perder oportunidade
    if auto_apply:
        alto_fit = [
            j for j in scored_new
            if j.get("status") == "nova" and (
                j.get("fit_level") == "alto"
                or (j.get("fit_level") == "medio" and j.get("contact_email"))
                or (j.get("fit_level") == "medio" and j.get("target_company"))
            )
        ]
        email_vagas    = [j for j in alto_fit if j.get("contact_email")]
        big_techs      = [j for j in alto_fit if j.get("target_company")]
        sem_email      = [j for j in alto_fit if not j.get("contact_email")]
        log.info("Vagas para auto-candidatura: %d total (%d big tech, %d com email direto, %d sem email)",
                 len(alto_fit), len(big_techs), len(email_vagas), len(sem_email))

        # A carta só é usada quando o email vai direto para o recrutador.
        # Com SEND_SELF_NOTIFICATIONS=false as demais nem são enviadas, então
        # gerar carta para elas só queimaria cota da Groq — que é melhor
        # aproveitada nas mensagens de conexão do LinkedIn.
        alvos_carta = email_vagas if not SEND_SELF_NOTIFICATIONS else alto_fit

        if alto_fit:
            letters = generate_letter_batch(alvos_carta) if alvos_carta else {}
            if len(alvos_carta) < len(alto_fit):
                log.info("Cartas geradas apenas para %d vaga(s) com email do recrutador "
                         "(%d sem email não recebem email, então não precisam de carta)",
                         len(alvos_carta), len(alto_fit) - len(alvos_carta))
            sent_ids = send_batch(alto_fit, letters)

            # Atualiza status e carta no banco
            sent_set = set(sent_ids)
            for job in all_jobs:
                if job["id"] in sent_set:
                    job["status"] = "enviada"
                    job["applied_at"] = datetime.now(timezone.utc).isoformat()
                    job["cover_letter"] = letters.get(job["id"], "")
            log.info("Candidaturas automáticas enviadas: %d", len(sent_ids))

    # 6. Diretório de recruiters — acumula quem publicou as vagas.
    #    Feito ANTES do arquivamento: a vaga sai quando fecha, mas o
    #    contato do recruiter é permanente.
    rec_data = merge_jobs_into_directory(scored_new)
    if auto_apply:  # só gasta cota da Groq quando o scan é o completo
        geradas = generate_recruiter_messages(rec_data["recruiters"])
        if geradas:
            log.info("Mensagens de conexão geradas: %d", geradas)
    save_recruiters(rec_data)
    log.info("Recruiters: %s", compute_recruiter_stats(rec_data))

    # 7. Confirma quais vagas seguem abertas e arquiva as que fecharam
    all_jobs = _verify_open_jobs(all_jobs)
    all_jobs, archived = _split_for_archive(all_jobs)
    if archived:
        _append_to_archive(archived)
        log.info("Arquivadas %d vagas em archive.json: %s", len(archived),
                 dict(Counter(j.get("archive_reason") for j in archived)))

    # 8. Salva dados atualizados
    stats = compute_stats(all_jobs)
    output = {
        "jobs": all_jobs,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
    }
    save_jobs(output)

    log.info("=== Daily Scan concluído — Stats: %s ===", stats)


def _parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _verify_open_jobs(jobs: list[dict]) -> list[dict]:
    """
    Confirma se as vagas continuam abertas. Quem reapareceu na busca (ou foi
    verificado) há menos de SEEN_FRESH_DAYS é considerado aberto sem visita;
    o resto é verificado, das mais antigas para as mais novas, até
    VERIFY_LIMIT por scan — o que sobrar fica para o próximo.
    """
    now = datetime.now(timezone.utc)
    pendentes = []
    for j in jobs:
        if j.get("closed"):
            continue
        datas = [d for d in (_parse_dt(j.get("last_seen_at")), _parse_dt(j.get("verified_at"))) if d]
        if datas and (now - max(datas)).days < SEEN_FRESH_DAYS:
            continue
        pendentes.append(j)
    if not pendentes:
        return jobs

    pendentes.sort(key=lambda j: j.get("verified_at") or j.get("last_seen_at") or j.get("found_at") or "")
    lote = pendentes[:VERIFY_LIMIT]
    with ThreadPoolExecutor(max_workers=4) as ex:
        resultados = list(ex.map(verify_job_open, lote))

    abertas = fechadas = incertas = 0
    for j, (aberta, vt) in zip(lote, resultados):
        if vt:
            j["valid_through"] = vt
        if not j.get("company_logo") and page_logo(j.get("url", "")):
            j["company_logo"] = page_logo(j["url"])
        if aberta is True:
            j["verified_at"] = now.isoformat()
            abertas += 1
        elif aberta is False:
            j["closed"] = True
            j["closed_at"] = now.isoformat()
            fechadas += 1
        else:
            incertas += 1
    log.info("Verificação de vagas abertas: %d checadas (%d abertas, %d fecharam, "
             "%d sem resposta) — %d ficam para o próximo scan",
             len(lote), abertas, fechadas, incertas, len(pendentes) - len(lote))
    return jobs


def _split_for_archive(jobs: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Mantém a vaga enquanto estiver aberta. Arquiva (com archive_reason):
      closed  — fechou na verificação ou o prazo de candidatura passou
      max_age — nenhuma confirmação (busca ou verificação) há MAX_AGE_DAYS
    """
    now = datetime.now(timezone.utc)
    active: list[dict] = []
    archived: list[dict] = []

    for j in jobs:
        motivo = None
        if j.get("closed") or deadline_passed(j.get("valid_through")):
            motivo = "closed"
        else:
            datas = [d for d in (_parse_dt(j.get("verified_at")),
                                 _parse_dt(j.get("last_seen_at")),
                                 _parse_dt(j.get("found_at"))) if d]
            if datas and (now - max(datas)).days >= MAX_AGE_DAYS:
                motivo = "max_age"
        if motivo:
            j["archive_reason"] = motivo
            j["archived_at"] = now.isoformat()
            archived.append(j)
        else:
            active.append(j)
    return active, archived


def _append_to_archive(jobs: list[dict]) -> None:
    """Anexa vagas ao archive.json (mantém histórico em arquivo separado)."""
    if ARCHIVE_FILE.exists():
        try:
            with open(ARCHIVE_FILE, encoding="utf-8") as f:
                archive = json.load(f)
        except (json.JSONDecodeError, OSError):
            archive = {"jobs": []}
    else:
        archive = {"jobs": []}

    archive["jobs"] = archive.get("jobs", []) + jobs
    archive["last_updated"] = datetime.now(timezone.utc).isoformat()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)


def restore_open_from_archive(limit: int = 150) -> None:
    """
    Uso único ao trocar a política de 24h por "sai quando fechar": traz de
    volta do archive.json as vagas de cargo da área que saíram só pela idade
    e continuam abertas. As confirmadas fechadas ficam marcadas no arquivo.
    """
    if not ARCHIVE_FILE.exists():
        log.info("Sem archive.json — nada a restaurar")
        return
    with open(ARCHIVE_FILE, encoding="utf-8") as f:
        arquivo = json.load(f)
    data = load_existing_jobs()
    ativos_ids = {j["id"] for j in data.get("jobs", [])}
    banidos = load_blacklist()

    vistos, candidatas = set(), []
    for j in sorted(arquivo.get("jobs", []), key=lambda x: x.get("found_at", ""), reverse=True):
        jid = j.get("id")
        if (not jid or jid in vistos or jid in ativos_ids or jid in banidos
                or j.get("archive_reason") or j.get("status") == "arquivada"
                or classify_title(j.get("title", "")) != "core"):
            continue
        vistos.add(jid)
        candidatas.append(j)
    lote = candidatas[:limit]
    log.info("Restauração: %d vagas da área no arquivo, verificando %d", len(candidatas), len(lote))

    rescored = [j for j in apply_scores([dict(j) for j in lote]) if not j.get("rejected")]
    with ThreadPoolExecutor(max_workers=4) as ex:
        resultados = list(ex.map(verify_job_open, rescored))

    agora = datetime.now(timezone.utc).isoformat()
    restauradas, fechadas = [], set()
    for j, (aberta, vt) in zip(rescored, resultados):
        if vt:
            j["valid_through"] = vt
        if aberta is True:
            j.update({"status": "nova", "verified_at": agora})
            j.pop("archive_reason", None)
            j.pop("closed", None)
            restauradas.append(j)
        elif aberta is False:
            fechadas.add(j["id"])

    ids_rest = {j["id"] for j in restauradas}
    for j in arquivo["jobs"]:
        if j.get("id") in fechadas:
            j["archive_reason"] = "closed"
    arquivo["jobs"] = [j for j in arquivo["jobs"] if j.get("id") not in ids_rest]
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(arquivo, f, ensure_ascii=False, indent=2)

    data["jobs"] = data.get("jobs", []) + restauradas
    data["stats"] = compute_stats(data["jobs"])
    data["last_updated"] = agora
    save_jobs(data)

    save_recruiters(merge_jobs_into_directory(restauradas))
    log.info("Restauração concluída: %d abertas voltaram, %d confirmadas fechadas, %d sem resposta",
             len(restauradas), len(fechadas), len(rescored) - len(restauradas) - len(fechadas))


def backfill_logos(limit: int = 200) -> None:
    """Preenche o logo das vagas do LinkedIn que ainda não têm (visita a página)."""
    data = load_existing_jobs()
    alvo = [j for j in data.get("jobs", [])
            if not j.get("company_logo") and j.get("source") == "LinkedIn" and j.get("url")][:limit]
    if not alvo:
        log.info("Todas as vagas do LinkedIn já têm logo")
        return
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(verify_job_open, alvo))
    achados = 0
    for j in alvo:
        logo = page_logo(j["url"])
        if logo:
            j["company_logo"] = logo
            achados += 1
    save_jobs(data)
    log.info("Logos: %d de %d vagas preenchidas", achados, len(alvo))


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

    sub.add_parser("restore", help="Traz de volta do arquivo as vagas da área ainda abertas")
    sub.add_parser("logos", help="Preenche o logo da empresa nas vagas que não têm")

    args = parser.parse_args()

    if args.command == "scan":
        run_daily_scan(auto_apply=not args.no_auto_apply)
    elif args.command == "apply":
        apply_single_job(args.job_id)
    elif args.command == "restore":
        restore_open_from_archive()
    elif args.command == "logos":
        backfill_logos()
    else:
        parser.print_help()
        sys.exit(1)
