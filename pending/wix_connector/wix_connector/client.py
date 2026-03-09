"""
Wix Headless API client.
Uses Wix's REST API with OAuth2 or API Key authentication.

Wix Headless API docs: https://dev.wix.com/docs/rest

To use:
1. Go to Wix dashboard → Settings → API Keys → Create API Key
2. Or use OAuth (for per-site access)
3. Set SITE_ID and API_KEY env vars
"""
from __future__ import annotations
import os
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

WIX_API_BASE = "https://www.wixapis.com"
WIX_MANAGE_BASE = "https://manage.wix.com/premium-purchase-page/dynamo"


@dataclass
class WixConfig:
    site_id: str           # Wix Site ID (from dashboard URL)
    api_key: str           # Wix API Key
    account_id: str = ""   # Account ID (optional, for some endpoints)


class WixClient:
    """Base Wix Headless API client."""

    def __init__(self, config: Optional[WixConfig] = None):
        self.config = config or self._load_from_env()
        self._session = None

    def _load_from_env(self) -> WixConfig:
        return WixConfig(
            site_id=os.getenv("WIX_SITE_ID", ""),
            api_key=os.getenv("WIX_API_KEY", ""),
            account_id=os.getenv("WIX_ACCOUNT_ID", ""),
        )

    @property
    def session(self):
        if self._session is None:
            try:
                import httpx
                self._session = httpx.Client(
                    timeout=30,
                    headers={
                        "Authorization": self.config.api_key,
                        "wix-site-id": self.config.site_id,
                        "Content-Type": "application/json",
                    }
                )
            except ImportError:
                raise RuntimeError("Run: pip install httpx")
        return self._session

    def is_configured(self) -> bool:
        return bool(self.config.site_id and self.config.api_key)

    def get(self, path: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a GET request to the Wix API."""
        if not self.is_configured():
            return {"error": "Wix not configured — set WIX_SITE_ID and WIX_API_KEY"}
        try:
            response = self.session.get(f"{WIX_API_BASE}{path}", params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Wix GET {path} failed: {e}")
            return {"error": str(e)}

    def post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Make a POST request to the Wix API."""
        if not self.is_configured():
            return {"error": "Wix not configured — set WIX_SITE_ID and WIX_API_KEY"}
        try:
            response = self.session.post(f"{WIX_API_BASE}{path}", json=body)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Wix POST {path} failed: {e}")
            return {"error": str(e)}

    def patch(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Make a PATCH request to the Wix API."""
        if not self.is_configured():
            return {"error": "Wix not configured"}
        try:
            response = self.session.patch(f"{WIX_API_BASE}{path}", json=body)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Wix PATCH {path} failed: {e}")
            return {"error": str(e)}

    def get_status(self) -> dict:
        return {
            "configured": self.is_configured(),
            "site_id": self.config.site_id[:8] + "..." if self.config.site_id else "not set",
            "api_key": "set" if self.config.api_key else "not set",
        }
