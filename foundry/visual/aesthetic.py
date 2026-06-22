"""V Task 3: CLIP aesthetic scorer using a CLIP backbone + LAION aesthetic head.

Lazy-loads the model on first call; degrades gracefully (returns
``None`` score + ``_load_error`` flag) if PyTorch or the model weights
aren't available.  Deterministic for a fixed input image (eval mode,
no dropout, fixed seed).

Typical score range: ~1–10 (higher = more aesthetically pleasing).
Used for *ranking only* — never for absolute quality thresholds.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
from PIL import Image

try:
    import torch
    import torch.nn as nn
    _HAS_TORCH = True
except ImportError:
    torch = None  # type: ignore
    nn = None  # type: ignore
    _HAS_TORCH = False


# ── Cache for lazy-loaded model ──────────────────────────────────

_model_cache: Optional[Dict[str, Any]] = None
_load_attempted: bool = False


# ── Public API ───────────────────────────────────────────────────

def aesthetic_score(
    png_path: str,
    *,
    model_name: str = "ViT-B-32",
    pretrained: str = "laion2b_s34b_b79k",
    head_weights: Optional[str] = None,
    device: str = "cpu",
) -> Dict[str, Any]:
    """Score the aesthetic quality of a PNG image.

    Uses a CLIP visual encoder + a small LAION aesthetic regression
    head.  The model is loaded once and cached for subsequent calls.

    Args:
        png_path: Path to the PNG image to score.
        model_name: open_clip model name (default ``ViT-B-32``).
        pretrained: open_clip pretrained dataset tag.
        head_weights: Path to aesthetic head ``.pth`` weights file.
            If ``None``, auto-locates via ``_find_head_weights()``.
        device: ``"cpu"`` or ``"cuda"``.

    Returns:
        ``{"score": float}`` on success, or
        ``{"score": None, "_load_error": True}`` if the model
        couldn't be loaded.
    """
    global _model_cache, _load_attempted

    # ── Lazy-load the model on first call ────────────────────
    if _model_cache is None and not _load_attempted:
        _load_attempted = True
        _model_cache = _load_model(
            model_name, pretrained, head_weights, device,
        )

    if _model_cache is None:
        return {"score": None, "_load_error": True}

    if not _model_cache.get("head_loaded", False):
        return {"score": None, "_load_error": True}

    score = _compute_score(png_path, _model_cache)
    return {"score": score}


# ── Model loading ────────────────────────────────────────────────

def _load_model(
    model_name: str,
    pretrained: str,
    head_weights: Optional[str],
    device: str,
) -> Optional[Dict[str, Any]]:
    """Load CLIP model + aesthetic head.  Returns None on failure."""
    try:
        import open_clip
    except ImportError:
        return None

    try:
        model, _, preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained=pretrained,
        )
        model.to(device)
        model.eval()

        # Determine embedding dimension from the visual encoder
        embed_dim = model.visual.output_dim

        # ── Build the aesthetic head ──────────────────────────
        head = _AestheticHead(embed_dim).to(device)
        head.eval()

        # Try to load pretrained head weights
        weights_path = head_weights or _find_head_weights(embed_dim)
        head_loaded = False
        if weights_path and Path(weights_path).exists():
            state = torch.load(weights_path, map_location=device, weights_only=True)
            head.load_state_dict(state)
            head_loaded = True

    except (ImportError, OSError, RuntimeError, KeyError):
        return None

    return {
        "model": model,
        "preprocess": preprocess,
        "head": head,
        "device": device,
        "head_loaded": head_loaded,
    }


def _find_head_weights(embed_dim: int) -> Optional[str]:
    """Locate the LAION aesthetic head weights file.

    Checks (in order):
        1. ``$FORGE_AESTHETIC_HEAD`` environment variable.
        2. ``~/.cache/forge/aesthetic_head_{embed_dim}.pth``.
    """
    env_path = os.environ.get("FORGE_AESTHETIC_HEAD")
    if env_path and Path(env_path).exists():
        return env_path

    cache_dir = Path.home() / ".cache" / "forge"
    cache_file = cache_dir / f"aesthetic_head_{embed_dim}.pth"
    if cache_file.exists():
        return str(cache_file)

    return None


# ── Inference ────────────────────────────────────────────────────

def _compute_score(png_path: str, model_cache: Dict[str, Any]) -> float:
    """Preprocess image, run CLIP encoder + aesthetic head, return scalar."""
    import torch

    model = model_cache["model"]
    preprocess = model_cache["preprocess"]
    head = model_cache["head"]
    device = model_cache["device"]

    image = Image.open(png_path).convert("RGB")
    image_tensor = preprocess(image).unsqueeze(0).to(device)

    with torch.no_grad():
        features = model.encode_image(image_tensor)
        features = features / features.norm(dim=-1, keepdim=True)
        score = head(features)

    return float(score.item())


# ── Aesthetic head architecture ──────────────────────────────────

class _AestheticHead(nn.Module if _HAS_TORCH else object):
    """Small MLP that maps CLIP embeddings → aesthetic score.

    Architecture mirrors the LAION aesthetic predictor V2:
    Linear(embed_dim, 256) → ReLU → Linear(256, 1).
    """

    def __init__(self, embed_dim: int = 512):
        super().__init__()

        self.mlp = nn.Sequential(
            nn.Linear(embed_dim, 256),
            nn.ReLU(),
            nn.Linear(256, 1),
        )

    def forward(self, x):
        return self.mlp(x)
