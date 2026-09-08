# Panda Editor POC — Development History / Changelog

This file preserves the long-form development history that previously lived in `README.md`.

## 0.4.36 — Shutdown / Heavy-Asset Stability Hardening

- Reworked Panda viewport shutdown into a strictly bounded graceful → terminate → force-kill sequence so a stalled graphics-driver/VRAM teardown cannot hold the pywebview application open indefinitely.
- Kept the viewport message pump alive during graceful cleanup so shutdown diagnostics remain observable.
- Added explicit console shutdown stages for editor host, Panda Play Mode/scripts, audio, particle previews, material RTT resources and ShowBase destruction.
- Added best-effort cleanup of particle preview state, material preview buffers and renderer-side caches before destroying the Panda graphics window.
- Multiprocessing queues and process handles are closed without waiting on feeder threads after the Panda child exits.
- No game/editor authoring features were intentionally changed in this pass.

## 0.4.35 — VFX Workspace Patch

- Fixed native Panda VFX preview clipping/scroll synchronization so the preview cannot remain stuck at the top or bottom when its HTML host scrolls out of view.
- Added explicit **Browse Texture…** and **Browse Model…** controls for VFX Sprite and Geom renderer asset references.

## 0.4.34 — Share-Ready Repository Pass

- Moved the accumulated development history out of the public-facing README.
- Rewrote `README.md` around project purpose, capabilities, controls, setup and requirements.
- Added repository hygiene through `.gitignore` while keeping the shipped default assets, templates, shaders and example scripts trackable.
- Removed generated Python cache artifacts from the share package.
- No editor/runtime feature behavior was intentionally changed in this pass.

---

# Panda Editor POC 0.4.33

## 0.4.33 — Asset Reference Picker + Authoring Workflow Polish

This pass replaces raw project-path entry as the primary workflow wherever the editor already knows what kind of asset is expected. A reusable, searchable **Project Asset Picker** now filters the Assets library by type, shows the current reference, supports double-click/use/clear, and offers **Import New…** for model, texture and audio categories. Manual path fields remain visible where useful for advanced users, but normal authoring no longer requires memorising `assets/...` paths.

Covered references include VFX Sprite textures and Geom models, World/Skybox models, Model components, Audio clips, Material/PBR texture maps, UI images, GLSL vertex/fragment/geometry files, Material graph Texture nodes, Terrain heightfields and Terrain paint-layer textures. Shader pickers additionally filter by sensible stage extensions.

The picker is bounded to the application window and uses the existing project asset index, so imported assets immediately become available without leaving the current workspace. VFX and World/Rendering use the same picker rather than special one-off path workflows.

## 0.4.32 — VFX / Particle Editor Completion

- Reworked VFX authoring around Panda-style Factory / Emitter / Renderer concepts.
- Added Sprite, Point, Line, Sparkle and Geom/Model renderers plus expanded emitter shapes and factory controls.
- Fixed VFX preview isolation so scene/entity syncs do not reveal the normal level while the VFX workspace owns the viewport.
- Added VFX renderer validation, API documentation and showcase examples.

## 0.4.31 — Tasks / Events + API Documentation Enrichment

- Added direct named-method timers for `world.task_every()` / `world.call_later()` alongside event delivery through `on_event()`.
- Documented callback shape, runtime-created task lifecycle and authored task controls.
- Added the runnable light-flicker task example and richer API Documentation sections for returns, notes, pitfalls and related API.

## 0.4.30 — Play / Output Workflow + Console Polish

- **Play now opens Output automatically.** Runtime startup, script logs and engine messages are visible immediately instead of remaining hidden behind the Assets tab.
- **Output follows the newest line while running.** Logging keeps the console pinned to the latest message.
- **Manual history inspection is respected.** Scroll upward and auto-follow pauses; scroll back to the bottom, press **LATEST**, or enable **FOLLOW** to resume.
- Added compact **FOLLOW / LATEST / COPY / CLEAR** Output controls and explicit Play start/stop separators.
- Stop leaves Output visible at the latest runtime messages for immediate post-run inspection.

## 0.4.29 — Component Browser / Inspector Workflow Polish

- Replaces the oversized Add Component dropdown with a bounded, searchable component browser that always fits inside the editor window.
- Components are grouped into Rendering, Lighting, Physics, AI / Navigation, Gameplay, World / FX, UI / HUD and Scripting categories.
- Added category filters, Recent components, keyboard navigation (Up/Down/Enter/Escape), descriptions and per-component search keywords.
- Components already present on the selected entity are visibly marked and disabled, including shared Light/UI backing components.
- The browser reports the selected entity and available result count, and remains compatible with the Panda viewport exclusion system.
- No component/runtime behavior was removed or changed by this pass.

## 0.4.28 — Input Capture Reliability + Shadow Capability Alignment

This pass fixes two integration issues found during native testing: captured free-look could slowly drift after pointer warps on Windows/pywebview, and simplepbr Point Light shadow requests could repeatedly generate unsupported shadow-map sampler errors.

### Captured mouse / Fly Camera

Captured mouse-look now reads the real window pointer relative to the viewport centre, normalizes that delta, recentres the pointer, suppresses the first two warp frames and applies a one-pixel jitter dead-zone. The old MouseWatcher path remains as a fallback. `scripts/example_fly_camera.py` also has a small defensive dead-zone/recapture guard, so the teaching example remains stable even on unusual mouse drivers.

### Renderer-aware shadow support

The runtime now checks the active render pipeline before enabling a shadow caster. Under **simplepbr**, Point Light shadow requests are safely disabled because simplepbr supports shadow mapping for **DirectionalLight and Spotlight**, not PointLight. This prevents the repeated `shadowMap` sampler mismatch/errors while preserving the authored request if the project later switches to a renderer that supports it.

Spot and Directional shadows remain enabled under simplepbr. Directional shadows now get an explicit orthographic shadow volume with editable **Shadow Area**, **Near**, **Far** and **Resolution** controls; Spot shadows expose Resolution and Shadow Near. Project Validation warns when a simplepbr Point Light is authored to cast shadows.

### Authoring clarity

Inspector and World / Rendering light editors now show the active capability instead of presenting every `Cast Shadows` checkbox as equally valid. Unsupported Point shadows are disabled in the UI while simplepbr is active, and shadow-map resolution/coverage settings are available for supported light types.

## 0.4.27 — Lighting / Material Pipeline Consistency + Rendering Polish

This pass fixes a rendering-state ordering bug that could make Material components behave differently from unmaterialed geometry when simplepbr/complexpbr was selected. Project rendering settings are now sent to the Panda child **before entities are built**, so Materials inherit the correct world pipeline from their first frame. Switching Built-in / simplepbr / complexpbr also cleanly restarts only the Panda viewport process, preserving the pywebview editor while preventing old root shaders/buffers from leaking into the next profile.

### Lit textured Plane fix

Panda `CardMaker` does not generate normals unless requested. The editor Plane primitive and Material Preview Plane now explicitly generate normals, which are required for lighting/PBR. This is particularly important for floor planes with Base Color textures.

### Material shader policy

The ambiguous per-object `Shader Auto` checkbox is replaced in the UI by an explicit policy:

- **Inherit World / Render Pipeline** — recommended; follows Built-in auto-shader, simplepbr, or complexpbr.
- **Force Panda Auto Shader** — intentionally overrides a selected PBR pipeline on this object.
- **Shader Off / Fixed Function** — disables shader rendering for this object.

