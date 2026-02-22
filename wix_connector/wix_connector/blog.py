"""
Wix Blog API — create and manage blog posts.
Uses the Wix Blog v3 API.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
from .client import WixClient, WixConfig

logger = logging.getLogger(__name__)


class WixBlog:
    """
    Create and manage Wix blog posts programmatically.
    
    Engineer0 can auto-publish daily digests, research summaries,
    or any content as blog posts.
    """

    def __init__(self, client: Optional[WixClient] = None, config: Optional[WixConfig] = None):
        self.wix = client or WixClient(config)

    def list_posts(self, limit: int = 20, status: str = "PUBLISHED") -> Dict[str, Any]:
        """List blog posts. status: PUBLISHED, DRAFT, SCHEDULED"""
        return self.wix.post("/blog/v3/posts/query", {
            "query": {
                "filter": {"status": status},
                "paging": {"limit": limit},
                "sort": [{"fieldName": "publishedDate", "order": "DESC"}],
            }
        })

    def get_post(self, post_id: str) -> Dict[str, Any]:
        """Get a single blog post."""
        return self.wix.get(f"/blog/v3/posts/{post_id}")

    def create_draft(
        self,
        title: str,
        content_html: str,
        excerpt: str = "",
        tags: List[str] = [],
        cover_media_url: str = "",
    ) -> Dict[str, Any]:
        """
        Create a blog post draft.
        
        content_html: HTML content for the post body
        Returns the created draft with post_id
        """
        body: Dict[str, Any] = {
            "post": {
                "title": title,
                "richContent": {
                    "nodes": [
                        {
                            "type": "PARAGRAPH",
                            "nodes": [{"type": "TEXT", "textData": {"text": content_html}}]
                        }
                    ]
                },
                "excerpt": excerpt or title[:200],
            }
        }
        if tags:
            body["post"]["tagIds"] = []  # Tags require separate tag creation
        if cover_media_url:
            body["post"]["media"] = {"custom": {"url": cover_media_url}}

        return self.wix.post("/blog/v3/posts", body)

    def publish_post(self, post_id: str) -> Dict[str, Any]:
        """Publish a draft post."""
        return self.wix.post(f"/blog/v3/posts/{post_id}/publish", {})

    def create_and_publish(self, title: str, content_html: str, excerpt: str = "") -> Dict[str, Any]:
        """Create a draft and immediately publish it."""
        draft_result = self.create_draft(title, content_html, excerpt)
        if "error" in draft_result:
            return draft_result
        
        post_id = draft_result.get("post", {}).get("id")
        if not post_id:
            return {"error": "No post ID in create response", "raw": draft_result}
        
        publish_result = self.publish_post(post_id)
        return {
            "success": "error" not in publish_result,
            "post_id": post_id,
            "publish_result": publish_result,
        }
