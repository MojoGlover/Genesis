"""
Wix CMS Collections — read and write content to Wix Data Collections.
Use this to read/write structured content on your Wix site.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
from .client import WixClient, WixConfig

logger = logging.getLogger(__name__)


class WixCMS:
    """
    Wix Data (CMS) API client.
    
    Read and write to Wix CMS collections.
    Common use: pull blog posts, products, or custom content collections.
    
    API: POST /wix-data/v2/items/query
    """

    def __init__(self, client: Optional[WixClient] = None, config: Optional[WixConfig] = None):
        self.wix = client or WixClient(config)

    def query(
        self,
        collection_id: str,
        filter: Optional[Dict] = None,
        sort: Optional[List] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Query a CMS collection.
        
        Example:
            cms.query("Blog/Posts", filter={"fieldName": "published", "operator": "eq", "value": True})
        """
        body = {
            "dataCollectionId": collection_id,
            "query": {
                "paging": {"limit": limit, "offset": offset},
            }
        }
        if filter:
            body["query"]["filter"] = filter
        if sort:
            body["query"]["sort"] = sort

        return self.wix.post("/wix-data/v2/items/query", body)

    def get_item(self, collection_id: str, item_id: str) -> Dict[str, Any]:
        """Get a single item by ID."""
        return self.wix.get(f"/wix-data/v2/items/{item_id}", params={"dataCollectionId": collection_id})

    def create_item(self, collection_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new item in a collection."""
        return self.wix.post("/wix-data/v2/items", {
            "dataCollectionId": collection_id,
            "dataItem": {"data": data},
        })

    def update_item(self, collection_id: str, item_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing item."""
        return self.wix.patch(f"/wix-data/v2/items/{item_id}", {
            "dataCollectionId": collection_id,
            "dataItem": {"id": item_id, "data": data},
        })

    def list_collections(self) -> Dict[str, Any]:
        """List all CMS collections on the site."""
        return self.wix.post("/wix-data/v2/collections/query", {"query": {}})