`Unlit` remains the explicit way to make a material ignore scene lights. Legacy `shader_auto` values remain readable for old scenes.

### Material colour correction

Base Color is now represented by Panda `Material` / PBR material state only. The runtime no longer applies the same RGB a second time through `ColorScale`, avoiding double-tinting/darkening of textured materials.

### World / Rendering clarity

`Panda Shader Auto` is renamed **Built-in Auto Shader** and is disabled in the UI for simplepbr/complexpbr because those profiles own the root shader. The Lighting & PBR Showcase now includes a repeated checker-textured floor specifically for regression-testing Point/Spot/Directional lighting across all three profiles.


## 0.4.26 — Editor Rendering Isolation + Viewport Helper Polish

This polish pass keeps game-world rendering and editor-only tooling visually separate. Authored lights, shaders, fog, textures, materials and colour-scale overrides must affect the game scene, not the editor grid, transform gizmo, axes, selection outline, camera/light/navigation/VFX helpers, collider helpers or terrain brush cursor.

### Editor helper render isolation

All authoring helpers now receive high-priority Panda render-state overrides for lighting, custom shaders, textures, fog, materials and inherited colour scale. Helpers remain parented where useful so they still follow entity transforms, but no longer inherit the entity/world visual state. This includes the Level grid and axes, transform gizmo, selection wireframe, light/camera/particle/navigation helpers, collider helpers, terrain brush cursor, Bullet debug root and VFX preview guide geometry.

### View menu helper controls

The View menu now exposes persistent editor-only visibility controls for **Editor Grid**, **World Axes**, **Scene Helpers** and **Collision Helpers**. Grid/axes/scene-helper preferences are stored locally in the editor UI and reapplied when the embedded Panda viewport starts. Workspace preview lifecycle still overrides them temporarily where appropriate and restores them on return to Level Editing.

### Separation rule

The authoring contract is now explicit: **world/game rendering state belongs to authored content; editor helper rendering belongs to the editor**. This pass changes no authored light/material/shader behavior and adds no new game subsystem.


## 0.4.23 — Beginner Controls / Fly Camera + Integration Polish

This polish pass keeps the complete 0.4.22 editor/runtime feature set and adds a beginner-friendly development/showcase controller that demonstrates the Input API in one readable place. No major subsystem is added or removed.

### Beginner keyboard + mouse fly camera

Added `scripts/example_fly_camera.py`, intended to be attached to an active **Fixed** Camera entity. The script is deliberately commented and uses both mapped actions and direct input:

- **W / S** — forward / backward through `world.action_axis()`
- **A / D** — strafe through `world.action_axis()`
- **Space / C** — world-space up / down through `world.key_down()`
- **Shift** — speed boost through the existing `sprint` Input Map action
- **Mouse movement** — captured relative-look through `world.mouse_delta`
- **Escape** — release the captured pointer
- **Left Click** — capture the pointer again

The tuning values (`MOVE_SPEED`, `BOOST_MULTIPLIER`, `LOOK_SENSITIVITY`, `MAX_PITCH`) are constants at the top of the file so beginners can safely experiment without first understanding the entire script.

A matching `project_templates/fly_camera_showcase.pscene` contains an active Camera plus simple reference geometry and lighting. It is useful both as a learning scene and as a quick free-fly inspection camera while developing other systems.

### Input API enrichment

Direct input now has edge queries in addition to held-state queries:

- `world.key_pressed(key)`
- `world.key_released(key)`
- `world.mouse_pressed(button)`
- `world.mouse_released(button)`
- `world.mouse_captured`

Input Map actions remain the preferred gameplay abstraction, while these direct queries are intentionally useful for debug/showcase tools, mouse capture, prototypes and beginner examples. The API Documentation and Scripting Quick API are updated alongside the runtime.

### Scripting workspace onboarding

The Scripting workspace now has a **Beginner · Keyboard + Mouse** card with direct buttons to open the Fly Camera source or load the demo scene. This gives new users a concrete starting point instead of requiring them to discover the example through the Assets tree.

### Camera `on_start()` integration fix

Camera runtime state is now initialized **before** script `on_start()` callbacks. Previously, camera overrides/activation requested from `on_start()` could be cleared immediately afterward by Play initialization. `camera_configure()` and `camera_activate()` are now valid from startup scripts as the API documentation implies.

---

## 0.4.22 — Integration QA / Workspace Reliability

This polish pass repairs editor integration regressions found during 0.4.21 testing and continues the no-major-subsystem polish run. Existing systems are retained.

### Fixed / enriched

- AI Behavior is restored as a registered, functional workspace with search, selection, full authoring controls, Inspector bridge, API shortcut and Level framing.
- The top-level Tools menu is now functional: Project Validation, Problems, API Documentation, Debug, Project Settings and Editor Settings are directly accessible.
- Special-workspace input/select/textarea styling now has explicit theme-aware foreground/background/placeholder colors, fixing low-contrast white/gray-on-light-field controls such as Tasks / Events.
- Panda DirectGUI Radio text no longer uses the unsupported U+25CB circle glyph. Runtime radios use ASCII-safe markers, removing the repeated Panda font warnings.
- Scene change publishing now includes dirty/path/Undo/Redo state and `_changed(False)` is supported correctly. New/Open/Save no longer throw the pywebview TypeError.
- Template/project scene opening now explicitly adopts the loaded scene in the browser, clears stale selection/command state, refreshes assets and preserves clean dirty-state semantics.
- All 17 workspace tabs are audited against the central workspace registry; AI Behavior was the missing registration and Terrain now has an explicit enter/render lifecycle.
- Navigation chase/flee completion no longer emits repeated `navigation_finished` events every repath when the agent is already at a temporary continuous-behavior target.

### Polish direction

0.4.22 is an integration/QA pass: workspace routing, scene loading, form legibility and runtime diagnostics are stabilized before any further feature expansion.

---

## 0.4.21 — Materials / VFX / Interval Timeline Polish

This is the next consolidation pass after 0.4.20. It keeps the existing engine/runtime feature set intact and concentrates on three advanced authoring surfaces that had grown faster than their editor ergonomics.

### Material graph usability

The Material / Shader graph now has real node selection and navigation workflow on top of the existing typed socket/link system. Nodes can be single- or multi-selected with Ctrl/Cmd, selected nodes are visually distinct, Delete/Backspace removes the selected removable nodes, and the toolbar provides **Frame All**, **Frame Selected** and **Delete Selected** actions. Middle-mouse or Alt+drag pans the graph viewport and `F` frames the current selection. Default Principled Surface / Material Output nodes remain protected. Graph edits continue to use the existing undoable `update_component()` command path.

### VFX preview polish

The isolated VFX preview keeps the 0.4.18 workspace/HUD isolation and gains persistent **Grid** and **Axes** visibility toggles plus a clear RUNNING/STOPPED preview state indicator. These options are handled by the Panda preview scene itself rather than hiding browser overlays, so the game scene remains unaffected. Camera orbit/pan/focus/zoom, Start/Burst/Stop/Clear and the full emitter authoring surface remain unchanged.

### Interval authoring timeline

The Intervals workspace now includes a visual authoring timeline rather than only rows. Sequence intervals show cumulative step placement across time; Parallel intervals place each step on its own lane starting at time zero. Timeline blocks are colored by step type and show duration, can be clicked to focus the corresponding step row, and interval tabs expose the total authored duration. Steps can now be reordered with Up/Down controls. This is an editor visualization of the existing Panda3D Interval data—the runtime Sequence/Parallel implementation is unchanged.

