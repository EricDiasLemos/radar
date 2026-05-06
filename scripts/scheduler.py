"""
Job Radar — Agendador local (roda dentro do container)
Executa o scan seg–sex às 08h e fica em loop aguardando.
"""

import logging
import sys
import time
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

SCAN_HOUR = 8    # 08:00 local do container
SCAN_DAYS = {0, 1, 2, 3, 4}  # seg=0 … sex=4


def should_run_now() -> bool:
    now = datetime.now()
    return now.weekday() in SCAN_DAYS and now.hour == SCAN_HOUR and now.minute == 0


def main() -> None:
    log.info("Job Radar Scheduler iniciado — scan diário às %02d:00 (seg–sex)", SCAN_HOUR)
    last_run_day = -1

    while True:
        now = datetime.now()
        if should_run_now() and now.day != last_run_day:
            log.info("Disparando scan diário...")
            try:
                from main import run_daily_scan
                run_daily_scan(auto_apply=True)
                last_run_day = now.day
            except Exception as e:
                log.error("Erro no scan: %s", e)
        time.sleep(30)


if __name__ == "__main__":
    main()
