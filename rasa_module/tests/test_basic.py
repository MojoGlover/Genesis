"""Basic tests for rasa_module."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_import():
    """Test rasa_module imports correctly."""
    import rasa_module
    assert rasa_module is not None


def test_agent_init():
    """Test SimplifiedRasaAgent can be initialized."""
    from rasa_module.ollama_policy import SimplifiedRasaAgent
    agent = SimplifiedRasaAgent(model="phi3:mini")
    assert agent.model == "phi3:mini"
    assert isinstance(agent.conversation_history, list)


def test_conversation_history_starts_empty():
    """Test conversation history is empty on init."""
    from rasa_module.ollama_policy import SimplifiedRasaAgent
    agent = SimplifiedRasaAgent()
    assert len(agent.conversation_history) == 0