### Reliability / compatibility

Material graph saves, Interval edits/reordering and existing component edits continue through the command-backed component update path, preserving Undo/Redo behavior. VFX preview options are editor-only and do not modify authored particle data. Terrain, HUD/UI, Tasks/Events, Render Attributes, Cameras, Navigation, AI Behavior, Physics, Scene Flow, scripting/API documentation and export remain in place.

---

## 0.4.20 — Authoring Reliability + Outliner / Assets Workflow

This polish pass keeps the complete 0.4.19 feature set intact while tightening the day-to-day authoring workflow. No major subsystem has been removed or replaced.

### Scene Outliner multi-selection

The Scene Outliner now supports normal desktop-style multi-selection:

- **Ctrl / Cmd + click** toggles individual entities.
- **Shift + click** selects a contiguous visible range from the selection anchor.
- **Ctrl / Cmd + Shift + click** adds a range to the current selection.
- The primary entity remains visually distinct and continues to drive the Inspector / Panda viewport selection.
- Right-clicking an already-selected row preserves the group selection.
- Dragging selected rows reparents the selected group.
- Duplicate and Delete operate on the selected group as a **single Undo step**.
- Parent + child selections are normalized so a subtree is not duplicated/deleted twice.

The Panda viewport remains intentionally single-primary-selection for transform gizmos in this pass; multi-selection is an authoring/outliner workflow first rather than a risky transform-system rewrite.

### Create project assets directly from Assets

The Assets pane now has a **Create** menu and a dedicated **Shaders** category. Assets can be created without first adding a scene object/component.

Current direct creation includes:

- **Material** — creates a reusable `.material` asset under `assets/materials/`.
- **GLSL Shader Pair** — creates matching `.vert` / `.frag` files under `assets/shaders/`.
- **Python Script** — creates a reusable `EntityScript` template under `scripts/`.

This keeps scene entities and reusable project resources separate: create the asset first, then assign/apply it where needed.

### Real scene dirty state

The editor now exposes the backend scene dirty state throughout the shell:

- Modified scenes show `*` in the title / scene status.
- The status bar shows **Modified** vs **Saved**.
- New/Open/Scene Flow open/Scene asset open use **Save / Don't Save / Cancel** when the current scene has unsaved changes.
- File → Exit uses the same unsaved-change decision before shutdown.
- Save/Open/New correctly synchronize the dirty state instead of a generic change event immediately marking a freshly saved/opened scene dirty again.

### Undo / Redo reliability

The command stack now reports `can_undo` / `can_redo` to the browser, allowing toolbar/menu state to reflect reality. New/Open clear stale history. No-op Undo/Redo no longer dirties the scene. Group duplicate/delete operations are one coherent command.

### Problems workflow

Project Validation now has a dedicated **Problems** bottom tab rather than only being a Debug text dump.

- Errors and warnings are grouped with severity, entity/component/path context.
- Entity-backed issues can jump to and frame the relevant entity.
- Asset-backed issues can jump to the Assets pane.
- The tab badge reports the current problem count.
- Any authoring change invalidates stale validation results until validation is run again.

### Selection / picking audit

The existing Panda picking priority remains deliberately conservative: transform gizmos win over scene geometry, locked editor entities are skipped, and otherwise the nearest valid visible entity is selected. Terrain sculpt/paint continues to own pointer input only while its explicit authoring mode is active. This pass avoids destabilizing the working terrain/picking fixes while the new Outliner multi-selection stays editor-side.

### Compatibility

Terrain/sculpt/material painting, VFX, Materials/Shaders, HUD/UI, Tasks/Events, Intervals, Render Attributes, Camera Systems, AI/Navigation, AI Behavior, Physics, FSM/Animation, Scene Flow, scripting/API documentation and export remain in place.

---

## 0.4.19 — UI / HUD Runtime QA + Workspace Consistency

This is the second consolidation pass. It does not add a new engine subsystem; it tightens the existing Game UI authoring/runtime path and brings the UI/HUD workspace closer to the common workspace language introduced in 0.4.18.

### UI/HUD authoring polish

The UI palette is now grouped into Layout, Display and Input controls, the design surface has an optional persisted 5% Safe Area guide, disabled-in-Play widgets are marked directly on the WYSIWYG canvas, and the workspace reports authoring/runtime parity warnings instead of silently allowing obviously invalid values.

The Inspector remains a quick-edit surface and now points directly to **Open UI / HUD Workspace** for advanced UI properties, signals and parity checks. This clarifies Inspector-vs-workspace ownership without removing any existing controls.

### DirectGUI runtime parity

Runtime DirectGUI controls now share a consistent text baseline so labels/buttons/checkbox/radio/dropdown/input text align more closely with the browser design surface. `DirectEntry` receives an explicit authored frame and left-aligned text position instead of relying on character-count sizing alone. Sliders explicitly use the horizontal orientation and retain the 0.4.10 no-argument callback fix.

Runtime `Set Text` is now control-aware: Text Input uses `DirectEntry.enterText()`, while Checkbox/Radio preserve their authored selection glyph when their label changes.

### UI validation

The UI/HUD workspace and Project Validation now detect the same common authoring mistakes: invalid slider ranges, out-of-range slider/progress values, empty dropdowns, invalid dropdown selection indexes, missing radio groups and unusably small widgets. The WYSIWYG status bar summarizes outstanding parity warnings.

### Runtime QA template

`project_templates/ui_hud_runtime_qa.pscene` and `scripts/example_ui_hud_runtime_qa.py` provide a compact runtime matrix containing Panel, Label, Button, Checkbox, Progress, Slider, Text Input, Dropdown, Radio and a disabled control. Every interactive control routes to the QA script so Output confirms the DirectGUI callback/Signals path.

### Workspace consistency groundwork

Special-workspace headers, search fields and UI/HUD property surfaces receive the same spacing/focus treatment while preserving the existing themes and layout. This continues the polish rule from 0.4.18: no existing system is removed or rewritten simply for appearance.

---

## 0.4.18 — Workspace / Preview Lifecycle Polish

This begins the consolidation run after the 0.4.x feature expansion. No major subsystem is added and existing editor/runtime features remain in place. The pass concentrates on workspace ownership, preview isolation and reducing state leaks between authoring tools.

### Central viewport context

The Panda viewport runtime now tracks an explicit editor view context: `level`, `vfx` or `material`. Common preview visibility rules live in one coordinator instead of being repeated independently by each workspace. Authored DirectGUI/HUD, editor helpers, navigation debug geometry and Bullet debug display are hidden when a preview context owns the viewport and restored when returning to Level authoring.

This directly fixes the case where authored HUD/UI controls could remain visible over the VFX preview because they live under `aspect2d` rather than under ordinary 3D entity roots.

### Workspace lifecycle registry

The browser-side workspace switch path is split into explicit shell, leave and enter phases. VFX, Material preview and Terrain edit cleanup now happen in the workspace leave lifecycle before the next workspace enters. Viewport visibility is controlled from one `VIEWPORT_WORKSPACES` set instead of being duplicated throughout the switch function.

Rapid duplicate workspace transitions are guarded so a second click cannot interleave preview teardown/startup while the previous transition is still running.

### Preview restoration

