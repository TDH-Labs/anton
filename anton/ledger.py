"""Append-only JSONL event log. One canonical writer (R9)."""
from __future__ import annotations

import fcntl
import json
import os
from typing import List, Optional

from .models import RunRecord


class Ledger:
    def __init__(self, path: str):
        self.path = path

    def ensure_dir(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def append(self, record: RunRecord) -> None:
        self.ensure_dir()
        with open(self.path, "a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(json.dumps(record.to_json(), ensure_ascii=False) + "\n")
                f.flush()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def read(self) -> List[dict]:
        if not os.path.exists(self.path):
            return []
        rows = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return rows

    def last_run(self, task: str) -> Optional[dict]:
        for row in reversed(self.read()):
            if row.get("task") == task:
                return row
        return None

    def runs_since(self, task: str, since_ts: str) -> List[dict]:
        return [r for r in self.read() if r.get("task") == task and r.get("ts", "") >= since_ts]
