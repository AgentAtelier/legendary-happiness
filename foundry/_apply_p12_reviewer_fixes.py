"""Apply the 5 P12 code-reviewer fixes to tests/test_scene_compiler.py.

1. AST-based compile_scene_does_not_call_ensure_room_shell (was regex-fragile).
2. Behavior-based scaffold_still_calls_ensure_room_shell (was source-inspection).
3. _default_box_shell autouse fixture docstring note.
4+5. _compile_with_shell helper docstring update.
"""
from pathlib import Path

p = Path("tests/test_scene_compiler.py")
t = p.read_text(encoding="utf-8")


def apply(label, needle, replacement):
    n = t.count(needle)
    assert n == 1, f"{label}: needle count = {n} (need 1)"
    return t.replace(needle, replacement)


# (1) AST-based regression guard
old1 = '''def test_compile_scene_does_not_call_ensure_room_shell(monkeypatch, tmp_path):
    """P12 regression guard: scene_compiler.compile_scene must NOT
    invoke ``room_shell.ensure_room_shell``.  If a future contributor
    re-introduces that call we want to know immediately — the cache
    write must stay in scaffold.py (cache-owning site).

    Implementation: read scene_compiler.py source as text and verify
    the call expression doesn't appear on any non-comment line.
    """
    import scene_compiler

    scene_compiler_src = (
        Path(__file__).parent.parent.joinpath("scene_compiler.py").read_text()
    )
    # The call expression must NOT appear on any non-comment line.
    offenders = []
    for line_no, line in enumerate(scene_compiler_src.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue  # whole-line comment
        if "room_shell.ensure_room_shell" in line:
            offenders.append((line_no, stripped))
    assert not offenders, (
        "P12 regression: scene_compiler.py invokes "
        "room_shell.ensure_room_shell at: "
        + ", ".join(f"L{ln}: {s!r}" for ln, s in offenders)
        + " — the cache-owning call must live in scaffold.py."
    )'''

new1 = '''def test_compile_scene_does_not_call_ensure_room_shell(tmp_path):
    """P12 regression guard: ``scene_compiler.compile_scene`` must NOT
    invoke ``room_shell.ensure_room_shell``.  If a future contributor
    re-introduces that call we want to know immediately — the cache
    write must stay in ``scaffold.py`` (cache-owning site).

    Implementation: walk ``scene_compiler.py`` AST for any ``ast.Call``
    whose function is ``<obj>.ensure_room_shell``.  Comments and string
    literals are absent from the AST — only real function-body calls are
    seen, so the regex was strictly more permissive than this in
    practice.
    """
    import ast as _ast
    scene_compiler_src = (
        Path(__file__).parent.parent.joinpath("scene_compiler.py").read_text()
    )
    tree = _ast.parse(scene_compiler_src)

    def _is_target(node):
        return isinstance(node, _ast.Attribute) and node.attr == "ensure_room_shell"

    offenders: list[tuple[int, str]] = []
    for sub in _ast.walk(tree):
        if isinstance(sub, _ast.Call) and _is_target(sub.func):
            offenders.append((sub.lineno, _ast.unparse(sub.func)))

    assert not offenders, (
        "P12 regression: scene_compiler.py invokes "
        "room_shell.ensure_room_shell at: "
        + ", ".join(f"L{ln}: {s!r}" for ln, s in offenders)
        + " — the cache-owning call must live in scaffold.py.  "
        + "If you re-introduce it intentionally, add an inline comment "
        + "explaining why AND update this guard."
    )'''
t = apply("(1) AST-based compile_scene_does_not", old1, new1)


# (2) Behavior-based scaffold_still_calls_ensure_room_shell
old2 = '''def test_scaffold_still_calls_ensure_room_shell(monkeypatch, tmp_path):
    """P12 sibling test: scaffold_project must still call
    ``room_shell.ensure_room_shell`` — the cache write belongs there.

    Ensures the de-dup is one-directional: we removed the call from
    ``compile_scene`` but kept it in ``scaffold_project``.
    """
    import scaffold

    source = scaffold.__file__
    text = Path(source).read_text(encoding="utf-8")
    assert "ensure_room_shell" in text, (
        "P12 regression: scaffold.py no longer references "
        "room_shell.ensure_room_shell — cache write site was lost.  "
        "If intentional, update this test."
    )'''