VFX and Material preview teardown now return through the shared Level context restoration path. Material preview remains a dedicated render-to-texture scene; VFX keeps its existing preview scene but now receives the same HUD/helper isolation rules.

### Debug visibility

Runtime debug snapshots now expose `viewport_context`, `preview_vfx` and `preview_material`, giving the Debug workspace a reliable source for future subsystem-health UI.

### UI cleanup groundwork

Workspace headers now use a consistent sticky treatment and workspace transitions temporarily block duplicate tab/action input. Preview hosts use explicit isolation so their overlays do not bleed into neighboring workspace layout. This is intentionally groundwork rather than a redesign; the existing visual language and controls are preserved.

---

## 0.4.17 — AI Behavior

This pass completes the current roadmap run by adding a high-level **AI Behavior** layer on top of the existing 0.4.16 Navigation and 0.4.x FSM systems. It is intentionally compositional: Navigation remains responsible for where/how an agent moves, FSM remains responsible for authored state/animation transitions, and AI Behavior decides *why* the entity should idle, patrol, chase, attack, flee or search.

### New AI Behavior component/workspace

Add **AI Behavior** to an entity to author perception and decision settings: target mode (explicit or nearest tag), sight distance, field of view, optional Bullet line-of-sight, think interval, attack distance/cooldown, target memory, aggressive/avoid/scripted disposition, patrol fallback, automatic Navigation driving and FSM state synchronization.

The dedicated **AI Behavior** workspace exposes the full configuration plus a six-state FSM mapping (`Idle`, `Patrol`, `Chase`, `Attack`, `Flee`, `Search`) and named events/signals for target acquired/lost, state changes and attack-ready opportunities.

### Runtime AI API

Entity API now includes:

```python
entity.has_ai_behavior
entity.ai_config
entity.ai_state
entity.ai_target
entity.ai_has_target
entity.ai_last_seen_position
entity.ai_blackboard

entity.ai_set_state("search")
entity.ai_set_target(target)
entity.ai_clear_target()
entity.ai_scan()
entity.ai_think_now()
entity.ai_pause()
entity.ai_resume()

entity.ai_blackboard_get("alert_level", 0)
entity.ai_blackboard_set("alert_level", 2)
```

World API adds:

```python
world.ai_entities
world.ai_find_targets(entity, tag="player", radius=20, fov=120, line_of_sight=True)
world.ai_broadcast("alarm", {"zone": 2}, tag="guard")
```

### Behavior integration

The automatic decision loop can drive an existing Navigation Agent and map its behavior state into an authored FSM on the same entity. The default mapping is:

```text
AI idle   -> FSM Idle
AI patrol -> FSM Patrol
AI chase  -> FSM Chase
AI attack -> FSM Attack
AI flee   -> FSM Flee
AI search -> FSM Search
```

This mapping is editable, and either Navigation automation or FSM synchronization can be disabled independently for script-driven/custom AI.

### Perception and memory

Perception supports range + FOV and optional Bullet raycast line-of-sight. Automatic tag targeting selects the nearest visible tagged entity. When a target leaves perception, the controller retains its last seen position for the configured memory duration and can enter `Search` before finally emitting target-lost and returning to Patrol/Idle.

### Attack-ready is a policy hook, not a combat system

When an aggressive AI reaches attack range, AI Behavior emits the configured `attack_ready` event/signal on its authored cooldown. It deliberately does **not** invent health/damage/combat rules; scripts, Signals, Tasks, Intervals or future game-specific systems decide what an attack actually does.

### Signals 2.0 additions

Signal connections can now invoke:

- AI Set State
- AI Set Target
- AI Clear Target
- AI Think Now

### Validation / documentation / examples

Project Validation now checks invalid AI disposition/target modes, perception values, and warns when Auto Navigation/FSM Sync are enabled without their corresponding components. API Documentation includes the AI state, perception, blackboard and world-query APIs. `project_templates/ai_behavior_demo.pscene` and `scripts/example_ai_behavior.py` demonstrate the complete Navigation + FSM + AI layering.

---

# Panda Editor POC 0.4.16 — Previous Pass

## 0.4.16 — AI / Navigation

This pass adds the navigation foundation after Camera Systems: editor-authored grid navigation surfaces, Terrain-backed path height sampling, Navigation Agents, obstacle carving, A* pathfinding, patrol/chase/flee movement, runtime API, validation, Signals-ready completion events, debug helpers and a dedicated AI / Navigation workspace. The implementation is editor-owned and dependency-free so it remains stable/offline; higher-level AI Behavior/FSM composition remains the next roadmap layer rather than being mixed into pathfinding.


## 0.4.15 — Camera Systems

This pass keeps 0.4.14 as the baseline and adds first-class gameplay Camera Systems without changing the existing editor camera, rendering, terrain, material, physics, task, interval, VFX or HUD systems.

### Camera authoring

The Camera component now supports projection/lens authoring plus four runtime rig modes: `fixed`, `look_at`, `follow` and `orbit`. Follow rigs expose target-local offset, damping and optional target-facing. Orbit rigs expose target, distance, heading, pitch, pitch clamps, distance clamps and damping. New cameras default to the existing fixed behavior, so old scenes remain compatible.

A dedicated **Camera Systems** workspace lists camera entities, edits lens/rig settings, marks the active camera, previews authored lenses in Level Editing and links directly to the runtime Camera API.

### Runtime Camera API

- `entity.has_camera`
- `entity.camera_config`
- `entity.camera_set(name, value)`
- `entity.camera_configure(**settings)`
- `entity.camera_activate(blend=0, ease="easeInOut")`
- `entity.camera_follow(...)`
- `entity.camera_orbit(...)`
- `entity.camera_orbit_input(...)`
- `entity.camera_shake(...)` / `camera_stop_shake()`
- `world.set_active_camera(camera, blend=0, ease="easeInOut")`
- `world.camera_blend_to(camera, duration, ease)`
- `world.camera_shake(...)`

Runtime rig overrides and shake state are discarded on Stop. Follow/orbit/look-at rigs never rewrite the authored Camera transform.

### Camera blending and shake

Camera activation can interpolate from the current rendered view to another authored camera. Blend curves support linear, ease-in, ease-out and ease-in/out. Shake is layered after the rig transform and decays over its duration, so it works with fixed, follow and orbit cameras.

### Signals / Hooks

Signals 2.0 can now target Camera entities with `Camera Activate / Blend`, `Camera Shake` and `Camera Stop Shake` actions.

### Validation and documentation

Project Validation now checks lens ranges, projection types, camera rig names, missing rig targets and orbit distance/pitch ranges. API Documentation and Scripting Quick API include the new Camera Systems surface.


## 0.4.14 — Character Rotation Fix + API Enrichment + Shaders / Rendering

This pass keeps 0.4.13 as the baseline and fixes the Character Controller turning regression before moving into the next roadmap phase.

### Character Controller correction

`entity.character_turn(degrees_per_second)` now passes the authored degrees-per-second value directly to Panda3D Bullet's `setAngularMovement()`. 0.4.13 incorrectly converted the value to radians, reducing `120` to about `2.09` and making turning appear extremely slow. The default input map now also contains `turn_left` (`Q`) and `turn_right` (`R`), so the bundled controller examples work without first creating custom actions.

Additional Character Controller API:

- `entity.character_turn_to(heading, speed=180)`
- `entity.character_face_direction(direction, speed=None)`
- `entity.character_max_slope`
- `entity.character_configure(..., max_slope=..., ghost_sweep=...)`
- Inspector controls for Max Slope and Ghost Sweep

