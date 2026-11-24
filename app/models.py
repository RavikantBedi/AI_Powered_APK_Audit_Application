"""ORM models: clients and conversations."""
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_name: Mapped[str] = mapped_column(String, nullable=False)
    industry: Mapped[str] = mapped_column(String, default="")
    tone_of_voice: Mapped[str] = mapped_column(String, default="friendly and professional")
    escalation_contact: Mapped[str] = mapped_column(String, default="")
    active_modules: Mapped[list] = mapped_column(JSON, default=list)  # e.g. ["reply_agent"]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="client")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String, default="widget")  # widget | whatsapp
    sender_id: Mapped[str] = mapped_column(String, default="", index=True)
    messages: Mapped[list] = mapped_column(JSON, default=list)  # [{role, text, ts, meta?}]
    status: Mapped[str] = mapped_column(String, default="open")  # open | escalated | resolved
    # Lead qualification (Module 2): None until the flow finishes, then
    # qualified | unqualified | needs_review. Answers: {question_key: answer}.
    lead_status: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    lead_answers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    client: Mapped["Client"] = relationship(back_populates="conversations")
