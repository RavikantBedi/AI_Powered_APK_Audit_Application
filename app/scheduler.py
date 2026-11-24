"""Weekly report scheduler (Module 4).

Default: Monday 09:00 server time. Override per client in their config:
  "report_schedule": {"day_of_week": "fri", "hour": 17}
"""
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import models
from app.config_loader import ClientConfigNotFound, load_client_config
from app.database import SessionLocal
from app.modules.report_agent import generate_report

logger = logging.getLogger("agency.scheduler")
scheduler = BackgroundScheduler()


def _run_report(client_id: int) -> None:
    db = SessionLocal()
    try:
        client = db.get(models.Client, client_id)
        if client and "auto_report" in (client.active_modules or []):
            generate_report(db, client)
            logger.info("scheduled report generated for client %s", client_id)
    except Exception as e:
        # One client's failure must never kill the scheduler.
        logger.error("scheduled report failed for client %s: %s", client_id, e)
    finally:
        db.close()


def schedule_all() -> None:
    db = SessionLocal()
    try:
        clients = db.query(models.Client).all()
    finally:
        db.close()
    for client in clients:
        if "auto_report" not in (client.active_modules or []):
            continue
        try:
            cfg = load_client_config(client.id).get("report_schedule", {})
        except ClientConfigNotFound:
            cfg = {}
        trigger = CronTrigger(
            day_of_week=cfg.get("day_of_week", "mon"),
            hour=int(cfg.get("hour", 9)),
            minute=0,
        )
        scheduler.add_job(
            _run_report, trigger, args=[client.id],
            id=f"report-client-{client.id}", replace_existing=True,
        )
        logger.info("scheduled weekly report for client %s (%s)", client.id, trigger)


def start() -> None:
    schedule_all()
    if not scheduler.running:
        scheduler.start()
