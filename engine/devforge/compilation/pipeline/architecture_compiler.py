from __future__ import annotations

from typing import Dict, List

from devforge.compilation.ir.plan import (
    PlanStep,
    DevForgePlan,
    CreateEntityStep,
    CreateScriptStep,
    AttachScriptStep,
    RemoveNodeStep,
    RenameNodeStep,
    SetPropertyStep,
    ConnectSignalStep,
)

from devforge.knowledge.scene.scene_graph import SceneGraph, VALID_GODOT_TYPES
from devforge.knowledge.scene.resource_templates import (
    MESH_RESOURCES,
    SHAPE_RESOURCES,
    make_material,
)
from devforge.knowledge.scene.godot_node_types import (
    NODES_WITHOUT_VECTOR3_TRANSFORM as _NON_3D_TYPES,
)
from devforge.infrastructure.logger import logger

# The signal a node most commonly emits — used to wire a connection when the
# planner names no signal. "body_entered" is only right for Areas; a Timer emits
# "timeout", a Button "pressed". The right signal name is what lets the
# connection actually attach instead of being rejected as nonexistent.
_DEFAULT_SIGNAL_BY_TYPE = {
    "Timer": "timeout",
    "Area3D": "body_entered",
    "Area2D": "body_entered",
    "RigidBody3D": "body_entered",
    "RigidBody2D": "body_entered",
    "Button": "pressed",
    "TextureButton": "pressed",
}

# Handler-method parameter signatures per signal — used by the reverse
# host-node (Slice B) to synthesize a STUB script with the *correct* arity for
# a script-less signal target, so a `connect` wires instead of failing at
# runtime. Only signals listed here get a stub; anything else falls back to the
# safe B2 drop (we won't guess a signature we can't guarantee).
_SIGNAL_HANDLER_ARGS = {
    "body_entered": "body: Node3D",
    "body_exited": "body: Node3D",
    "area_entered": "area: Area3D",
    "area_exited": "area: Area3D",
    "timeout": "",
    "pressed": "",
    "toggled": "toggled_on: bool",
    "tree_entered": "",
    "tree_exited": "",
    "ready": "",
}


# `_NON_3D_TYPES` (imported above as NODES_WITHOUT_VECTOR3_TRANSFORM) is the
# canonical set of node types with no Vector3 transform — they emit
# PROPERTY_NOT_ON_CLASS if you set `position` on them. Single source of truth
# now lives in knowledge/scene/godot_node_types.py so the validator
# (_property_matches_type) and this compiler (Fix A / connection loop) agree.