new2 = '''def test_scaffold_still_calls_ensure_room_shell(monkeypatch, tmp_path):
    """P12 sibling test: ``scaffold_project`` must still call
    ``room_shell.ensure_room_shell`` — the cache write belongs there.

    Ensures the de-dup is one-directional: we removed the call from
    ``compile_scene`` but kept it in ``scaffold_project``.  We prove
    the call site is wired by setting a sentinel recorder and
    running a real ``scaffold_project`` invocation.
    """
    import scaffold
    import room_shell

    recorder: list[tuple] = []
    fake_glb = tmp_path / "fake_shell.glb"
    fake_glb.write_bytes(b"GLB")

    def fake_ensure_room_shell(*args, **kwargs):
        recorder.append((args, kwargs))
        return (fake_glb, [])

    monkeypatch.setattr(room_shell, "ensure_room_shell", fake_ensure_room_shell)

    # Build a minimal-but-valid template so scaffold_project can
    # run without Godot / Blender.  We only need it to reach the
    # shell cache call site (which fires during the asset-copy
    # stage, before Godot import).
    td_template = tmp_path / "template"
    td_template.mkdir()
    (td_template / "project.godot").write_text(
        "[application]\\nconfig/name=\\"t\\"\\n"
        "config/features=PackedStringArray(\\"4.7\\")\\n",
        encoding="utf-8",
    )
    td_library = tmp_path / "library"
    td_library.mkdir()

    scaffold.scaffold_project(
        "smoke",
        [{"npc_id": "npc_0", "npc_role": "hermit",
          "target_entity": "table_0",
          "dialogue": {"greet": "", "ask": "", "wrong": "", "thank": ""},
          "objective": {"type": "fetch", "target": "table_0",
                        "giver": "npc"}}],
        manifest=[{"id": "table_0", "category": "table",
                   "material": "worn_oak"}],
        template_dir=str(td_template),
        library_dir=str(td_library),
        out_root=str(tmp_path / "builds"),
    )

    assert recorder, (
        "P12 regression: scaffold_project did NOT call "
        "room_shell.ensure_room_shell — the cache write site was lost."
    )
    # Spot-check that the call includes the theme + (windows=) args,
    # proving it's the canonical call site, not a stray test stub.
    args, kwargs = recorder[0]
    assert len(args) >= 4, (
        f"first ensure_room_shell call should have "
        f"(w, d, h, theme) positional args; got args={args!r}"
    )'''
t = apply("(2) behaviour scaffold_still_calls", old2, new2)


# (3) _default_box_shell autouse fixture docstring note
old3 = '''def _default_box_shell():
    """Default ``room_shell.ensure_room_shell`` to None so tests that
    DON'T explicitly request a GLB take the box-shell fallback branch
    (their old assertions about floor_mat/wall_mat/ceiling_mat/FloorMesh
    stay green even when Blender is installed in the test env).

    Tests that want the GLB branch re-monkeypatch with a Path and
    win — last monkeypatch.setattr wins within a single test.

    Uses manual patch/restore (not pytest monkeypatch) so the original
    function is ALWAYS restored — prevents state leaking into other
    test modules when monkeypatch teardown ordering is unlucky.
    """'''
new3 = '''def _default_box_shell():
    """Default ``room_shell.ensure_room_shell`` to None so tests that
    DON'T explicitly request a GLB take the box-shell fallback branch
    (their old assertions about floor_mat/wall_mat/ceiling_mat/FloorMesh
    stay green even when Blender is installed in the test env).

    Tests that want the GLB branch re-monkeypatch with a Path and
    win — last monkeypatch.setattr wins within a single test.

    AUDIT-05 P12: this fixture affects the ``scaffold_project`` call
    path (which still reads ``ensure_room_shell`` via the cache).
    ``compile_scene`` itself no longer reads the function — its calls
    fall through to compile_scene via the kwargs scaffold threads in.
    The fixture is therefore a no-op for scene_compiler unit tests
    but still matters when a test invokes ``scaffold_project``.

    Uses manual patch/restore (not pytest monkeypatch) so the original
    function is ALWAYS restored — prevents state leaking into other
    test modules when monkeypatch teardown ordering is unlucky.
    """'''
t = apply("(3) autouse fixture docstring", old3, new3)


# (4+5) _compile_with_shell helper docstring
old5 = '''def _compile_with_shell(manifest=None, room_size=None, theme=None, *,
                        shell_glb_path=None, shell_decisions=None):
    """Helper: compile with room_size + theme, return text and parsed."""
    spec = dict(_QUEST_SPEC)
    man = manifest or _minimal_manifest()
    spec["target_entity"] = man[0]["id"]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out, room_size=room_size, theme=theme,
                      shell_glb_path=shell_glb_path,
                      shell_decisions=shell_decisions)
        text = Path(out).read_text(encoding="utf-8")
        return text
    finally:
        Path(out).unlink()
        # Clean up the quest_data.json too
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()'''
new5 = '''def _compile_with_shell(manifest=None, room_size=None, theme=None, *,
                        shell_glb_path=None, shell_decisions=None):
    """Helper: run ``compile_scene`` with room_size + theme and (P12)
    optionally ``shell_glb_path`` + ``shell_decisions`` kwargs.

    Returns the .tscn text only — callers that need the parsed dict
    call ``_parse_scene_text(text)`` themselves.  When
    ``shell_glb_path`` is None the box-shell fallback branch fires
    (FloorMesh + wall/ceiling BoxMesh + per-theme tint sub_resources).
    """
    spec = dict(_QUEST_SPEC)
    man = manifest or _minimal_manifest()
    spec["target_entity"] = man[0]["id"]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out, room_size=room_size, theme=theme,
                      shell_glb_path=shell_glb_path,
                      shell_decisions=shell_decisions)
        text = Path(out).read_text(encoding="utf-8")
        return text
    finally:
        Path(out).unlink()
        # Clean up the quest_data.json too
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()'''

if old5 in t:
    t = apply("(4+5) helper docstring", old5, new5)
else:
    print("(4+5) helper docstring: signature differs from expected — skipping")

p.write_text(t, encoding="utf-8")
print("P12 reviewer fixes applied.")
