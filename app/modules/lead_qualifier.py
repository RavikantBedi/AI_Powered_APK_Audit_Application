"""Module 2: Lead Qualifier Agent.

For clients with this module active, a new conversation starts with 2-4
configurable qualifying questions (from the client's config). Answers are
stored on the conversation; once all questions are answered, the LLM judges
the lead against the client's qualification criteria.

The question flow itself is deterministic (no LLM needed) — only the final
qualified/unqualified judgment uses the LLM, and it fails safe to
"needs_review" so a lead is never lost to an API error.
"""
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from app.llm_providers import PROVIDERS, LLMCallError, chat_json


class LeadVerdict(BaseModel):
    qualified: bool
    reason: str


@dataclass
class LeadStep:
    reply: str                 # what to send the customer next
    finished: bool             # True once all questions are answered
    lead_status: str | None    # qualified | unqualified | needs_review (when finished)
    answers: dict              # answers collected so far {key: text}


def get_questions(config: dict) -> list[dict]:
    """Qualifying questions from client config: [{key, question}, ...]."""
    return config.get("qualifying_questions", [])


def flow_state(lead_answers: dict | None) -> dict:
    return lead_answers or {"answers": {}, "asked_index": -1}


def step(config: dict, lead_answers: dict | None, incoming_text: str,
         llm: dict | None = None) -> LeadStep:
    """Advance the qualification flow by one customer message."""
    questions = get_questions(config)
    state = flow_state(lead_answers)
    asked = state["asked_index"]
    answers = dict(state["answers"])

    # Record the answer to the question we asked last turn.
    if 0 <= asked < len(questions):
        answers[questions[asked]["key"]] = incoming_text.strip()

    next_index = asked + 1
    if next_index < len(questions):
        intro = ""
        if asked == -1 and config.get("lead_intro"):
            intro = config["lead_intro"] + " "
        return LeadStep(
            reply=intro + questions[next_index]["question"],
            finished=False,
            lead_status=None,
            answers={"answers": answers, "asked_index": next_index},
        )

    # All questions answered — judge the lead.
    verdict, reason = _evaluate(config, answers, llm)
    outro = config.get(
        "lead_outro",
        "Thanks! We have everything we need — our team will get back to you shortly.",
    )
    return LeadStep(
        reply=outro,
        finished=True,
        lead_status=verdict,
        answers={"answers": answers, "asked_index": next_index, "reason": reason},
    )


def _evaluate(config: dict, answers: dict, llm: dict | None) -> tuple[str, str]:
    criteria = config.get("qualification_criteria", "")
    if not criteria:
        return "needs_review", "No qualification criteria configured"

    llm = llm or {}
    provider = llm.get("provider") or "gemini"
    system = (
        "You qualify sales leads. Given the criteria and the lead's answers, "
        "decide if the lead is qualified.\n"
        f"CRITERIA: {criteria}\n"
        'Respond with ONLY a JSON object: {"qualified": true or false, "reason": "brief"}'
    )
    answer_text = "\n".join(f"{k}: {v}" for k, v in answers.items())
    try:
        if provider in PROVIDERS:
            data = chat_json(provider, llm.get("api_key"), system,
                             [{"role": "user", "content": answer_text}], llm.get("model"))
            verdict = LeadVerdict.model_validate(data)
        else:
            # Anthropic path reuses the SDK via reply_agent's client.
            from app.modules.reply_agent import get_llm_client, ANTHROPIC_MODEL
            import anthropic
            client = anthropic.Anthropic(api_key=llm["api_key"]) if llm.get("api_key") else get_llm_client()
            response = client.messages.parse(
                model=llm.get("model") or ANTHROPIC_MODEL,
                max_tokens=512,
                system=system,
                messages=[{"role": "user", "content": answer_text}],
                output_format=LeadVerdict,
            )
            verdict = response.parsed_output
    except (LLMCallError, ValidationError) as e:
        return "needs_review", f"Evaluation failed: {e}"
    except Exception as e:
        return "needs_review", f"Evaluation failed: {type(e).__name__}: {e}"

    return ("qualified" if verdict.qualified else "unqualified"), verdict.reason
