"""core.tools — Shared utility tools available to all GENESIS modules."""
from .web_search import (
    search_web,
    search_trusted,
    search_official,
    search_and_summarize,
    search_summarized,
    result_to_chunk,
    classify_source,
    classify_source_domain,
    get_source_ledger,
    TrustTier,
    SourceGrade,
    SearchResult,
    SearchSummary,
    SourceLedger,
)

__all__ = [
    "search_web", "search_trusted", "search_official",
    "search_and_summarize", "search_summarized", "result_to_chunk",
    "classify_source", "classify_source_domain", "get_source_ledger",
    "TrustTier", "SourceGrade", "SearchResult", "SearchSummary", "SourceLedger",
]
