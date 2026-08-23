"""BYO password-manager adapters (handoff #12).

The credential broker stores either inline secrets or REFERENCES:
    op://<vault>/<item>/<field>      -> 1Password (`op read`)
    bw://<item-id>[/<field>]         -> Bitwarden (`bw get item <id>`)
    vault://<relative/key>           -> file-backed secret dir (0700)

Resolution happens inside the broker at fetch time. Refs are treated as
secret material for storage purposes (encrypted, never logged) but the
RESOLVED value is what leaves the broker over the socket. Every adapter
fails closed: a missing CLI, nonzero exit, or timeout raises
RefResolutionError — the executor surfaces an explicit degraded state,
never a silent fallback.
"""
from __future__ import annotations

import os
import subprocess


class RefResolutionError(Exception):
    """A secret reference could not be resolved. Details stay internal —
    the broker surfaces only a generic denial to callers."""


class SecretAdapter:
    scheme = ""

    def resolve(self, ref: str) -> str:
        raise NotImplementedError


class CallableAdapter(SecretAdapter):
    def __init__(self, scheme: str, fn):
        self.scheme = scheme
        self._fn = fn

    def resolve(self, ref: str) -> str:
        out = self._fn(f"{self.scheme}://{ref}")
        if not isinstance(out, str) or not out:
            raise RefResolutionError("adapter returned empty value")
        return out


class CliAdapter(SecretAdapter):
    """Shells out with a minimal environment and hard timeout. stdout is
    the secret; it is stripped once and never echoed into exceptions."""

    def __init__(self, scheme: str, argv_template: list[str],
                 timeout_s: float = 15.0):
        self.scheme = scheme
        self.argv_template = list(argv_template)
        self.timeout_s = timeout_s

    def resolve(self, ref: str) -> str:
        # "{ref}" -> scheme-less body, "{uri}" -> full scheme://body
        argv = [a.replace("{uri}", f"{self.scheme}://{ref}")
                .replace("{ref}", ref)
                for a in self.argv_template]
        env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
               "HOME": os.environ.get("HOME", "/")}
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=self.timeout_s,
                env=env)
        except FileNotFoundError as e:
            raise RefResolutionError(
                f"{self.scheme} CLI not installed") from e
        except subprocess.TimeoutExpired as e:
            raise RefResolutionError(
                f"{self.scheme} CLI timed out") from e
        if proc.returncode != 0 or not proc.stdout.strip():
            raise RefResolutionError(f"{self.scheme} resolution failed")
        return proc.stdout.strip()


class FileVaultAdapter(SecretAdapter):
    """vault://<key> reads <root>/<key> (0600 expected). Rooted at a fixed
    directory; traversal out of the root is refused."""

    def __init__(self, root: str):
        self.scheme = "vault"
        self.root = os.path.realpath(root)

    def resolve(self, key: str) -> str:
        candidate = os.path.realpath(os.path.join(self.root, key))
        if not candidate.startswith(self.root + os.sep):
            raise RefResolutionError("vault ref escapes its root")
        if not os.path.isfile(candidate):
            raise RefResolutionError("vault file missing")
        with open(candidate, encoding="utf-8") as f:
            value = f.read().strip()
        if not value:
            raise RefResolutionError("vault file empty")
        return value


def default_resolver(vault_root: str | None = None) -> "SecretRefResolver":
    """BYO defaults: 1Password and Bitwarden via their CLIs, plus the
    file-backed vault. Deployments override any leg by calling
    broker.set_ref_adapters() with their own callables."""
    vault_root = vault_root or os.path.expanduser("~/secrets")
    return SecretRefResolver({
        "op": CliAdapter("op", ["op", "read", "{uri}"]),
        "bw": CliAdapter("bw", ["bw", "get", "item", "{ref}"]),
        "vault": FileVaultAdapter(vault_root),
    })


def _split_ref(value: str) -> tuple[str, str]:
    scheme, sep, rest = value.partition("://")
    if not sep or not rest or "://" in rest:
        raise RefResolutionError("unrecognized reference format")
    return scheme, rest


class SecretRefResolver:
    def __init__(self, adapters: dict[str, SecretAdapter]):
        self.adapters = adapters

    def is_ref(self, value: str) -> bool:
        try:
            scheme, _ = _split_ref(value)
        except RefResolutionError:
            return False
        return True

    def resolve(self, value: str) -> str:
        scheme, body = _split_ref(value)
        adapter = self.adapters.get(scheme)
        if adapter is None:
            raise RefResolutionError(f"no adapter for scheme {scheme!r}")
        resolved = adapter.resolve(body)
        if not resolved:
            raise RefResolutionError("resolution produced an empty secret")
        return resolved
