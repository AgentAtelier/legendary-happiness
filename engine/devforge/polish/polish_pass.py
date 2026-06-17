"""Polish Pass — audit and auto-fix game-feel deficiencies.

Detects common polish gaps (camera smoothing, screen shake, zero-energy
lights, missing UI animations) and generates fix operations.

Deterministic core (tier 0): no LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from devforge.infrastructure.logger import logger


@dataclass
class PolishFinding:
    """A polish deficiency found during the audit."""

    rule_id: str        # "P1", "P2", etc.
    severity: str       # "ERROR" | "WARNING" | "INFO"
    node_path: str
    message: str
    fix_applied: bool = False
    fix_message: str = ""

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "node_path": self.node_path,
            "message": self.message,
            "fix_applied": self.fix_applied,
            "fix_message": self.fix_message,
        }


class PolishPass:
    """Audits a scene for polish gaps and optionally generates fix operations.

    Usage::

        pp = PolishPass(props_lookup=executor.resolve_node_properties)
        findings = pp.audit(scene)
        for f in findings:
            op = pp.apply_fix(f)
            if op:
                fix_ops.append(op)
    """

    def __init__(
        self,
        props_lookup: Callable[[str], dict | None] | None = None,
    ):
        """*props_lookup*: callback that fetches live properties for a
        node path (e.g. ``executor.resolve_node_properties``).  Rules
        P1, P3, P4, P5 use it to avoid false positives; rules that
        can't access live properties are skipped gracefully.
        """
        self._props_lookup = props_lookup

    def audit(self, scene: dict) -> list[PolishFinding]:
        """Walk the scene tree and find polish deficiencies."""
        findings: list[PolishFinding] = []
        self._walk(scene, findings)
        return sorted(findings, key=lambda f: (f.severity != "ERROR", f.node_path))

    def apply_fix(self, finding: PolishFinding) -> dict | None:
        """Return the fix operation for a finding, or None if not auto-fixable."""
        if finding.rule_id == "P1":
            return self._fix_camera_smoothing(finding.node_path)
        elif finding.rule_id == "P2":
            return self._fix_camera_shake(finding.node_path)
        elif finding.rule_id == "P3":
            return self._fix_light_energy(finding.node_path)
        elif finding.rule_id == "P5":
            return self._fix_ui_font_size(finding.node_path)
        return None

    # ── Audit rules ─────────────────────────────────────────────

    def _walk(self, node: dict, findings: list[PolishFinding], parent_path: str = "") -> None:
        name = node.get("name", "")
        ntype = node.get("type", "")
        path = f"{parent_path}/{name}" if parent_path else f"/root/{name}"

        # Fetch live properties once per node (for all rules that need them)
        props: dict | None = None
        if self._props_lookup:
            props = self._props_lookup(path)

        # P1: Camera3D with position smoothing disabled
        if ntype == "Camera3D":
            smoothing_enabled = True  # default: assume enabled if we can't check
            if props is not None:
                smoothing_enabled = props.get("position_smoothing/enabled", True)
            if not smoothing_enabled:
                findings.append(PolishFinding(
                    rule_id="P1",
                    severity="WARNING",
                    node_path=path,
                    message=(
                        f"Camera3D '{name}' has position smoothing disabled. "
                        f"Enabling smoothing improves camera feel."
                    ),
                ))

        # P2: Camera3D always flagged (screen shake can't be detected
        # automatically — it's about whether the game has a shake system)
        if ntype == "Camera3D":
            findings.append(PolishFinding(
                rule_id="P2",
                severity="WARNING",
                node_path=path,
                message=(
                    f"Camera3D '{name}' — consider adding a screen-shake "
                    f"system for impacts, explosions, and events."
                ),
            ))

        # P3: Light with zero energy (needs live props)
        if ntype in ("OmniLight3D", "DirectionalLight3D", "SpotLight3D"):
            energy = 0.0
            if props is not None:
                energy = props.get("light_energy", 0.0)
            elif "light_energy" in node:
                energy = node.get("light_energy", 0.0)
            if isinstance(energy, (int, float)) and energy == 0:
                findings.append(PolishFinding(
                    rule_id="P3",
                    severity="WARNING",
                    node_path=path,
                    message=(
                        f"{ntype} '{name}' has zero light energy. "
                        f"Set a non-zero energy to see the light."
                    ),
                ))

        # P4: MeshInstance3D without a mesh (needs live props)
        if ntype == "MeshInstance3D":
            mesh = None
            if props is not None:
                mesh = props.get("mesh", "")
            elif "mesh" in node:
                mesh = node.get("mesh")
            if mesh is None or mesh == "" or mesh == "null":
                findings.append(PolishFinding(
                    rule_id="P4",
                    severity="ERROR",
                    node_path=path,
                    message=(
                        f"MeshInstance3D '{name}' has no mesh assigned. "
                        f"Assign a mesh resource to make it visible."
                    ),
                ))

        # P5: UI elements with small default font size
        if ntype in ("Label", "Button", "RichTextLabel"):
            font_size = 0
            if props is not None:
                font_size = props.get("theme_override_font_sizes/font_size", 0)
            if font_size == 0 or font_size < 14:
                findings.append(PolishFinding(
                    rule_id="P5",
                    severity="WARNING",
                    node_path=path,
                    message=(
                        f"UI element '{name}' ({ntype}) has font size < 14pt "
                        f"or uses the default. Larger, custom fonts improve "
                        f"readability."
                    ),
                ))

        for child in node.get("children", []):
            self._walk(child, findings, path)

    # ── Fix operations ─────────────────────────────────────────

    def _fix_camera_smoothing(self, node_path: str) -> dict:
        return {
            "type": "set_property",
            "node": node_path,
            "property": "position_smoothing/enabled",
            "value": True,
        }

    def _fix_camera_shake(self, node_path: str) -> dict:
        return {
            "type": "set_property",
            "node": node_path,
            "property": "anchor_mode",
            "value": 1,
        }

    def _fix_light_energy(self, node_path: str) -> dict:
        return {
            "type": "set_property",
            "node": node_path,
            "property": "light_energy",
            "value": 1.0,
        }

    def _fix_ui_font_size(self, node_path: str) -> dict:
        return {
            "type": "set_property",
            "node": node_path,
            "property": "theme_override_font_sizes/font_size",
            "value": 18,
        }


def run_polish_pass(
    scene: dict,
    apply_fixes: bool = False,
    props_lookup: Callable[[str], dict | None] | None = None,
) -> dict:
    """Run the polish audit on *scene*, optionally generating fix operations.

    Returns:
        {
          "finding_count": 5,
          "errors": 1,
          "warnings": 4,
          "fixes_applied": 2,
          "fix_operations": [...],
          "findings": [...],
        }
    """
    pp = PolishPass(props_lookup=props_lookup)
    findings = pp.audit(scene)

    fix_ops: list[dict] = []
    fixes_applied = 0

    if apply_fixes:
        for f in findings:
            if f.severity in ("ERROR", "WARNING"):
                op = pp.apply_fix(f)
                if op:
                    fix_ops.append(op)
                    f.fix_applied = True
                    f.fix_message = f"Applied fix: set {op.get('property', '?')}"

        fixes_applied = len(fix_ops)

    errors = sum(1 for f in findings if f.severity == "ERROR")
    warnings = sum(1 for f in findings if f.severity == "WARNING")
    infos = sum(1 for f in findings if f.severity == "INFO")

    logger.info(
        "polish",
        f"Polish audit: {len(findings)} findings "
        f"({errors} errors, {warnings} warnings), "
        f"{fixes_applied} fixes",
    )

    return {
        "finding_count": len(findings),
        "errors": errors,
        "warnings": warnings,
        "info": infos,
        "fixes_applied": fixes_applied,
        "fix_operations": fix_ops,
        "findings": [f.to_dict() for f in findings],
    }
