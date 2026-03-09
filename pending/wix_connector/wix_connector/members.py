"""Wix Members/Contacts — read contact list."""
from __future__ import annotations
from typing import Any, Dict, Optional
from .client import WixClient, WixConfig


class WixMembers:
    """Read Wix Contacts/Members."""

    def __init__(self, client: Optional[WixClient] = None, config: Optional[WixConfig] = None):
        self.wix = client or WixClient(config)

    def list_contacts(self, limit: int = 50) -> Dict[str, Any]:
        return self.wix.post("/contacts/v4/contacts/query", {
            "query": {"paging": {"limit": limit}}
        })

    def search_contacts(self, query: str) -> Dict[str, Any]:
        return self.wix.post("/contacts/v4/contacts/query", {
            "query": {"filter": {"$or": [
                {"info.name.first": {"$contains": query}},
                {"primaryInfo.email": {"$contains": query}},
            ]}}
        })
