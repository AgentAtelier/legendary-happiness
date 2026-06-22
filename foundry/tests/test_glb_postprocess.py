"""Regression tests for glb_postprocess.inject_occlusion_texture.

Fix-Batch-1 shipped this inline in build_asset.py and it silently failed on
every real asset: adding ``occlusionTexture`` grows the JSON chunk, hitting the
GLB-rebuild path, which packed the header with the 4-byte version *bytes* where
struct expected an int → struct.error, swallowed. So AO was never applied. These
tests exercise the grows-path and assert a valid rebuilt GLB.
"""
from __future__ import annotations

import json
import struct

from glb_postprocess import inject_occlusion_texture

_JSON = 0x4E4F534A
_BIN = 0x004E4942


def _make_glb(gltf: dict, bin_data: bytes = b"\x01\x02\x03\x04") -> bytes:
    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    bn = bin_data + b"\x00" * ((4 - len(bin_data) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(bn)
    out = struct.pack("<4sII", b"glTF", 2, total)
    out += struct.pack("<II", len(js), _JSON) + js
    out += struct.pack("<II", len(bn), _BIN) + bn
    return out


def _parse(path):
    with open(path, "rb") as f:
        data = f.read()
    magic, ver, total = struct.unpack("<4sII", data[:12])
    assert magic == b"glTF"
    assert total == len(data), f"total_len {total} != file size {len(data)}"
    clen, ctype = struct.unpack("<II", data[12:20])
    assert ctype == _JSON
    gltf = json.loads(data[20:20 + clen])
    return gltf, data


def test_inject_grows_json_and_rebuilds_valid_glb(tmp_path):
    """The common case: JSON grows, GLB is rebuilt and stays valid; the BIN
    chunk is preserved; occlusionTexture points at the metallicRoughness image."""
    gltf = {
        "asset": {"version": "2.0"},
        "materials": [{
            "name": "m",
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": 0},
                "metallicRoughnessTexture": {"index": 1},
            },
            "normalTexture": {"index": 2},
        }],
        "images": [{"name": "a"}, {"name": "orm"}, {"name": "n"}],
        "textures": [{"source": 0}, {"source": 1}, {"source": 2}],
    }
    bin_data = bytes(range(32))
    p = tmp_path / "a.glb"
    p.write_bytes(_make_glb(gltf, bin_data))

    changed = inject_occlusion_texture(str(p))
    assert changed is True

    out, raw = _parse(str(p))
    occ = out["materials"][0].get("occlusionTexture")
    assert occ is not None and occ["index"] == 1  # points at the ORM image
    # BIN chunk preserved
    clen = struct.unpack("<I", raw[12:16])[0]
    bin_off = 20 + clen + 8
    assert raw[bin_off:bin_off + 32] == bin_data


def test_inject_noop_without_metallic_roughness(tmp_path):
    gltf = {"asset": {"version": "2.0"}, "materials": [{"name": "flat"}]}
    p = tmp_path / "b.glb"
    p.write_bytes(_make_glb(gltf))
    assert inject_occlusion_texture(str(p)) is False
    out, _ = _parse(str(p))
    assert "occlusionTexture" not in out["materials"][0]


def test_inject_idempotent(tmp_path):
    gltf = {
        "asset": {"version": "2.0"},
        "materials": [{
            "pbrMetallicRoughness": {"metallicRoughnessTexture": {"index": 0}},
        }],
    }
    p = tmp_path / "c.glb"
    p.write_bytes(_make_glb(gltf))
    assert inject_occlusion_texture(str(p)) is True
    assert inject_occlusion_texture(str(p)) is False  # already present
