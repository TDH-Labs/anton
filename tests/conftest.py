"""Suite-wide environment neutralization.

Two CI-only failures have had the same root cause: the developer's machine
carries ambient provider state that CI does not -- an Ollama listening on
127.0.0.1:11434, provider API keys in the environment, vendor OAuth
credentials under $HOME. scheduler._provider_block (anton/scheduler.py:412)
consults exactly that state before every dispatch, so a job that CI skips
with exit 6 dispatches locally, and every assertion about the dispatch
passes locally and fails only on CI.

This makes a local run environmentally identical to CI for that class of
dependency. A test that needs a provider to LOOK present sets the variable
itself (monkeypatch.setenv / mock.patch.dict) -- explicit, visible in the
test, and undone at teardown. There is deliberately no opt-out marker: a
test that needs the real machine's provider state is by definition a test
that cannot pass on CI.
"""
import os
import tempfile

import pytest

# scheduler._PROVIDER_ENV_VARS / cli._PROVIDER_ENV_VARS -- the cloud leg of
# _provider_block (anton/scheduler.py:447).
_PROVIDER_KEYS = (
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
    "OPENROUTER_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY",
    "MISTRAL_API_KEY", "XAI_API_KEY",
)

# qbo_oauth.load_qbo_credentials (anton/qbo_oauth.py:62-65) and the
# per-provider fallback at anton/dashboard.py:1132.
_OAUTH_KEYS = (
    "ANTON_QBO_CLIENT_ID", "ANTON_QBO_CLIENT_SECRET",
    "QBO_CLIENT_ID", "QBO_CLIENT_SECRET", "QUICKBOOKS_CLIENT_SECRET",
)

# Deployment wiring that changes behaviour when an operator machine has it
# set: config.BRIDGE_ENV_VARS (anton/config.py:84-91), dashboard.py:327/384,
# mcp_server.py:261-262, ssh_executor.py:29-32, dashboard.py:109.
_DEPLOYMENT_KEYS = (
    "ANTON_COMPOSIO_API_KEY", "ANTON_COMPOSIO_BASE_URL",
    "ANTON_NANGO_SECRET_KEY", "ANTON_NANGO_HOST",
    "ANTON_DASHBOARD_TOKEN", "ANTON_BASE_URL", "ANTON_N8N_BASE_URL",
    "ANTON_WEB_DIST",
    "ANTON_SSH_HOST", "ANTON_SSH_USER", "ANTON_SSH_KEY", "ANTON_SSH_COMMAND",
)

# 127.0.0.1:1 refuses instantly (ECONNREFUSED); a black-holed address would
# cost _tcp_reachable's full 1s timeout on every gated dispatch.
UNREACHABLE_OLLAMA = "127.0.0.1:1"


def pytest_configure(config):
    """$HOME is redirected before anton is imported anywhere, because two
    credential legs read the developer's real home directory and neither is
    an env var: qbo_oauth.SECRETS_ENV_CANDIDATES (anton/qbo_oauth.py:19-22,
    a module-level tuple built at import time) and the vendor-credential
    file at anton/qbo_oauth.py:89. authz/secretrefs.py:102 defaults its
    file vault to ~/secrets the same way.
    """
    os.environ["HOME"] = tempfile.mkdtemp(prefix="anton-test-home-")


@pytest.fixture(autouse=True)
def isolated_environment():
    """Snapshot and restore the WHOLE environment, not just the names below.

    Restoring matters independently of neutralising: cli._load_secrets_into_env
    writes into the live os.environ (anton/cli.py:75) and is reached from
    POST /api/wizard/providers via dashboard.save_provider_key
    (anton/dashboard.py:868), so without this tests/test_dashboard_auth.py
    leaves OPENAI_API_KEY=sk-test set for every test that runs after it in
    the same process. monkeypatch.delenv cannot cover that -- deleting an
    already-absent name records nothing to undo.
    """
    saved = dict(os.environ)
    os.environ["OLLAMA_HOST"] = UNREACHABLE_OLLAMA
    for name in _PROVIDER_KEYS + _OAUTH_KEYS + _DEPLOYMENT_KEYS:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)
