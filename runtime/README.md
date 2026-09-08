# Standalone Runtime

`runtime/standalone.py` is the first editor-independent game host.

It deliberately reuses `PandaProcessRuntime`'s component builders and runtime APIs so editor Play Mode and standalone execution share the same code for:

- scene entity/component construction
- Python `EntityScript` lifecycle
- Input Map/action state
- Bullet rigid bodies, triggers, character controllers and raycasts
- audio sources and 3D audio
- active Camera selection
- model/GLB loading and project-relative resources

The standalone host does **not** create pywebview, editor panels, selection picking, gizmos, grids, Outliner/Inspector state or editor IPC.

## Direct usage

```bat
run_game.bat project_templates\character_controller_demo.pscene
```

Or configure `startup_scene` in `project_settings.json` and run:

```bat
run_game.bat
```

This module is the foundation for the Windows `build_apps` export pipeline planned for the next pass.

## 0.3.7 Actor / Animation

Entities with a Model + Animation component are loaded through Panda3D `Actor`.  Embedded animation names are discovered using `getAnimNames()`.  Runtime scripts can play/loop/stop/pose clips through the `RuntimeEntity` animation API.  The same path is used by Play Mode and standalone builds.

## 0.3.9 Game UI / HUD

The shared runtime now builds `.pscene` `ui` components through Panda3D DirectGUI / `aspect2d`. This path is shared by editor Play Mode and standalone/exported games. UI Buttons broadcast runtime script events; RuntimeEntity exposes text/visibility/color helpers.


## 0.4.23 Input / development camera

The shared Play/standalone runtime exposes mapped actions plus direct keyboard/mouse held and edge states. `scripts/example_fly_camera.py` demonstrates a Fixed Camera controlled with WASD, Space/C, Shift and captured mouse-look. Direct edge helpers (`key_pressed`, `key_released`, `mouse_pressed`, `mouse_released`) are available for capture/toggle/debug controls, and `mouse_captured` reports current pointer ownership. Captured delta uses centre-relative window-pointer sampling with warp-frame suppression/dead-zone handling for stable Windows free-look.

## 0.4.25 editor-only rendering note

Editor grids, gizmos, helper wireframes and preview guides are authoring-only render state. Runtime/game lights and shaders remain unchanged; the editor now explicitly isolates those helpers from authored render state.
