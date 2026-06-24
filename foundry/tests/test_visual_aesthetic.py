"""Unit tests for foundry.visual.aesthetic (V Task 3) — model mocked.

The CLIP model is never unit-tested (it's the judge).  All tests mock
the model loader to return a deterministic dummy scorer so the pipeline
is validated without requiring real model weights.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Reset module-level cache between tests
import visual.aesthetic as _aesthetic
from PIL import Image as PILImage


@pytest.fixture(autouse=True)
def _reset_model_cache():
    """Clear the lazy-load cache so each test starts fresh."""
    _aesthetic._model_cache = None
    _aesthetic._load_attempted = False
    yield
    _aesthetic._model_cache = None
    _aesthetic._load_attempted = False


@pytest.fixture
def fake_png(tmp_path):
    """Create a valid 1x1 red PNG using PIL."""
    from PIL import Image as PILImage
    png = tmp_path / "test.png"
    img = PILImage.new("RGB", (1, 1), color=(255, 0, 0))
    img.save(png)
    return str(png)


def _mock_model_cache():
    """Return a fake model cache that produces deterministic scores."""
    import torch

    class FakeHead:
        def __init__(self):
            pass

        def __call__(self, features):
            # Deterministic: use first element (varies by input)
            return torch.tensor([float(features[0, 0].item())])

        def eval(self):
            return self

        def to(self, device):
            return self

    class FakeModel:
        def encode_image(self, tensor):
            return tensor.flatten(start_dim=1)

        def eval(self):
            return self

        def to(self, device):
            return self

    return {
        "model": FakeModel(),
        "preprocess": _fake_preprocess,
        "head": FakeHead(),
        "device": "cpu",
        "head_loaded": True,
    }


def _fake_preprocess(image):
    """Fake CLIP preprocess that returns a deterministic tensor."""
    import torch
    # Return a fixed 3x224x224 tensor based on image pixel mean
    arr = image.resize((224, 224))
    # Deterministic: use image mean as input
    import numpy as np
    pixels = np.array(arr, dtype=np.float32) / 255.0
    return torch.from_numpy(pixels).permute(2, 0, 1)


# ── Tests ────────────────────────────────────────────────────────

def test_aesthetic_score_returns_float_on_mocked_model(fake_png, monkeypatch):
    """With mocked model, returns a float score."""
    monkeypatch.setattr(
        _aesthetic, "_load_model",
        lambda *a, **kw: _mock_model_cache(),
    )
    result = _aesthetic.aesthetic_score(fake_png)
    assert "score" in result
    assert isinstance(result["score"], float)
    assert result["score"] > 0
    assert "_load_error" not in result


def test_aesthetic_score_deterministic(fake_png, monkeypatch):
    """Same image → same score on repeated calls."""
    monkeypatch.setattr(
        _aesthetic, "_load_model",
        lambda *a, **kw: _mock_model_cache(),
    )
    score1 = _aesthetic.aesthetic_score(fake_png)["score"]
    score2 = _aesthetic.aesthetic_score(fake_png)["score"]
    assert score1 == score2


def test_aesthetic_score_model_cached(fake_png, monkeypatch):
    """Second call reuses the lazy-loaded model (no reload)."""
    load_count = [0]

    def counting_loader(*a, **kw):
        load_count[0] += 1
        return _mock_model_cache()

    monkeypatch.setattr(_aesthetic, "_load_model", counting_loader)

    _aesthetic.aesthetic_score(fake_png)
    _aesthetic.aesthetic_score(fake_png)
    _aesthetic.aesthetic_score(fake_png)

    assert load_count[0] == 1  # only loaded once


def test_aesthetic_score_graceful_degradation(fake_png, monkeypatch):
    """When model can't be loaded, returns None score + _load_error flag."""
    monkeypatch.setattr(
        _aesthetic, "_load_model",
        lambda *a, **kw: None,
    )
    result = _aesthetic.aesthetic_score(fake_png)
    assert result["score"] is None
    assert result["_load_error"] is True


def test_aesthetic_score_caches_failure(monkeypatch):
    """Once load fails, subsequent calls don't retry (cached None)."""
    load_count = [0]

    def failing_loader(*a, **kw):
        load_count[0] += 1
        return None

    monkeypatch.setattr(_aesthetic, "_load_model", failing_loader)

    _aesthetic.aesthetic_score("nonexistent.png")
    _aesthetic.aesthetic_score("nonexistent.png")
    _aesthetic.aesthetic_score("nonexistent.png")

    # Load only attempted once despite 3 calls
    assert load_count[0] == 1


def test_aesthetic_score_different_images_different_scores(tmp_path, monkeypatch):
    """Different images produce different scores."""
    monkeypatch.setattr(
        _aesthetic, "_load_model",
        lambda *a, **kw: _mock_model_cache(),
    )

    png1 = tmp_path / "red.png"
    png2 = tmp_path / "blue.png"
    PILImage.new("RGB", (10, 10), color=(255, 0, 0)).save(png1)
    PILImage.new("RGB", (10, 10), color=(0, 0, 255)).save(png2)

    score1 = _aesthetic.aesthetic_score(str(png1))["score"]
    score2 = _aesthetic.aesthetic_score(str(png2))["score"]
    assert score1 != score2


def test_aesthetic_score_with_custom_model_params(fake_png, monkeypatch):
    """Custom model_name and pretrained are forwarded to _load_model."""
    seen_params = []

    def capturing_loader(model_name, pretrained, head_weights, device):
        seen_params.append((model_name, pretrained, head_weights, device))
        return _mock_model_cache()

    monkeypatch.setattr(_aesthetic, "_load_model", capturing_loader)

    _aesthetic.aesthetic_score(
        fake_png,
        model_name="ViT-L-14",
        pretrained="datacomp_xl",
        head_weights="/path/to/weights.pth",
        device="cuda",
    )

    assert seen_params[0] == ("ViT-L-14", "datacomp_xl", "/path/to/weights.pth", "cuda")


def test__find_head_weights_env_var(tmp_path, monkeypatch):
    """FORGE_AESTHETIC_HEAD env var takes priority."""
    weights = tmp_path / "my_head.pth"
    weights.write_text("fake weights")

    monkeypatch.setenv("FORGE_AESTHETIC_HEAD", str(weights))
    result = _aesthetic._find_head_weights(512)
    assert result == str(weights)


def test__find_head_weights_cache_file(tmp_path, monkeypatch):
    """Cache file is checked when env var not set."""
    monkeypatch.delenv("FORGE_AESTHETIC_HEAD", raising=False)

    cache_dir = tmp_path / ".cache" / "forge"
    cache_dir.mkdir(parents=True)
    weights = cache_dir / "aesthetic_head_512.pth"
    weights.write_text("cached weights")

    # Override home to point at tmp_path
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    result = _aesthetic._find_head_weights(512)
    assert result == str(weights)


def test__find_head_weights_not_found(monkeypatch):
    """Returns None when no weights file exists."""
    monkeypatch.delenv("FORGE_AESTHETIC_HEAD", raising=False)
    monkeypatch.setattr(
        _aesthetic.Path, "home",
        lambda: Path("/nonexistent_home_for_test"),
    )
    result = _aesthetic._find_head_weights(512)
    assert result is None
