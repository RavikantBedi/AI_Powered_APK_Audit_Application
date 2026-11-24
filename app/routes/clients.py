"""Client management endpoints (minimal — full onboarding form comes in Stage 7)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.schemas import ClientCreate, ClientOut

router = APIRouter(prefix="/clients")


@router.post("", response_model=ClientOut)
def create_client(payload: ClientCreate, db: Session = Depends(get_db)):
    client = models.Client(**payload.model_dump())
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.get("", response_model=list[ClientOut])
def list_clients(db: Session = Depends(get_db)):
    return db.query(models.Client).order_by(models.Client.id).all()


@router.get("/{client_id}/starters")
def conversation_starters(client_id: int):
    """Suggested first questions for the chat widget, from the client's config."""
    try:
        from app.config_loader import load_client_config
        config = load_client_config(client_id)
    except Exception:
        return {"starters": []}
    starters = [faq["q"] for faq in config.get("faqs", [])[:4]]
    if not starters and config.get("qualifying_questions"):
        starters = ["Hi, I'm interested!"]
    return {"starters": starters}


@router.get("/{client_id}/leads")
def list_leads(client_id: int, db: Session = Depends(get_db)):
    """Leads that completed the qualification flow, newest first."""
    if db.get(models.Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Unknown client")
    leads = (
        db.query(models.Conversation)
        .filter(models.Conversation.client_id == client_id,
                models.Conversation.lead_status.isnot(None))
        .order_by(models.Conversation.id.desc())
        .all()
    )
    return [
        {
            "conversation_id": c.id,
            "sender_id": c.sender_id,
            "channel": c.channel,
            "lead_status": c.lead_status,
            "answers": (c.lead_answers or {}).get("answers", {}),
            "reason": (c.lead_answers or {}).get("reason"),
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in leads
    ]


@router.get("/{client_id}/conversations")
def list_conversations(client_id: int, db: Session = Depends(get_db)):
    if db.get(models.Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Unknown client")
    convos = (
        db.query(models.Conversation)
        .filter_by(client_id=client_id)
        .order_by(models.Conversation.id.desc())
        .all()
    )
    return [
        {
            "id": c.id,
            "channel": c.channel,
            "sender_id": c.sender_id,
            "status": c.status,
            "messages": c.messages,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in convos
    ]
