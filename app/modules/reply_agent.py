"""Module 1: Customer Reply Agent.

Drafts a reply from the client's business config. If the answer isn't in the
config, the agent must say so (can_answer=False) and the conversation is
escalated instead of auto-replied — a confident wrong answer to a customer is
the failure mode this exists to prevent.

Provider is selectable per request (widget settings) or via LLM_PROVIDER env:
  anthropic (Claude SDK) | gemini | groq | xai (OpenAI-compatible endpoints).
"""
import os
from dataclasses import dataclass

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from app.llm_providers import PROVIDERS, LLMCallError, chat_json
from app.modules import guardrails, knowledge_base

load_dotenv()

ANTHROPIC_MODEL = os.getenv("AGENT_MODEL", "claude-opus-5")

_client: anthropic.Anthropic | None = None


def get_llm_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


class DraftedReply(BaseModel):
    can_answer: bool
    reply: str
    reason: str
    suggestions: list[str] = []


@dataclass
class AgentResult:
    escalate: bool
    reply: str | None
    reason: str
    suggestions: list[str] = None  # type: ignore[assignment]
    blocked_rule: str | None = None  # set when a guardrail blocked an otherwise-drafted reply

    def __post_init__(self):
        if self.suggestions is None:
            self.suggestions = []


SYSTEM_TEMPLATE = """You are a customer support agent for {business_name} ({industry}).
Tone of voice: {tone}.

You may ONLY answer using the business facts below. Do not use general
knowledge for anything business-specific (prices, hours, policies, services).
If the facts don't cover the question, you must escalate — never guess or
fill gaps from general knowledge, even if the answer seems obvious.

BUSINESS FACTS:
{facts}
{retrieved_section}
{never_say_section}
Rules:
- Greetings and small talk ("hi", "hello", "thanks"): set can_answer=true and
  reply with a short friendly greeting offering help — never escalate these.
- If the customer's question is fully answerable from the business facts
  and/or retrieved document excerpts above, set can_answer=true and write
  the reply in the business's tone. Keep it short and suitable for a chat
  message.
- If the facts do not contain the answer, or the message needs a human
  (complaints, refunds, emergencies), set can_answer=false, leave reply
  empty, and explain briefly in reason.
- Never invent prices, availability, or promises not present in the facts.
- In "reason", explain your decision in one short sentence (this is shown to
  the business owner as your reasoning).
- In "suggestions", give 2-3 short follow-up questions the customer might
  ask next that ARE answerable from the business facts. Empty list when
  escalating.
"""

JSON_INSTRUCTION = """
Respond with ONLY a JSON object, no other text:
{"can_answer": true or false, "reply": "the reply text or empty string", "reason": "brief explanation", "suggestions": ["follow-up question", "..."]}
"""


def _format_facts(config: dict) -> str:
    lines = []
    for faq in config.get("faqs", []):
        lines.append(f"Q: {faq['q']}\nA: {faq['a']}")
    if config.get("services"):
        lines.append("Services: " + "; ".join(config["services"]))
    if config.get("pricing"):
        lines.append("Pricing: " + "; ".join(f"{k}: {v}" for k, v in config["pricing"].items()))
    if config.get("hours"):
        lines.append("Hours: " + config["hours"])
    if config.get("extra_facts"):
        lines.append("Other facts: " + "; ".join(config["extra_facts"]))
    return "\n\n".join(lines) if lines else "(no facts configured)"


def _format_retrieved(chunks: list[knowledge_base.RetrievedChunk]) -> str:
    if not chunks:
        return ""
    body = "\n\n".join(f"[from {c.source}]\n{c.text}" for c in chunks)
    return (
        "\nRELEVANT DOCUMENT EXCERPTS (retrieved for this question — treat as "
        "authoritative business facts, do not use anything outside these "
        f"excerpts and the facts above):\n{body}\n"
    )


def _format_never_say(config: dict) -> str:
    rules = config.get("never_say", [])
    if not rules:
        return ""
    return "\nNEVER, under any circumstances, say or imply:\n" + "\n".join(f"- {r}" for r in rules) + "\n"


def _draft_anthropic(system: str, messages: list[dict],
                     model: str | None, api_key: str | None) -> DraftedReply:
    client = anthropic.Anthropic(api_key=api_key) if api_key else get_llm_client()
    response = client.messages.parse(
        model=model or ANTHROPIC_MODEL,
        max_tokens=1024,
        system=system,
        messages=messages,
        output_format=DraftedReply,
    )
    return response.parsed_output


def draft_reply(config: dict, business_name: str, industry: str, tone: str,
                history: list[dict], incoming_text: str,
                llm: dict | None = None, client_id: int | None = None) -> AgentResult:
    """Draft a reply for an incoming message. Fails safe: any error escalates.

    llm: optional per-request override {"provider", "model", "api_key"}.
    client_id: when set, retrieves grounding chunks from that client's
    knowledge base (Stage 8) — strictly scoped to this client, never mixed
    with another client's documents.
    """
    llm = llm or {}
    provider = llm.get("provider") or os.getenv("LLM_PROVIDER", "anthropic")
    model = llm.get("model") or None
    api_key = llm.get("api_key") or None

    retrieved: list[knowledge_base.RetrievedChunk] = []
    if client_id is not None:
        retrieved = knowledge_base.retrieve(client_id, incoming_text)

    system = SYSTEM_TEMPLATE.format(
        business_name=business_name,
        industry=industry or "general business",
        tone=tone,
        facts=_format_facts(config),
        retrieved_section=_format_retrieved(retrieved),
        never_say_section=_format_never_say(config),
    )
    # Replay recent turns so follow-up questions have context.
    messages = [
        {"role": "assistant" if m["role"] == "agent" else "user", "content": m["text"]}
        for m in history[-10:]
        if m["role"] in ("customer", "agent") and m.get("text")
    ]
    messages.append({"role": "user", "content": incoming_text})

    # Fail safe: any failure (API error, bad key, parse error) escalates to a
    # human instead of crashing or guessing.
    try:
        if provider == "anthropic":
            drafted = _draft_anthropic(system, messages, model, api_key)
        elif provider in PROVIDERS:
            data = chat_json(provider, api_key, system + JSON_INSTRUCTION, messages, model)
            drafted = DraftedReply.model_validate(data)
        else:
            return AgentResult(escalate=True, reply=None, reason=f"Unknown LLM provider '{provider}'")
    except (LLMCallError, ValidationError) as e:
        return AgentResult(escalate=True, reply=None, reason=f"LLM call failed: {e}")
    except Exception as e:
        return AgentResult(escalate=True, reply=None, reason=f"LLM call failed: {type(e).__name__}: {e}")

    if not drafted.can_answer or not drafted.reply.strip():
        return AgentResult(escalate=True, reply=None, reason=drafted.reason or "Agent not confident")

    # Guardrail: check the drafted reply against this client's never-say
    # rules before it can be sent. A rule match blocks the reply and
    # escalates instead — checked in code, not just relied on as a prompt
    # instruction the model could ignore.
    violation = guardrails.check_reply(drafted.reply, config.get("never_say", []))
    if violation:
        return AgentResult(
            escalate=True, reply=None,
            reason=f"Blocked by guardrail '{violation}' — drafted reply would have violated a never-say rule",
            blocked_rule=violation,
        )

    return AgentResult(escalate=False, reply=drafted.reply, reason=drafted.reason,
                       suggestions=[s for s in drafted.suggestions if s.strip()][:3])
