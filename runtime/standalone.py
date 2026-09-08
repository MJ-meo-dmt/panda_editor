from __future__ import annotations

import copy
import traceback
from pathlib import Path

from panda3d.core import AmbientLight, DirectionalLight, PerspectiveLens, Vec4, loadPrcFileData
from direct.showbase.ShowBase import ShowBase

from editor.config import ROOT
from editor.project_settings import ProjectSettings
from engine.panda_process import PandaProcessRuntime
from scene.serialization import load_scene


class _NullQueue:
    def put(self, _value) -> None:
        pass


class StandaloneGameRuntime(PandaProcessRuntime):
    """Standalone game host using the same component/script/physics runtime as Play Mode.

    No pywebview, native embedding, Outliner, Inspector, editor picker or editor helpers
    are created here.  The inherited runtime component builders are intentionally shared
    with editor Play Mode so behavior does not diverge between testing and standalone.
    """

    def __init__(self, scene_path: str | Path, settings: ProjectSettings | None = None) -> None:
        super().__init__(0, _NullQueue(), _NullQueue())
        self.scene_path = Path(scene_path).resolve()
        self._standalone_game = True
        self.settings_obj = settings or ProjectSettings.load()
        self.project_settings = self.settings_obj.to_dict()
        self.rect = (0, 0, int(self.settings_obj.game_window_width), int(self.settings_obj.game_window_height))

    def log(self, message: str) -> None:
        print(message, flush=True)

    def event(self, name: str, **payload) -> None:
        if name == 'play_state_changed':
            self.log(f'Runtime state: {payload.get("state", "unknown")}')

    def _configure_window(self) -> None:
        title = self.settings_obj.game_window_title or self.scene_path.stem
        loadPrcFileData('', f'window-title {title}')
        loadPrcFileData('', f'win-size {int(self.settings_obj.game_window_width)} {int(self.settings_obj.game_window_height)}')
        loadPrcFileData('', 'fullscreen true' if self.settings_obj.game_fullscreen else 'fullscreen false')
        loadPrcFileData('', 'show-frame-rate-meter false')

    def run_game(self) -> None:
        if not self.scene_path.is_file():
            raise FileNotFoundError(f'Scene does not exist: {self.scene_path}')
        try:
            if ROOT.resolve() not in self.scene_path.parents and self.scene_path != ROOT.resolve():
                self.log(f'Warning: scene is outside project root: {self.scene_path}')
        except Exception:
            pass

        scene = load_scene(self.scene_path)
        try:self.current_runtime_scene = str(self.scene_path.relative_to(ROOT.resolve())).replace('\\','/')
        except Exception:self.current_runtime_scene = self.scene_path.name
        entities = [copy.deepcopy(e.to_dict()) for e in scene.entities.values()]
        self._configure_window()

        self.base = ShowBase()
        self.base.disableMouse()
        self.base.render.setShaderAuto()
        self.base.setBackgroundColor(0.028, 0.036, 0.048, 1)

        # World / Rendering project settings provide the shared environment baseline.
        ambient = AmbientLight('runtimeFallbackAmbient')
        ambient.setColor(Vec4(0.38, 0.41, 0.46, 1))
        self.editor_ambient_np = self.base.render.attachNewNode(ambient)
        self.base.render.setLight(self.editor_ambient_np)
        sun = DirectionalLight('runtimeFallbackSun')
        sun.setColor(Vec4(0.94, 0.92, 0.86, 1))
        sun_np = self.base.render.attachNewNode(sun)
        sun_np.setHpr(-35, -55, 0)
        self.editor_sun_np = sun_np
        self.base.render.setLight(sun_np)
        self._apply_world_settings()

        lens = PerspectiveLens()
        lens.setFov(60)
        lens.setAspectRatio(max(0.1, self.rect[2] / max(1, self.rect[3])))
        lens.setNearFar(0.1, 5000)
        self.base.cam.node().setLens(lens)
        self.camera_target.set(0, 0, 1)
        self.camera_distance = 18.5
        self.camera_heading = -32.0
        self.camera_pitch = 27.0
        self._apply_editor_camera()  # fallback only when a scene has no active camera

        # Play update is the same method used by the embedded editor runtime.
        self.base.taskMgr.add(self._play_update_task, 'gameRuntimeUpdate')
        settings = dict(self.project_settings); settings['_current_scene']=self.current_runtime_scene
        self._start_play(entities, settings)
        self.log(f'Standalone Runtime: {self.scene_path.name} | {len(entities)} entities')
        if not self.play_camera_id:
            self.log('Standalone Runtime: no active Camera; using fallback runtime camera.')

        try:
            self.base.run()
        finally:
            try:
                if self.play_mode:
                    self._stop_play()
            except Exception:
                self.log('Runtime shutdown error:\n' + traceback.format_exc())
            try:
                self.base.destroy()
            except Exception:
                pass


def resolve_startup_scene(scene_arg: str | Path | None = None, settings: ProjectSettings | None = None) -> Path:
    settings = settings or ProjectSettings.load()
    if scene_arg:
        candidate = Path(scene_arg)
        return candidate.resolve() if candidate.is_absolute() else (ROOT / candidate).resolve()
    rel = str(settings.startup_scene or '').strip()
    if not rel:
        raise RuntimeError('No startup scene configured. Set one in Project Settings or pass a .pscene path.')
    return (ROOT / rel).resolve()


def run_standalone_game(scene_arg: str | Path | None = None) -> None:
    settings = ProjectSettings.load()
    scene_path = resolve_startup_scene(scene_arg, settings)
    StandaloneGameRuntime(scene_path, settings).run_game()
