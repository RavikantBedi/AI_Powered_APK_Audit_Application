"""OpenAI-compatible chat client for alternative LLM providers.

Gemini (free tier at aistudio.google.com), Groq (free tier, fast Llama
models), and xAI Grok all expose OpenAI-compatible /chat/completions
endpoints, so one httpx client covers them. Anthropic keeps its own SDK
path in reply_agent.py.
"""
import json
import os

import httpx

PROVIDERS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-3.7-flash",
        "key_env": "GEMINI_API_KEY",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "openai/gpt-oss-120b",
        "key_env": "GROQ_API_KEY",
    },
    "xai": {
        "base_url": "https://api.x.ai/v1",
        "default_model": "grok-4.3",
        "key_env": "XAI_API_KEY",
    },
}


class LLMCallError(Exception):
    pass


def resolve_key(provider: str, api_key: str | None) -> str | None:
    spec = PROVIDERS.get(provider)
    for candidate in (api_key, os.getenv(spec["key_env"]) if spec else None,
                      os.getenv("LLM_API_KEY")):
        if candidate and candidate.strip():
            return candidate.strip()
    return None


def chat_json(provider: str, api_key: str | None, system: str,
              messages: list[dict], model: str | None = None) -> dict:
    """Send a chat request expecting a JSON object back. Raises LLMCallError."""
    spec = PROVIDERS.get(provider)
    if spec is None:
        raise LLMCallError(f"Unknown provider '{provider}'")
    key = resolve_key(provider, api_key)
    if not key:
        raise LLMCallError(f"No API key provided for provider '{provider}'")

    payload = {
        "model": model or spec["default_model"],
        "messages": [{"role": "system", "content": system}, *messages],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }
    try:
        r = httpx.post(
            f"{spec['base_url']}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {key}"},
            timeout=60,
        )
    except httpx.HTTPError as e:
        raise LLMCallError(f"{provider} request failed: {e}") from e
    if r.status_code != 200:
        raise LLMCallError(f"{provider} returned {r.status_code}: {r.text[:300]}")

    try:
        content = r.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as e:
        raise LLMCallError(f"{provider} returned unexpected response shape: {e}") from e

    # Some models wrap JSON in code fences despite response_format — extract
    # the outermost object rather than trusting the raw string.
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end == -1:
        raise LLMCallError(f"{provider} did not return JSON: {content[:200]}")
    try:
        return json.loads(content[start:end + 1])
    except json.JSONDecodeError as e:
        raise LLMCallError(f"{provider} returned invalid JSON: {e}") from e