### GLSL Shader component

Entities can now attach a `GLSL Shader` component with project-relative vertex, fragment and optional geometry shader assets. Runtime support includes:

- `entity.has_shader`
- `entity.shader_config`
- `entity.shader_reload()`
- `entity.shader_set_input(name, value)`
- `entity.shader_clear_input(name)`
- `entity.shader_clear()`

Shader inputs accept normal scalar/vector values plus typed texture/entity references. Shader asset paths and typed texture inputs participate in asset reference tracking, rename propagation and project validation.

Bundled shader assets:

- `assets/shaders/basic.vert`
- `assets/shaders/basic.frag`
- `assets/shaders/pulse.vert`
- `assets/shaders/pulse.frag`

A runnable `project_templates/shader_rendering_demo.pscene` and `scripts/example_shader_rendering.py` demonstrate live shader inputs.

### Post-processing / rendering

World / Rendering now exposes Panda CommonFilters-backed authoring controls for:

- Bloom
- Ambient occlusion
- Gamma
- Exposure
- sRGB encode

Runtime API:

- `world.render_pipeline`
- `world.post_process`
- `world.post_process_set(name, enabled=True, **settings)`
- `world.post_process_clear()`

The existing built-in/simplepbr render-pipeline choice, Material/Shader graph groundwork, Render Attributes and Terrain rendering are preserved.

### API Documentation

The API Documentation and Scripting Quick API have been expanded for the corrected Character Controller surface and the new shader/post-processing APIs. Existing API semantics remain unchanged unless this pass explicitly fixes the 0.4.13 angular-unit bug.


## 0.4.13 — Runtime API / Scripting Enrichment

This pass keeps the 0.4.12 editor/runtime systems intact and substantially expands the stable Play Mode scripting surface. API Documentation is updated with each new public method/property.

### Character Controller / Physics

- `entity.character_rotation` / `entity.character_heading`
- `entity.character_rotate()`
- `entity.character_turn(degrees_per_second)` / `character_stop_turn()`
- `entity.character_configure(gravity=..., jump_speed=..., fall_speed=..., max_jump_height=...)`
- `entity.physics_body_type`, `mass`, `friction`, `restitution`
- `entity.apply_torque()` / `apply_torque_impulse()` / `clear_forces()`
- Existing `linear_velocity` and `angular_velocity` are documented together with the new rigid-body controls.

Character angular movement is reset at the start of each runtime frame, matching the existing `character_move()` contract: a controller script writes the desired movement/turn rate each frame rather than leaving stale motion behind. Direct heading/rotation assignment updates the Bullet Character Controller NodePath and visible entity together.

### Transform / Entity utilities

- explicit `world_position` and `world_rotation`
- `forward`, `right`, `up` basis vectors
- `look_at()`, `distance_to()`, `direction_to()`
- `component_names`, `has_component()`
- tags through `tags` / `has_tag()`
- hierarchy through `parent` / `children`
- runtime `visible` inspection

The long-standing `entity.position` behavior is preserved for compatibility; scripts that need unambiguous world coordinates can now use `world_position`.

### World discovery / runtime control

- `world.find_all(name=None, component=None, tag=None)`
- `world.entities_with_component()` / `entities_with_tag()` / `has_entity()`
- `world.active_camera` / `world.set_active_camera()`
- `world.set_gravity()` alongside `world.gravity`
- Runtime clock/entity collection documented through `world.time`, `world.dt`, `world.entities`.

### Existing subsystem APIs enriched

- Light: `has_light`, `light_enabled`, `light_set_intensity()`
- Audio: `audio_loop`, `audio_rate`
- Animation: `animation_num_frames()`, `animation_duration()`
- Tasks: entity-scoped `task_pause()`, `task_resume()`, `task_info()`
- Intervals: `interval_info()`, `interval_set_rate()`

See `scripts/example_enhanced_runtime_api.py` for a practical Character Controller + discovery/facing example.

---

## 0.4.12 — Graceful Exit + Tasks/Events Enrichment + Intervals + Render Attributes

This pass continues directly from the working 0.4.11 terrain/material/API repair. Existing Terrain sculpt/material painting, Materials/Shaders preview and graph, HUD/UI, FSM/Animation, VFX, Scene Flow, physics, assets and export behavior remain in place.

### Graceful application shutdown

- Added **File → Exit Panda Editor** and a bridge-level `request_exit()` path.
- Window closing/closed events now enter one idempotent shutdown routine before WebView2 disposal races can continue emitting UI events.
- Active Windows game export/build work is cancelled during shutdown.
- The Panda viewport receives an orderly `stop` command first, is allowed time to stop Play Mode/audio/material preview and destroy Panda cleanly, and is force-terminated only as a fallback.
- Multiprocessing queues/message-pump shutdown no longer waits indefinitely on queue feeder threads.
- Process-level `atexit` protection uses the same shutdown routine.

### Tasks / Events enrichment

The existing managed task/event system remains intact and gains more runtime control rather than being replaced:

- Finite authored tasks can now emit a **Finished Event** and/or **Finished Signal**.
- `world.task_info(name)` exposes live cadence/repeat/owner/time-until information.
- `world.task_pause(name)` / `world.task_resume(name)` preserve remaining delay instead of resetting cadence.
- Signals 2.0 can now target authored task actions: **Task Start**, **Task Stop**, **Task Trigger**.
- The Tasks / Events workspace exposes finished-event/signal fields alongside the existing Once / Interval / Every Frame modes.

### First-class Panda3D Intervals

A new **Intervals** component and workspace authors finite/timed actions using Panda3D's interval system.

- Composition: **Sequence** or **Parallel**.
- Steps: Wait, Move, Rotate, Scale, Event, Signal, Animation and Sound.
- Per-transform-step blend: Linear, Ease In, Ease Out, Ease In/Out.
- Interval-level Play Rate, Autostart, Loop, Finished Event and Finished Signal.
- Play/Pause in Panda Editor also pauses/resumes live intervals.
- Stop Play tears intervals down without firing their remaining completion callbacks.
- Signals 2.0 actions: Interval Start, Pause, Resume and Finish.
- Runtime entity API: `interval_names`, `interval_start()`, `interval_pause()`, `interval_resume()`, `interval_finish()`, `interval_is_playing()`.
- Runtime world API: `world.interval_sequence()` and `world.interval_parallel()` for script-created interval groups.

### Render Attributes

Entities can now receive an attachable **Render Attributes** component. It is intentionally an editor abstraction over useful Panda NodePath render state rather than a dump of every low-level attribute.

Current authored/runtime controls:

- Depth Test / Depth Write
- Cull: Inherit / Back / Front / None
- Transparency: Inherit / None / Alpha / Binary / Multisample
- Color Scale RGBA
- Render Bin + Sort
- Depth Offset
- Point-eye Billboard
- Lighting Off
- Shader Off

Runtime API:

- `entity.has_render_attributes`
- `entity.render_attributes`
- `entity.render_set(name, value)` — Play-session-only override
- `entity.render_reset()` — clear live overrides and return to inherited/default state

World / Rendering now reports Render Attribute usage alongside the existing LOD/Terrain performance information. Project Validation checks authored culling/transparency/color-scale values.

### API / validation / example content

