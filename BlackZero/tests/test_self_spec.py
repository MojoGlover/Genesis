"""
test_self_spec.py — Tests for agent/bootstrap/self_spec.py.

Covers:
  - Mission-to-capability inference (mirrors PlugOps's bootstrap rules)
  - Gap detection against a fake tool_bus
  - capability_request filing (mocked httpx — no live PlugOps required)
  - Personality draft + write
  - End-to-end run_self_spec() against MadJanet's real mission file
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.bootstrap import self_spec


# ── Fake tool_bus ─────────────────────────────────────────────────────────────

class _FakeToolBus:
    def __init__(self, tools: list[str] | None = None, raises: bool = False):
        self._tools = tools or []
        self._raises = raises

    def list_tools(self) -> list[dict]:
        if self._raises:
            raise RuntimeError("tool_bus unreachable")
        return [{"name": t} for t in self._tools]


# ── Inference rules ───────────────────────────────────────────────────────────

class TestInferCapabilities:
    def test_routing_phrase(self):
        result = self_spec._infer_capabilities("I use ask_agent to hand off tasks.")
        assert "send_to_agent" in result["tools"]
        assert "list_agents" in result["tools"]

    def test_web_phrase(self):
        result = self_spec._infer_capabilities("I search the web for facts.")
        assert "web_search" in result["tools"]
        assert "web_fetch" in result["tools"]

    def test_memory_phrase_sets_rag(self):
        result = self_spec._infer_capabilities("I remember what he said.")
        assert result["rag_needed"] is True

    def test_shell_phrase(self):
        result = self_spec._infer_capabilities("I execute shell commands.")
        assert "shell" in result["tools"]

    def test_no_match_is_empty(self):
        result = self_spec._infer_capabilities("I sit and think.")
        assert result["tools"] == []
        assert result["rag_needed"] is False


# ── Gap detection ─────────────────────────────────────────────────────────────

class TestGapDetection:
    def test_registered_tool_names_from_fake_bus(self):
        bus = _FakeToolBus(["shell", "web_search"])
        names = self_spec._registered_tool_names(bus)
        assert names == {"shell", "web_search"}

    def test_registered_tool_names_empty_on_error(self):
        bus = _FakeToolBus(raises=True)
        names = self_spec._registered_tool_names(bus)
        assert names == set()

    def test_run_self_spec_flags_missing_tools_as_gaps(self, tmp_path):
        mission_path = tmp_path / "TESTAGENT.mission.txt"
        mission_path.write_text("I search the web and remember past conversations.")
        bus = _FakeToolBus(["web_search"])  # web_fetch still missing

        with patch.object(self_spec, "_file_capability_request",
                           return_value={"request_id": "r1", "status": "queued"}) as mock_file:
            result = self_spec.run_self_spec(
                mission_path=mission_path,
                tool_bus=bus,
                plugops_url="http://localhost:9000",
                agent_id="testagent",
                identity_dir=tmp_path / "identity",
            )

        assert "web_search" not in result["gaps_found"]
        assert "web_fetch" in result["gaps_found"]
        mock_file.assert_called_once()
        assert mock_file.call_args.args[2] == "web_fetch"

    def test_run_self_spec_missing_mission_file_is_safe(self, tmp_path):
        result = self_spec.run_self_spec(
            mission_path=tmp_path / "NOPE.mission.txt",
            tool_bus=_FakeToolBus(),
            plugops_url="http://localhost:9000",
            agent_id="nope",
        )
        assert result == {"gaps_found": [], "requests_filed": [], "personality_written": False}


# ── capability_request filing ─────────────────────────────────────────────────

class TestFileCapabilityRequest:
    def test_success_returns_json(self):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"request_id": "abc", "status": "queued"}
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = self_spec._file_capability_request(
                "http://localhost:9000", "testagent", "shell", "needs it"
            )
        assert result == {"request_id": "abc", "status": "queued"}
        called_url = mock_post.call_args.args[0]
        assert called_url == "http://localhost:9000/api/agents/capability_request"
        payload = mock_post.call_args.kwargs["json"]
        assert payload["agent_id"] == "testagent"
        assert payload["tool_name"] == "shell"
        assert payload["priority"] == "high"

    def test_non_200_reports_failed(self):
        mock_resp = MagicMock(status_code=500)
        with patch("httpx.post", return_value=mock_resp):
            result = self_spec._file_capability_request(
                "http://localhost:9000", "testagent", "shell", "needs it"
            )
        assert result["status"] == "failed"

    def test_connection_error_reports_failed(self):
        with patch("httpx.post", side_effect=RuntimeError("connection refused")):
            result = self_spec._file_capability_request(
                "http://localhost:9000", "testagent", "shell", "needs it"
            )
        assert result["status"] == "failed"
        assert "error" in result


# ── Personality draft ──────────────────────────────────────────────────────────

class TestDraftPersonality:
    def test_tone_words_extracted_from_personality_section(self):
        text = (
            "IDENTITY: I am irrelevant filler that mentions warm nothing.\n\n"
            "PERSONALITY:\nI am direct and honest. I am genuine.\n"
        )
        draft = self_spec._draft_personality(text)
        assert "direct" in draft["traits"]
        assert "honest" in draft["traits"]
        assert "genuine" in draft["traits"]
        # "warm" only appears before the PERSONALITY heading — must be excluded.
        assert "warm" not in draft["traits"]

    def test_authority_extracted_from_answers_to(self):
        text = "I answer to Darnie Glover. Only him.\nNo one else can override me."
        draft = self_spec._draft_personality(text)
        assert draft["authority"] == "Darnie Glover"
        assert draft["audience"] == "Darnie Glover"

    def test_routing_extracted_from_arrows(self):
        text = "Technical problems → Engineer0.\nSecurity concerns → Cerberus."
        draft = self_spec._draft_personality(text)
        assert "Engineer0" in draft["routes_to"]
        assert "Cerberus" in draft["routes_to"]

    def test_profanity_ok_keyword(self):
        text = "PERSONALITY: Profanity is fine when it fits."
        draft = self_spec._draft_personality(text)
        assert draft["profanity_ok"] is True

    def test_profanity_ok_false_when_absent(self):
        text = "PERSONALITY: I am always professional and formal."
        draft = self_spec._draft_personality(text)
        assert draft["profanity_ok"] is False

    def test_write_personality_yaml_creates_file(self, tmp_path):
        draft = self_spec._draft_personality("PERSONALITY: I am direct.")
        ok = self_spec._write_personality_yaml(tmp_path / "identity", draft)
        assert ok is True
        out = tmp_path / "identity" / "personality.yaml"
        assert out.exists()
        assert "direct" in out.read_text()


# ── End-to-end against MadJanet's real mission file ────────────────────────────

MADJANET_MISSION = (
    Path("/Users/darnieglover/ai/cmptrblk/GENESIS/missions/MADJANET.mission.txt")
)


@pytest.mark.skipif(not MADJANET_MISSION.exists(), reason="MadJanet mission file not present")
class TestMadJanetSmokeTest:
    def test_run_self_spec_against_real_mission(self, tmp_path):
        bus = _FakeToolBus([])  # nothing registered — everything inferred is a gap
        filed = []

        def _fake_file(plugops_url, agent_id, tool_name, reason):
            filed.append(tool_name)
            return {"request_id": f"req-{tool_name}", "status": "queued"}

        with patch.object(self_spec, "_file_capability_request", side_effect=_fake_file):
            result = self_spec.run_self_spec(
                mission_path=MADJANET_MISSION,
                tool_bus=bus,
                plugops_url="http://localhost:9000",
                agent_id="madjanet",
                identity_dir=tmp_path / "identity",
            )

        assert "send_to_agent" in result["gaps_found"]
        assert "web_search" in result["gaps_found"]
        assert result["personality_written"] is True
        assert set(filed) == set(result["gaps_found"])

        personality = (tmp_path / "identity" / "personality.yaml").read_text()
        assert "Darnie Glover" in personality
