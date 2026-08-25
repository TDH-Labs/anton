"""Bridge Anton's saved provider credentials into the dsh web host's own
settings document, so chat sessions use what the wizard saved.

WHY THIS EXISTS — the split-brain: the Ops Center settings page writes
provider keys into Anton's secrets.yaml, but the composer's model picker and
default model live in the HARNESS's config: $DSH_HOME/settings.yaml (an
`llm-pi-ai:` provider-profile section + an `agent-default-model:` section)
and `$DSH_HOME/.credentials.yaml`. Both documents are HOT-RELOADED by the
web host, so writing them applies immediately — no restart.

What we write per saved provider:
  - credentials document: <ENV_VAR>: <key>          (0600, atomic replace)
  - settings `llm-pi-ai.providers.<provider>`:      {apiKeyEnv: <ENV_VAR>}
    → registers a catalog route; every built-in model for that provider
    appears in the composer's picker.
When routes.cloud_model names an OpenRouter model that may not be in the
installed catalog (e.g. ox-alpha), we additionally emit a hand-declared twin
route `<provider>-custom` pinning exactly that model id, and point
agent-default-model at it — so the composer shows the user's choice as the
default instead of deepseek-official/deepseek-v4-flash.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

import yaml

# Hand-declared route support: providers where arbitrary model ids are
# reachable through one OpenAI-compatible base URL. Catalog-only elsewhere.
CUSTOM_ROUTE_BASES: dict[str, tuple[str, str]] = {
    # provider: (base_url, pi-ai api protocol)
    "openrouter": ("https://openrouter.ai/api/v1", "openai-completions"),
}

# Plausible capacity floor for hand-declared models whose true context is
# unknown; dispatch degrades gracefully if a request outgrows it.
_CUSTOM_CONTEXT_WINDOW = 128_000
_CUSTOM_MAX_TOKENS = 8_192


def dsh_home() -> str:
    """The web host's harness home. entrypoint.sh pins DSH_HOME into the data
    volume so settings/credentials/sessions survive app updates; the ~/.dsh
    fallback keeps local dev working."""
    from_env = os.environ.get("DSH_HOME", "").strip()
    return from_env or os.path.join(os.path.expanduser("~"), ".dsh")


def _read_yaml(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}
    except OSError:
        return {}


def _write_yaml_atomic(path: str, doc: dict[str, Any], mode: int) -> None:
    """Atomic replace so hot-reload watchers never observe a torn file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(doc, f)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def sync_dsh_settings(data_dir: str, config: dict) -> list[str]:
    """Mirror secrets.yaml provider keys (+ the cloud_model default pick)
    into the harness home. Idempotent; additive per provider — sections the
    user manages themselves in settings.yaml are merged, not clobbered.
    Returns human-readable change notes (for tests and startup logs)."""
    from .dashboard import _read_secrets  # single secrets-view implementation
    from .cli import _PROVIDER_ENV_VARS

    home = dsh_home()
    settings_path = os.path.join(home, "settings.yaml")
    creds_path = os.path.join(home, ".credentials.yaml")

    secrets = _read_secrets(data_dir)
    saved = {p: k for p, k in secrets.items()
             if p in _PROVIDER_ENV_VARS and isinstance(k, str) and k.strip()}
    if not saved:
        return []

    changes: list[str] = []

    # 1. Credentials document — flat name→secret map at 0600.
    creds = _read_yaml(creds_path)
    creds_changed = False
    for provider, key in saved.items():
        env_var = _PROVIDER_ENV_VARS[provider]
        if creds.get(env_var) != key:
            creds[env_var] = key
            creds_changed = True
            changes.append(f"credential {env_var} updated")
    if creds_changed:
        _write_yaml_atomic(creds_path, creds, 0o600)

    # 2. Settings document — llm-pi-ai profiles + agent-default-model.
    doc = _read_yaml(settings_path)
    section = dict(doc.get("llm-pi-ai") or {})
    providers = dict(section.get("providers") or {})
    registered: list[str] = []
    for provider in saved:
        env_var = _PROVIDER_ENV_VARS[provider]
        profile = dict(providers.get(provider) or {})
        profile.setdefault("apiKeyEnv", env_var)
        providers[provider] = profile
        registered.append(provider)

    cloud_model = ((config.get("routes") or {}).get("cloud_model") or "")
    prefer_cloud = (config.get("routes") or {}).get("prefer") == "cloud"
    if "/" in cloud_model and prefer_cloud:
        provider_part, model_part = cloud_model.split("/", 1)
        if provider_part in CUSTOM_ROUTE_BASES and provider_part in saved:
            base_url, api = CUSTOM_ROUTE_BASES[provider_part]
            custom_id = f"{provider_part}-custom"
            providers[custom_id] = {
                "displayName": "OpenRouter (custom)",
                "apiKeyEnv": _PROVIDER_ENV_VARS[provider_part],
                "api": api,
                "baseURL": base_url,
                "models": [{
                    "id": model_part,
                    "name": model_part,
                    "contextWindow": _CUSTOM_CONTEXT_WINDOW,
                    "maxTokens": _CUSTOM_MAX_TOKENS,
                }],
            }
            default_provider = custom_id
        else:
            default_provider = provider_part
        section["providers"] = providers
        doc["llm-pi-ai"] = section
        doc["agent-default-model"] = {"provider": default_provider, "model": model_part}
    else:
        section["providers"] = providers
        doc["llm-pi-ai"] = section

    old = _read_yaml(settings_path)
    if old != doc:
        _write_yaml_atomic(settings_path, doc, 0o600)
        changes.append(
            f"llm-pi-ai routes registered: {', '.join(registered)}"
            + (f"; agent-default-model set to {cloud_model}" if prefer_cloud and "/" in cloud_model else ""))

    return changes
