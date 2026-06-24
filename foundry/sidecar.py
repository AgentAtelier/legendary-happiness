"""Asset metadata sidecar — every forged asset gets a validated .sidecar.json
(C-07).  The sidecar records the pipeline type, generator, and export parameters
so the live pipeline can reason about assets without opening the GLB."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from decisions import DecisionPoint, to_dict as _decision_to_dict

# Resolved at module load: sidecar.py lives in foundry/ → parents[1] is repo root.
_SCHEMA_PATH = str(
    Path(__file__).resolve().parents[1]
    / "engine"
    / "devforge"
    / "governance"
    / "schemas"
    / "asset_metadata_sidecar_schema.json"
)


def _load_schema() -> dict:
    """Read the sidecar schema JSON from the engine checkout (standalone — no
    devforge import)."""
    return json.loads(Path(_SCHEMA_PATH).read_text(encoding="utf-8"))


def validate_sidecar(sidecar: dict) -> None:
    """Raise ``jsonschema.exceptions.ValidationError`` if *sidecar* does not
    conform to the asset metadata sidecar schema."""
    import jsonschema

    schema = _load_schema()
    jsonschema.validate(instance=sidecar, schema=schema)


def build_sidecar(
    spec: dict,
    glb_filename: str = "",
    decisions: Sequence[DecisionPoint] | None = None,
) -> dict:
    """Produce a sidecar dict VALID against the ``procedural`` branch of the
    asset-metadata schema.

    Parameters
    ----------
    spec:
        Compiled asset-spec (must contain ``asset_id`` and ``generator``).
    glb_filename:
        Reserved for future use (e.g. hashing the GLB); not currently written
        into the sidecar.
    decisions:
        Optional list of Decision Points to persist under the top-level
        ``"decisions"`` key (via ``decisions.to_dict``).  Falsy / empty
        means the key is OMITTED from the sidecar (the schema doesn't
        require it; future readers treat absence as "no decisions").
    """
    sidecar: dict = {
        "asset_id": spec["asset_id"],
        "pipeline_type": "procedural",
        "creation_date": datetime.now(UTC).isoformat(),
        "style_version": "0.1.0",
        "procedural": {
            "geometry_template_id": spec["generator"],
            "seed": 0,
            "export_parameters": {
                "format": "glb",
                "scale": 1.0,
                "apply_modifiers": True,
            },
            "lod_configuration": {
                "levels": [],
            },
            "collision_type": "convex",
            "biome_tags": [],
        },
    }
    if decisions:
        sidecar["decisions"] = [_decision_to_dict(d) for d in decisions]
    return sidecar


def write_sidecar(out_dir: str, asset_basename: str, sidecar: dict) -> str:
    """Write *sidecar* as ``<asset_basename>.sidecar.json`` inside *out_dir*.

    Returns the full path to the written file.
    """
    sidecar_path = Path(out_dir) / f"{asset_basename}.sidecar.json"
    sidecar_path.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
    return str(sidecar_path)
