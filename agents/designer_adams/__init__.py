"""
Designer Adams — Technical ComfyUI Specialist
GENESIS Agent | Built on BlackZero

Usage:
    from GENESIS.agents.designer_adams import adams

    # Analyze a workflow
    report = adams.analyze_workflow("path/to/workflow.json")

    # Build a new Flux workflow
    workflow = adams.build_flux_txt2img(prompt="...")

    # Debug why something isn't working
    issues = adams.debug("path/to/workflow.json")

    # Check ComfyUI status
    print(adams.status())
"""

from .workflow_engine.parser import parse_workflow
from .workflow_engine.builder import WorkflowBuilder
from .analyzer.debugger import WorkflowDebugger
from .api_client.comfyui_api import client as comfyui_client, status_report
from .voice.profile import adams_voice


class DesignerAdams:
    def __init__(self):
        self.name = "Designer Adams"
        self.debugger = WorkflowDebugger()
        self.comfyui = comfyui_client
        self.voice = adams_voice

    def analyze_workflow(self, source) -> str:
        """Parse a workflow and return a human-readable summary."""
        graph = parse_workflow(source)
        return graph.summary()

    def debug(self, source) -> str:
        """Analyze a workflow and return a full debug report."""
        graph = parse_workflow(source)
        return self.debugger.report(graph)

    def build_flux_txt2img(self, **kwargs) -> dict:
        b = WorkflowBuilder()
        return b.flux_txt2img(**kwargs)

    def build_sdxl_txt2img(self, **kwargs) -> dict:
        b = WorkflowBuilder()
        return b.sdxl_txt2img(**kwargs)

    def build_sdxl_img2img(self, **kwargs) -> dict:
        b = WorkflowBuilder()
        return b.sdxl_img2img(**kwargs)

    def status(self) -> str:
        return status_report()

    def queue(self, workflow: dict) -> str:
        """Queue a workflow dict in ComfyUI. Returns prompt_id."""
        return self.comfyui.queue_prompt(workflow)

    def queue_file(self, path: str) -> str:
        """Queue a workflow JSON file. Returns prompt_id."""
        return self.comfyui.queue_workflow_file(path)

    def available_models(self, model_type: str = "checkpoints") -> list[str]:
        return self.comfyui.get_available_models(model_type)


# Singleton
adams = DesignerAdams()

__all__ = ["adams", "DesignerAdams", "parse_workflow", "WorkflowBuilder", "WorkflowDebugger"]