- API Documentation has entries for the new task controls, Interval authoring/runtime controls and Render Attributes.
- Scripting Quick API includes `task_info()`, `interval_start()` and `render_set()`.
- Project Validation understands Interval composition/step types/durations and Render Attributes enum/value shape.
- Added `scripts/example_intervals_render_attributes.py`.
- Added `project_templates/intervals_render_attributes_demo.pscene` demonstrating a finite task feeding an authored interval and runtime-only render-state changes.

---

## 0.4.10 — UI/HUD Runtime Fixes + True Offscreen Material Preview + Material Browser/Node Wiring

This pass is constrained to the problems found while testing 0.4.9. Existing Terrain sculpt/paint, Tasks/Events, FSM, VFX, Scene Flow and other editor systems remain in place.

### UI / HUD
- Fixed `DirectSlider` callback handling: Panda calls the slider command with no value argument; the runtime now reads `slider['value']` from the widget.
- Slider geometry now uses explicit authored frame/thumb sizes instead of scaling the default widget geometry.
- Dropdowns now use explicit authored frame sizing, text placement, marker placement and popup item styling.
- Runtime `Set Value` respects slider min/max rather than the Progress range field.

### Material preview
The material preview now follows Panda3D's render-to-texture pattern: a hidden `GraphicsBuffer`, a dedicated camera and a completely separate preview scene graph. The Level scene is never part of that camera's scene tree. The resulting texture is displayed inside the embedded material-preview viewport. Only the selected Sphere/Cube/Plane and preview lights exist in the preview scene.

### Material browser
The workspace left pane now browses Scene Materials, reusable Material presets, Textures and Shader assets. Material presets/textures can be selected for isolated preview without mutating the scene; they are only applied when the user explicitly chooses Apply/Use.

### Node links
Connection interaction no longer relies on pointer capture returning the destination socket. Drag release resolves the actual element under the cursor, and click-to-connect is also supported as a fallback. Typed socket compatibility and one-input/one-link replacement remain enforced.

---

# Panda Editor POC 0.4.9

## Terrain / Material stability pass

- Added an isolated live **Material / Shader preview viewport** with Sphere/Cube/Plane meshes, Studio/Neutral/Dark lighting, orbit/zoom/focus controls and project render-pipeline awareness.
- Material graph Principled/Texture edits can now preview without leaving the Materials / Shaders workspace; Apply Graph still commits to the scene Material component.
- Terrain material painting now updates a retained in-memory Panda `PNMImage`/`Texture` during a stroke and writes the RGBA splat PNG once on stroke end. It no longer rebuilds the entire GeoMipTerrain on every paint sample.
- Terrain brush mouse-move events are coalesced to animation frames in the UI.
- Height sculpt PNG writes / GeoMip refreshes are throttled during a drag and always flushed on mouse-up, greatly reducing high-resolution sculpt hitching while preserving Undo/Redo.
- Terrain authoring resolution and GeoMip runtime LOD remain independent controls. Auto Flatten remains **Off** by default.

# Panda Editor POC 0.4.9

## 0.4.9 Terrain Paint Fix + High-Detail Heightfields + Working Material Graph Subset

- Fixed live terrain material painting: mutable splat PNGs now bypass Panda's TexturePool cache, and splat UVs are derived directly from GeoMipTerrain vertex coordinates with the correct PNG-Y orientation.
- Terrain generation now defaults to 257×257 and exposes 65/129/257/513/1025/2049 authoring resolutions. Existing editable heightfields can be non-destructively refined to a higher resolution using bilinear resampling into a new project asset.
- The Terrain workspace reports approximate world-units per quad so sculpt resolution is visible rather than implicit.
- Material graph now has a working compile subset: Principled Base Color/Metallic/Roughness/Emission and Texture target nodes can be applied to the live Material component.
- PBR texture assignment now uses Panda semantic TextureStages (BaseColor/Modulate, MetalRoughness/Selector, Normals/Normal, Emission/Emission), matching simplepbr's documented contract.
- simplepbr initialization requests normal, emission and occlusion-map support where the installed version accepts those options.


## 0.4.9 Terrain Materials + Material/Shader Foundation + LOD/Culling

This pass continues directly from the working 0.4.5 terrain-sculpt coordinate fix. Existing scene editing, picking, sculpting, Tasks / Events, FSM, VFX, UI/HUD, physics and runtime APIs remain in place.

### Terrain authoring

- New Terrain defaults use **Auto Flatten: Off**. Light / Medium / Strong remain available as explicit GeoMip performance options.
- Terrain material painting uses an editable RGBA splat map. Channels R/G/B/A represent four independently configured terrain layers.
- The Terrain workspace can create a splat map, configure four layer textures/tints/roughness/metallic metadata, and paint Layer 1–4 directly in the Level viewport using the existing Radius / Strength / Falloff brush system.
- Material paint strokes are grouped into Undo/Redo commands just like sculpt strokes.
- Material painting is independent from destructive heightfield sculpt format restrictions: imported heightfields may use a separately generated Panda Editor splat map.
- Runtime terrain rendering includes a four-layer splat shader when Material Painting is enabled.

### Materials / Shaders foundation

A new **Materials / Shaders** workspace introduces a serializable node-graph contract inspired by Blender-style material authoring. The graph starts as `Principled Surface -> Material Output`, supports draggable/add/remove nodes and persistent link data, while the existing stable Material component remains the runtime authority until a later shader-graph compiler pass. This deliberately lays the editor/data foundation without replacing working material behavior.

The optional baseline PBR integration is **panda3d-simplepbr**. Project World / Rendering settings can select Panda Built-in or simplepbr. Built-in remains the safe default. RenderPipeline is not bundled as the baseline because it is a substantially broader deferred rendering framework and is better suited to a later advanced rendering profile.

### Performance / Culling / LOD

- World / Rendering now has a Performance / Culling / LOD section.
- Normal entities can receive an attachable **LOD / Culling** component with Enabled, Near, Far, Fade Band (reserved for the later transition implementation) and Scope metadata.
- The current runtime implementation performs camera-distance whole-entity culling. The serialized scope is designed so later passes can add component/representation LOD without changing the component contract.
- Project Validation checks LOD distance ranges and Terrain material/splat resources.
- Runtime API documentation includes `entity.has_lod`, `entity.lod_config`, `entity.lod_set()`, Terrain material authoring, material graph authoring and the simplepbr project pipeline.

### PBR dependency

`requirements.txt` now includes `panda3d-simplepbr>=0.13.1`. If simplepbr cannot initialize, the runtime logs the problem and falls back to the built-in rendering path.

---

# Panda Editor POC 0.4.5 — previous release

## 0.4.5 Terrain sculpt coordinate hotfix

This is a constrained patch on top of 0.4.4. The Terrain brush ray/hit path introduced in 0.4.4 was correct, but the authoring writer mapped Terrain-local Y directly to raw PNG row Y. PNG scanlines run in the opposite vertical direction to the Terrain/PNM coordinate used by the visible GeoMip surface, so sculpt strokes were written to a vertically mirrored location.

0.4.5 mirrors **only the raw PNG authoring row** before applying Raise, Lower, Smooth or Flatten. Brush cursor placement, analytic terrain hit testing, world-space radius, strength/falloff, Undo/Redo, object picking, Tasks / Events and every other 0.4.4 subsystem remain unchanged.

---


## 0.4.4 Terrain sculpt fix + Tasks / Events

This pass continues directly from 0.4.3 and changes only the terrain sculpt authoring path plus the next planned runtime/editor subsystem.

