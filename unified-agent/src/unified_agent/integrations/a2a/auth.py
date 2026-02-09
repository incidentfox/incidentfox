"""
Authentication handlers for A2A protocol.

Supports:
- Bearer Token (service-to-service)
- API Key (header or query param)
- OAuth 2.0 Client Credentials (enterprise)
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class A2AAuth(ABC):
    """Base class for A2A authentication."""

    @abstractmethod
    def apply_auth(self, headers: dict[str, str], params: dict[str, str]) -> None:
        """
        Apply authentication to request.

        Args:
            headers: Request headers dict (will be modified)
            params: Request params dict (will be modified)
        """
        pass


class NoAuth(A2AAuth):
    """No authentication (public agents)."""

    def apply_auth(self, headers: dict[str, str], params: dict[str, str]) -> None:
        pass


class BearerAuth(A2AAuth):
    """Bearer token authentication."""

    def __init__(self, token: str):
        self.token = token

    def apply_auth(self, headers: dict[str, str], params: dict[str, str]) -> None:
        headers["Authorization"] = f"Bearer {self.token}"


class APIKeyAuth(A2AAuth):
    """API key authentication (header or query param)."""

    def __init__(
        self, api_key: str, location: str = "header", key_name: str = "X-API-Key"
    ):
        """
        Args:
            api_key: The API key value
            location: 'header' or 'query'
            key_name: Header name or query param name
        """
        self.api_key = api_key
        self.location = location
        self.key_name = key_name

    def apply_auth(self, headers: dict[str, str], params: dict[str, str]) -> None:
        if self.location == "header":
            headers[self.key_name] = self.api_key
        else:  # query
            params[self.key_name] = self.api_key


class OAuth2Auth(A2AAuth):
    """OAuth 2.0 Client Credentials flow authentication."""

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: str | None = None,
    ):
        """
        Args:
            token_url: OAuth token endpoint
            client_id: OAuth client ID
            client_secret: OAuth client secret
            scope: Optional OAuth scope
        """
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope

        self._access_token: str | None = None
        self._token_expiry: float = 0

    def apply_auth(self, headers: dict[str, str], params: dict[str, str]) -> None:
        """Apply OAuth2 bearer token, refreshing if needed."""
        token = self._get_valid_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

    def _get_valid_token(self) -> str | None:
        """Get a valid access token, refreshing if expired."""
        now = time.time()

        if self._access_token and now < self._token_expiry:
            return self._access_token

        try:
            data = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
            if self.scope:
                data["scope"] = self.scope

            with httpx.Client(timeout=10.0) as client:
                response = client.post(self.token_url, data=data)
                response.raise_for_status()

                token_data = response.json()
                self._access_token = token_data.get("access_token")
                expires_in = token_data.get("expires_in", 3600)

                # Refresh 5 minutes before expiry
                self._token_expiry = now + expires_in - 300

                logger.info("OAuth2 token refreshed (expires_in=%d)", expires_in)
                return self._access_token

        except Exception as e:
            logger.error("OAuth2 token refresh failed: %s", e)
            return None


def create_auth_from_config(auth_config: dict[str, Any]) -> A2AAuth:
    """
    Create auth handler from configuration.

    Args:
        auth_config: Auth configuration dict

    Returns:
        A2AAuth instance

    Example configs:
        {"type": "none"}
        {"type": "bearer", "token": "sk-abc123"}
        {"type": "apikey", "api_key": "abc123", "location": "header", "key_name": "X-API-Key"}
        {"type": "oauth2", "token_url": "...", "client_id": "...", "client_secret": "..."}
    """
    auth_type = auth_config.get("type", "none")

    if auth_type == "none":
        return NoAuth()

    elif auth_type == "bearer":
        return BearerAuth(token=auth_config["token"])

    elif auth_type == "apikey":
        return APIKeyAuth(
            api_key=auth_config["api_key"],
            location=auth_config.get("location", "header"),
            key_name=auth_config.get("key_name", "X-API-Key"),
        )

    elif auth_type == "oauth2":
        return OAuth2Auth(
            token_url=auth_config["token_url"],
            client_id=auth_config["client_id"],
            client_secret=auth_config["client_secret"],
            scope=auth_config.get("scope"),
        )

    else:
        logger.warning("Unknown auth type: %s", auth_type)
        return NoAuth()
