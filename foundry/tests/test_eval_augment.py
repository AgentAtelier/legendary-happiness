"""TDD tests for foundry.eval.augment — corpus augmentation via slot-filling (Prompt 6).

All tests use the FAKE paraphraser (format template) — deterministic,
no qwen.  Tests cover:
  - dedup removes normalized duplicates
  - validity filter keeps Decision-Point-firing requests
  - output size bounded by --target
  - slot-filling covers all four generators
  - adversarial templates included
  - stats dict has expected keys
"""

from __future__ import annotations

import json


# ── Fake paraphraser + fake llm ───────────────────────────────────────


def _fake_paraphrase(template: str, **slots) -> str:
    """Same as augment._fake_paraphrase — just format the template."""
    return template.format(**slots)


def _stub_llm():
    import json as _json
    spec = _json.dumps({
        "asset_id": "table",
        "generator": "table",
        "params": {
            "top_width": 1.2, "top_depth": 0.8, "top_thickness": 0.06,
            "leg_height": 0.65, "leg_radius": 0.05, "leg_inset": 0.1,
        },
    })

    def _stub(prompt: str, grammar) -> str:
        return spec

    return _stub


# ── Dedup ─────────────────────────────────────────────────────────────

def test_dedup_removes_normalized_duplicate(tmp_path):
    """Two requests that normalize to the same text → one kept."""
    from eval.augment import augment_corpus, _normalize, _request_key
    out = tmp_path / "corpus.txt"

    requests, stats = augment_corpus(
        str(out),
        target=20,
        seed=42,
        paraphrase=_fake_paraphrase,
        llm=_stub_llm(),
    )

    # All requests should be unique by normalized hash
    keys = [_request_key(r) for r in requests]
    assert len(keys) == len(set(keys)), f"duplicate keys: {len(keys)} vs {len(set(keys))}"

    # Dedup rate should be reasonable (some raw combos overlap after
    # normalization — e.g. "a table" appears from multiple templates)
    assert stats["dedup_rate"] > 0, "expected some dedup to happen"


# ── Validity filter keeps Decision-Point-firing requests ──────────────

def test_decision_firers_kept(tmp_path):
    """Requests that fire Decision Points are NOT dropped by the validity
    filter — conflicts/defaults are valuable edge cases."""
    from eval.augment import augment_corpus
    out = tmp_path / "corpus.txt"

    requests, stats = augment_corpus(
        str(out),
        target=100,
        seed=42,
        paraphrase=_fake_paraphrase,
        llm=_stub_llm(),
    )

    # decision_firers should be >0 (e.g. unspecified material defaults
    # fire, and cross-family conflicts fire)
    assert stats["decision_firers"] > 0, (
        f"expected some requests to fire Decision Points, got {stats}"
    )
    # All decision-firers should be in the output
    assert stats["decision_firers"] <= len(requests)


# ── Output size bounded by --target ───────────────────────────────────

def test_output_capped_by_target(tmp_path):
    """Output size never exceeds --target."""
    from eval.augment import augment_corpus
    out = tmp_path / "corpus.txt"

    for target in [10, 50, 100]:
        requests, stats = augment_corpus(
            str(out),
            target=target,
            seed=42,
            paraphrase=_fake_paraphrase,
            llm=_stub_llm(),
        )
        assert len(requests) <= target, (
            f"expected <= {target} but got {len(requests)}"
        )
        assert stats["valid"] <= target


# ── Slot-filling covers all four generators ───────────────────────────

def test_generators_all_covered(tmp_path):
    """The generated corpus includes all four generator families."""
    from eval.augment import augment_corpus, _GENERATOR_NOUNS
    out = tmp_path / "corpus.txt"

    requests, stats = augment_corpus(
        str(out),
        target=250,
        seed=42,
        paraphrase=_fake_paraphrase,
        llm=_stub_llm(),
    )

    # Each generator should appear in at least some requests
    gc = stats["generator_counts"]
    for gen in _GENERATOR_NOUNS:
        assert gc.get(gen, 0) > 0, (
            f"generator {gen!r} not represented in output: {gc}"
        )


def test_adversarial_templates_included(tmp_path):
    """Adversarial requests are prepended to the output."""
    from eval.augment import augment_corpus
    out = tmp_path / "corpus.txt"

    requests, stats = augment_corpus(
        str(out),
        target=250,
        seed=42,
        paraphrase=_fake_paraphrase,
        llm=_stub_llm(),
    )

    assert stats["adversarial_count"] > 0
    # Adversarial are valid by construction (use real lexicons)
    assert len(requests) > 0


# ── Stats dict shape ──────────────────────────────────────────────────

def test_stats_dict_has_expected_keys(tmp_path):
    from eval.augment import augment_corpus
    out = tmp_path / "corpus.txt"

    _requests, stats = augment_corpus(
        str(out),
        target=10,
        seed=42,
        paraphrase=_fake_paraphrase,
        llm=_stub_llm(),
    )

    expected_keys = {
        "target", "seed", "raw_generated", "unique_after_dedup",
        "dedup_rate", "valid", "rejected_by_validity",
        "decision_firers", "adversarial_count", "generator_counts",
    }
    for key in expected_keys:
        assert key in stats, f"missing key: {key}"


# ── Dry run ───────────────────────────────────────────────────────────

def test_dry_run_does_not_write(tmp_path):
    """--dry-run prints stats but doesn't write the output file."""
    from eval.augment import augment_corpus
    out = tmp_path / "corpus.txt"

    requests, stats = augment_corpus(
        str(out),
        target=50,
        seed=42,
        dry_run=True,
        paraphrase=_fake_paraphrase,
        llm=_stub_llm(),
    )

    assert not out.exists(), f"dry-run should not write {out}"
    assert stats["valid"] > 0
    assert len(requests) > 0


# ── Determinism ───────────────────────────────────────────────────────

def test_same_seed_same_output(tmp_path):
    """Same seed + same params → same output."""
    from eval.augment import augment_corpus
    out1 = tmp_path / "corpus1.txt"
    out2 = tmp_path / "corpus2.txt"

    r1, s1 = augment_corpus(
        str(out1), target=30, seed=42,
        paraphrase=_fake_paraphrase, llm=_stub_llm(),
    )
    r2, s2 = augment_corpus(
        str(out2), target=30, seed=42,
        paraphrase=_fake_paraphrase, llm=_stub_llm(),
    )

    assert r1 == r2
    assert s1 == s2


# ── Normalize / dedup helpers ─────────────────────────────────────────

def test_normalize_lowercases_and_strips_punctuation():
    from eval.augment import _normalize
    assert _normalize("A Table, Old.") == "a table old"
    assert _normalize("  multiple   spaces  ") == "multiple spaces"
    assert _normalize("brand-new") == "brandnew"
    assert _normalize("hello!@#$%^&*()world") == "helloworld"


def test_request_key_same_for_normalized_duplicate():
    from eval.augment import _request_key
    assert _request_key("A Table") == _request_key("a table")
    assert _request_key("a table, old") == _request_key("A TABLE OLD")
    assert _request_key("a table") != _request_key("a chair")