### Terrain sculpting fix

The 0.4.3 brush depended on the Panda collision traverser receiving a usable surface entry from the adaptive GeoMipTerrain render geometry. That is not reliable across the generated LOD mesh, so the editor could show a valid Terrain component while Raise/Lower/Smooth/Flatten emitted no usable stroke.

0.4.4 removes that dependency for sculpting. The brush now extrudes the camera ray, transforms it into the selected Terrain entity's local space, clips the ray to the authored heightfield footprint, samples the actual height data, finds the first surface crossing and binary-refines the hit. The brush cursor and stroke use the same terrain hit path. Normal object selection remains separate from this sculpt-specific hit test.

The existing generated-heightfield brush implementation, PNG mutation, terrain refresh and grouped Undo/Redo command behavior are retained.

### Tasks / Events

A new **Tasks / Events** workspace and `tasks_events` entity component provide managed runtime flow without requiring scripts to hand-build every timer in `on_update()`. Authored tasks support `Once`, `Interval` and `Every Frame` modes, initial delay, repeat count (`-1` = indefinite), autostart, named event output and optional Signals 2.0 output. Custom event hooks route named runtime events into an entity's existing `on_event()` callback and/or a Signals 2.0 output.

Runtime API additions:

```python
world.call_later(delay, event_name, payload=None, target=None, name=None)
world.task_every(interval, event_name, payload=None, target=None, name=None, repeat=-1)
world.task_cancel(name)
world.task_exists(name)
world.tasks
world.event_send(event_name, payload=None, target=None)

entity.task_names
entity.task_start(name)
entity.task_stop(name)
entity.task_trigger(name, payload=None)
entity.event_send(event_name, payload=None)
```

Managed timers use a pause-aware runtime task clock. `on_update()` remains the preferred path for continuous movement/simulation; Tasks / Events are aimed at delayed actions, cadence-driven logic, orchestration and event-driven behavior.

Included examples:

- `scripts/example_tasks_events.py`
- `project_templates/tasks_events_demo.pscene`

Project Validation now checks duplicate/unnamed managed tasks, unsupported task modes, invalid interval timing and duplicate authored custom event hooks. API Documentation includes the new task/event runtime surface.

---


## 0.4.3 Terrain editor refinement

This pass keeps the 0.4.2 Terrain runtime intact and improves authoring/picking only.

### Interactive generated-heightfield sculpting

Editor-generated 8-bit grayscale PNG heightfields can now be edited directly in the normal Level viewport. Select a Terrain entity and choose **Sculpt Terrain**, or use **Sculpt in Level View** from the Terrain workspace.

The terrain brush toolbar provides:

- **Raise** — build hills and ridges.
- **Lower** — carve/depress terrain.
- **Smooth** — soften abrupt height transitions.
- **Flatten** — level toward the height sampled by the first point of the stroke.
- **Radius** — world-space brush radius.
- **Strength** — stroke influence.
- **Falloff** — edge softness.

The viewport displays a live brush ring over the selected terrain. A mouse drag is committed as one command, so normal Undo/Redo restores the heightfield before/after that stroke. Runtime Terrain scripting remains the same as 0.4.2; authoring edits modify the project heightfield asset and are intentionally separate from Play-mode runtime configuration.

Imported heightfields remain supported for rendering. Destructive sculpting is deliberately limited to Panda Editor generated 8-bit grayscale PNGs in this pass so externally-authored formats are not silently rewritten.

### Picking refinement

Generated Terrain no longer uses one terrain-sized AABB as its editor pick proxy. The editor now marks the actual generated terrain GeomNodes as pickable and ray-tests the visible triangles. This prevents a broad terrain bounds box from masking small objects such as the default cube when they sit on or above the terrain. Model and primitive picking behavior is otherwise unchanged.

### Reference direction

The workflow is inspired by the useful editor-facing ideas in Zylann's Godot terrain work: raise/carve/smooth brushes, configurable brush influence, and undoable terrain authoring. The implementation here remains Panda Editor/Panda3D specific and continues using GeoMipTerrain rather than copying Godot internals.

## 0.4.2 Terrain pass

This pass continues directly from the 0.4.1 FSM / Animation + API coverage baseline. It adds a dedicated Terrain system without replacing or restructuring the existing editor/runtime systems.

- Dedicated **Terrain** workspace and Terrain entity/component.
- Panda3D `GeoMipTerrain` heightfield generation with authored world size and height scale.
- Workspace heightfield import plus generated **Flat** and **Rolling** 129×129 heightfields.
- LOD controls: block size, world-space near/far distances, minimum LOD, bruteforce, border stitching and auto-flatten mode.
- Optional static Bullet triangle-mesh collision generated from terrain geometry in Play Mode.
- Runtime API: `has_terrain`, `terrain_config`, `terrain_get()`, `terrain_set()`, `terrain_configure()`, `terrain_height()`, `terrain_normal()` and `terrain_regenerate()`.
- Terrain entries are searchable in **API Documentation** and linked from the Scripting workspace.
- Project Validation checks missing heightfields, invalid world size and suspicious block sizes.
- `project_templates/terrain_demo.pscene` and `scripts/example_terrain_controller.py` demonstrate the system.
- Existing Material components also apply to generated terrain geometry.

---


**0.4.1** enriches workspace parity: UI/HUD now exposes its relevant component and signal controls directly, VFX/Particles gains a real live Panda3D authoring preview plus transform tools, and Lighting gains direct signal/hook targeting and test controls.

0.4.1 stabilizes and enriches the **Game UI / HUD authoring workflow** while preserving the scene editor, scripting, physics, audio, materials, animation, standalone runtime and Windows export pipeline from previous builds.

## Game UI / HUD

Screen-space UI is stored declaratively in `.pscene` under an entity `ui` component and rendered through Panda3D DirectGUI / `aspect2d`. UI-only entities are selected from the Outliner rather than 3D picking.

Supported UI entity types:

- UI Canvas
- UI Panel
- UI Label
- UI Image
- UI Button

The Add menu and Add Component menu both expose these types. A dedicated **UI / HUD** workspace provides a scene-wide list and quick creation workflow, while detailed settings remain in the normal Inspector.

### Layout

UI layout uses:

- named screen anchors: center, top/bottom/left/right and corners
- pixel offsets
- pixel width/height
- text and font size
- frame/tint and text colors
- image asset path
- button event name
- visibility / enabled state

Pixel layout is converted to Panda3D `aspect2d` coordinates at runtime and rebuilt when the viewport changes size.

### Runtime buttons and events

UI Button interaction is disabled while authoring and enabled during Play Mode / standalone runtime. Buttons broadcast their configured event name (default `ui_click`) through the existing Python `on_event()` system.

### Python API

The API Documentation workspace now includes the new Game UI category:

```python
entity.has_ui
entity.ui_text
entity.ui_show()
entity.ui_hide()
entity.ui_set_color(r, g, b, a=1.0)
```

Example:

```python
def on_event(self, entity, world, event_name, payload):
    if event_name == "add_point":
        label = world.find("Score Label")
        if label:
            label.ui_text = "Score: 1"
```

Runtime UI changes are discarded when Play Mode stops, keeping the authoring scene canonical.

## UI image asset workflow

A selected texture can be assigned directly to a selected **UI Image** entity from the Asset Manager. Dragging a texture onto a UI Image in the Outliner also assigns the UI image rather than creating a Material component. UI image paths participate in asset reference validation, rename repair and managed-folder moves.

