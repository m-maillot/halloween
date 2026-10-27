"""Erreurs structurées de l'API : `detail = {message, issues[]}`."""

from fastapi import HTTPException

from halloween.api.schemas import IssueOut
from halloween.issues import Issue


def api_error(
    status: int, message: str, issues: list[Issue] | None = None, **extra: object
) -> HTTPException:
    body = {
        "message": message,
        "issues": [IssueOut.from_issue(i).model_dump() for i in issues or []],
        **extra,
    }
    return HTTPException(status, detail=body)
