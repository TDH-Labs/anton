"""Provider routing: local-first, cloud fallback (fleet philosophy, Q2)."""
from __future__ import annotations

import dataclasses
from typing import Optional

DEFAULT_LOCAL_MODEL = "[REDACTED-LOCAL-MODEL]"  # reference default; configurable
DEFAULT_CLOUD_MODEL = "openrouter/anthropic/claude-3.5-sonnet"


@dataclasses.dataclass
class Route:
    provider: str  # "local" | "cloud"
    model: str
    fallback: Optional[str] = None


def is_cloud(route: Route) -> bool:
    return route.provider == "cloud"


def select_route(*, local_model: str = DEFAULT_LOCAL_MODEL,
                 cloud_model: str = DEFAULT_CLOUD_MODEL,
                 prefer: str = "local") -> Route:
    if prefer == "cloud":
        return Route(provider="cloud", model=cloud_model, fallback=None)
    # local-first with cloud fallback
    return Route(provider="local", model=local_model, fallback=cloud_model)