## Included demo

Open:

```text
project_templates/ui_hud_demo.pscene
```

Then press Play. The demo contains a panel, score label and button. Clicking **Add Point** broadcasts `add_point`; `scripts/example_ui_hud.py` updates the Score Label through the runtime UI API.

## Existing systems retained

0.3.8 keeps the existing Asset Manager thumbnails/filter-aware folders, API Docs syntax highlighting, Actor/Animation, Materials, Bullet physics, scripting, audio, prefabs, Debug/PStats tools, standalone runtime and Windows build/package support.


## 0.4.1 stabilization notes

- Asset Manager now switches between List, Compact Icons and Thumbnails; the choice persists locally.
- UI / HUD workspace now includes a 1280×720 visual design surface with selection, drag placement, snap/grid, zoom, resize, duplicate/delete, visibility and quick exact properties.
- API Documentation code blocks no longer inherit the fullscreen script-editor overlay CSS.
- WebView2 shutdown is guarded before native disposal so background viewport/build events stop trying to evaluate JavaScript after the window begins closing.
- The embedded Panda child requests non-foreground creation to reduce unnecessary focus forcing on Windows.


## 0.4.1
- Selectable/copyable Output pane.
- Addressable UI signal/hook connections with target entity + action.
- Script print() routed through editor Output during Play Mode.
- WebView2 shutdown race hardened.
- VFX / Particles workspace and Particle Emitter runtime component/API.


## 0.4.1 refinement
- Lighting workspace broadened to World / Rendering with global background, skybox model, fog, fallback ambient/sun and shader-auto project settings.
- VFX workspace now uses an isolated Panda3D preview scene instead of the authored game scene, with orbit/pan/zoom/focus controls and normal mouse navigation.
- UI/HUD signal target/action dropdowns no longer rerender/reset while choosing values.
- Compact Asset view now uses a dense grid without large flex gaps.

## 0.4.1 — Scene / Game Flow + Signals 2.0

This pass establishes runtime scene transitions and broadens the signal layer beyond UI-button-only wiring.

### Scene Flow
- New Scene Flow workspace discovers project `.pscene` files.
- Set any project scene as Startup Scene without opening it first.
- Open a scene for authoring or launch a selected scene in the standalone runtime.
- Runtime API: `world.load_scene(path)`, `world.restart_scene()`, `world.quit_game()`.
- Signal actions: `scene_load`, `scene_restart`, `game_quit`.
- Scene changes are queued until the current update callback completes.

### Signals 2.0
- New `Signals / Hooks` component for script-emitted named outputs.
- Runtime API: `entity.signal(name, payload)` and `world.signal(sender, name, payload)`.
- Signals can target scripts, visibility, UI text/value, particles, lights, audio, animation, or Scene Flow.
- UI Slider, Text Input, Dropdown, Radio, Button and Checkbox participate as signal sources.

### HUD / UI expansion
- Added Slider, Text Input, Dropdown and Radio controls.
- Existing Canvas, Panel, Label, Image, Button, Checkbox and Progress remain supported.
- New interactive controls use the same reference-resolution WYSIWYG designer, anchors and targeted hook system.

### VFX enrichment
- Duration / finite emitters with optional looping.
- `finished` signal when a finite emitter drains.
- Start rotation and spin rate.
- Local-space vs world-space particles.
- Alpha or additive blending.
- Existing Point/Sphere/Box/Ring/Cone, speed/lifetime variation, gravity, drag, size/color over life and isolated preview remain intact.

## Roadmap after 0.4.1

The next phase is aligned to the Panda3D Programming Manual and will be implemented in focused passes rather than as disconnected features:

1. **FSM + Animation integration** — editor-authored state machines, animation state actions/transitions, signal conditions.
2. **Terrain** — heightfield authoring/import, collision/nav integration, LOD/tessellation direction.
3. **Tasks / Events** — managed runtime tasks, do-later timers, event sources and signal bridges.
4. **Intervals** — lerps, Actor/Sound intervals, Sequences/Parallels, motion paths and editor timelines.
5. **Render Attributes** — explicit render-state controls such as depth, culling, transparency, color, bin/order, billboard/compass effects and inherited state.
6. **Shaders / Rendering** — GLSL assets, shader inputs, post-processing, PBR direction and later graph-based material/shader authoring.
7. **Camera Systems** — richer lenses, camera rigs/controllers, follow/orbit/shake, camera switching and transition support.
8. **AI / Navigation** — navigation surfaces/navmesh or grid generation, pathfinding, obstacles, agents, patrol/chase APIs, then FSM/behavior tooling on top.
9. **Prefab 2.0 / persistence** — linked prefab overrides and persistent game-state/entity strategy across scene transitions.

The Panda3D Programming Manual is treated as a coverage checklist for engine capabilities; the Reference API remains the source for exact class/method details.

## 0.4.1 - FSM / Animation + API coverage pass

- Added a data-driven FSM component and dedicated FSM / Animation workspace.
- FSM states can map directly to Panda Actor clips with per-state loop/rate settings.
- Runtime FSM API: `has_fsm`, `fsm_state`, `fsm_states`, `fsm_request()`, `fsm_send()`.
- Added animation inspection helpers: `animation_is_playing()`, `animation_frame()`, `animation_set_rate()`.
- Expanded VFX runtime API to expose the full authored emitter configuration through `particle_config`, `particles_get()`, `particles_set()` and `particles_configure(**settings)` plus convenience properties.
- API Documentation is updated in the same pass and is now treated as part of feature completeness.
- Project Validation now checks FSM initial states, transitions and animation mappings.


## 0.4.9 — Terrain Paint + Material Graph Refinement

- Terrain paint authoring now uses a deterministic CPU-composited live albedo texture driven by the RGBA splat map. The splat/layer data remains authoritative for later PBR terrain shader work.
- Live painting recomposes only the affected brush region; no GeoMip rebuild is required for paint feedback.
- Materials / Shaders graph now has typed input/output sockets, interactive links, SVG node icons, persisted connections, and a useful compilation subset.
- Material preview uses a dedicated camera mask and contains only the chosen Sphere/Cube/Plane preview mesh with preview-only lighting. No Level terrain, floor, gizmos or scene objects are rendered in the preview.

## 0.4.26 — Advanced PBR option + Spot Lights

- Added optional `panda3d-complexpbr` rendering profile alongside Panda Built-in and simplepbr. complexpbr is intended as the advanced IBL/reflection profile and requires GLSL 4.30+ hardware. Optional complexpbr screenspace effects are kept separate from Panda CommonFilters.
- Added first-class Spot Light entities/components with range, FOV, focus exponent, direction from entity rotation, optional shadow request, editor cone helper, World/Rendering authoring and project validation.
- Point lights now also pass max-distance information to Panda when supported; light shadow requests are available without changing the default (off).


## 0.4.26 — Material / Texturing Enrichment

Material components now expose shared UV texture transforms and sampling controls: Repeat/Scale U/V, Offset U/V, rotation, U/V wrap modes, min/mag filtering and anisotropic filtering. The same transform is applied to BaseColor, Metal/Roughness, Normal and Emission semantic texture stages so PBR maps stay registered. The Inspector and Materials / Shaders workspace both expose these settings, material presets persist them, Project Validation checks them, and Play scripts can use `entity.material_config`, `entity.material_configure()` and `entity.material_set_texture_transform()`.
