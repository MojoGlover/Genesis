"""
test_scoring.py — Reddit Crawler scoring logic.

Run with: pytest tests/test_scoring.py -v
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MODULE_DIR))

import main as crawler  # noqa: E402


def make_post(**overrides):
    post = {
        "subreddit": "antiwork",
        "title": "My manager yelled at me and I quit",
        "selftext": "Full story here.",
        "permalink": "/r/antiwork/comments/abc123/",
        "created_utc": time.time() - 3600,
        "num_comments": 40,
        "upvote_ratio": 0.9,
    }
    post.update(overrides)
    return post


def test_compute_age_hours():
    now = 1_000_000.0
    created = now - 7200
    assert crawler.compute_age_hours(created, now) == 2.0


def test_filter_recent_discards_old_posts():
    now = time.time()
    fresh = make_post(created_utc=now - 3600)
    stale = make_post(created_utc=now - 100 * 3600)
    result = crawler.filter_recent([fresh, stale], max_age_hours=72, now=now)
    assert result == [fresh]


def test_significant_words_drops_stopwords_and_short_tokens():
    words = crawler.significant_words("My Manager Yelled At Me and I Quit")
    assert "manager" in words
    assert "yelled" in words
    assert "and" not in words
    assert "at" not in words


def test_jaccard_similarity():
    a = {"manager", "yelled", "quit"}
    b = {"manager", "screamed", "quit"}
    assert 0.0 < crawler.jaccard(a, b) < 1.0
    assert crawler.jaccard(set(), b) == 0.0


def test_cluster_posts_groups_similar_titles():
    posts = [
        make_post(title="My manager screamed at me and I quit"),
        make_post(title="Boss screamed at me and I quit on the spot"),
        make_post(title="TIFU by microwaving fish in the break room"),
    ]
    sizes = crawler.cluster_posts(posts, threshold=0.3)
    assert sizes[0] == sizes[1] == 2
    assert sizes[2] == 1


def test_score_posts_rewards_velocity_ratio_and_repeats():
    now = time.time()
    posts = [
        make_post(title="Angry complaint one", num_comments=100, upvote_ratio=0.95,
                   created_utc=now - 3600),
        make_post(title="Angry complaint two", num_comments=1, upvote_ratio=0.5,
                   created_utc=now - 3600),
    ]
    config = {
        "scoring": {
            "weight_comment_velocity": 1.0,
            "weight_upvote_ratio": 5.0,
            "weight_repeat_signal": 3.0,
            "phrase_cluster_jaccard_threshold": 0.9,
        }
    }
    scored = crawler.score_posts(posts, config, now=now)
    assert scored[0]["score"] > scored[1]["score"]


def test_rank_top_respects_top_n():
    scored = [{"score": i} for i in range(20)]
    top = crawler.rank_top(scored, top_n=10)
    assert len(top) == 10
    assert top[0]["score"] == 19
    assert top[-1]["score"] == 10


def test_run_pipeline_dry_run_returns_ranked_results():
    config = crawler.load_config()
    config["output"]["top_n"] = 5
    results = crawler.run_pipeline(config, dry_run=True)
    assert 1 <= len(results) <= 5
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)
    for r in results:
        assert "url" in r and r["url"].startswith("https://reddit.com")
        assert "top_snippet" in r
