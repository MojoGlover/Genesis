"""
GENESIS Agent Registry

Manages agent lifecycle and provides control actions:
- Register/unregister agents
- Start/stop/restart agents
- Clear agent errors
- Query agent status

Integrates with HealthMonitor for status tracking.
"""

from __future__ import annotations
import logging
import threading
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.framework.agent_base import AgentBase

logger = logging.getLogger(__name__)


class AgentAction(Enum):
    """Actions that can be performed on agents."""
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    CLEAR_ERRORS = "clear_errors"


class AgentRegistry:
    """
    Central registry for all GENESIS agents.
    
    Provides:
    - Agent registration and discovery
    - Lifecycle management (start/stop/restart)
    - Error clearing
    - Integration with health monitor
    
    Usage:
        registry = get_agent_registry()
        registry.register(my_agent)
        registry.perform_action("my_agent", AgentAction.RESTART)
    """
    
    _instance: Optional[AgentRegistry] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> AgentRegistry:
        """Singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._agents: Dict[str, AgentBase] = {}
        self._agent_factories: Dict[str, Callable[[], AgentBase]] = {}
        self._action_history: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._initialized = True
        logger.info("AgentRegistry initialized")
    
    def register(self, agent: AgentBase, factory: Optional[Callable[[], AgentBase]] = None) -> None:
        """
        Register an agent with the registry.
        
        Args:
            agent: The agent instance to register
            factory: Optional factory function to recreate the agent on restart
        """
        with self._lock:
            name = agent.name
            if name in self._agents:
                logger.warning(f"Agent {name} already registered, replacing")
            
            self._agents[name] = agent
            if factory:
                self._agent_factories[name] = factory
            
            logger.info(f"Agent registered: {name}")
    
    def unregister(self, name: str) -> bool:
        """
        Unregister an agent.
        
        Args:
            name: The agent name to unregister
            
        Returns:
            True if agent was found and unregistered
        """
        with self._lock:
            if name in self._agents:
                del self._agents[name]
                if name in self._agent_factories:
                    del self._agent_factories[name]
                logger.info(f"Agent unregistered: {name}")
                return True
            return False
    
    def get_agent(self, name: str) -> Optional[AgentBase]:
        """Get an agent by name."""
        return self._agents.get(name)
    
    def list_agents(self) -> List[str]:
        """List all registered agent names."""
        return list(self._agents.keys())
    
    def get_all_agents(self) -> Dict[str, AgentBase]:
        """Get all registered agents."""
        return dict(self._agents)
    
    def perform_action(self, name: str, action: AgentAction) -> Dict[str, Any]:
        """
        Perform an action on an agent.
        
        Args:
            name: Agent name
            action: Action to perform
            
        Returns:
            Result dict with status and message
        """
        result = {
            "agent": name,
            "action": action.value,
            "timestamp": datetime.now().isoformat(),
            "success": False,
            "message": "",
        }
        
        agent = self._agents.get(name)
        if agent is None:
            result["message"] = f"Agent {name} not found in registry"
            self._record_action(result)
            return result
        
        try:
            if action == AgentAction.START:
                result = self._start_agent(agent, result)
            elif action == AgentAction.STOP:
                result = self._stop_agent(agent, result)
            elif action == AgentAction.RESTART:
                result = self._restart_agent(name, agent, result)
            elif action == AgentAction.CLEAR_ERRORS:
                result = self._clear_errors(agent, result)
            else:
                result["message"] = f"Unknown action: {action}"
                
        except Exception as e:
            logger.error(f"Error performing {action.value} on {name}: {e}")
            result["message"] = f"Error: {str(e)}"
        
        self._record_action(result)
        return result
    
    def _start_agent(self, agent: AgentBase, result: Dict) -> Dict:
        """Start an agent."""
        from core.framework.agent_base import AgentState
        
        if agent.state == AgentState.READY or agent.state == AgentState.BUSY:
            result["message"] = "Agent already running"
            result["success"] = True
            return result
        
        agent.start()
        result["success"] = True
        result["message"] = "Agent started"
        return result
    
    def _stop_agent(self, agent: AgentBase, result: Dict) -> Dict:
        """Stop an agent."""
        from core.framework.agent_base import AgentState
        
        if agent.state == AgentState.STOPPED:
            result["message"] = "Agent already stopped"
            result["success"] = True
            return result
        
        agent.stop()
        result["success"] = True
        result["message"] = "Agent stopped"
        return result
    
    def _restart_agent(self, name: str, agent: AgentBase, result: Dict) -> Dict:
        """Restart an agent (stop + start, or recreate if factory exists)."""
        # Stop first
        agent.stop()
        
        # If we have a factory, recreate the agent
        if name in self._agent_factories:
            factory = self._agent_factories[name]
            new_agent = factory()
            with self._lock:
                self._agents[name] = new_agent
            new_agent.start()
            result["message"] = "Agent recreated and started"
        else:
            # Just restart the existing instance
            agent.start()
            result["message"] = "Agent restarted"
        
        result["success"] = True
        return result
    
    def _clear_errors(self, agent: AgentBase, result: Dict) -> Dict:
        """Clear agent error count."""
        agent.reset_error_count()
        result["success"] = True
        result["message"] = "Errors cleared"
        return result
    
    def _record_action(self, result: Dict) -> None:
        """Record action in history."""
        self._action_history.append(result)
        # Keep last 100 actions
        if len(self._action_history) > 100:
            self._action_history = self._action_history[-100:]
    
    def get_action_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent action history."""
        return self._action_history[-limit:][::-1]
    
    def get_registry_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        return {
            "total_agents": len(self._agents),
            "agents": self.list_agents(),
            "agents_with_factory": list(self._agent_factories.keys()),
            "recent_actions": len(self._action_history),
        }


# Singleton accessor
_registry: Optional[AgentRegistry] = None


def get_agent_registry() -> AgentRegistry:
    """Get the global agent registry singleton."""
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry
