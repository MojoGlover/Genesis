"""PlugOps integration bridge for Rasa agent."""
import sys
from pathlib import Path

# Add PlugOps to path if available
plugops_path = Path.home() / "ai" / "PlugOps"
if plugops_path.exists():
    sys.path.insert(0, str(plugops_path))

try:
    from plugops.integrations.agent_bridge import connect_to_plugops
    PLUGOPS_AVAILABLE = True
except ImportError:
    PLUGOPS_AVAILABLE = False


async def register_rasa_agent(agent, agent_name: str = "RasaAgent"):
    """Register Rasa agent with PlugOps.
    
    Args:
        agent: SimplifiedRasaAgent instance
        agent_name: Name for the agent in PlugOps
        
    Returns:
        PlugOpsBridge instance or None if unavailable
    """
    if not PLUGOPS_AVAILABLE:
        print("⚠️  PlugOps not available - running standalone")
        return None
    
    bridge = await connect_to_plugops(
        agent_name=agent_name,
        agent_type="conversational",
        base_dir=str(Path(__file__).parent.parent),
        capabilities=["chat", "dialogue", "nlu"]
    )
    
    return bridge
