from decouple import config
from loguru import logger
from apscheduler.schedulers.background import BackgroundScheduler
from reports import send_report

REPORT_PERIOD_HOURS = config("REPORT_PERIOD_HOURS", cast=int, default=24)
REPORT_HOUR = config("REPORT_CRON_HOUR", cast=int, default=8)

def job_relatorio():
    try:
        send_report(REPORT_PERIOD_HOURS)
        logger.info("Relatório enviado")
    except Exception as e:
        logger.exception(f"Falha relatório: {e}")

sched = BackgroundScheduler(timezone="America/Sao_Paulo")
sched.add_job(job_relatorio, "cron", hour=REPORT_HOUR, minute=0, id="relatorio", coalesce=True)
sched.start()
