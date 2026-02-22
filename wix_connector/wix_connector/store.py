"""Wix Store — read product catalog."""
from __future__ import annotations
from typing import Any, Dict, Optional
from .client import WixClient, WixConfig


class WixStore:
    """Read Wix Store product catalog."""

    def __init__(self, client: Optional[WixClient] = None, config: Optional[WixConfig] = None):
        self.wix = client or WixClient(config)

    def list_products(self, limit: int = 20, in_stock_only: bool = False) -> Dict[str, Any]:
        body: Dict[str, Any] = {"query": {"paging": {"limit": limit}}}
        if in_stock_only:
            body["query"]["filter"] = {"inStock": True}
        return self.wix.post("/stores/v1/products/query", body)

    def get_product(self, product_id: str) -> Dict[str, Any]:
        return self.wix.get(f"/stores/v1/products/{product_id}")
