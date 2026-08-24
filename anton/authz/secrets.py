"""0600 file-write discipline for authZ artifacts (claim codes, keys,
genesis stamps). Writes are atomic (temp file + rename) so a crash never
leaves a truncated marker."""
from __future__ import annotations

import os


def write_private_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    os.chmod(path, 0o600)
