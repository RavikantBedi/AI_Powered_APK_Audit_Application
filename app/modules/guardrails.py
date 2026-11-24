"""Stage 9: Guardrails checked against a drafted reply before it can be sent.

Two layers, both checked in code (never just a prompt instruction the model
could ignore or be talked out of):

1. Deterministic keyword/phrase match against each client's "never_say"
   rules — fast, free, and can't be bypassed by clever phrasing of the
   rule itself since it's substring/regex matching on the output.
2. A lightweight LLM semantic check for rules a keyword match would miss
   (e.g. "no discount promises" should catch "I can knock off 10%" even
   though the word "discount" never appears). Only runs if rules are
   configured and a key is available; fails safe (no block) on LLM error
   so a guardrail-check outage doesn't just escalate every single reply —
   the deterministic layer is the one that must never be skippable.
"""
import logging
import re

from app.llm_providers import PROVIDERS, LLMCallError, chat_json

logger = logging.getLogger("agency.guardrails")

# Rule phrases mapped to the literal patterns/keywords that should never
# appear in a reply. Keyed by a short slug so violations are readable in logs.
_BUILTIN_PATTERNS = {
    "no_discount_promises": [
        r"\bdiscount\b", r"\b\d{1,2}%\s*off\b", r"\bfree\s+(of\s+charge|for\s+you)\b",
        r"\bwaive[d]?\s+the\s+fee\b", r"\bspecial\s+price\s+for\s+you\b",
    ],
    "no_refund_guarantees": [
        r"\bguarantee[d]?\s+(a\s+)?refund\b", r"\bfull\s+refund\b.*\bpromise\b",
        r"\byou\s+will\s+get\s+your\s+money\s+back\b",
    ],
    "no_medical_advice": [
        r"\byou\s+(should|need to)\s+take\s+\w+\s+(mg|milligrams|tablets|pills)\b",
        r"\bthis\s+will\s+cure\b", r"\bstop\s+taking\s+your\s+medication\b",
    ],
    "no_legal_claims": [
        r"\bwe\s+guarantee\s+you\s+will\s+win\b", r"\blegally\s+binding\s+promise\b",
        r"\bthis\s+is\s+not\s+a\s+scam\b",
    ],
}


def _matches_builtin(reply: str, rule_text: str) -> str | None:
    """If a client's free-text rule maps to a known builtin pattern set
    (matched by keyword overlap), check those regexes against the reply."""
    rule_lower = rule_text.lower()
    for slug, patterns in _BUILTIN_PATTERNS.items():
        trigger_words = slug.replace("no_", "").split("_")
        if any(w in rule_lower for w in trigger_words):
            for pattern in patterns:
                if re.search(pattern, reply, re.IGNORECASE):
                    return slug
    return None


def _keyword_check(reply: str, never_say: list[str]) -> str | None:
    """Direct substring check: if the rule text itself names a forbidden
    word/phrase (e.g. "never say 'lifetime warranty'"), catch a literal
    match first — cheapest and most reliable check."""
    reply_lower = reply.lower()
    for rule in never_say:
        quoted = re.findall(r"['\"]([^'\"]+)['\"]", rule)
        for phrase in quoted:
            if phrase.lower() in reply_lower:
                return rule
    return None


def check_reply(reply: str, never_say: list[str], llm: dict | None = None) -> str | None:
    """Return the violated rule (str) if the reply breaks a guardrail, else None.

    Runs cheapest checks first. The deterministic layers never fail open —
    if they match, the reply is blocked, full stop.
    """
    if not never_say or not reply.strip():
        return None

    hit = _keyword_check(reply, never_say)
    if hit:
        return hit

    for rule in never_say:
        hit = _matches_builtin(reply, rule)
        if hit:
            return hit

    # Semantic layer: only attempted if an LLM key is available; any
    # failure here is swallowed (fail-safe = allow, since the deterministic
    # layers already covered the hard guarantees).
    llm = llm or {}
    provider = llm.get("provider")
    if provider in PROVIDERS and llm.get("api_key"):
        try:
            return _semantic_check(reply, never_say, llm)
        except LLMCallError as e:
            logger.warning("semantic guardrail check failed, allowing reply through "
                           "deterministic checks only: %s", e)
    return None


def _semantic_check(reply: str, never_say: list[str], llm: dict) -> str | None:
    system = (
        "You check draft customer-service replies against a business's rules. "
        "Given the RULES and the DRAFT REPLY, decide if the reply violates any "
        "rule in spirit (even if it doesn't use the exact forbidden words).\n"
        'Respond with ONLY JSON: {"violates": true or false, "rule": "the exact violated rule text or empty string"}'
    )
    rules_text = "\n".join(f"- {r}" for r in never_say)
    user = f"RULES:\n{rules_text}\n\nDRAFT REPLY:\n{reply}"
    data = chat_json(llm["provider"], llm.get("api_key"), system,
                     [{"role": "user", "content": user}], llm.get("model"))
    if data.get("violates") and data.get("rule"):
        return str(data["rule"])
    return None
