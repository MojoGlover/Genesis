"""
Designer Adams — Workflow Debugger
Analyzes a parsed WorkflowGraph and returns a list of issues,
each with a severity, description, and fix suggestion.
"""
from dataclasses import dataclass
from typing import Literal
import sys
sys.path.insert(0, '/Users/darnieglover/ai/GENESIS/agents/designer_adams')

from workflow_engine.parser import WorkflowGraph, WorkflowNode
from node_library.core_nodes import SAMPLER_RECOMMENDATIONS


Severity = Literal["error", "warning", "tip"]


@dataclass
class Issue:
    severity: Severity
    node_id: str
    node_type: str
    title: str
    detail: str
    fix: str

    def __str__(self):
        icon = {"error": "✗", "warning": "⚠", "tip": "→"}[self.severity]
        return (
            f"{icon} [{self.severity.upper()}] Node {self.node_id} ({self.node_type})\n"
            f"   {self.title}\n"
            f"   Detail: {self.detail}\n"
            f"   Fix: {self.fix}"
        )


class WorkflowDebugger:

    def analyze(self, graph: WorkflowGraph) -> list[Issue]:
        issues = []
        issues.extend(self._check_disconnected_required_inputs(graph))
        issues.extend(self._check_flux_setup(graph))
        issues.extend(self._check_sampler_settings(graph))
        issues.extend(self._check_latent_dimensions(graph))
        issues.extend(self._check_lora_strength(graph))
        issues.extend(self._check_missing_output(graph))
        return issues

    def report(self, graph: WorkflowGraph) -> str:
        issues = self.analyze(graph)
        if not issues:
            return "No issues found. Workflow looks clean."

        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        tips = [i for i in issues if i.severity == "tip"]

        lines = [f"Found {len(issues)} issue(s): {len(errors)} errors, {len(warnings)} warnings, {len(tips)} tips\n"]

        for section, items in [("ERRORS", errors), ("WARNINGS", warnings), ("TIPS", tips)]:
            if items:
                lines.append(f"── {section} ──")
                for issue in items:
                    lines.append(str(issue))
                lines.append("")

        return "\n".join(lines)

    # ── CHECKS ────────────────────────────────────────────────────────────────

    def _check_disconnected_required_inputs(self, graph: WorkflowGraph) -> list[Issue]:
        """Critical inputs that must be connected but aren't."""
        issues = []
        required_connections = {
            "KSampler": ["model", "positive", "negative", "latent_image"],
            "KSamplerAdvanced": ["model", "positive", "negative", "latent_image"],
            "VAEDecode": ["samples", "vae"],
            "VAEEncode": ["pixels", "vae"],
            "CLIPTextEncode": ["clip"],
            "ControlNetApply": ["conditioning", "control_net", "image"],
            "LoraLoader": ["model", "clip"],
        }
        for node in graph.nodes.values():
            required = required_connections.get(node.class_type, [])
            connections = node.get_connections()
            for req_input in required:
                if req_input not in connections and req_input not in node.get_literal_inputs():
                    issues.append(Issue(
                        severity="error",
                        node_id=node.id,
                        node_type=node.class_type,
                        title=f"Required input '{req_input}' not connected",
                        detail=f"{node.class_type} needs '{req_input}' to function",
                        fix=f"Connect the appropriate output to '{req_input}' on node {node.id}"
                    ))
        return issues

    def _check_flux_setup(self, graph: WorkflowGraph) -> list[Issue]:
        """Flux-specific setup validation."""
        issues = []
        unet_nodes = graph.find_by_type("UNETLoader")
        checkpoint_nodes = graph.find_by_type("CheckpointLoaderSimple")
        dual_clip_nodes = graph.find_by_type("DualCLIPLoader")
        clip_nodes = graph.find_by_type("CLIPLoader")
        empty_latent_nodes = graph.find_by_type("EmptyLatentImage")
        sd3_latent_nodes = graph.find_by_type("EmptySD3LatentImage")

        # If using UNETLoader, must have DualCLIPLoader
        if unet_nodes and not dual_clip_nodes:
            issues.append(Issue(
                severity="error",
                node_id=unet_nodes[0].id,
                node_type="UNETLoader",
                title="Flux workflow missing DualCLIPLoader",
                detail="Flux requires T5-XXL + CLIP-L loaded via DualCLIPLoader",
                fix="Add a DualCLIPLoader node with t5xxl_fp8_e4m3fn.safetensors and clip_l.safetensors"
            ))

        # If using UNETLoader (Flux), should use EmptySD3LatentImage not EmptyLatentImage
        if unet_nodes and empty_latent_nodes and not sd3_latent_nodes:
            issues.append(Issue(
                severity="warning",
                node_id=empty_latent_nodes[0].id,
                node_type="EmptyLatentImage",
                title="Using EmptyLatentImage with Flux — may cause scaling issues",
                detail="Flux uses a different latent space (16-channel vs 4-channel)",
                fix="Replace EmptyLatentImage with EmptySD3LatentImage"
            ))

        # Check KSampler CFG for Flux workflows
        if unet_nodes:
            samplers = graph.find_by_type("KSampler") + graph.find_by_type("KSamplerAdvanced")
            for sampler in samplers:
                lits = sampler.get_literal_inputs()
                cfg = lits.get("cfg")
                if cfg is not None and float(cfg) > 2.0:
                    issues.append(Issue(
                        severity="warning",
                        node_id=sampler.id,
                        node_type=sampler.class_type,
                        title=f"CFG={cfg} is too high for Flux",
                        detail="Flux is a guidance-distilled model. CFG above 1.0-2.0 produces worse results.",
                        fix="Set cfg to 1.0 for Flux"
                    ))
                scheduler = lits.get("scheduler")
                if scheduler == "karras":
                    issues.append(Issue(
                        severity="warning",
                        node_id=sampler.id,
                        node_type=sampler.class_type,
                        title="Karras scheduler not recommended for Flux",
                        detail="Flux works best with 'simple' or 'beta' scheduler",
                        fix="Change scheduler to 'simple'"
                    ))
        return issues

    def _check_sampler_settings(self, graph: WorkflowGraph) -> list[Issue]:
        """General sampler sanity checks."""
        issues = []
        samplers = graph.find_by_type("KSampler") + graph.find_by_type("KSamplerAdvanced")
        for sampler in samplers:
            lits = sampler.get_literal_inputs()
            steps = lits.get("steps")
            if steps is not None and int(steps) < 10:
                issues.append(Issue(
                    severity="warning",
                    node_id=sampler.id,
                    node_type=sampler.class_type,
                    title=f"Steps={steps} is very low",
                    detail="Under 10 steps rarely produces quality results",
                    fix="Set steps to at least 20 for most workflows"
                ))
            cfg = lits.get("cfg")
            if cfg is not None and float(cfg) > 15:
                issues.append(Issue(
                    severity="warning",
                    node_id=sampler.id,
                    node_type=sampler.class_type,
                    title=f"CFG={cfg} is very high",
                    detail="CFG above 12-15 causes oversaturation and artifacts in most models",
                    fix="Try CFG 7-9 for SDXL/Pony"
                ))
        return issues

    def _check_latent_dimensions(self, graph: WorkflowGraph) -> list[Issue]:
        """Check for non-standard or mismatched latent dimensions."""
        issues = []
        latent_nodes = graph.find_by_type("EmptyLatentImage") + graph.find_by_type("EmptySD3LatentImage")
        for node in latent_nodes:
            lits = node.get_literal_inputs()
            w = lits.get("width", 0)
            h = lits.get("height", 0)
            if w and h:
                if int(w) % 64 != 0 or int(h) % 64 != 0:
                    issues.append(Issue(
                        severity="error",
                        node_id=node.id,
                        node_type=node.class_type,
                        title=f"Dimensions {w}x{h} not divisible by 64",
                        detail="All latent dimensions must be multiples of 64",
                        fix=f"Round to nearest 64: {round(int(w)/64)*64}x{round(int(h)/64)*64}"
                    ))
                if int(w) < 512 or int(h) < 512:
                    issues.append(Issue(
                        severity="warning",
                        node_id=node.id,
                        node_type=node.class_type,
                        title=f"Dimensions {w}x{h} may be too small",
                        detail="SD1.5 minimum is 512px. SDXL/Flux minimum recommended is 768px.",
                        fix="Use at least 1024x1024 for SDXL/Flux"
                    ))
        return issues

    def _check_lora_strength(self, graph: WorkflowGraph) -> list[Issue]:
        """Flag LoRA strengths that are likely to cause issues."""
        issues = []
        for node in graph.find_by_type("LoraLoader"):
            lits = node.get_literal_inputs()
            strength = lits.get("strength_model", 1.0)
            if float(strength) > 1.2:
                issues.append(Issue(
                    severity="warning",
                    node_id=node.id,
                    node_type="LoraLoader",
                    title=f"LoRA strength_model={strength} is high",
                    detail=f"LoRA '{lits.get('lora_name', 'unknown')}' at {strength} may cause artifacts or style blowout",
                    fix="Try reducing to 0.7-0.9"
                ))
        return issues

    def _check_missing_output(self, graph: WorkflowGraph) -> list[Issue]:
        """Warn if there's no SaveImage or PreviewImage in the workflow."""
        issues = []
        output_nodes = (
            graph.find_by_type("SaveImage") +
            graph.find_by_type("PreviewImage") +
            graph.find_by_type("VHS_VideoCombine")
        )
        if not output_nodes:
            issues.append(Issue(
                severity="warning",
                node_id="—",
                node_type="—",
                title="No output node found",
                detail="Workflow has no SaveImage, PreviewImage, or video output node",
                fix="Add a SaveImage or PreviewImage node connected to your final VAEDecode output"
            ))
        return issues
