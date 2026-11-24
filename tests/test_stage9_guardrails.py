"""Stage 9 tests: guardrail keyword/pattern matching against drafted replies.

Deterministic layer only (no LLM key in test env) — this is also the layer
that must never fail open, so it's the one worth testing hardest.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.modules import guardrails


def test_no_rules_never_blocks():
    assert guardrails.check_reply("Sure, I'll give you a 20% discount!", []) is None


def test_quoted_phrase_rule_blocks_literal_match():
    rules = ["Never say 'lifetime warranty'"]
    assert guardrails.check_reply("This comes with a lifetime warranty.", rules) == rules[0]
    assert guardrails.check_reply("This comes with a 2-year warranty.", rules) is None


def test_discount_builtin_pattern_blocks():
    rules = ["No discount promises"]
    assert guardrails.check_reply("I can offer you a 15% off deal.", rules) == "no_discount_promises"
    assert guardrails.check_reply("Our checkup costs Rs. 500.", rules) is None


def test_refund_guarantee_builtin_pattern_blocks():
    rules = ["No refund guarantees"]
    reply = "I guarantee a refund if you're not happy."
    assert guardrails.check_reply(reply, rules) == "no_refund_guarantees"


def test_medical_advice_builtin_pattern_blocks():
    rules = ["No medical advice"]
    reply = "You should take 500 mg of that twice a day."
    assert guardrails.check_reply(reply, rules) == "no_medical_advice"


def test_unrelated_rule_does_not_false_positive():
    # A rule about legal claims shouldn't block a normal discount-free reply.
    rules = ["No legal claims"]
    assert guardrails.check_reply("Our clinic is open Mon-Sat 9:30-7pm.", rules) is None


def test_empty_reply_never_blocks():
    assert guardrails.check_reply("", ["No discount promises"]) is None
