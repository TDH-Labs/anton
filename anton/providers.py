"""Shared AI-provider catalog + live model listing.

Single source of truth for every surface that shows providers (first-run
wizard, settings API-keys section, Add-ons). Before this file both UI
surfaces hardcoded their own diverging lists and there was no way to see
which models a key can actually use -- you saved a key into a void.
"""

import os
import urllib.error
import urllib.request
from typing import Any


def _p(id_: str, label: str, key_hint: str, signup_url: str, base_url: str,
       default_model: str, api_style: str = "openai") -> dict[str, Any]:
    return {
        "id": id_,
        "label": label,
        "keyHint": key_hint,
        "signupUrl": signup_url,
        "baseUrl": base_url,
        "defaultModel": default_model,
        # how its model-listing API is called: "openai" (Bearer, GET /models),
        # "anthropic" (x-api-key, GET /v1/models), "gemini" (?key= query).
        "apiStyle": api_style,
    }


PROVIDER_CATALOG: dict[str, dict[str, Any]] = {
    p["id"]: p
    for p in [
        _p("anthropic", "Anthropic", "sk-ant-…", "https://console.anthropic.com/settings/keys",
           "https://api.anthropic.com", "claude-sonnet-4-5", api_style="anthropic"),
        _p("openai", "OpenAI", "sk-…", "https://platform.openai.com/api-keys",
           "https://api.openai.com/v1", "gpt-4o"),
        _p("deepseek", "DeepSeek", "sk-…", "https://platform.deepseek.com/api_keys",
           "https://api.deepseek.com", "deepseek-chat"),
        _p("openrouter", "OpenRouter", "sk-or-…", "https://openrouter.ai/keys",
           "https://openrouter.ai/api/v1", "openrouter/auto"),
        _p("gemini", "Google Gemini", "AI…", "https://aistudio.google.com/app/apikey",
           "https://generativelanguage.googleapis.com/v1beta", "gemini-2.0-flash", api_style="gemini"),
        _p("groq", "Groq", "gsk_…", "https://console.groq.com/keys",
           "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
        _p("mistral", "Mistral", "…", "https://console.mistral.ai/api-keys",
           "https://api.mistral.ai/v1", "mistral-large-latest"),
        _p("xai", "xAI", "xai-…", "https://console.x.ai",
           "https://api.x.ai/v1", "grok-3-latest"),
    ]
}

CUSTOM_PROVIDER_ID = "custom"


def catalog_for_ui() -> list[dict[str, Any]]:
    """Providers plus the custom (OpenAI-compatible) option, ready for JSON."""
    out = sorted(PROVIDER_CATALOG.values(), key=lambda p: p["label"])
    out.append({
        "id": CUSTOM_PROVIDER_ID,
        "label": "Custom (OpenAI-compatible)",
        "keyHint": "API key",
        "signupUrl": "",
        "baseUrl": "",
        "defaultModel": "",
        "apiStyle": "openai",
        "custom": True,
    })
    return out


def _http_json(url: str, headers: dict[str, str], timeout: float = 12.0) -> Any:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def list_models(provider: str, key: str, base_url: str | None = None) -> list[str]:
    """Live-list model ids for a provider key. Raises ValueError with a
    user-presentable message on anything that isn't a clean model list."""
    if not key:
        raise ValueError("No API key provided")
    if provider == CUSTOM_PROVIDER_ID:
        if not base_url:
            raise ValueError("Custom providers need a base URL (e.g. http://localhost:11434/v1)")
        style, url = "openai", base_url.rstrip("/") + "/models"
    elif provider == "anthropic":
        style = "anthropic"
        url = PROVIDER_CATALOG["anthropic"]["baseUrl"] + "/v1/models"
    elif provider == "gemini":
        style = "gemini"
        url = PROVIDER_CATALOG["gemini"]["baseUrl"] + "/models"
    elif provider in PROVIDER_CATALOG:
        entry = PROVIDER_CATALOG[provider]
        style, url = "openai", entry["baseUrl"].rstrip("/") + "/models"
    else:
        raise ValueError(f"Unknown provider '{provider}'")

    import json
    try:
        if style == "anthropic":
            data = json.loads(_http_json(url, {"x-api-key": key, "anthropic-version": "2023-06-01"}))
            return sorted(m["id"] for m in data.get("data", []) if m.get("id"))
        if style == "gemini":
            data = json.loads(_http_json(f"{url}?key={key}"))
            models = [(m.get("name") or "").split("/")[-1] for m in data.get("models", []) if m.get("name")]
            return sorted(models)
        data = json.loads(_http_json(url, {"Authorization": f"Bearer {key}"}))
        ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
        return sorted(ids)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        if e.code in (401, 403):
            raise ValueError(f"{provider} rejected this key ({e.code}). Check the key and its billing status.") from e
        raise ValueError(f"{provider} returned {e.code}: {detail or e.reason}") from e
    except Exception as e:
        raise ValueError(f"Could not reach {provider}: {e}") from e
