"""
core/tools/web_search.py — Trusted web search with continuous source grading

Replaces the original bare DuckDuckGo wrapper with a tiered, continuously
evaluated search system. Sources are not just classified once on ingest —
they are graded every time they appear, tracked over time, and demoted if
they produce inconsistent or low-quality content.

Trust Tiers (structural — based on domain):
    Tier 1 — HIGH    Official docs, .gov, .edu, framework sites, standards bodies
    Tier 2 — MEDIUM  Well-known dev communities, GitHub, established tech blogs
    Tier 3 — LOW     General web (never trusted for teacher ingestion without review)

Source Grades (dynamic — earned through evaluation history):
    A  Consistently accurate, cross-validates well, high relevance
    B  Mostly accurate, minor gaps or stale content occasionally
    C  Mixed quality, use with verification
    D  Frequently inconsistent or low-relevance — demoted, flagged for review
    F  Known bad actor / disqualified — never served

Grade starts at the structural tier baseline and shifts over time:
    - Each use: cross-validation pass → updates running accuracy score
    - Score > 0.85  → promote toward A
    - Score 0.65–0.85 → hold at B/C
    - Score < 0.65  → demote toward D
    - Score < 0.40  → auto-flag for F review

Usage:
    from core.tools.web_search import search_trusted, classify_source, get_source_ledger

    results = search_trusted("Python asyncio tutorial", min_tier=2)
    for r in results:
        print(r.title, r.grade, r.trust_tier.label, r.url)

    # View the running grade ledger
    ledger = get_source_ledger()
    print(ledger.get_domain_summary("realpython.com"))

    # Manually record a quality signal after a result was used
    ledger.record_use("realpython.com", accurate=True, relevant=True)
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_LEDGER_DB = Path.home() / ".genesis" / "source_ledger.db"


# ── Trust Tier (structural) ───────────────────────────────────────────────────

class TrustTier(Enum):
    HIGH   = 1
    MEDIUM = 2
    LOW    = 3

    @property
    def label(self) -> str:
        return {1: "high", 2: "medium", 3: "low"}[self.value]


# ── Source Grade (dynamic, earned) ───────────────────────────────────────────

class SourceGrade(Enum):
    A = "A"   # Consistently excellent — trust and use freely
    B = "B"   # Mostly reliable — use with light verification
    C = "C"   # Mixed quality — always cross-check before teaching
    D = "D"   # Demoted — flagged, use only if no alternative
    F = "F"   # Disqualified — never served

    @property
    def label(self) -> str:
        descriptions = {
            "A": "excellent",
            "B": "reliable",
            "C": "mixed",
            "D": "demoted",
            "F": "disqualified",
        }
        return descriptions[self.value]

    @property
    def usable(self) -> bool:
        return self.value not in ("D", "F")


def _tier_to_initial_grade(tier: TrustTier) -> SourceGrade:
    """New domains start at a grade that reflects their structural tier."""
    return {
        TrustTier.HIGH:   SourceGrade.A,
        TrustTier.MEDIUM: SourceGrade.B,
        TrustTier.LOW:    SourceGrade.C,
    }[tier]


def _score_to_grade(score: float) -> SourceGrade:
    if score >= 0.90: return SourceGrade.A
    if score >= 0.75: return SourceGrade.B
    if score >= 0.55: return SourceGrade.C
    if score >= 0.35: return SourceGrade.D
    return SourceGrade.F


# ── Domain lists ──────────────────────────────────────────────────────────────

_TIER1_EXACT: set[str] = {
    # Python
    "docs.python.org", "python.org", "pypi.org",
    "docs.djangoproject.com", "fastapi.tiangolo.com",
    "flask.palletsprojects.com", "docs.aiohttp.org",
    "pydantic-docs.helpmanual.io", "docs.pydantic.dev",
    # JS / Web
    "developer.mozilla.org", "nodejs.org", "deno.land",
    "reactjs.org", "vuejs.org", "angular.io",
    "nextjs.org", "svelte.dev", "typescriptlang.org",
    # Systems languages
    "doc.rust-lang.org", "docs.rs", "go.dev",
    "kotlinlang.org", "swift.org", "docs.oracle.com",
    # Cloud / infra
    "docs.aws.amazon.com", "cloud.google.com",
    "docs.microsoft.com", "learn.microsoft.com",
    "docs.docker.com", "kubernetes.io", "helm.sh",
    # AI / ML
    "docs.anthropic.com", "platform.openai.com",
    "huggingface.co", "pytorch.org", "tensorflow.org",
    "scikit-learn.org", "numpy.org", "pandas.pydata.org",
    # Standards
    "ietf.org", "w3.org", "iso.org", "nist.gov", "owasp.org",
    # Databases
    "postgresql.org", "sqlite.org", "redis.io",
    "mongodb.com", "docs.qdrant.tech",
}

_TIER1_SUFFIXES: tuple[str, ...] = (".gov", ".edu")

_TIER2_EXACT: set[str] = {
    "stackoverflow.com", "github.com", "github.io",
    "dev.to", "hashnode.dev", "medium.com",
    "realpython.com", "css-tricks.com", "smashingmagazine.com",
    "digitalocean.com", "readthedocs.io", "gitbook.io",
    "blog.cloudflare.com", "netflixtechblog.com", "engineering.fb.com",
    "arxiv.org", "papers.nips.cc", "openreview.net",
    "towardsdatascience.com", "machinelearningmastery.com",
    "geeksforgeeks.org", "freecodecamp.org",
}

# Known bad actors — never serve regardless of tier
_BLOCKLIST: set[str] = {
    # Add domains here if they consistently produce hallucinated or harmful content
}


# ── Source Ledger (persistent grade tracking) ─────────────────────────────────

class DomainRecord(BaseModel):
    """Running quality record for a single domain."""
    domain:          str
    structural_tier: int
    current_grade:   str   = "B"
    accuracy_score:  float = 0.75     # running 0.0–1.0
    use_count:       int   = 0
    accurate_count:  int   = 0
    relevant_count:  int   = 0
    last_seen:       str   = Field(default_factory=lambda: datetime.utcnow().isoformat())
    flagged:         bool  = False
    notes:           str   = ""


class SourceLedger:
    """
    Persistent, thread-safe grade ledger for all domains seen by the search tool.

    Grades are updated every time a result is used and evaluated.
    The ledger is stored in SQLite at ~/.genesis/source_ledger.db.
    """

    def __init__(self, db_path: Path = _LEDGER_DB):
        self._db   = db_path
        self._lock = threading.Lock()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS domains (
                    domain           TEXT PRIMARY KEY,
                    structural_tier  INTEGER NOT NULL DEFAULT 2,
                    current_grade    TEXT    NOT NULL DEFAULT 'B',
                    accuracy_score   REAL    NOT NULL DEFAULT 0.75,
                    use_count        INTEGER NOT NULL DEFAULT 0,
                    accurate_count   INTEGER NOT NULL DEFAULT 0,
                    relevant_count   INTEGER NOT NULL DEFAULT 0,
                    last_seen        TEXT,
                    flagged          INTEGER NOT NULL DEFAULT 0,
                    notes            TEXT    DEFAULT ''
                )
            """)
            conn.commit()

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(self, domain: str) -> Optional[DomainRecord]:
        with sqlite3.connect(self._db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM domains WHERE domain = ?", (domain,)
            ).fetchone()
        if row:
            return DomainRecord(**dict(row), flagged=bool(row["flagged"]))
        return None

    def get_domain_summary(self, domain: str) -> Dict[str, Any]:
        rec = self.get(domain)
        if not rec:
            return {"domain": domain, "status": "unseen"}
        return {
            "domain":         rec.domain,
            "grade":          rec.current_grade,
            "accuracy_score": round(rec.accuracy_score, 3),
            "use_count":      rec.use_count,
            "flagged":        rec.flagged,
            "last_seen":      rec.last_seen,
        }

    def get_all_grades(self) -> List[Dict[str, Any]]:
        """Return all domain records sorted by grade then accuracy."""
        with sqlite3.connect(self._db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM domains ORDER BY current_grade ASC, accuracy_score DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Write ─────────────────────────────────────────────────────────────────

    def ensure_domain(self, domain: str, tier: TrustTier) -> DomainRecord:
        """Register a domain the first time it's seen, or return existing record."""
        existing = self.get(domain)
        if existing:
            return existing

        initial_grade = _tier_to_initial_grade(tier)
        initial_score = {
            TrustTier.HIGH:   0.90,
            TrustTier.MEDIUM: 0.75,
            TrustTier.LOW:    0.55,
        }[tier]

        with self._lock:
            with sqlite3.connect(self._db) as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO domains
                        (domain, structural_tier, current_grade, accuracy_score, last_seen)
                    VALUES (?, ?, ?, ?, ?)
                """, (domain, tier.value, initial_grade.value,
                      initial_score, datetime.utcnow().isoformat()))
                conn.commit()

        return self.get(domain)  # type: ignore

    def record_use(
        self,
        domain:   str,
        accurate: bool = True,
        relevant: bool = True,
    ) -> SourceGrade:
        """
        Record a quality signal after a result from this domain was used.

        Call this whenever a teacher module:
        - successfully teaches from a result (accurate=True, relevant=True)
        - finds the content contradicts verified knowledge (accurate=False)
        - finds the content off-topic (relevant=False)

        Returns the updated grade.
        """
        with self._lock:
            rec = self.get(domain)
            if not rec:
                tier = classify_source_domain(domain)
                rec  = self.ensure_domain(domain, tier)

            new_use      = rec.use_count + 1
            new_accurate = rec.accurate_count + (1 if accurate else 0)
            new_relevant = rec.relevant_count + (1 if relevant else 0)

            # Weighted accuracy: accuracy gets 70%, relevance 30%
            acc_ratio = new_accurate / new_use
            rel_ratio = new_relevant / new_use
            new_score = (acc_ratio * 0.70) + (rel_ratio * 0.30)

            # Never let official Tier-1 domains fall below C (structural floor)
            if rec.structural_tier == 1:
                new_score = max(new_score, 0.55)

            new_grade = _score_to_grade(new_score)
            flagged   = new_score < 0.40

            with sqlite3.connect(self._db) as conn:
                conn.execute("""
                    UPDATE domains SET
                        use_count      = ?,
                        accurate_count = ?,
                        relevant_count = ?,
                        accuracy_score = ?,
                        current_grade  = ?,
                        flagged        = ?,
                        last_seen      = ?
                    WHERE domain = ?
                """, (new_use, new_accurate, new_relevant,
                      round(new_score, 4), new_grade.value,
                      int(flagged), datetime.utcnow().isoformat(),
                      domain))
                conn.commit()

            if flagged:
                logger.warning(
                    f"[SourceLedger] Domain '{domain}' auto-flagged: "
                    f"score={new_score:.2f} after {new_use} uses"
                )
            elif new_grade.value in ("C", "D"):
                logger.info(
                    f"[SourceLedger] Domain '{domain}' graded {new_grade.value}: "
                    f"score={new_score:.2f}"
                )

            return new_grade

    def flag_domain(self, domain: str, notes: str = "") -> None:
        """Manually flag a domain for human review."""
        with self._lock:
            with sqlite3.connect(self._db) as conn:
                conn.execute(
                    "UPDATE domains SET flagged = 1, notes = ? WHERE domain = ?",
                    (notes, domain),
                )
                conn.commit()
        logger.warning(f"[SourceLedger] Manually flagged domain: {domain} — {notes}")

    def disqualify_domain(self, domain: str, reason: str = "") -> None:
        """Set a domain to grade F — it will never be served again."""
        with self._lock:
            with sqlite3.connect(self._db) as conn:
                conn.execute(
                    "UPDATE domains SET current_grade = 'F', flagged = 1, notes = ? WHERE domain = ?",
                    (reason, domain),
                )
                conn.commit()
        logger.warning(f"[SourceLedger] Disqualified domain: {domain} — {reason}")


# ── Pydantic models ──────────────────────────────────────────────────────────

class SearchResult(BaseModel):
    """A single classified, continuously-graded search result."""
    title:       str
    snippet:     str
    url:         str
    trust_tier:  int   = 2           # structural: 1=high, 2=medium, 3=low
    grade:       str   = "B"         # dynamic: A/B/C/D/F
    confidence:  str   = "medium"    # derived from grade
    domain:      str   = ""
    raw_score:   float = 0.0         # position-based relevance score


class SearchSummary(BaseModel):
    query:       str
    results:     List[SearchResult]
    total_found: int = 0
    tier1_count: int = 0
    tier2_count: int = 0
    tier3_count: int = 0
    grade_a:     int = 0
    grade_b:     int = 0
    grade_c:     int = 0
    demoted:     int = 0
    error:       Optional[str] = None


# ── Source classification ─────────────────────────────────────────────────────

def classify_source_domain(domain: str) -> TrustTier:
    """Classify a bare domain string into a structural TrustTier."""
    d = re.sub(r"^www\.", "", domain).lower()

    if d in _TIER1_EXACT:
        return TrustTier.HIGH
    for t1 in _TIER1_EXACT:
        if d.endswith("." + t1):
            return TrustTier.HIGH
    if any(d.endswith(s) for s in _TIER1_SUFFIXES):
        return TrustTier.HIGH
    if d in _TIER2_EXACT:
        return TrustTier.MEDIUM
    for t2 in _TIER2_EXACT:
        if d.endswith("." + t2):
            return TrustTier.MEDIUM

    return TrustTier.LOW


def classify_source(url: str) -> TrustTier:
    """Classify a URL into a structural TrustTier."""
    if not url:
        return TrustTier.LOW
    try:
        hostname = urlparse(url if url.startswith("http") else f"https://{url}").hostname or ""
    except Exception:
        return TrustTier.LOW
    return classify_source_domain(hostname)


def _grade_to_confidence(grade: SourceGrade) -> str:
    return {"A": "high", "B": "high", "C": "medium", "D": "low", "F": "low"}[grade.value]


def _position_score(rank: int, total: int) -> float:
    if total <= 1:
        return 1.0
    return max(0.1, 1.0 - (rank / total) * 0.9)


# ── Core search ───────────────────────────────────────────────────────────────

def search_web(
    query:       str,
    max_results: int = 10,
    min_tier:    int = 3,
    min_grade:   str = "C",
) -> List[SearchResult]:
    """
    Search the web and return continuously-graded, classified results.

    Args:
        query:       Search query.
        max_results: Raw result count requested from DuckDuckGo.
        min_tier:    Structural filter (1=official only, 2=+community, 3=all).
        min_grade:   Dynamic grade floor ("A", "B", "C", "D").
                     Results from domains graded below this floor are excluded.
                     "F" domains are ALWAYS excluded regardless.

    Returns:
        List[SearchResult] sorted by (grade asc, position score desc).
    """
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        logger.error("[web_search] duckduckgo_search not installed — pip install duckduckgo-search")
        return []

    raw = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                raw.append(r)
    except Exception as exc:
        logger.warning(f"[web_search] DuckDuckGo search failed: {exc}")
        return []

    ledger    = get_source_ledger()
    total     = len(raw)
    grade_order = ["A", "B", "C", "D", "F"]
    min_grade_idx = grade_order.index(min_grade.upper()) if min_grade.upper() in grade_order else 2

    classified: List[SearchResult] = []

    for rank, r in enumerate(raw):
        url = r.get("href", "")

        # Skip blocklisted domains
        try:
            hostname = urlparse(url).hostname or ""
            domain   = re.sub(r"^www\.", "", hostname).lower()
        except Exception:
            domain = ""

        if domain in _BLOCKLIST:
            continue

        tier = classify_source_domain(domain)

        # Structural tier filter
        if tier.value > min_tier:
            continue

        # Ensure domain is in ledger (first-seen registration)
        rec = ledger.ensure_domain(domain, tier)

        # Dynamic grade filter — never serve F, filter below min_grade
        current_grade = SourceGrade(rec.current_grade) if rec else _tier_to_initial_grade(tier)
        if current_grade == SourceGrade.F:
            continue
        if grade_order.index(current_grade.value) > min_grade_idx:
            logger.debug(
                f"[web_search] Filtered '{domain}' — grade {current_grade.value} "
                f"below floor {min_grade}"
            )
            continue

        classified.append(SearchResult(
            title      = r.get("title", "").strip(),
            snippet    = r.get("body", "").strip(),
            url        = url,
            trust_tier = tier.value,
            grade      = current_grade.value,
            confidence = _grade_to_confidence(current_grade),
            domain     = domain,
            raw_score  = _position_score(rank, total),
        ))

    # Sort: best grade first, then by position relevance
    classified.sort(key=lambda r: (grade_order.index(r.grade), -r.raw_score))

    return classified


def search_trusted(
    query:       str,
    max_results: int = 8,
    min_tier:    int = 2,
    min_grade:   str = "C",
) -> List[SearchResult]:
    """
    Safe for teacher ingestion — Tier 1 + 2 only, grade C or better.
    """
    return search_web(
        query, max_results=max_results,
        min_tier=min_tier, min_grade=min_grade,
    )


def search_official(
    query:       str,
    max_results: int = 5,
) -> List[SearchResult]:
    """Tier 1 only (official docs, .gov, .edu). Maximum quality."""
    return search_web(query, max_results=max_results, min_tier=1, min_grade="B")


def search_and_summarize(
    query:       str,
    max_results: int = 5,
    min_tier:    int = 2,
) -> str:
    """
    Backward-compatible summary string (used by existing code).
    Returns a formatted text block with grade labels.
    """
    results = search_web(query, max_results=max_results, min_tier=min_tier, min_grade="C")

    if not results:
        return f"No trusted results found for: {query}"

    grade_icon = {"A": "✅", "B": "🔵", "C": "🟡", "D": "🔴", "F": "⛔"}
    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        icon  = grade_icon.get(r.grade, "?")
        lines.append(f"{i}. {icon} [{r.grade}] {r.title}")
        lines.append(f"   {r.snippet[:200]}...")
        lines.append(f"   {r.url}")
        lines.append("")

    return "\n".join(lines)


def search_summarized(
    query:       str,
    max_results: int = 5,
    min_tier:    int = 2,
    min_grade:   str = "C",
) -> SearchSummary:
    """Full summary object with tier + grade stats."""
    results = search_web(query, max_results=max_results,
                         min_tier=min_tier, min_grade=min_grade)

    return SearchSummary(
        query       = query,
        results     = results,
        total_found = len(results),
        tier1_count = sum(1 for r in results if r.trust_tier == 1),
        tier2_count = sum(1 for r in results if r.trust_tier == 2),
        tier3_count = sum(1 for r in results if r.trust_tier == 3),
        grade_a     = sum(1 for r in results if r.grade == "A"),
        grade_b     = sum(1 for r in results if r.grade == "B"),
        grade_c     = sum(1 for r in results if r.grade == "C"),
        demoted     = sum(1 for r in results if r.grade in ("D", "F")),
    )


# ── RAG integration helper ────────────────────────────────────────────────────

def result_to_chunk(
    result:     SearchResult,
    topic:      str = "",
    chunk_type: str = "fact",
) -> Dict[str, Any]:
    """
    Convert a SearchResult to a metadata dict for RAGRetriever.store().

    Usage:
        from core.tools.web_search import search_trusted, result_to_chunk
        from core.intelligence.rag import get_retriever

        retriever = get_retriever()
        for r in search_trusted("Python decorators"):
            retriever.store(
                text=r.snippet,
                metadata=result_to_chunk(r, topic="python", chunk_type="concept"),
                collection="teacher_knowledge",
            )
    """
    return {
        "source":     result.url,
        "trust_tier": result.trust_tier,
        "grade":      result.grade,
        "confidence": result.confidence,
        "topic":      topic,
        "type":       chunk_type,
        "domain":     result.domain,
        "title":      result.title,
    }


# ── Singleton ─────────────────────────────────────────────────────────────────

_ledger: Optional[SourceLedger] = None


def get_source_ledger() -> SourceLedger:
    """Get (or create) the global SourceLedger singleton."""
    global _ledger
    if _ledger is None:
        _ledger = SourceLedger()
    return _ledger
