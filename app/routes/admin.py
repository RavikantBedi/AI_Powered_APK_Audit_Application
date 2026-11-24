"""Agency-owner endpoints backing the admin dashboard (Stage 6)."""
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.modules.report_agent import generate_report

router = APIRouter()


@router.get("/admin/escalated")
def escalated_conversations(db: Session = Depends(get_db)):
    """All escalated conversations across clients, newest first."""
    rows = (
        db.query(models.Conversation, models.Client.business_name)
        .join(models.Client, models.Conversation.client_id == models.Client.id)
        .filter(models.Conversation.status == "escalated")
        .order_by(models.Conversation.id.desc())
        .all()
    )
    return [
        {
            "conversation_id": c.id,
            "client_id": c.client_id,
            "business_name": name,
            "channel": c.channel,
            "sender_id": c.sender_id,
            "messages": c.messages,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c, name in rows
    ]


@router.post("/admin/conversations/{conversation_id}/resolve")
def resolve_conversation(conversation_id: int, db: Session = Depends(get_db)):
    convo = db.get(models.Conversation, conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Unknown conversation")
    convo.status = "resolved"
    db.commit()
    return {"conversation_id": convo.id, "status": convo.status}


@router.post("/clients/{client_id}/report")
def trigger_report(client_id: int, llm: dict | None = Body(default=None),
                   db: Session = Depends(get_db)):
    """Manually generate a report now (for testing / the dashboard button)."""
    client = db.get(models.Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Unknown client")
    report = generate_report(db, client, llm=llm)
    return {"client_id": client_id, "report": report}
