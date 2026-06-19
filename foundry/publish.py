"""Publish forged assets into a Godot project by copying .glb files and
registering their lexicon paths (as material variants where applicable).
This is the bridge that makes the live spatial compiler emit instanced-asset
ops instead of greyboxes."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import List, Optional, Tuple, TypedDict

from library import register_asset, register_variant


class PublishedEntry(TypedDict):
    id: str
    src: str
    dst: str
    res_path: str
    material_id: str


class SkippedEntry(TypedDict):
    file: str
    reason: str


class PublishResult(TypedDict):
    published: List[PublishedEntry]
    skipped: List[SkippedEntry]


def _resolve_asset_and_material(
    stem: str, lexicon_ids: set
) -> tuple[str | None, str]:
    """Derive (asset_id, material_id) from a filename stem.

    Rules:
    - Full stem is a lexicon id → (stem, "default")
    - Full stem is NOT a lexicon id → split on FIRST "_" only:
      part0 must be a lexicon id → (part0, rest_with_underscores)
      Otherwise → (None, "")

    Examples:
      "table"            → ("table", "default")
      "table_dark_walnut" → ("table", "dark_walnut")
      "table_dark"        → ("table", "dark")  -- if "table" is known
      "dragon"            → (None, "")
    """
    if stem in lexicon_ids:
        return stem, "default"
    parts = stem.split("_", 1)
    if len(parts) == 2 and parts[0] in lexicon_ids:
        return parts[0], parts[1]
    return None, ""


def publish(
    library_dir: str,
    project_dir: str,
    lexicon_path: str,
    assets_subdir: str = "assets",
) -> PublishResult:
    """Publish each ``*.glb`` in *library_dir* into a Godot project.

    For every .glb file whose filename stem resolves to a known lexicon
    entry, the asset is copied into ``<project_dir>/<assets_subdir>/<id>.glb``
    and the lexicon entry's ``path`` is set to
    ``res://<assets_subdir>/<id>.glb`` via :func:`library.register_asset`.

    Parameters
    ----------
    library_dir:
        Directory containing forged ``.glb`` files.
    project_dir:
        Root of the target Godot project.
    lexicon_path:
        Path to the asset lexicon JSON to update.
    assets_subdir:
        Subdirectory (relative to *project_dir*) where assets are placed.
        Defaults to ``"assets"``.

    Returns
    -------
    PublishResult
        A dict with ``published`` (list of PublishedEntry) and ``skipped``
        (list of SkippedEntry).
    """
    lib = Path(library_dir)
    proj = Path(project_dir)
    assets_dir = proj / assets_subdir

    # Load lexicon ids once
    lexicon_data = json.loads(Path(lexicon_path).read_text(encoding="utf-8"))
    lexicon_ids: set = set(lexicon_data.get("assets", {}).keys())

    published: list[PublishedEntry] = []
    skipped: list[SkippedEntry] = []

    if not lib.is_dir():
        return {"published": published, "skipped": skipped}

    assets_dir.mkdir(parents=True, exist_ok=True)

    for glb_path in sorted(lib.glob("*.glb")):
        stem = glb_path.stem  # "table" or "table_dark_walnut"
        asset_id, material_id = _resolve_asset_and_material(stem, lexicon_ids)

        if asset_id is None:
            skipped.append({
                "file": glb_path.name,
                "reason": f"stem {stem!r} not in lexicon",
            })
            continue

        # Destination — keep the full stem as filename (variant-aware).
        dst = assets_dir / f"{stem}.glb"
        shutil.copy2(glb_path, dst)

        res_path = f"res://{assets_subdir}/{stem}.glb"
        register_variant(lexicon_path, asset_id, material_id, res_path)

        published.append({
            "id": asset_id,
            "src": str(glb_path),
            "dst": str(dst),
            "res_path": res_path,
            "material_id": material_id,
        })

        # Copy the sidecar JSON alongside if it exists.
        sidecar_src = glb_path.with_suffix(".sidecar.json")
        if sidecar_src.exists():
            sidecar_dst = assets_dir / f"{stem}.sidecar.json"
            shutil.copy2(sidecar_src, sidecar_dst)

    return {"published": published, "skipped": skipped}


def copy_asset_family(
    category: str,
    material: str,
    library_dir: str,
    dest_assets_dir: str,
) -> List[str]:
    """Copy a GLB and its entire file family into a destination.

    For a (category, material) pair, globs and copies every file whose
    stem starts with ``{category}_{material}``: the .glb, its .glb.import
    sidecar, any ``_baked_*.png`` textures, any ``*.png.import`` sidecars,
    and the .sidecar.json.  Does NOT reason about which textures are
    actually referenced — brings the whole family so the probe is the
    completeness gate.

    Returns the list of copied file names (basename only).
    """
    stem = f"{category}_{material}"
    lib = Path(library_dir)
    dest = Path(dest_assets_dir)
    dest.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    # Match: {stem}.glb, {stem}.glb.import, {stem}_baked_*.png,
    #        {stem}_baked_*.png.import, {stem}.sidecar.json
    # ([._][^.]+)? matches both _texture and .sidecar suffixes.
    pattern = re.compile(r"^" + re.escape(stem) + r"([._][^.]+)?\.(glb|png|json)(\.import)?$")
    for fpath in sorted(lib.iterdir()):
        if pattern.match(fpath.name):
            dst = dest / fpath.name
            shutil.copy2(fpath, dst)
            copied.append(fpath.name)

    return copied


def _main() -> int:
    """CLI entry-point::

        python -m foundry.publish <library_dir> <project_dir> <lexicon_path> [assets_subdir]
    """
    import sys
    from pathlib import Path as _Path

    # Ensure bare imports (from library import ...) work for direct invocation
    _foundry_dir = str(_Path(__file__).resolve().parent)
    if _foundry_dir not in sys.path:
        sys.path.insert(0, _foundry_dir)

    if len(sys.argv) < 4:
        print(
            "usage: python -m foundry.publish <library_dir> <project_dir>"
            " <lexicon_path> [assets_subdir]"
        )
        return 2

    library_dir = sys.argv[1]
    project_dir = sys.argv[2]
    lexicon_path = sys.argv[3]
    assets_subdir = sys.argv[4] if len(sys.argv) > 4 else "assets"

    result = publish(library_dir, project_dir, lexicon_path, assets_subdir)

    print(f"Published {len(result['published'])}:")
    for entry in result["published"]:
        print(f"  {entry['id']} [{entry['material_id']}] → {entry['res_path']}")

    print(f"\nSkipped {len(result['skipped'])}:")
    for entry in result["skipped"]:
        print(f"  {entry['file']}: {entry['reason']}")

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_main())
