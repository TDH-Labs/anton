"""Typed principals for Anton authZ (AUTHZ-SPEC §9, REQ-PRIN-01).

Non-human principals are distinct types, never aliases of a human admin.
Repo functions that require a non-human context accept only
SystemPrincipal / MigrationPrincipal; UserPrincipal (including an Admin's)
raises PrincipalTypeError.
"""
from __future__ import annotations

from dataclasses import dataclass


class PrincipalTypeError(TypeError):
    """A human principal was supplied where a typed non-human principal is
    required (or vice versa)."""


@dataclass(frozen=True)
class UserPrincipal:
    user_id: str
    username: str
    role: str | None
    human_id: str  # the human sponsor behind this identity (self for users)
    kind: str = "user"  # "user" | "service"
    session_id: str = ""

    @property
    def principal_id(self) -> str:
        return self.user_id


@dataclass(frozen=True)
class SystemPrincipal:
    """Background jobs / schedulers / seeds. Narrowly scoped per invocation;
    never equals or borrows a human identity."""
    job_id: str
    kind: str = "system"

    @property
    def principal_id(self) -> str:
        return f"system:{self.job_id}"


@dataclass(frozen=True)
class MigrationPrincipal:
    """Alembic/raw-SQL migrations exclusively."""
    migration_name: str
    kind: str = "migration"

    @property
    def principal_id(self) -> str:
        return f"migration:{self.migration_name}"


def require_nonhuman(principal) -> None:
    if isinstance(principal, (SystemPrincipal, MigrationPrincipal)):
        return
    raise PrincipalTypeError(
        f"non-human principal required, got {type(principal).__name__}")
