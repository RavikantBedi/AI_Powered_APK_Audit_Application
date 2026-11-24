"""Pydantic schemas for API requests/responses."""
from pydantic import BaseModel, Field


class LLMSettings(BaseModel):
    """Per-request LLM override (from the widget settings panel).

    The api_key is used for the outbound LLM call only — never stored.
    """
    provider: str | None = None  # anthropic | gemini | groq | xai
    model: str | None = None
    api_key: str | None = None


class IncomingMessage(BaseModel):
    client_id: int
    channel: str = "widget"  # widget | whatsapp
    sender_id: str = Field(..., min_length=1, description="Customer identifier (phone, session id)")
    text: str = Field(..., min_length=1)
    llm: LLMSettings | None = None


class WebhookResponse(BaseModel):
    conversation_id: int
    status: str  # open | escalated | resolved
    reply: str | None = None  # None when escalated (nothing auto-sent)
    escalated: bool = False
    module: str | None = None      # which module handled it
    reason: str | None = None      # the agent's reasoning (shown as "AI thinking")
    suggestions: list[str] = []    # tappable follow-up questions


class ClientCreate(BaseModel):
    business_name: str
    industry: str = ""
    tone_of_voice: str = "friendly and professional"
    escalation_contact: str = ""
    active_modules: list[str] = []


class ClientOut(ClientCreate):
    id: int

    model_config = {"from_attributes": True}
