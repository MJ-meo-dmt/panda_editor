# Panda Editor distribution foundation — 0.4.8

The editor now includes an initial Panda3D `build_apps` configuration. This is a packaging foundation, not yet the final release pipeline.

## Development build

From the project root:

```bat
distribution\build_editor.bat
```

or:

```bat
venv\Scripts\python.exe distribution\setup_editor.py build_apps
```

The configuration explicitly includes Panda3D's OpenGL renderer and OpenAL audio plug-in. `p3ffmpeg` is also included for additional media formats.

## Why console mode first

The first packaging pass intentionally uses `console_apps`. Startup, native-window embedding, multiprocessing and plug-in errors remain visible while the packaging path is being proven. Once the packaged editor is stable this can move to `gui_apps` while retaining the configured output log.

## Current scope

This packages the **editor**. A later export/build pipeline should generate a smaller standalone game/player package from the active project instead of shipping editor UI/tooling with the game.


## Game export (0.4.1)

Use the editor Export workspace for Windows x64 game builds. It generates `.panda_export/setup_game.py` plus a game-only requirements file and invokes Panda3D `build_apps` asynchronously.


## Game packaging (0.4.1)

The Export workspace can now run Panda3D `bdist_apps` for `win_amd64`. ZIP requires no external installer tooling. NSIS requires `makensis.exe` on PATH. Folder builds remain available separately through `build_apps`.
