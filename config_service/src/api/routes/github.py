"""
GitHub App OAuth routes.

Handles the callback and setup URLs for GitHub App installation flow.
These are public-facing endpoints that GitHub redirects users to.
"""

import os
from typing import Optional
from urllib.parse import urlencode

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.db.models import GitHubInstallation
from src.db.session import get_db

logger = structlog.get_logger()

router = APIRouter(prefix="/github", tags=["github"])


def _get_github_app_config() -> dict:
    """Get GitHub App configuration from environment."""
    return {
        "app_id": os.getenv("GITHUB_APP_ID", ""),
        "client_id": os.getenv("GITHUB_APP_CLIENT_ID", ""),
        "client_secret": os.getenv("GITHUB_APP_CLIENT_SECRET", ""),
        "private_key": os.getenv("GITHUB_APP_PRIVATE_KEY", ""),
        "webhook_secret": os.getenv("GITHUB_APP_WEBHOOK_SECRET", ""),
        "app_name": os.getenv("GITHUB_APP_NAME", "incidentfox"),
        # Where to redirect after setup
        "setup_redirect_url": os.getenv(
            "GITHUB_SETUP_REDIRECT_URL",
            "https://ui.incidentfox.ai/integrations/github/setup",
        ),
    }


class GitHubInstallationInfo(BaseModel):
    """Information about a GitHub App installation."""

    installation_id: int
    account_login: str
    account_type: str
    account_avatar_url: Optional[str] = None
    repository_selection: Optional[str] = None
    repositories: Optional[list] = None
    linked: bool = False
    org_id: Optional[str] = None
    team_node_id: Optional[str] = None


@router.get("/callback")
async def github_callback(
    installation_id: Optional[int] = Query(None),
    setup_action: Optional[str] = Query(None),  # "install", "update", or "request"
    code: Optional[str] = Query(None),  # OAuth code for user auth (optional)
    state: Optional[str] = Query(None),  # State parameter for CSRF protection
    session: Session = Depends(get_db),
):
    """
    GitHub App installation callback.

    GitHub redirects here after a user installs or updates the app.
    We fetch the installation details and store them, then redirect to setup.

    Query Parameters (from GitHub):
    - installation_id: The GitHub App installation ID
    - setup_action: "install" for new installs, "update" for changes
    - code: OAuth authorization code (if user auth is requested)
    - state: CSRF protection state (if using OAuth)
    """
    config = _get_github_app_config()

    logger.info(
        "github_callback_received",
        installation_id=installation_id,
        setup_action=setup_action,
        has_code=bool(code),
    )

    if not installation_id:
        logger.warning("github_callback_missing_installation_id")
        raise HTTPException(
            status_code=400,
            detail="Missing installation_id. This endpoint should be called by GitHub.",
        )

    # Fetch installation details from GitHub API
    installation_data = await _fetch_installation_details(installation_id, config)

    if not installation_data:
        logger.error(
            "github_callback_fetch_failed",
            installation_id=installation_id,
        )
        raise HTTPException(
            status_code=502,
            detail="Failed to fetch installation details from GitHub",
        )

    # Store or update the installation
    account = installation_data.get("account", {})

    # Validate required fields from GitHub API
    account_login = account.get("login")
    account_type = account.get("type")
    account_id = account.get("id")

    if not account_login or not account_type or not account_id:
        logger.error(
            "github_callback_missing_account_data",
            installation_id=installation_id,
            has_login=bool(account_login),
            has_type=bool(account_type),
            has_id=bool(account_id),
        )
        raise HTTPException(
            status_code=502,
            detail="GitHub API returned incomplete account data",
        )

    existing = (
        session.query(GitHubInstallation)
        .filter(GitHubInstallation.installation_id == installation_id)
        .first()
    )

    if existing:
        # Update existing installation
        existing.app_id = installation_data.get("app_id")
        existing.account_id = account_id
        existing.account_login = account_login
        existing.account_type = account_type
        existing.account_avatar_url = account.get("avatar_url")
        existing.permissions = installation_data.get("permissions")
        existing.repository_selection = installation_data.get("repository_selection")
        existing.status = "active"
        existing.raw_data = installation_data

        # Fetch repositories if selection is "selected"
        if installation_data.get("repository_selection") == "selected":
            repos = await _fetch_installation_repositories(installation_id, config)
            existing.repositories = repos

        session.commit()
        logger.info(
            "github_installation_updated_via_callback",
            id=existing.id,
            installation_id=installation_id,
            account_login=account_login,
        )
    else:
        # Create new installation
        import uuid

        repos = None
        if installation_data.get("repository_selection") == "selected":
            repos = await _fetch_installation_repositories(installation_id, config)

        installation = GitHubInstallation(
            id=str(uuid.uuid4()),
            installation_id=installation_id,
            app_id=installation_data.get("app_id"),
            account_id=account_id,
            account_login=account_login,
            account_type=account_type,
            account_avatar_url=account.get("avatar_url"),
            permissions=installation_data.get("permissions"),
            repository_selection=installation_data.get("repository_selection"),
            repositories=repos,
            status="active",
            raw_data=installation_data,
        )
        session.add(installation)
        session.commit()

        logger.info(
            "github_installation_created_via_callback",
            id=installation.id,
            installation_id=installation_id,
            account_login=account_login,
        )

    # Redirect to setup page with installation_id
    setup_url = config["setup_redirect_url"]
    params = {
        "installation_id": str(installation_id),
        "account": account_login,
        "action": setup_action or "install",
    }
    redirect_url = f"{setup_url}?{urlencode(params)}"

    logger.info(
        "github_callback_redirecting",
        installation_id=installation_id,
        redirect_url=redirect_url,
    )

    return RedirectResponse(url=redirect_url, status_code=302)


