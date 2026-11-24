"""Module 4: Auto-Report Agent.

Pulls a client's conversation/lead data for the period, summarizes it in
plain English via the LLM (fail-safe: a plain stats template), saves the
report to reports/, and emails it if SMTP is configured.
"""
import logging
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy.orm import Session

from app import models
from app.llm_providers import PROVIDERS, LLMCallError, chat_json

logger = logging.getLogger("agency.reports")
REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"


def gather_stats(db: Session, client_id: int, days: int = 7) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    convos = (
        db.query(models.Conversation)
        .filter(models.Conversation.client_id == client_id,
                models.Conversation.created_at >= since)
        .all()
    )
    first_questions = []
    for c in convos:
        for m in c.messages or []:
            if m.get("role") == "customer":
                first_questions.append(m.get("text", "")[:120])
                break
    return {
        "days": days,
        "total_conversations": len(convos),
        "escalated": sum(1 for c in convos if c.status == "escalated"),
        "resolved": sum(1 for c in convos if c.status == "resolved"),
        "leads_qualified": sum(1 for c in convos if c.lead_status == "qualified"),
        "leads_unqualified": sum(1 for c in convos if c.lead_status == "unqualified"),
        "leads_needs_review": sum(1 for c in convos if c.lead_status == "needs_review"),
        "sample_questions": first_questions[:20],
    }


def _fallback_summary(business_name: str, stats: dict) -> str:
    lines = [
        f"Weekly report for {business_name} (last {stats['days']} days)",
        "",
        f"- Conversations: {stats['total_conversations']}",
        f"- Escalated to you: {stats['escalated']}",
        f"- Resolved: {stats['resolved']}",
    ]
    if stats["leads_qualified"] or stats["leads_unqualified"] or stats["leads_needs_review"]:
        lines.append(f"- Leads: {stats['leads_qualified']} qualified, "
                     f"{stats['leads_unqualified']} unqualified, "
                     f"{stats['leads_needs_review']} need review")
    if stats["sample_questions"]:
        lines.append("- Recent customer questions: " + "; ".join(stats["sample_questions"][:5]))
    return "\n".join(lines)


def generate_report(db: Session, client: models.Client, llm: dict | None = None) -> str:
    stats = gather_stats(db, client.id)
    text = _fallback_summary(client.business_name, stats)

    llm = llm or {}
    provider = llm.get("provider") or os.getenv("LLM_PROVIDER", "gemini")
    if provider in PROVIDERS:
        system = (
            "You write short weekly business reports for small business owners. "
            "Plain English, no jargon, 5-8 sentences, mention what needs their "
            "attention (escalations, leads to call back). "
            'Respond with ONLY JSON: {"report": "..."}'
        )
        try:
            data = chat_json(provider, llm.get("api_key"), system,
                             [{"role": "user", "content": str(stats)}], llm.get("model"))
            if isinstance(data.get("report"), str) and data["report"].strip():
                text = data["report"].strip()
        except LLMCallError as e:
            logger.warning("LLM summary failed for client %s, using stats template: %s",
                           client.id, e)

    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = REPORTS_DIR / f"client_{client.id}_{stamp}.txt"
    path.write_text(text, encoding="utf-8")
    _maybe_email(client, text)
    return text


def _maybe_email(client: models.Client, body: str) -> None:
    host = os.getenv("SMTP_HOST")
    to_addr = client.escalation_contact
    if not host or not to_addr:
        logger.info("SMTP not configured or no contact for client %s — report saved to file only",
                    client.id)
        return
    msg = EmailMessage()
    msg["Subject"] = f"Weekly report — {client.business_name}"
    msg["From"] = os.getenv("REPORT_FROM", "reports@localhost")
    msg["To"] = to_addr
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587"))) as s:
            s.starttls()
            user, pw = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
            if user and pw:
                s.login(user, pw)
            s.send_message(msg)
        logger.info("emailed report to %s", to_addr)
    except Exception as e:
        logger.error("email failed for client %s: %s", client.id, e)
