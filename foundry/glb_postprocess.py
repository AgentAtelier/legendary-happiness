"""GLB post-processing helpers (pure Python — no bpy, so unit-testable).

Extracted from build_asset.py so the GLB byte-munging can be tested without
Blender. The Fix-Batch-1 occlusion injection lived inline and silently failed
on every real asset because the "JSON grew" rebuild path packed the GLB header
with the 4-byte version *bytes* where struct expected an int.
"""
from __future__ import annotations

import json
import struct

_JSON_CHUNK_TYPE = 0x4E4F534A  # "JSON"


def inject_occlusion_texture(glb_path: str) -> bool:
    """Ensure every material with a ``metallicRoughnessTexture`` also has an
    ``occlusionTexture`` pointing at the same image (glTF ORM: occlusion=R,
    roughness=G, metallic=B). Rewrites *glb_path* in place. Returns True if a
    change was made.

    Adding the key grows the JSON chunk, so the rebuild path (below) is the
    common case and MUST be correct.
    """
    with open(glb_path, "rb") as f:
        data = f.read()
    if data[0:4] != b"glTF":
        raise ValueError(f"not a GLB file: {glb_path}")

    json_start = 12
    chunk_len = struct.unpack("<I", data[json_start:json_start + 4])[0]
    json_bytes = data[json_start + 8:json_start + 8 + chunk_len]
    gltf = json.loads(json_bytes.decode("utf-8"))

    modified = False
    for mat in gltf.get("materials", []):
        pbr = mat.get("pbrMetallicRoughness")
        if pbr and "metallicRoughnessTexture" in pbr and "occlusionTexture" not in mat:
            mrt = pbr["metallicRoughnessTexture"]
            mat["occlusionTexture"] = {
                "index": mrt.get("index", 0),
                "texCoord": mrt.get("texCoord", 0),
            }
            modified = True
    if not modified:
        return False

    new_json = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    binary_chunk = data[json_start + 8 + chunk_len:]

    if len(new_json) <= chunk_len:
        # Fits in the existing (space-padded) chunk — patch in place.
        new_json += b" " * (chunk_len - len(new_json))
        out = bytearray(data)
        out[json_start + 8:json_start + 8 + chunk_len] = new_json
        with open(glb_path, "wb") as f:
            f.write(bytes(out))
        return True

    # JSON grew — rebuild the GLB. Align the JSON chunk to 4 bytes with spaces.
    padded_len = (len(new_json) + 3) & ~3
    new_json_padded = new_json + b" " * (padded_len - len(new_json))
    total_len = 12 + 8 + padded_len + len(binary_chunk)
    version = struct.unpack("<I", data[4:8])[0]            # <-- the fix: int, not bytes
    header = struct.pack("<4sII", data[0:4], version, total_len)
    json_header = struct.pack("<II", padded_len, _JSON_CHUNK_TYPE)
    with open(glb_path, "wb") as f:
        f.write(header + json_header + new_json_padded + binary_chunk)
    return True
