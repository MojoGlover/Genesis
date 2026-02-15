"""LangGraph-inspired workflow system for multi-step agent execution."""

from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, Field

from ai_starter.core.state import Step, Task


class NodeType(str, Enum):
    """Types of workflow nodes."""
    llm = "llm"
    tool = "tool"
    decision = "decision"
    end = "end"


class WorkflowNode(BaseModel):
    """A node in the workflow graph."""
    id: str
    type: NodeType
    action: str  # LLM prompt, tool name, or decision logic
    next_nodes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowGraph(BaseModel):
    """Directed graph representing an agent workflow."""
    nodes: dict[str, WorkflowNode] = Field(default_factory=dict)
    start_node: str = "start"
    
    def add_node(self, node: WorkflowNode) -> None:
        """Add a node to the graph."""
        self.nodes[node.id] = node
    
    def add_edge(self, from_node: str, to_node: str) -> None:
        """Add an edge between nodes."""
        if from_node in self.nodes:
            if to_node not in self.nodes[from_node].next_nodes:
                self.nodes[from_node].next_nodes.append(to_node)
    
    def get_next_node(self, current_node: str, condition: Any = None) -> str | None:
        """Get next node in workflow based on conditions."""
        if current_node not in self.nodes:
            return None
        
        next_nodes = self.nodes[current_node].next_nodes
        if not next_nodes:
            return None
        
        # Simple routing - can be enhanced with conditional logic
        return next_nodes[0]


class WorkflowExecutor:
    """Executor for LangGraph-style workflows."""
    
    def __init__(self, graph: WorkflowGraph):
        self.graph = graph
        self.execution_trace: list[str] = []
    
    async def execute(
        self,
        task: Task,
        node_handlers: dict[NodeType, Callable],
    ) -> dict[str, Any]:
        """Execute workflow from start to end."""
        current_node_id = self.graph.start_node
        context: dict[str, Any] = {"task": task, "results": []}
        
        while current_node_id:
            node = self.graph.nodes.get(current_node_id)
            if not node:
                break
            
            self.execution_trace.append(current_node_id)
            
            # Execute node based on type
            if node.type == NodeType.end:
                break
            
            handler = node_handlers.get(node.type)
            if handler:
                result = await handler(node, context)
                context["results"].append(result)
            
            # Get next node
            current_node_id = self.graph.get_next_node(current_node_id, context)
        
        return context
    
    def get_trace(self) -> list[str]:
        """Get execution trace for debugging."""
        return self.execution_trace


def create_simple_workflow() -> WorkflowGraph:
    """Create a simple plan-execute-reflect workflow."""
    graph = WorkflowGraph(start_node="plan")
    
    # Plan node
    graph.add_node(WorkflowNode(
        id="plan",
        type=NodeType.llm,
        action="Generate execution plan",
        next_nodes=["execute"],
    ))
    
    # Execute node
    graph.add_node(WorkflowNode(
        id="execute",
        type=NodeType.tool,
        action="Execute planned steps",
        next_nodes=["reflect"],
    ))
    
    # Reflect node
    graph.add_node(WorkflowNode(
        id="reflect",
        type=NodeType.llm,
        action="Reflect on execution",
        next_nodes=["end"],
    ))
    
    # End node
    graph.add_node(WorkflowNode(
        id="end",
        type=NodeType.end,
        action="Complete",
    ))
    
    return graph
