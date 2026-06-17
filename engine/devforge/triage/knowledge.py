"""Knowledge table of common Godot 4 runtime errors.

Each entry matches a Godot error message against a regex, then provides
a human-readable explanation and a concrete fix hint.  The table is
ordered — first match wins.  No LLM calls; explanations come from this
table, not from generation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnownError:
    """A classified Godot error pattern."""

    id: str  # "E01".."E20"
    pattern: str  # regex, matched with re.IGNORECASE
    category: str  # see categories below
    explanation: str  # 1-2 sentences: what this means in Godot terms
    fix_hint: str  # 1 sentence: the usual fix


KNOWN_ERRORS: list[KnownError] = [
    # ── null_access ─────────────────────────────────────────────
    KnownError(
        id="E01",
        pattern=r"Invalid call\.\s*Nonexistent function\s+'(\w+)'\s+in base\s+'(\w+)'",
        category="missing_member",
        explanation=(
            "A function is being called on an object that doesn't have it. "
            "This often means the variable holds a different type than expected "
            "(e.g. you called a CharacterBody3D method on a plain Node3D)."
        ),
        fix_hint="Check the variable type at the call site — it may need a cast or the node path may resolve to the wrong type.",
    ),
    KnownError(
        id="E02",
        pattern=r"(?:Invalid get index|Attempt to call function)\s.*(?:on a null instance|on base: 'Nil')",
        category="null_access",
        explanation=(
            "A method or property is being accessed on a null reference. "
            "The variable was never assigned, or a get_node() returned null "
            "because the path doesn't exist in the scene."
        ),
        fix_hint="Add a null check before the call, verify the node path in get_node(), or ensure @onready variables are initialized.",
    ),
    KnownError(
        id="E11",
        pattern=r"Attempt to call function\s+'\w+'\s+in base\s+'previously freed'",
        category="null_access",
        explanation=(
            "A reference to a node or resource that has been freed (queue_free() "
            "or remove_child()) is being used. The object still exists as a variable "
            "but is no longer valid."
        ),
        fix_hint="Check is_instance_valid(obj) before using the reference, or use signals to detect deletion.",
    ),
    # ── missing_member ──────────────────────────────────────────
    KnownError(
        id="E04",
        pattern=r"Cannot find member\s+\"(\w+)\"\s+in base\s+\"(\w+)\"",
        category="missing_member",
        explanation=(
            "A property or method name doesn't exist on the object type. "
            "This often happens after refactoring (renamed variable) or "
            "when calling engine methods with a typo."
        ),
        fix_hint="Verify the member name matches the class definition. If it's a custom property, check the script is attached to the correct node.",
    ),
    # ── parse_error ─────────────────────────────────────────────
    KnownError(
        id="E03",
        pattern=r'Identifier\s+"(\w+)"\s+not declared in the current scope',
        category="parse_error",
        explanation=(
            "A variable or function name is used before being declared. "
            "This is a GDScript parse error — the script won't run at all."
        ),
        fix_hint="Declare the variable with 'var' before using it, or check for a typo in the name.",
    ),
    KnownError(
        id="E08",
        pattern=r"Parse Error:\s*(?:Expected|Unexpected)\s",
        category="parse_error",
        explanation=("The GDScript parser found a syntax error. The script cannot run until the syntax is fixed."),
        fix_hint="Check the line mentioned in the error for missing parentheses, brackets, colons, or indentation issues.",
    ),
    KnownError(
        id="E13",
        pattern=r"(?:Cyclic reference|Could not resolve class|Could not find type)",
        category="parse_error",
        explanation=(
            "A class name couldn't be resolved, or a script has a circular "
            "dependency (A extends B which extends A). Godot can't compile it."
        ),
        fix_hint="Check class_name declarations and preload/load paths. Break cycles by using a base class or signals instead of direct references.",
    ),
    KnownError(
        id="E17",
        pattern=r"Cannot assign.*(?:onready|@onready)",
        category="parse_error",
        explanation=(
            "An @onready variable is being assigned outside its declaration. "
            "@onready runs once when the node enters the tree; reassigning it "
            "may conflict with the deferred initialization."
        ),
        fix_hint="Move the assignment into _ready() or use a regular variable instead of @onready.",
    ),
    # ── type_error ──────────────────────────────────────────────
    KnownError(
        id="E07",
        pattern=r"Invalid type in function\s+'\w+'.*\bCannot convert argument\b",
        category="type_error",
        explanation=(
            "A function received an argument of the wrong type. GDScript is "
            "dynamically typed but some engine methods enforce types at runtime."
        ),
        fix_hint="Check the argument type — you may need to cast with 'as', use int()/float()/str(), or wrap in the expected type.",
    ),
    KnownError(
        id="E15",
        pattern=r"Division by zero",
        category="type_error",
        explanation=("A math operation tried to divide by zero. This crashes the current script execution."),
        fix_hint="Add a guard: if divisor != 0: before the division. Check for zero-length vectors with length() > 0.",
    ),
    KnownError(
        id="E16",
        pattern=r"Out of bounds get index",
        category="type_error",
        explanation=("An array or PackedArray index is outside the valid range (negative or >= size())."),
        fix_hint="Check array.size() before indexing, or iterate with 'for item in array' instead of by index.",
    ),
    # ── node_path ───────────────────────────────────────────────
    KnownError(
        id="E05",
        pattern=r"Node not found:\s*\"(.+?)\"",
        category="node_path",
        explanation=(
            "get_node() or a NodePath reference couldn't find the target node. "
            "The path doesn't exist relative to the current node, or the node "
            "was removed/renamed."
        ),
        fix_hint="Verify the node path relative to the calling node. Use %UniqueName in the scene or absolute paths ($/root/Main/Target).",
    ),
    KnownError(
        id="E20",
        pattern=r"Condition\s+\"!is_inside_tree\(\)\"\s+is true",
        category="node_path",
        explanation=(
            "A node is being used before it's added to the scene tree. "
            "Operations like get_node() or get_tree() fail outside the tree."
        ),
        fix_hint="Use call_deferred() to delay the operation until the node is in the tree, or move the logic to _ready() or _enter_tree().",
    ),
    # ── signal ──────────────────────────────────────────────────
    KnownError(
        id="E06",
        pattern=r"Signal\s+\"(\w+)\"\s+is already connected",
        category="signal",
        explanation=(
            "The same signal-to-method connection is being made twice. "
            "In Godot 4, signals use CONNECT_ONE_SHOT by default only if "
            "explicitly requested."
        ),
        fix_hint="Check for duplicate connect() calls, or use CONNECT_ONE_SHOT as the last argument to signal.connect().",
    ),
    KnownError(
        id="E14",
        pattern=r"emit_signal:\s*Signal\s+\"(\w+)\"\s+doesn't exist",
        category="signal",
        explanation=(
            "emit_signal() is called with a signal name that isn't declared "
            "on the class. The signal may have been removed or renamed."
        ),
        fix_hint="Declare the signal with 'signal signal_name' at the top of the script, or check for a typo in the emit_signal() call.",
    ),
    # ── physics ─────────────────────────────────────────────────
    KnownError(
        id="E09",
        pattern=r"(?:move_and_slide|move_and_collide|test_move).*(?:_process|_ready)",
        category="physics",
        explanation=(
            "A physics function (move_and_slide, move_and_collide) is being "
            "called outside _physics_process(). Physics functions expect to "
            "run at a fixed timestep; running them in _process() or _ready() "
            "produces inconsistent results."
        ),
        fix_hint="Move the physics call to _physics_process(delta). Use _process() only for visual/logic updates that don't need fixed-rate physics.",
    ),
    # ── resource ────────────────────────────────────────────────
    KnownError(
        id="E10",
        pattern=r"(?:Cannot load resource|No loader found for resource|Failed to load)",
        category="resource",
        explanation=(
            "Godot can't find or load a resource file. The path may be wrong, "
            "the file may have been moved/deleted, or the format isn't supported."
        ),
        fix_hint="Check the file path (case-sensitive on some platforms). Use 'res://' prefix for project-relative paths. Verify the file exists on disk.",
    ),
    KnownError(
        id="E18",
        pattern=r"Viewport Texture must be set to use it",
        category="resource",
        explanation=(
            "A ViewportTexture is referenced but the viewport hasn't been "
            "configured. Common with render-to-texture setups and minimap cameras."
        ),
        fix_hint="Assign a SubViewport to the texture's viewport_path, or check that the camera is rendering to the correct viewport.",
    ),
    # ── other ───────────────────────────────────────────────────
    KnownError(
        id="E12",
        pattern=r"The function\s+'(\w+)\(\)'\s+returns a value, but this value is never used",
        category="other",
        explanation=(
            "A function returns a value but the caller ignores it. This is "
            "a warning — not a crash — but may indicate a logic bug."
        ),
        fix_hint="Assign the return value to a variable, or explicitly discard it: 'var _ = func_call()' if you truly don't need it.",
    ),
    KnownError(
        id="E19",
        pattern=r"(?:RID allocation leak|ObjectDB instances leaked at exit)",
        category="other",
        explanation=(
            "Godot detected leaked resources when the game closed. Resources "
            "were created but never freed. In GDScript this is rare but can "
            "happen with raw RID usage or Resource objects held in static variables."
        ),
        fix_hint="Check for resources created with Resource.new() or RID.create() that aren't freed. Ensure static/autoload variables release references on exit.",
    ),
]
