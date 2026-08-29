"""Web form mirroring .github/ISSUE_TEMPLATE/openbao-secret-request.yml, for
requesters who don't have (or don't want to use) a GitHub account. Files the
exact same shape of issue via the GitHub API, so the Cloud Operator's process
(infra/openbao/README.md) never needs to know which path a request came in
through - just the resulting issue.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from app.auth import require_auth
from app.config import settings
from app.github_issue_client import GitHubIssueError, create_issue
from app.templates import templates

logger = logging.getLogger(__name__)
router = APIRouter(tags=["openbao-request"])


def _build_issue(
    *,
    app_name: str,
    secret_name: str,
    requested_by: str,
    justification: str,
    token_period: str,
    submitted_by: str,
) -> tuple[str, str]:
    title = f"[OpenBao] {app_name}"
    body = "\n".join(
        [
            "### App name",
            "",
            app_name,
            "",
            "### Secret name",
            "",
            secret_name,
            "",
            "### Requested by (team or person)",
            "",
            requested_by,
            "",
            "### Why does this app need it?",
            "",
            justification,
            "",
            "### Token renewal period (optional)",
            "",
            token_period or "_(default)_",
            "",
            "---",
            f"_Filed via the in-app request form by {submitted_by}._",
        ]
    )
    return title, body


@router.get("/openbao-request", response_class=HTMLResponse)
async def openbao_request_form(request: Request, user: dict = Depends(require_auth)):
    return templates.TemplateResponse(
        request,
        "openbao_request.html",
        {
            "user": user,
            "page_title": "OpenBao",
            "form": {
                "app_name": "",
                "secret_name": "",
                "requested_by": user.get("name") or user.get("email") or "",
                "justification": "",
                "token_period": "",
            },
        },
    )


@router.post("/openbao-request", response_class=HTMLResponse)
async def openbao_request_submit(
    request: Request,
    app_name: Annotated[str, Form()],
    secret_name: Annotated[str, Form()],
    requested_by: Annotated[str, Form()],
    justification: Annotated[str, Form()],
    token_period: Annotated[str, Form()] = "",
    user: dict = Depends(require_auth),
):
    form = {
        "app_name": app_name.strip(),
        "secret_name": secret_name.strip(),
        "requested_by": requested_by.strip(),
        "justification": justification.strip(),
        "token_period": token_period.strip(),
    }
    context = {"user": user, "page_title": "OpenBao", "form": form}

    if not settings.OPENBAO_REQUEST_GITHUB_TOKEN:
        context["error"] = "openbao_request.error_not_configured"
        return templates.TemplateResponse(request, "openbao_request.html", context)

    submitted_by = user.get("email") or user.get("preferred_username") or user.get("sub", "unknown")
    title, body = _build_issue(**form, submitted_by=submitted_by)
    try:
        issue_url = await create_issue(
            repo=settings.OPENBAO_REQUEST_GITHUB_REPO,
            token=settings.OPENBAO_REQUEST_GITHUB_TOKEN,
            title=title,
            body=body,
            labels=["openbao-request"],
        )
    except GitHubIssueError as exc:
        logger.warning("Failed to file OpenBao request issue: %s", exc)
        context["error_detail"] = str(exc)
        return templates.TemplateResponse(request, "openbao_request.html", context)

    return templates.TemplateResponse(
        request, "openbao_request.html", {**context, "success_url": issue_url}
    )
