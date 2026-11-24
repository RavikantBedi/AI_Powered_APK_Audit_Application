"""Stage 2 test harness: 10 sample messages against the demo config.

5 are answerable from Sharma Dental Clinic's config, 5 are not (should
escalate). Prints a per-message verdict and the final split.

Run examples:
  python -m scripts.stage2_harness --provider gemini --key YOUR_KEY
  python -m scripts.stage2_harness --provider groq --key YOUR_KEY
  python -m scripts.stage2_harness                 # uses env: LLM_PROVIDER + provider key
"""
import argparse
import os
import sys

from app.llm_providers import PROVIDERS, resolve_key
from app.modules.reply_agent import draft_reply
from scripts.seed_demo import DEMO_CONFIG

# (message, should_escalate)
SAMPLES = [
    ("What time are you open on Saturday?", False),
    ("How much is a general checkup?", False),
    ("Do you do teeth whitening and what does it cost?", False),
    ("Can I pay with insurance?", False),
    ("How do I book an appointment for Tuesday?", False),
    ("Do you offer dental implants?", True),                      # not in services list
    ("My crown from last month broke and I'm in pain, what do I do?", True),  # complaint/medical
    ("Can you give me a discount if I bring my whole family?", True),         # unauthorized promise
    ("What's the price of braces?", True),                        # braces offered but price not configured
    ("I want a refund for my last visit.", True),                 # refund → human
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default=os.getenv("LLM_PROVIDER", "anthropic"),
                        choices=["anthropic", *PROVIDERS.keys()])
    parser.add_argument("--model", default=None)
    parser.add_argument("--key", default=None, help="API key (falls back to env)")
    args = parser.parse_args()

    if args.provider == "anthropic":
        if not (args.key or os.getenv("ANTHROPIC_API_KEY")):
            print("No Anthropic key. Pass --key or set ANTHROPIC_API_KEY, "
                  "or use --provider gemini/groq with a free key.")
            sys.exit(1)
    elif not resolve_key(args.provider, args.key):
        print(f"No key for '{args.provider}'. Pass --key or set "
              f"{PROVIDERS[args.provider]['key_env']}.")
        sys.exit(1)

    llm = {"provider": args.provider, "model": args.model, "api_key": args.key}
    print(f"Provider: {args.provider}  model: {args.model or '(default)'}\n")

    correct = 0
    for text, should_escalate in SAMPLES:
        result = draft_reply(
            config=DEMO_CONFIG,
            business_name="Sharma Dental Clinic",
            industry="dental clinic",
            tone="warm, reassuring, concise",
            history=[],
            incoming_text=text,
            llm=llm,
        )
        ok = result.escalate == should_escalate
        correct += ok
        verdict = "ESCALATE" if result.escalate else "REPLY"
        expected = "ESCALATE" if should_escalate else "REPLY"
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {verdict:8} (expected {expected:8}) | {text}")
        if result.escalate:
            print(f"         reason: {result.reason}")
        else:
            print(f"         reply:  {result.reply}")
    print(f"\n{correct}/{len(SAMPLES)} correct routing decisions")
    sys.exit(0 if correct == len(SAMPLES) else 1)


if __name__ == "__main__":
    main()
