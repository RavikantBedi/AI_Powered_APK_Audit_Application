"""Incoming-message webhook.

Stage 1: receive a message, load the right client + config, store it.
Stage 2: if the client has the reply_agent module, draft a reply or escalate.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.config_loader import ClientConfigNotFound, load_client_config
from app.database import get_db
from app.modules import lead_qualifier
from app.modules.reply_agent import draft_reply
from app.schemas import IncomingMessage, WebhookResponse

logger = logging.getLogger("agency.webhook")
router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/webhook", response_model=WebhookResponse)
def receive_message(msg: IncomingMessage, db: Session = Depends(get_db)):
    client = db.get(models.Client, msg.client_id)
    if client is None:
        raise HTTPException(status_code=404, detail=f"Unknown client_id {msg.client_id}")

    try:
        config = load_client_config(client.id)
    except ClientConfigNotFound:
        raise HTTPException(status_code=500, detail=f"Client {client.id} has no config file")

    # Reuse the open conversation for this sender on this channel, else start one.
    convo = (
        db.query(models.Conversation)
        .filter_by(client_id=client.id, channel=msg.channel, sender_id=msg.sender_id, status="open")
        .order_by(models.Conversation.id.desc())
        .first()
    )
    if convo is None:
        convo = models.Conversation(
            client_id=client.id, channel=msg.channel, sender_id=msg.sender_id, messages=[]
        )
        db.add(convo)

    history = list(convo.messages or [])
    history.append({"role": "customer", "text": msg.text, "ts": _now_iso()})
    logger.info("client=%s channel=%s sender=%s: %r", client.id, msg.channel, msg.sender_id, msg.text)

    reply_text: str | None = None
    escalated = False
    reason: str | None = None
    suggestions: list[str] = []
    handled_by: str | None = None
    modules = client.active_modules or []
    llm = msg.llm.model_dump() if msg.llm else None

    # Module 2: lead qualification runs first for new conversations, until
    # all questions are answered. Then the reply agent (if active) takes over.
    in_lead_flow = (
        "lead_qualifier" in modules
        and convo.lead_status is None
        and lead_qualifier.get_questions(config)
    )
    if in_lead_flow:
        result = lead_qualifier.step(config, convo.lead_answers, msg.text, llm=llm)
        convo.lead_answers = result.answers
        questions = lead_qualifier.get_questions(config)
        if result.finished:
            convo.lead_status = result.lead_status
            reason = (f"All {len(questions)} qualifying answers collected — "
                      f"lead evaluated as '{result.lead_status}'")
            logger.info("conversation %s lead flow finished: %s", convo.id, result.lead_status)
        else:
            asked = result.answers.get("asked_index", 0)
            reason = f"Qualifying this lead — asking question {asked + 1} of {len(questions)}"
        reply_text = result.reply
        history.append({"role": "agent", "text": reply_text, "ts": _now_iso()})
        convo.messages = history
        db.commit()
        db.refresh(convo)
        return WebhookResponse(
            conversation_id=convo.id, status=convo.status, reply=reply_text,
            escalated=False, module="lead_qualifier", reason=reason,
        )

    if "reply_agent" in modules:
        handled_by = "reply_agent"
        result = draft_reply(
            config=config,
            business_name=client.business_name,
            industry=client.industry,
            tone=client.tone_of_voice,
            history=history[:-1],
            incoming_text=msg.text,
            llm=llm,
            client_id=client.id,
        )
        reason = result.reason
        if result.escalate:
            escalated = True
            convo.status = "escalated"
            history.append({"role": "system", "text": f"ESCALATED: {result.reason}", "ts": _now_iso()})
            logger.warning("conversation %s escalated: %s", convo.id, result.reason)
        else:
            reply_text = result.reply
            suggestions = result.suggestions
            history.append({"role": "agent", "text": reply_text, "ts": _now_iso()})

    convo.messages = history  # reassign so SQLAlchemy detects the JSON change
    db.commit()
    db.refresh(convo)

    return WebhookResponse(
        conversation_id=convo.id, status=convo.status, reply=reply_text,
        escalated=escalated, module=handled_by, reason=reason, suggestions=suggestions,
    )