@router.get("/installations/{installation_id}", response_model=GitHubInstallationInfo)
async def get_installation_info(
    installation_id: int,
    session: Session = Depends(get_db),
):
    """
    Get information about a GitHub installation.

    Used by the setup UI to display installation details.
    """
    installation = (
        session.query(GitHubInstallation)
        .filter(GitHubInstallation.installation_id == installation_id)
        .first()
    )

    if not installation:
        raise HTTPException(status_code=404, detail="Installation not found")

    return GitHubInstallationInfo(
        installation_id=installation.installation_id,
        account_login=installation.account_login,
        account_type=installation.account_type,
        account_avatar_url=installation.account_avatar_url,
        repository_selection=installation.repository_selection,
        repositories=installation.repositories,
        linked=bool(installation.org_id and installation.team_node_id),
        org_id=installation.org_id,
        team_node_id=installation.team_node_id,
    )


async def _fetch_installation_details(
    installation_id: int, config: dict
) -> Optional[dict]:
    """
    Fetch installation details from GitHub API using JWT authentication.

    Uses the GitHub App's private key to generate a JWT, then fetches
    the installation details.
    """
    import time

    import jwt

    app_id = config.get("app_id")
    private_key = config.get("private_key")

    if not app_id or not private_key:
        logger.error("github_app_not_configured", has_app_id=bool(app_id))
        return None

    # Generate JWT for GitHub App authentication
    now = int(time.time())
    payload = {
        "iat": now - 60,  # Issued 60 seconds ago (clock skew buffer)
        "exp": now + (10 * 60),  # Expires in 10 minutes
        "iss": app_id,
    }

    try:
        # Handle private key format (may have literal \n or actual newlines)
        if "\\n" in private_key:
            private_key = private_key.replace("\\n", "\n")

        token = jwt.encode(payload, private_key, algorithm="RS256")
    except Exception as e:
        logger.error("github_jwt_generation_failed", error=str(e))
        return None

    # Fetch installation details
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"https://api.github.com/app/installations/{installation_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )

            if response.status_code == 404:
                logger.warning(
                    "github_installation_not_found",
                    installation_id=installation_id,
                )
                return None

            response.raise_for_status()
            return response.json()

    except httpx.HTTPError as e:
        logger.error(
            "github_api_request_failed",
            installation_id=installation_id,
            error=str(e),
        )
        return None


async def _fetch_installation_repositories(
    installation_id: int, config: dict
) -> Optional[list]:
    """
    Fetch the list of repositories accessible to this installation.

    Returns a list of repository full names (e.g., ["org/repo1", "org/repo2"]).
    """
    import time

    import jwt

    app_id = config.get("app_id")
    private_key = config.get("private_key")

    if not app_id or not private_key:
        return None

    # Generate JWT
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (10 * 60),
        "iss": app_id,
    }

    try:
        if "\\n" in private_key:
            private_key = private_key.replace("\\n", "\n")
        token = jwt.encode(payload, private_key, algorithm="RS256")
    except Exception as e:
        logger.error("github_jwt_generation_failed", error=str(e))
        return None

    # Get installation access token
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # First, get an installation access token
            token_response = await client.post(
                f"https://api.github.com/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            token_response.raise_for_status()
            access_token = token_response.json().get("token")

            # Now fetch repositories with the installation token
            repos_response = await client.get(
                "https://api.github.com/installation/repositories",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            repos_response.raise_for_status()

            repos_data = repos_response.json()
            repositories = repos_data.get("repositories", [])

            return [
                repo.get("full_name") for repo in repositories if repo.get("full_name")
            ]

    except httpx.HTTPError as e:
        logger.error(
            "github_repos_fetch_failed",
            installation_id=installation_id,
            error=str(e),
        )
        return None
