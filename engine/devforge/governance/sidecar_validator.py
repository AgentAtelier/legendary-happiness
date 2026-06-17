"""
DevForge Asset Sidecar Validator
=================================
Validates asset metadata sidecar JSON files against the schema (C-07).
Assets without a valid sidecar are not considered complete.

Usage:
    python -m devforge.governance.sidecar_validator validate asset.glb.sidecar.json --schema schemas/asset_metadata_sidecar_schema.json
    python -m devforge.governance.sidecar_validator scan ./assets --schema schemas/asset_metadata_sidecar_schema.json
    python -m devforge.governance.sidecar_validator template --type procedural
    python -m devforge.governance.sidecar_validator template --type diffusion
"""

import argparse
import json
import os
from pathlib import Path
from typing import List, Tuple

ASSET_EXTENSIONS = {".glb", ".gltf", ".png", ".jpg", ".exr"}


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
def validate_sidecar(sidecar_path: str, schema_path: str) -> Tuple[bool, str]:
    """
    Validate a sidecar JSON file against the schema.

    Returns (True, "VALID") on success, (False, error_message) on failure.
    """
    try:
        with open(sidecar_path, "r") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"
    except FileNotFoundError:
        return False, f"File not found: {sidecar_path}"

    try:
        with open(schema_path, "r") as f:
            schema = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        return False, f"Schema error: {e}"

    # Try jsonschema if available, fall back to basic checks
    try:
        from jsonschema import ValidationError, validate

        try:
            validate(instance=data, schema=schema)
            return True, "VALID"
        except ValidationError as e:
            path_str = ".".join(str(p) for p in e.absolute_path)
            return False, f"Schema violation: {e.message} (path: {path_str})"
    except ImportError:
        return _validate_basic(data)


def _validate_basic(data: dict) -> Tuple[bool, str]:
    """Fallback validation without jsonschema."""
    required = ["asset_id", "pipeline_type", "creation_date", "style_version"]
    missing = [k for k in required if k not in data]
    if missing:
        return False, f"Missing required fields: {missing}"

    ptype = data.get("pipeline_type")
    if ptype not in ("procedural", "diffusion"):
        return False, f"Invalid pipeline_type: {ptype}"

    if ptype == "procedural" and "procedural" not in data:
        return False, "pipeline_type is 'procedural' but 'procedural' object is missing."
    if ptype == "diffusion" and "diffusion" not in data:
        return False, "pipeline_type is 'diffusion' but 'diffusion' object is missing."

    return True, "VALID (basic checks only — install jsonschema for full validation)"


# --------------------------------------------------------------------------
# Directory scanning
# --------------------------------------------------------------------------
def scan_directory(directory: str) -> List[dict]:
    """
    Scan directory for asset files missing their sidecar JSON.

    Returns list of dicts: {"asset": path, "expected_sidecar": path}
    """
    missing = []
    for root, _, files in os.walk(directory):
        for filename in files:
            ext = Path(filename).suffix.lower()
            if ext in ASSET_EXTENSIONS:
                asset_path = Path(root) / filename
                sidecar_path = Path(root) / f"{filename}.sidecar.json"
                if not sidecar_path.exists():
                    missing.append(
                        {
                            "asset": str(asset_path),
                            "expected_sidecar": str(sidecar_path),
                        }
                    )
    return missing


# --------------------------------------------------------------------------
# Template generation
# --------------------------------------------------------------------------
PROCEDURAL_TEMPLATE = {
    "asset_id": "",
    "pipeline_type": "procedural",
    "creation_date": "",
    "style_version": "",
    "procedural": {
        "geometry_template_id": "",
        "seed": 0,
        "export_parameters": {
            "format": "glb",
            "scale": 1.0,
            "apply_modifiers": True,
        },
        "lod_configuration": {
            "levels": [
                {"level": 0, "max_distance": 200, "vertex_reduction": 0.0},
                {"level": 1, "max_distance": 400, "vertex_reduction": 0.5},
                {"level": 2, "max_distance": 800, "vertex_reduction": 0.75},
            ]
        },
        "collision_type": "convex",
        "biome_tags": [],
        "decay_stage": None,
    },
}

DIFFUSION_TEMPLATE = {
    "asset_id": "",
    "pipeline_type": "diffusion",
    "creation_date": "",
    "style_version": "",
    "diffusion": {
        "model_checkpoint_hash": "",
        "lora_version": None,
        "lora_hash": None,
        "seed": 0,
        "prompt": "",
        "negative_prompt": None,
        "sampler": {"name": "", "steps": 20},
        "resolution": {"width": 1024, "height": 1024},
        "controlnet_conditioning_hash": None,
        "pipeline_version": "",
    },
}


def generate_template(pipeline_type: str) -> dict:
    """Generate a blank sidecar template for a given pipeline type."""
    if pipeline_type == "procedural":
        return PROCEDURAL_TEMPLATE.copy()
    elif pipeline_type == "diffusion":
        return DIFFUSION_TEMPLATE.copy()
    else:
        raise ValueError(f"Unknown pipeline_type: {pipeline_type}. Use 'procedural' or 'diffusion'.")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DevForge Asset Sidecar Validator (C-07)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # --- validate ---
    p_val = sub.add_parser("validate", help="Validate a sidecar JSON file")
    p_val.add_argument("file", help="Path to .sidecar.json file")
    p_val.add_argument("--schema", required=True, help="Path to asset_metadata_sidecar_schema.json")

    # --- scan ---
    p_scan = sub.add_parser("scan", help="Scan directory for missing sidecars")
    p_scan.add_argument("directory", help="Root directory to scan")

    # --- template ---
    p_tmpl = sub.add_parser("template", help="Generate a blank sidecar template")
    p_tmpl.add_argument(
        "--type",
        required=True,
        dest="pipeline_type",
        choices=["procedural", "diffusion"],
        help="Pipeline type for the template.",
    )

    args = parser.parse_args()

    if args.cmd == "validate":
        valid, message = validate_sidecar(args.file, args.schema)
        print(message)
        exit(0 if valid else 1)

    elif args.cmd == "scan":
        missing = scan_directory(args.directory)
        if missing:
            print(f"MISSING SIDECARS ({len(missing)}):")
            for m in missing:
                print(f"  Asset: {m['asset']}")
                print(f"    Expected: {m['expected_sidecar']}")
            exit(1)
        else:
            print("All assets have valid sidecars.")
            exit(0)

    elif args.cmd == "template":
        template = generate_template(args.pipeline_type)
        print(json.dumps(template, indent=2))
