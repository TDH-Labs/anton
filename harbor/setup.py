"""Installer/setup: provision a fresh install dir (idempotent)."""
from __future__ import annotations

import os
import stat
from typing import Optional

from .config import load_config
from .db import init_db
from .defaults import DEFAULT_CONFIG_YAML, DEFAULT_JOBS_YAML
from .vault import provision_vault
from .vault_db import init_vault_db


def run_setup(install_dir: str, *, executor: str = "fake", org_id: str = "default",
              provider_keys: Optional[dict] = None, force: bool = False) -> dict:
    os.makedirs(install_dir, exist_ok=True)
    data_dir = os.path.join(install_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    cfg_path = os.path.join(install_dir, "config.yaml")
    if not os.path.exists(cfg_path) or force:
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(DEFAULT_CONFIG_YAML)
    config = load_config(cfg_path)
    config["general"]["executor"] = executor
    config["general"]["org_id"] = org_id

    jobs_path = os.path.join(data_dir, "jobs.yaml")
    if not os.path.exists(jobs_path) or force:
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(DEFAULT_JOBS_YAML)

    init_db(os.path.join(data_dir, "isolation.db"))
    vault_dir = provision_vault(os.path.join(data_dir, "vault"))
    init_vault_db(os.path.join(vault_dir, "vault.db"))

    secrets_path = os.path.join(install_dir, "secrets.yaml")
    if provider_keys and (not os.path.exists(secrets_path) or force):
        import yaml
        with open(secrets_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(provider_keys, f)
        os.chmod(secrets_path, stat.S_IRUSR | stat.S_IWUSR)  # 600

    return {
        "install_dir": install_dir,
        "data_dir": data_dir,
        "config": cfg_path,
        "jobs": jobs_path,
        "vault": vault_dir,
        "executor": executor,
        "org_id": org_id,
    }
