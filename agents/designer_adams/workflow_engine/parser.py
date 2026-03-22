"""
ComfyUI Workflow Parser
Reads a workflow JSON and builds an internal graph representation
Adams can reason about — what connects to what, what type is where.
"""
import json
from pathlib import Path
from typing import Any, Optional


class WorkflowNode:
    def __init__(self, node_id: str, data: dict):
        self.id = node_id
        self.class_type = data.get("class_type", "Unknown")
        self.title = data.get("_meta", {}).get("title", self.class_type)
        self.inputs = data.get("inputs", {})
        self.outputs_meta = data.get("outputs", [])

    def get_connections(self) -> dict[str, tuple[str, int]]:
        """Returns {input_name: (source_node_id, output_slot)} for all connected inputs."""
        connections = {}
        for input_name, value in self.inputs.items():
            if isinstance(value, list) and len(value) == 2:
                source_id, source_slot = value
                connections[input_name] = (str(source_id), int(source_slot))
        return connections

    def get_literal_inputs(self) -> dict[str, Any]:
        """Returns {input_name: value} for all non-connected (literal) inputs."""
        literals = {}
        for input_name, value in self.inputs.items():
            if not (isinstance(value, list) and len(value) == 2):
                literals[input_name] = value
        return literals

    def __repr__(self):
        return f"Node({self.id}: {self.class_type})"


class WorkflowGraph:
    def __init__(self, nodes: dict[str, WorkflowNode]):
        self.nodes = nodes  # {node_id: WorkflowNode}

    def get_node(self, node_id: str) -> Optional[WorkflowNode]:
        return self.nodes.get(str(node_id))

    def find_by_type(self, class_type: str) -> list[WorkflowNode]:
        return [n for n in self.nodes.values() if n.class_type == class_type]

    def get_upstream(self, node_id: str) -> list[WorkflowNode]:
        """Get all nodes that feed into this node."""
        node = self.get_node(node_id)
        if not node:
            return []
        upstream = []
        for source_id, _ in node.get_connections().values():
            source = self.get_node(source_id)
            if source:
                upstream.append(source)
        return upstream

    def get_downstream(self, node_id: str) -> list[WorkflowNode]:
        """Get all nodes that consume output from this node."""
        downstream = []
        for n in self.nodes.values():
            for source_id, _ in n.get_connections().values():
                if source_id == str(node_id):
                    downstream.append(n)
        return downstream

    def find_terminal_nodes(self) -> list[WorkflowNode]:
        """Nodes with no outputs consumed by anything — usually SaveImage, PreviewImage."""
        all_source_ids = set()
        for n in self.nodes.values():
            for source_id, _ in n.get_connections().values():
                all_source_ids.add(source_id)
        return [n for n in self.nodes.values() if n.id not in all_source_ids]

    def find_root_nodes(self) -> list[WorkflowNode]:
        """Nodes with no connected inputs — loaders, empty latents."""
        return [n for n in self.nodes.values() if not n.get_connections()]

    def summary(self) -> str:
        """Human-readable summary for Adams to describe the workflow."""
        lines = [f"Workflow: {len(self.nodes)} nodes\n"]

        roots = self.find_root_nodes()
        lines.append(f"Entry points ({len(roots)}):")
        for n in roots:
            lits = n.get_literal_inputs()
            hint = ""
            if "ckpt_name" in lits:
                hint = f" [{lits['ckpt_name']}]"
            elif "unet_name" in lits:
                hint = f" [{lits['unet_name']}]"
            lines.append(f"  • {n.class_type}{hint}")

        samplers = self.find_by_type("KSampler") + self.find_by_type("KSamplerAdvanced")
        if samplers:
            lines.append(f"\nSamplers ({len(samplers)}):")
            for s in samplers:
                lits = s.get_literal_inputs()
                lines.append(
                    f"  • {s.class_type} — {lits.get('sampler_name','?')} / "
                    f"{lits.get('scheduler','?')} / "
                    f"steps={lits.get('steps','?')} / cfg={lits.get('cfg','?')}"
                )

        terminals = self.find_terminal_nodes()
        lines.append(f"\nOutputs ({len(terminals)}):")
        for t in terminals:
            lines.append(f"  • {t.class_type}")

        return "\n".join(lines)


def parse_workflow(source: str | dict | Path) -> WorkflowGraph:
    """
    Parse a ComfyUI workflow from:
    - A dict (already loaded JSON)
    - A JSON string
    - A file path
    """
    if isinstance(source, Path):
        with open(source) as f:
            data = json.load(f)
    elif isinstance(source, str):
        try:
            data = json.loads(source)
        except json.JSONDecodeError:
            # Maybe it's a file path as string
            with open(source) as f:
                data = json.load(f)
    else:
        data = source

    # ComfyUI API format: {node_id: {class_type, inputs, ...}}
    nodes = {}
    for node_id, node_data in data.items():
        if isinstance(node_data, dict) and "class_type" in node_data:
            nodes[str(node_id)] = WorkflowNode(str(node_id), node_data)

    return WorkflowGraph(nodes)
