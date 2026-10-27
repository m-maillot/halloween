"""Modèles de réponse de l'API (documentés dans l'OpenAPI)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from halloween.issues import Issue


class IssueOut(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    node_id: str | None = None
    component_id: str | None = None

    @classmethod
    def from_issue(cls, issue: Issue) -> IssueOut:
        return cls(
            severity=issue.severity,
            code=issue.code,
            message=issue.message,
            node_id=issue.node_id,
            component_id=issue.component_id,
        )


class ErrorBody(BaseModel):
    """Corps des erreurs structurées (`detail`) : message lisible et problèmes localisés."""

    message: str
    issues: list[IssueOut] = []


class RunOut(BaseModel):
    run_id: str
    program_id: str
    state: Literal["queued", "running", "ended"]
    outcome: Literal["completed", "stopped", "failed", "timeout"] | None = None
    error: str | None = None
    started_at: float | None = None
    ended_at: float | None = None


class HomeAssistantStatus(BaseModel):
    mode: Literal["real", "dry-run"]
    url: str | None = None
    last_ok_at: float | None = None
    last_error: str | None = None


class LockOut(BaseModel):
    locked: bool
    has_code: bool
    # Secondes avant le prochain essai de code autorisé (après trop d'essais ratés).
    retry_after_s: int | None = None


class Status(BaseModel):
    version: str
    lock: LockOut
    runs: list[RunOut]
    relays: dict[str, bool]
    home_assistant: HomeAssistantStatus
    startup_issues: list[IssueOut]


class Health(BaseModel):
    ok: bool