class ArchitectureCompiler:
    def compile(self, delta: Dict, scene: SceneGraph | None = None) -> DevForgePlan:

        steps: List[PlanStep] = []

        entities = delta.get("entities", [])
        systems = delta.get("systems", [])

        # Per-entity parent map. Built from the optional ``parent`` field
        # on each entity and from the top-level ``parents`` dict the planner
        # forwards.  Resolved by _resolve_parent() below.
        parent_map: Dict[str, str] = dict(delta.get("parents") or {})
        for entity in entities:
            if isinstance(entity, dict):
                name = entity.get("name", "").strip()
                parent = entity.get("parent")
                if name and parent:
                    parent_map[name] = parent

        # Track parents introduced in *this* delta so children can reference
        # siblings that don't exist in the live scene yet.
        delta_parents: Dict[str, str] = {}
        # entity name → its full resolved path, so script attachment targets the
        # node at its REAL (possibly nested) path, not a flat /root/Main/<name>.
        entity_paths: Dict[str, str] = {}
        entity_types: Dict[str, str] = {}  # entity name → Godot type (T1 signal)
        system_attach: Dict[str, str] = {}  # system name → node path it attaches to (T1)

        logger.info(
            "arch_compiler",
            "Compiling delta",
            entities=len(entities),
            systems=len(systems),
        )

        root_path = "/root"

        if scene:
            root_path = scene.root.path

        def _resolve_parent(name: str) -> str:
            """Resolve the effective parent for an entity.

            Priority: per-entity ``parent`` field → /root/Main if it
            exists in the scene → scene root → /root. Always falls back
            to a path that exists so we never produce a dangling parent.
            """
            explicit = parent_map.get(name)
            if explicit:
                # Accept the parent if it already exists in the scene
                if scene and scene.has_path(explicit):
                    return explicit
                # ...or a sibling entity created earlier in THIS delta: the
                # model references it by bare name ("Arena"), but the executor
                # needs its FULL path. delta_parents[name] is the entity's own
                # parent path, so its own path is "<parent>/<name>". Returning
                # the bare name here made every nested op fail validation
                # ("parent 'Arena' not found in scene").
                if explicit in delta_parents:
                    return f"{delta_parents[explicit]}/{explicit}"
                # If it's just a bare name, try as a sibling/root child
                if "/" not in explicit and scene:
                    candidate = f"{root_path}/{explicit}"
                    if scene.has_path(candidate):
                        return candidate
                # Fall through to safe default rather than fail
                logger.warn(
                    "arch_compiler",
                    f"Parent '{explicit}' for '{name}' not found; falling back to scene root",
                )
            # Default to the ACTUAL scene root, resolved at runtime
            # (scene.root.path = /root/<RootName>). Hardcoding "/root/Main"
            # here corrupted any scene whose root wasn't literally "Main":
            # if a prior build left the root as "Main2", every top-level
            # entity targeted a non-existent "/root/Main", the bridge then
            # materialized a fresh "Main" → Godot auto-suffixed it, and the
            # build cascaded under a rogue root. Use the real root instead.
            return root_path

        # ── Entities → CreateEntityStep ──
        # IMPORTANT: process entities BEFORE rename/remove markers.
        # Bug 2.1 (2026-06-15): markers were processed first, so a
        # "create X then delete/rename X" prompt fired the remove/rename
        # op before the create op → "node not found" spurious error.
        # entity_paths is populated during this loop so the rename/remove
        # block below can resolve same-delta targets.
        for entity in entities:
            if not isinstance(entity, dict):
                continue

            name = entity.get("name", "").strip()
            node_type = entity.get("type", "Node3D").strip()

            if not name:
                continue

            if node_type not in VALID_GODOT_TYPES:
                node_type = "Node3D"

            parent = _resolve_parent(name)
            entity_path = f"{parent}/{name}"

            if scene and scene.has_path(entity_path):
                logger.info("arch_compiler", f"Entity '{name}' already exists, skipping")
                continue

            steps.append(
                CreateEntityStep(
                    name=name,
                    node_type=node_type,
                    parent=parent,
                )
            )
            delta_parents[name] = parent
            entity_paths[name] = entity_path
            entity_types[name] = node_type

            # Phase 4: emit SetPropertySteps from the entity's props dict
            props = entity.get("props")
            if isinstance(props, dict) and props:
                prop_steps = self._props_to_steps(props, entity_path, node_type)
                steps.extend(prop_steps)

        # ── Systems → Script + Attach ──
        # Track script contents so Fix B3 can check method existence.
        script_contents: Dict[str, str] = {}  # system_name → script_content
        for system in systems:
            if not isinstance(system, dict):
                continue

            name = system.get("name", "").strip()

            if not name:
                continue

            safe_name = name.replace(" ", "_").lower()

            script_path = f"scripts/{safe_name}.gd"

            content = self._generate_system_script(name, system)
            script_contents[name] = content

            steps.append(
                CreateScriptStep(
                    path=script_path,
                    content=content,
                )
            )

            attach_target = self._find_attach_target(name, entities, entity_types)

            if attach_target:
                # Use the target's real (possibly nested) path; fall back to a
                # flat root child only if we never created/saw it this delta.
                attach_node = entity_paths.get(attach_target, f"{root_path}/{attach_target}")
                system_attach[name] = attach_node  # T1: signals can target the script's node
                steps.append(
                    AttachScriptStep(
                        node=attach_node,
                        script=script_path,
                    )
                )
            else:
                # No matching entity — create a dedicated Node3D host so
                # signal connections to this system can resolve a target_path
                # (G5: SpawnerSystem had no host → connect_signal dropped, 0/1
                # signals, 2026-06-15). The old Strategy 3 fallback attached
                # to the first entity, causing silent script-overwrite bugs.
                host_name = name
                host_path = f"{root_path}/{host_name}"
                if not (scene and scene.has_path(host_path)):
                    steps.append(
                        CreateEntityStep(
                            name=host_name,
                            node_type="Node3D",
                            parent=root_path,
                        )
                    )
                    delta_parents[host_name] = root_path
                    entity_paths[host_name] = host_path
                    entity_types[host_name] = "Node3D"
                    # Append to entities so sibling systems see this host
                    entities.append({"name": host_name, "type": "Node3D"})
                    logger.info(
                        "arch_compiler",
                        f"Created host node '{host_path}' for orphaned system '{name}' — enables signal connections.",
                    )
                else:
                    logger.warn(
                        "arch_compiler",
                        f"Host node '{host_path}' for system '{name}' already "
                        f"exists in live scene — attaching script will overwrite "
                        f"its existing script.",
                    )
                system_attach[name] = host_path
                steps.append(
                    AttachScriptStep(
                        node=host_path,
                        script=script_path,
                    )
                )

        # ── Rename / Remove markers (deterministic planner) ──
        # Processed AFTER entities+systems so same-delta creates exist
        # when delete/rename ops fire (Bug 2.1, 2026-06-15: markers were
        # processed before entities, causing "node not found" spurious errors
        # for "create X then delete/rename X" prompts).
        # entity_paths is used for same-delta resolution before falling back
        # to _resolve_node_target (scene lookup).
        rename = delta.get("_rename")
        if isinstance(rename, dict):
            target = (rename.get("from") or "").strip()
            new_name = (rename.get("to") or "").strip()
            if target and new_name:
                # Resolve against same-delta entities first, then scene
                node_path = entity_paths.get(target)
                if node_path is None:
                    node_path = self._resolve_node_target(target, scene, root_path)
                steps.append(RenameNodeStep(node=node_path, new_name=new_name))

        remove = delta.get("_remove")
        if isinstance(remove, str) and remove.strip():
            target = remove.strip()
            node_path = entity_paths.get(target)
            if node_path is None:
                node_path = self._resolve_node_target(target, scene, root_path)
            steps.append(RemoveNodeStep(node=node_path))

        # ── Connections → ConnectSignalStep (T1: signal wiring) ──
        # The planner emits connections like {"from": "Coin", "to": "Coin",
        # "type": "signal"} — previously these were parsed from the LLM
        # response but never compiled into ConnectSignalStep operations,
        # so connect_signal fired zero times. Now each connection gets
        # resolved to entity paths and emitted as a real signal connection.
        connections = delta.get("connections", [])
        # Compute once: nodes that received scripts this delta (Fix B2).
        attached_nodes = set(system_attach.values())
        for conn in connections:
            if not isinstance(conn, dict):
                continue
            conn_type = conn.get("type", "")
            if conn_type != "signal":
                continue  # only "signal" connections emit ConnectSignalStep

            from_name = conn.get("from", "").strip()
            to_name = conn.get("to", "").strip()
            signal_name = conn.get("signal", "")
            method_name = conn.get("method", "")

            if not from_name or not to_name:
                continue

            # Resolve entity names to full paths (entities created in this delta)
            source_path = entity_paths.get(from_name)
            target_path = entity_paths.get(to_name)

            # T1: a connection often names a SYSTEM (a script) as an endpoint,
            # not a node — e.g. "connect SpawnTimer.timeout to Spawner". Resolve
            # such names to the node the script is attached to.
            if source_path is None and from_name in system_attach:
                source_path = system_attach[from_name]
            if target_path is None and to_name in system_attach:
                target_path = system_attach[to_name]

            # If not in this delta, try scene lookup
            if source_path is None and scene:
                node = scene.find_by_name(from_name)
                if node:
                    source_path = node.path
            if target_path is None and scene:
                node = scene.find_by_name(to_name)
                if node:
                    target_path = node.path

            # Drop connections whose endpoints can't be resolved to a real node
            # (this delta, a system attach point, or the live scene). The LLM
            # frequently hallucinates wiring to a phantom node — e.g. a
            # "ScoreLabel" it assumed exists from a collectible-game pattern.
            # Fabricating "/root/Main/ScoreLabel" and emitting the connect_signal
            # anyway made the ATOMIC batch fail and roll back the ENTIRE build
            # (G4_children: 0 nodes built from 3 phantom-signal errors, 6/15).
            # Same principle as the invalid-property drop (Bug 1): never let one
            # un-buildable op nuke the valid ones.
            if source_path is None or target_path is None:
                logger.warn(
                    "arch_compiler",
                    f"Signal connection '{from_name}' → '{to_name}' DROPPED — "
                    f"endpoint not resolvable (source={source_path}, "
                    f"target={target_path}); likely a hallucinated node.",
                )
                continue

            # T1: derive the signal from the SOURCE node's type when the planner
            # didn't name one — "body_entered" is wrong for a Timer (timeout) or a
            # Button (pressed). A correct signal name is what makes the connection
            # actually wire instead of being rejected.
            if not signal_name:
                signal_name = _DEFAULT_SIGNAL_BY_TYPE.get(entity_types.get(from_name, ""), "body_entered")
            if not method_name:
                method_name = f"_on_{signal_name}"

            # Fix B (2026-06-15): drop connections whose target can't handle
            # the signal method — runs AFTER signal/method derivation so
            # default-derived _on_ names are also checked.  Two cases:
            #
            # B1 — UI/non-3D target: a Label or CanvasLayer has no
            #   body_entered handler (G7: _on_body_entered → Label).
            # B2 — Same-delta target without a script: the LLM emits a
            #   connection to a node created in this batch that has no
            #   attached script defining the method (G5: _on_SpawnTimer_timeout
            #   → SpawnerSystem, a plain Node3D).
            #
            # Only check same-delta targets for B2 — pre-existing scene nodes
            # may have scripts from prior runs that we can't see here.
            target_type = entity_types.get(to_name, "")
            if target_type in _NON_3D_TYPES and method_name.startswith("_on_"):
                logger.warn(
                    "arch_compiler",
                    f"Signal connection '{from_name}' → '{to_name}' DROPPED "
                    f"(B1) — method '{method_name}' on {target_type} target; "
                    f"{target_type} is not a 3D node and cannot handle "
                    f"physics signal handlers.",
                )
                continue
            if to_name in entity_paths and target_path not in attached_nodes and method_name.startswith("_on_"):
                # Slice B — reverse host-node: rather than DROP a connection to
                # a script-less same-delta target, synthesize a stub script
                # that defines the handler (with the correct signature for the
                # signal) and attach it, so the signal wires. This is the mirror
                # of the forward host-node (system with no entity → Node3D host).
                # If we can't guarantee a correct handler signature, fall back to
                # the safe drop — a wrong signature is worse than a missing wire.
                stub = self._generate_signal_stub(entity_types.get(to_name, "Node3D"), method_name, signal_name)
                if stub is not None:
                    stub_path = f"scripts/{to_name.replace(' ', '_').lower()}_stub.gd"
                    steps.append(CreateScriptStep(path=stub_path, content=stub))
                    steps.append(AttachScriptStep(node=target_path, script=stub_path))
                    attached_nodes.add(target_path)
                    system_attach[to_name] = target_path
                    script_contents[to_name] = stub
                    logger.info(
                        "arch_compiler",
                        f"Signal target '{to_name}' had no script — synthesized a "
                        f"stub defining '{method_name}' so the connection from "
                        f"'{from_name}' wires (reverse host-node, Slice B).",
                    )
                    # fall through: B3 below re-validates the stub, then the
                    # ConnectSignalStep is appended.
                else:
                    logger.warn(
                        "arch_compiler",
                        f"Signal connection '{from_name}' → '{to_name}' DROPPED "
                        f"(B2) — target '{to_name}' created in this delta has no "
                        f"attached script and signal '{signal_name}' has no known "
                        f"handler signature to stub; method '{method_name}' would "
                        f"fail with PROPERTY_NOT_ON_CLASS at execution.",
                    )
                    continue

            # B3: same-delta target HAS an attached script, but the generated
            # script content may not define the method being connected (e.g.
            # a stub script connected to _on_SpawnTimer_timeout → G5 gauntlet
            # atomic rollback, 2026-06-15).  Only check same-delta entities;
            # pre-existing scene nodes may have scripts from prior runs.
            if to_name in entity_paths and target_path in attached_nodes:
                # Find the script content that was attached to this entity
                target_script = None
                for sys_name, sys_path in system_attach.items():
                    if sys_path == target_path:
                        target_script = script_contents.get(sys_name)
                        break
                if target_script and method_name:
                    # Use "func <name>(" to avoid substring false positives
                    # ("_on_timeout" matching "_on_timeout_extended").
                    if f"func {method_name}(" not in target_script:
                        # Fallback: the LLM may name the method too specifically
                        # ("_on_SpawnTimer_timeout") — try the default
                        # "_on_{signal}" pattern which stubs/templates define.
                        default_method = f"_on_{signal_name}"
                        if default_method != method_name and f"func {default_method}(" in target_script:
                            logger.info(
                                "arch_compiler",
                                f"Signal connection '{from_name}' → '{to_name}': "
                                f"method '{method_name}' not in script, "
                                f"falling back to '{default_method}'.",
                            )
                            method_name = default_method
                        else:
                            import re as _re

                            funcs = _re.findall(r"func\s+(\w+)", target_script)
                            logger.warn(
                                "arch_compiler",
                                f"Signal connection '{from_name}' → '{to_name}' DROPPED "
                                f"(B3) — method '{method_name}' not found in script "
                                f"attached to target '{to_name}' (script defines: "
                                + (", ".join(funcs) if funcs else "none")
                                + "); connecting would fail with PROPERTY_NOT_ON_CLASS.",
                            )
                            continue

            steps.append(
                ConnectSignalStep(
                    source=source_path,
                    signal=signal_name,
                    target=target_path,
                    method=method_name,
                )
            )
            logger.info(
                "arch_compiler",
                f"Signal connection: {source_path}.{signal_name} → {target_path}.{method_name}",
            )

        plan = DevForgePlan(goal="", steps=steps)

        errors = plan.validate()

        if errors:
            logger.warn("arch_compiler", "Plan has validation warnings", errors=errors)

        # ── Semantic validation (Slice 4, 2026-06-15) ──
        # Check entity relationships that are structurally valid but
        # semantically wrong — e.g. Camera3D with a MeshInstance3D child.
        # These errors are stored on the instance so the pipeline engine
        # can surface them in PipelineResult.errors.
        self._semantic_errors: List[str] = []
        # Check 1: Camera3D with MeshInstance3D child (G8 adversarials, Slice 4).
        # Use delta_parents (parent→child relationships), not path-string
        # matching, to catch nested cases too. delta_parents maps entity→its parent.
        for ename, etype in entity_types.items():
            if etype == "Camera3D":
                for child_name, child_type in entity_types.items():
                    if child_name == ename:
                        continue
                    # Check if child's parent is this Camera3D entity
                    child_parent = delta_parents.get(child_name, "")
                    if child_parent and child_parent.endswith(f"/{ename}"):
                        if "MeshInstance" in child_type:
                            self._semantic_errors.append(
                                f"Semantic violation: Camera3D '{ename}' has a "
                                f"MeshInstance3D child '{child_name}' — cameras "
                                f"are not renderable; mesh children are wasted."
                            )
                            logger.warn(
                                "arch_compiler",
                                f"Semantic: Camera3D '{entity_paths.get(ename)}' with "
                                f"MeshInstance3D child '{entity_paths.get(child_name)}' — flagged.",
                            )

        logger.info("arch_compiler", f"Compiled {len(steps)} steps")

        return plan

    @staticmethod
    def _resolve_node_target(target: str, scene: SceneGraph | None, root_path: str) -> str:
        """Resolve a user-named rename/remove target to a scene node path.

        Accepts a full path as-is. Bare names are matched against the
        scene case-insensitively (prompts may not match Godot's exact
        node-name casing). Unresolved names fall back to a root-child
        path so the validator can reject them with a clear
        "node not found" error instead of the op silently vanishing.
        """
        if "/" in target:
            return target

        nodes = list(scene.all_nodes()) if scene else []

        # The marker source (the LLM, or the deterministic intent pre-pass)
        # frequently hands us a punctuated span or a whole noun phrase rather
        # than a clean node name — e.g. "Victim.", "the node named Victim from
        # the scene.", "the node Before". Resolve robustly instead of requiring
        # an exact literal match (which fails on every realistic edit prompt).

        # 1) exact (case-insensitive) match on the punctuation-stripped span.
        cleaned = target.strip().strip(".,;:!?\"'()[]").strip()
        cl = cleaned.lower()
        for node in nodes:
            if node.name.lower() == cl:
                return node.path

        # 2) token match: a known node name appearing as a word in the span.
        # Resolves noun phrases + stray punctuation by matching the LONGEST
        # node name present as a token (most specific wins).
        import re as _re

        tokens = {t.lower() for t in _re.findall(r"[A-Za-z0-9_]+", target)}
        best = None
        for node in nodes:
            if node.name.lower() in tokens and (best is None or len(node.name) > len(best.name)):
                best = node
        if best is not None:
            return best.path

        logger.warn(
            "arch_compiler",
            f"Rename/remove target '{target}' not found in scene; passing through for validation",
        )
        return f"{root_path}/{cleaned or target}"

    @staticmethod
    def _props_to_steps(props: Dict, entity_path: str, node_type: str) -> List[PlanStep]:
        """Convert per-entity props dict into SetPropertySteps.

        Supported keys and their Godot property mappings:
          mesh: "box"|"sphere"|"capsule"|"plane"|"cylinder" → mesh resource
          shape: "box"|"sphere"|"capsule"|"cylinder" → shape resource
          color: [r,g,b] → StandardMaterial3D albedo_color
          position: [x,y,z] → Vector3 position
          text: "..." → Label text

        Type-validation is deferred to the OperationValidator which checks
        ``_property_matches_type`` against ``PROPERTY_ALLOWLIST``.  This
        method emits the SetPropertyStep unconditionally; the validator
        drops it with a counted error if the prop-type pair is invalid.
        The only exception is ``position`` on non-3D types — the validator
        does not yet have a position allowlist, so we skip it here (Fix A).
        """
        steps: List[PlanStep] = []

        for key, value in props.items():
            if key == "mesh" and isinstance(value, str):
                mesh_res = MESH_RESOURCES.get(value.lower())
                if mesh_res:
                    steps.append(SetPropertyStep(node=entity_path, property="mesh", value=mesh_res))

            elif key == "shape" and isinstance(value, str):
                shape_res = SHAPE_RESOURCES.get(value.lower())
                if shape_res:
                    steps.append(SetPropertyStep(node=entity_path, property="shape", value=shape_res))

            elif key == "color" and isinstance(value, list) and len(value) == 3:
                r, g, b = float(value[0]), float(value[1]), float(value[2])
                material = make_material(r, g, b)
                steps.append(SetPropertyStep(node=entity_path, property="material_override", value=material))

            elif key == "position" and isinstance(value, list) and len(value) == 3:
                # Fix A (2026-06-15): skip position on nodes that don't inherit
                # from Node3D — Timer, Label, CanvasLayer, and other plain-Node
                # types have no transform and cause PROPERTY_NOT_ON_CLASS at
                # execution time.  The validator does not yet have a position
                # allowlist, so this guard is still needed.
                if node_type in _NON_3D_TYPES:
                    logger.warn(
                        "arch_compiler",
                        f"position prop on {node_type} '{entity_path}' — SKIPPED "
                        f"(position requires Node3D or subclass)",
                    )
                    continue
                x, y, z = float(value[0]), float(value[1]), float(value[2])
                steps.append(SetPropertyStep(node=entity_path, property="position", value={"x": x, "y": y, "z": z}))

            elif key == "text" and isinstance(value, str):
                steps.append(SetPropertyStep(node=entity_path, property="text", value=value))

        return steps

    # ── Phase 5: intent keywords for script template selection ──
    # T2: expanded keyword coverage — large prompts with generic system names
    # ("GameManager", "WorldState", etc.) were falling back to stubs because
    # no keywords matched. Broader coverage + lower threshold (1 hit) ensures
    # more systems get real scripts instead of vanishing.
    _INTENT_KEYWORDS: Dict[str, List[str]] = {
        "movement": [
            "movement",
            "player",
            "input",
            "wasd",
            "walk",
            "move",
            "control",
            "keyboard",
            "character",
            "controller",
            "fly",
            "run",
            "dash",
            "jump",
            "swim",
            "drive",
            "pilot",
        ],
        "collectible": [
            "collect",
            "coin",
            "pickup",
            "item",
            "body_entered",
            "trigger",
            "area",
            "gem",
            "loot",
            "powerup",
            "health",
            "ammo",
            "resource",
            "drop",
            "spawn",
        ],
        "score": [
            "score",
            "ui",
            "label",
            "hud",
            "display",
            "counter",
            "gui",
            "points",
            "timer",
            "wave",
            "level",
            "inventory",
            "shop",
        ],
    }

    def _generate_signal_stub(self, node_type: str, method_name: str, signal_name: str) -> str | None:
        """Stub script defining *method_name* for *signal_name* (reverse host-node).

        Returns GDScript text, or None when *signal_name* has no known handler
        signature (caller then keeps the safe B2 drop). The script `extends` the
        target's own type when valid, else Node3D, so attaching is legal.
        """
        if signal_name not in _SIGNAL_HANDLER_ARGS:
            return None
        args = _SIGNAL_HANDLER_ARGS[signal_name]
        base = node_type if node_type in VALID_GODOT_TYPES else "Node3D"
        return (
            f"extends {base}\n\n"
            f"# Auto-generated stub (reverse host-node) — handles "
            f"'{signal_name}' from a connected node.\n"
            f"func {method_name}({args}) -> void:\n"
            f"    pass\n"
        )

    # ── Phase 5: script templates (real GDScript, not stubs) ──
    _SCRIPT_TEMPLATES: Dict[str, str] = {
        "movement": """extends Node3D

# {name}
# {description}

var speed: float = 5.0

func _process(delta: float) -> void:
    var input_dir := Vector3.ZERO
    if Input.is_key_pressed(KEY_W) or Input.is_key_pressed(KEY_UP):
        input_dir.z -= 1.0
    if Input.is_key_pressed(KEY_S) or Input.is_key_pressed(KEY_DOWN):
        input_dir.z += 1.0
    if Input.is_key_pressed(KEY_A) or Input.is_key_pressed(KEY_LEFT):
        input_dir.x -= 1.0
    if Input.is_key_pressed(KEY_D) or Input.is_key_pressed(KEY_RIGHT):
        input_dir.x += 1.0
    if input_dir != Vector3.ZERO:
        input_dir = input_dir.normalized()
    position += input_dir * speed * delta

func _on_timeout() -> void:
    pass
""",
        "collectible": """extends Area3D

# {name}
# {description}

func _ready() -> void:
    if not body_entered.is_connected(_on_body_entered):
        body_entered.connect(_on_body_entered)

func _on_body_entered(body: Node3D) -> void:
    queue_free()
    # Try to increment the ScoreLabel if it exists
    var sl = get_node_or_null("/root/Main/Arena/UI/ScoreLabel")
    if sl and sl is Label:
        var parts = sl.text.split(": ")
        if parts.size() >= 2 and parts[1].is_valid_int():
            sl.text = "Score: " + str(int(parts[1]) + 1)

func _on_timeout() -> void:
    pass
""",
        "score": """extends Node

# {name}
# {description}

var score: int = 0

func add_score(amount: int) -> void:
    score += amount
    if has_method("set_text"):
        text = "Score: " + str(score)

func _on_timeout() -> void:
    pass
""",
    }

    # Entity types that justify each behavior intent (so we don't invent a
    # movement script when there's no body to move).
    _INTENT_ENTITY_TYPES: Dict[str, set] = {
        "movement": {"CharacterBody3D", "CharacterBody2D", "RigidBody3D", "RigidBody2D"},
        "collectible": {"Area3D", "Area2D"},
        "score": {"Label", "CanvasLayer"},
    }
    _INTENT_SYSTEM: Dict[str, tuple] = {
        "movement": ("PlayerMovement", "WASD keyboard movement"),
        "collectible": ("CollectibleHandler", "body_entered frees self and adds score"),
        "score": ("ScoreSystem", "tracks and displays the score"),
    }

    @classmethod
    def infer_systems(cls, prompt: str, entities: List[Dict], existing_systems: List[Dict]) -> List[Dict]:
        """T2: deterministically recover behavior systems the LLM drops under load.

        For big prompts the planner emits entities but an empty `systems` array,
        so no scripts are generated (G7: 0 scripts). Scan the prompt for template
        intents and, for each intent the prompt asks for that (a) isn't already
        covered by an LLM-emitted system and (b) has a matching entity type in the
        scene, synthesize a system dict. The existing systems→script→attach
        pipeline then produces and wires the right GDScript. Deterministic — no
        extra LLM call.
        """
        text = (prompt or "").lower()
        covered = {
            cls._detect_intent(s.get("name", ""), s.get("description", ""))
            for s in (existing_systems or [])
            if isinstance(s, dict)
        }
        present_types = {e.get("type", "") for e in entities if isinstance(e, dict)}
        inferred: List[Dict] = []
        for intent, kws in cls._INTENT_KEYWORDS.items():
            if intent in covered:
                continue
            if not (cls._INTENT_ENTITY_TYPES.get(intent, set()) & present_types):
                continue
            if any(kw in text for kw in kws):
                sysname, desc = cls._INTENT_SYSTEM[intent]
                inferred.append({"name": sysname, "description": desc})
        return inferred

    @classmethod
    def _detect_intent(cls, name: str, description: str) -> str:
        """Detect the script intent from system name + description keywords.

        Returns one of 'movement', 'collectible', 'score', or '' (default).
        """
        combined = (name + " " + description).lower()
        best = ""
        best_score = 0
        for intent, keywords in cls._INTENT_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in combined)
            if score > best_score:
                best_score = score
                best = intent
        # Require at least 1 keyword hit (T2: lowered from 2 — large prompts
        # with generic system names were falling back to stubs, causing script
        # vanish (G7: 0 generated)). Single-hit still gives best match.
        return best if best_score >= 1 else ""

    def _generate_system_script(self, name: str, system: Dict) -> str:
        """Generate a real GDScript body based on detected intent.

        Phase 5: replaced one-line stubs with template-based scripts that
        actually implement the requested behavior (WASD movement,
        body_entered signal → queue_free + score increment, score tracking).
        Falls back to the old stub for unrecognized intents.
        """
        description = system.get("description", "")
        intent = self._detect_intent(name, description)

        if intent and intent in self._SCRIPT_TEMPLATES:
            logger.info("arch_compiler", f"Using {intent} template for system '{name}'")
            return self._SCRIPT_TEMPLATES[intent].format(name=name, description=description)

        # Fallback: old stub for unrecognized intents
        return f"""extends Node

# {name}
# {description}

func _ready() -> void:
    pass

func _process(delta: float) -> void:
    pass

func _on_timeout() -> void:
    pass
"""

    @staticmethod
    def _find_attach_target(system_name: str, entities: List[Dict], entity_types: Dict[str, str] | None = None):
        """Find the best entity to attach a script to.

        Phase 5: multi-strategy matching —
          1. Name match: system name contains entity name (or vice versa).
          2. Type match: movement prefers CharacterBody3D/MeshInstance3D;
             collectible prefers Area3D.
          3. Fallback: first entity in the list.

        entity_types: optional dict mapping entity name → Godot type.
        """
        name_lower = system_name.lower()
        entity_types = entity_types or {}

        # Strategy 1: name substring match (both directions)
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            ename = entity.get("name", "")
            ename_lower = ename.lower()
            if ename_lower and (ename_lower in name_lower or name_lower in ename_lower):
                return ename

        # Strategy 2: type-based matching
        movement_types = {"characterbody3d", "meshinstance3d", "node3d", "rigidbody3d"}
        collectible_types = {"area3d", "rigidbody3d"}

        name_norm = name_lower
        if any(kw in name_norm for kw in ("movement", "player", "input", "wasd", "move", "walk")):
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                etype = entity.get("type", "").lower()
                if etype in movement_types:
                    return entity.get("name")

        if any(kw in name_norm for kw in ("collect", "coin", "pickup", "item")):
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                etype = entity.get("type", "").lower()
                if etype in collectible_types:
                    return entity.get("name")

        # Strategy 3: no fallback.  The old code fell back to the first
        # entity when no name/type match was found, but this caused
        # silent script-overwrite bugs — e.g. SpawnerSystem got attached
        # to Hero (the first entity), overwriting HeroMovementSystem's
        # script, then connect_signal wired a SpawnerSystem-only method
        # to Hero → PROPERTY_NOT_ON_CLASS → atomic rollback → 0 nodes
        # (G5 gauntlet, 2026-06-15).  Return None: let the script be
        # created without attachment; Fix B2 will drop connections to
        # unscripted nodes, keeping the valid ops alive.
        return None
