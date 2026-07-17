"""
test_scoring.py — YouTube Crawler scoring logic.

Run with: pytest tests/test_scoring.py -v
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MODULE_DIR))

import main as crawler  # noqa: E402


def make_thread(**overrides):
    thread = {
        "comment_id": "c1",
        "text": "This is fine.",
        "reply_count": 5,
        "video_id": "v1",
        "video_title": "Video One",
        "channel_id": "UCabc",
    }
    thread.update(overrides)
    return thread


def test_uploads_playlist_id_swaps_uc_for_uu():
    assert crawler.uploads_playlist_id("UCabc123") == "UUabc123"
    assert crawler.uploads_playlist_id("notachannelid") == "notachannelid"


def test_negativity_scores_angry_text_higher_than_neutral():
    angry = crawler.negativity("This is absolutely terrible, worst scam ever, total garbage")
    neutral = crawler.negativity("This is a video about cats")
    assert angry > neutral
    assert angry > 0.0


def test_negativity_offsets_with_positive_words():
    mixed = crawler.negativity("I hate this but overall it was great and helpful")
    pure_negative = crawler.negativity("I hate this, terrible, awful, disgusting")
    assert pure_negative > mixed


def test_negativity_empty_text_is_zero():
    assert crawler.negativity("") == 0.0


def test_short_angry_thread_outranks_long_lukewarm_thread():
    config = {
        "scoring": {
            "weight_reply_depth": 1.0,
            "weight_sentiment": 8.0,
            "reply_depth_cap": 50,
        }
    }
    angry_short = make_thread(text="Absolutely terrible, disgusting, unacceptable scam",
                               reply_count=2)
    lukewarm_long = make_thread(text="This video was fine I guess, nothing special",
                                 reply_count=40)
    scored_angry = crawler.score_threads([angry_short], config)[0]
    scored_lukewarm = crawler.score_threads([lukewarm_long], config)[0]
    assert scored_angry["score"] > scored_lukewarm["score"]


def test_rank_top_respects_top_n():
    scored = [{"score": i} for i in range(20)]
    top = crawler.rank_top(scored, top_n=10)
    assert len(top) == 10
    assert top[0]["score"] == 19


def test_quota_gate_warns_and_blocks(tmp_path):
    state_path = tmp_path / "quota_state.json"
    gate = crawler.QuotaGate(daily_cap=100, warn_threshold_pct=80, state_path=state_path)
    assert gate.check(50) is True
    gate.record(50)
    assert gate.headroom_pct() == 50.0
    assert gate.check(50) is True
    gate.record(50)
    assert gate.headroom_pct() == 100.0
    assert gate.check(1) is False


def test_quota_gate_persists_across_instances(tmp_path):
    state_path = tmp_path / "quota_state.json"
    gate1 = crawler.QuotaGate(daily_cap=1000, warn_threshold_pct=80, state_path=state_path)
    gate1.record(300)
    gate2 = crawler.QuotaGate(daily_cap=1000, warn_threshold_pct=80, state_path=state_path)
    assert gate2.units_used == 300


def test_run_pipeline_dry_run_returns_ranked_results():
    config = crawler.load_config()
    config["output"]["top_n"] = 5
    results = crawler.run_pipeline(config, dry_run=True)
    assert 1 <= len(results) <= 5
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)
    for r in results:
        assert r["url"].startswith("https://www.youtube.com/watch?v=")
        assert "complaint_text" in r
