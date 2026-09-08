from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

from editor.config import ROOT

PROJECT_SETTINGS_PATH = ROOT / 'project_settings.json'


def _default_layers() -> list[str]:
    names = ['Default', 'Player', 'Enemy', 'Interactable', 'Trigger', 'Projectile']
    return names + [f'Layer {i}' for i in range(len(names), 32)]


def _default_actions() -> dict[str, list[str]]:
    return {
        'move_forward': ['w', 'up'],
        'move_backward': ['s', 'down'],
        'move_left': ['a', 'left'],
        'move_right': ['d', 'right'],
        'jump': ['space'],
        'interact': ['e'],
        'sprint': ['shift'],
        'turn_left': ['q'],
        'turn_right': ['r'],
    }


@dataclass
class ProjectSettings:
    gravity: list[float] = field(default_factory=lambda: [0.0, 0.0, -9.81])
    collision_layers: list[str] = field(default_factory=_default_layers)
    input_actions: dict[str, list[str]] = field(default_factory=_default_actions)
    audio_master_volume: float = 1.0
    audio_sfx_volume: float = 1.0
    audio_music_volume: float = 0.85
    startup_scene: str = 'project_templates/character_controller_demo.pscene'
    game_window_title: str = 'Panda3D Game'
    game_window_width: int = 1280
    game_window_height: int = 720
    game_fullscreen: bool = False
    world_background_color: list[float] = field(default_factory=lambda: [0.028, 0.036, 0.048, 1.0])
    world_ambient_color: list[float] = field(default_factory=lambda: [0.38, 0.41, 0.46, 1.0])
    world_ambient_intensity: float = 1.0
    world_sun_enabled: bool = True
    world_sun_color: list[float] = field(default_factory=lambda: [0.94, 0.92, 0.86, 1.0])
    world_sun_intensity: float = 1.0
    world_sun_hpr: list[float] = field(default_factory=lambda: [-35.0, -55.0, 0.0])
    world_fog_enabled: bool = False
    world_fog_mode: str = 'exponential'
    world_fog_color: list[float] = field(default_factory=lambda: [0.10, 0.13, 0.17, 1.0])
    world_fog_density: float = 0.015
    world_fog_start: float = 25.0
    world_fog_end: float = 180.0
    world_skybox_model: str = ''
    world_shader_auto: bool = True
    world_render_pipeline: str = 'builtin'
    world_complexpbr_intensity: float = 1.0
    world_complexpbr_env_res: int = 256
    world_complexpbr_screenspace: bool = False
    world_complexpbr_static_reflections: bool = False
    world_post_bloom: bool = False
    world_post_bloom_intensity: float = 1.0
    world_post_bloom_size: str = 'medium'
    world_post_ambient_occlusion: bool = False
    world_post_ao_samples: int = 16
    world_post_gamma: float = 1.0
    world_post_exposure: float = 0.0
    world_post_srgb: bool = False
    export_app_name: str = 'Panda3D Game'
    export_executable_name: str = 'Panda3DGame'
    export_version: str = '0.1.0'
    export_company: str = ''
    export_output_dir: str = 'build_exports'
    export_build_type: str = 'development'
    export_prefer_discrete_gpu: bool = True
    export_include_ffmpeg: bool = True
    export_package_format: str = 'zip'
    export_icon_path: str = ''
    export_description: str = ''

    @classmethod
    def load(cls) -> 'ProjectSettings':
        if not PROJECT_SETTINGS_PATH.exists():
            obj = cls(); obj.save(); return obj
        try:
            raw = json.loads(PROJECT_SETTINGS_PATH.read_text(encoding='utf-8'))
            obj = cls()
            gravity = raw.get('gravity', obj.gravity)
            if isinstance(gravity, list) and len(gravity) >= 3:
                obj.gravity = [float(gravity[0]), float(gravity[1]), float(gravity[2])]
            layers = raw.get('collision_layers')
            if isinstance(layers, list):
                merged = [str(v or '').strip() or f'Layer {i}' for i, v in enumerate(layers[:32])]
                obj.collision_layers = (merged + _default_layers()[len(merged):])[:32]
            obj.audio_master_volume = max(0.0, min(1.0, float(raw.get('audio_master_volume', obj.audio_master_volume))))
            obj.audio_sfx_volume = max(0.0, min(1.0, float(raw.get('audio_sfx_volume', obj.audio_sfx_volume))))
            obj.audio_music_volume = max(0.0, min(1.0, float(raw.get('audio_music_volume', obj.audio_music_volume))))
            obj.startup_scene = str(raw.get('startup_scene', obj.startup_scene) or '').replace('\\','/').lstrip('/')
            obj.game_window_title = str(raw.get('game_window_title', obj.game_window_title) or 'Panda3D Game')
            obj.game_window_width = max(320, min(7680, int(raw.get('game_window_width', obj.game_window_width))))
            obj.game_window_height = max(240, min(4320, int(raw.get('game_window_height', obj.game_window_height))))
            obj.game_fullscreen = bool(raw.get('game_fullscreen', obj.game_fullscreen))
            def _vec4(key, current):
                v = raw.get(key, current)
                if isinstance(v, list) and len(v) >= 3:
                    return [float(v[0]), float(v[1]), float(v[2]), float(v[3] if len(v)>3 else 1.0)]
                return current
            obj.world_background_color = _vec4('world_background_color', obj.world_background_color)
            obj.world_ambient_color = _vec4('world_ambient_color', obj.world_ambient_color)
            obj.world_ambient_intensity = max(0.0, float(raw.get('world_ambient_intensity', obj.world_ambient_intensity)))
            obj.world_sun_enabled = bool(raw.get('world_sun_enabled', obj.world_sun_enabled))
            obj.world_sun_color = _vec4('world_sun_color', obj.world_sun_color)
            obj.world_sun_intensity = max(0.0, float(raw.get('world_sun_intensity', obj.world_sun_intensity)))
            hpr = raw.get('world_sun_hpr', obj.world_sun_hpr)
            if isinstance(hpr, list) and len(hpr) >= 3: obj.world_sun_hpr = [float(hpr[0]),float(hpr[1]),float(hpr[2])]
            obj.world_fog_enabled = bool(raw.get('world_fog_enabled', obj.world_fog_enabled))
            obj.world_fog_mode = str(raw.get('world_fog_mode', obj.world_fog_mode) or 'exponential').lower()
            if obj.world_fog_mode not in {'exponential','linear'}: obj.world_fog_mode='exponential'
            obj.world_fog_color = _vec4('world_fog_color', obj.world_fog_color)
            obj.world_fog_density = max(0.0, float(raw.get('world_fog_density', obj.world_fog_density)))
            obj.world_fog_start = float(raw.get('world_fog_start', obj.world_fog_start))
            obj.world_fog_end = max(obj.world_fog_start + .01, float(raw.get('world_fog_end', obj.world_fog_end)))
            obj.world_skybox_model = str(raw.get('world_skybox_model', obj.world_skybox_model) or '').replace('\\','/').lstrip('/')
            obj.world_shader_auto = bool(raw.get('world_shader_auto', obj.world_shader_auto))
            obj.world_render_pipeline = str(raw.get('world_render_pipeline', obj.world_render_pipeline) or 'builtin').lower()
            if obj.world_render_pipeline not in {'builtin','simplepbr','complexpbr'}: obj.world_render_pipeline='builtin'
            obj.world_complexpbr_intensity = max(0.0, float(raw.get('world_complexpbr_intensity', obj.world_complexpbr_intensity)))
            obj.world_complexpbr_env_res = max(32, min(2048, int(raw.get('world_complexpbr_env_res', obj.world_complexpbr_env_res))))
            obj.world_complexpbr_screenspace = bool(raw.get('world_complexpbr_screenspace', obj.world_complexpbr_screenspace))
            obj.world_complexpbr_static_reflections = bool(raw.get('world_complexpbr_static_reflections', obj.world_complexpbr_static_reflections))
            obj.world_post_bloom = bool(raw.get('world_post_bloom', obj.world_post_bloom))
            obj.world_post_bloom_intensity = max(0.0, float(raw.get('world_post_bloom_intensity', obj.world_post_bloom_intensity)))
            obj.world_post_bloom_size = str(raw.get('world_post_bloom_size', obj.world_post_bloom_size) or 'medium').lower()
            if obj.world_post_bloom_size not in {'small','medium','large'}: obj.world_post_bloom_size='medium'
            obj.world_post_ambient_occlusion = bool(raw.get('world_post_ambient_occlusion', obj.world_post_ambient_occlusion))
            obj.world_post_ao_samples = max(1, min(64, int(raw.get('world_post_ao_samples', obj.world_post_ao_samples))))
            obj.world_post_gamma = max(0.05, float(raw.get('world_post_gamma', obj.world_post_gamma)))
            obj.world_post_exposure = float(raw.get('world_post_exposure', obj.world_post_exposure))
            obj.world_post_srgb = bool(raw.get('world_post_srgb', obj.world_post_srgb))
            obj.export_app_name = str(raw.get('export_app_name', obj.export_app_name) or obj.game_window_title or 'Panda3D Game')
            obj.export_executable_name = str(raw.get('export_executable_name', obj.export_executable_name) or 'Panda3DGame')
            obj.export_version = str(raw.get('export_version', obj.export_version) or '0.1.0')
            obj.export_company = str(raw.get('export_company', obj.export_company) or '')
            obj.export_output_dir = str(raw.get('export_output_dir', obj.export_output_dir) or 'build_exports').replace('\\','/').strip('/')
            obj.export_build_type = str(raw.get('export_build_type', obj.export_build_type) or 'development').lower()
            if obj.export_build_type not in {'development','release'}:
                obj.export_build_type = 'development'
            obj.export_prefer_discrete_gpu = bool(raw.get('export_prefer_discrete_gpu', obj.export_prefer_discrete_gpu))
            obj.export_include_ffmpeg = bool(raw.get('export_include_ffmpeg', obj.export_include_ffmpeg))
            obj.export_package_format = str(raw.get('export_package_format', obj.export_package_format) or 'zip').lower()
            if obj.export_package_format not in {'zip','nsis'}:
                obj.export_package_format = 'zip'
            obj.export_icon_path = str(raw.get('export_icon_path', obj.export_icon_path) or '').replace('\\','/').lstrip('/')
            obj.export_description = str(raw.get('export_description', obj.export_description) or '')
            actions = raw.get('input_actions')
            if isinstance(actions, dict):
                clean: dict[str, list[str]] = {}
                for name, keys in actions.items():
                    n = str(name).strip()
                    if not n: continue
                    if isinstance(keys, str): keys = [keys]
                    if isinstance(keys, list):
                        clean[n] = [str(k).strip().lower() for k in keys if str(k).strip()]
                if clean: obj.input_actions = clean
            return obj
        except Exception:
            return cls()

    def update_from_dict(self, raw: dict) -> None:
        if 'gravity' in raw:
            g = list(raw.get('gravity') or [])
            if len(g) >= 3:
                self.gravity = [float(g[0]), float(g[1]), float(g[2])]
        if 'collision_layers' in raw:
            layers = list(raw.get('collision_layers') or [])[:32]
            defaults = _default_layers()
            self.collision_layers = [(str(layers[i]).strip() if i < len(layers) else '') or defaults[i] for i in range(32)]
        if 'audio_master_volume' in raw:
            self.audio_master_volume = max(0.0, min(1.0, float(raw.get('audio_master_volume', 1.0))))
        if 'audio_sfx_volume' in raw:
            self.audio_sfx_volume = max(0.0, min(1.0, float(raw.get('audio_sfx_volume', 1.0))))
        if 'audio_music_volume' in raw:
            self.audio_music_volume = max(0.0, min(1.0, float(raw.get('audio_music_volume', 0.85))))
        if 'startup_scene' in raw:
            self.startup_scene = str(raw.get('startup_scene') or '').replace('\\','/').lstrip('/')
        if 'game_window_title' in raw:
            self.game_window_title = str(raw.get('game_window_title') or 'Panda3D Game')
        if 'game_window_width' in raw:
            self.game_window_width = max(320, min(7680, int(raw.get('game_window_width') or 1280)))
        if 'game_window_height' in raw:
            self.game_window_height = max(240, min(4320, int(raw.get('game_window_height') or 720)))
        if 'game_fullscreen' in raw:
            self.game_fullscreen = bool(raw.get('game_fullscreen'))
        def _set_vec4(key, attr):
            if key in raw:
                v=list(raw.get(key) or [])
                if len(v)>=3: setattr(self, attr, [float(v[0]),float(v[1]),float(v[2]),float(v[3] if len(v)>3 else 1.0)])
        _set_vec4('world_background_color','world_background_color')
        _set_vec4('world_ambient_color','world_ambient_color')
        if 'world_ambient_intensity' in raw: self.world_ambient_intensity=max(0.0,float(raw.get('world_ambient_intensity') or 0))
        if 'world_sun_enabled' in raw: self.world_sun_enabled=bool(raw.get('world_sun_enabled'))
        _set_vec4('world_sun_color','world_sun_color')
        if 'world_sun_intensity' in raw: self.world_sun_intensity=max(0.0,float(raw.get('world_sun_intensity') or 0))
        if 'world_sun_hpr' in raw:
            v=list(raw.get('world_sun_hpr') or [])
            if len(v)>=3: self.world_sun_hpr=[float(v[0]),float(v[1]),float(v[2])]
        if 'world_fog_enabled' in raw: self.world_fog_enabled=bool(raw.get('world_fog_enabled'))
        if 'world_fog_mode' in raw:
            v=str(raw.get('world_fog_mode') or 'exponential').lower(); self.world_fog_mode=v if v in {'exponential','linear'} else 'exponential'
        _set_vec4('world_fog_color','world_fog_color')
        if 'world_fog_density' in raw: self.world_fog_density=max(0.0,float(raw.get('world_fog_density') or 0))
        if 'world_fog_start' in raw: self.world_fog_start=float(raw.get('world_fog_start') or 0)
        if 'world_fog_end' in raw: self.world_fog_end=max(self.world_fog_start+.01,float(raw.get('world_fog_end') or self.world_fog_start+.01))
        if 'world_skybox_model' in raw: self.world_skybox_model=str(raw.get('world_skybox_model') or '').replace('\\','/').lstrip('/')
        if 'world_shader_auto' in raw: self.world_shader_auto=bool(raw.get('world_shader_auto'))
        if 'world_render_pipeline' in raw:
            v=str(raw.get('world_render_pipeline') or 'builtin').lower(); self.world_render_pipeline=v if v in {'builtin','simplepbr','complexpbr'} else 'builtin'
        if 'world_complexpbr_intensity' in raw: self.world_complexpbr_intensity=max(0.0,float(raw.get('world_complexpbr_intensity') or 0.0))
        if 'world_complexpbr_env_res' in raw: self.world_complexpbr_env_res=max(32,min(2048,int(raw.get('world_complexpbr_env_res') or 256)))
        if 'world_complexpbr_screenspace' in raw: self.world_complexpbr_screenspace=bool(raw.get('world_complexpbr_screenspace'))
        if 'world_complexpbr_static_reflections' in raw: self.world_complexpbr_static_reflections=bool(raw.get('world_complexpbr_static_reflections'))
        if 'world_post_bloom' in raw: self.world_post_bloom=bool(raw.get('world_post_bloom'))
        if 'world_post_bloom_intensity' in raw: self.world_post_bloom_intensity=max(0.0,float(raw.get('world_post_bloom_intensity') or 0.0))
        if 'world_post_bloom_size' in raw:
            v=str(raw.get('world_post_bloom_size') or 'medium').lower(); self.world_post_bloom_size=v if v in {'small','medium','large'} else 'medium'
        if 'world_post_ambient_occlusion' in raw: self.world_post_ambient_occlusion=bool(raw.get('world_post_ambient_occlusion'))
        if 'world_post_ao_samples' in raw: self.world_post_ao_samples=max(1,min(64,int(raw.get('world_post_ao_samples') or 16)))
        if 'world_post_gamma' in raw: self.world_post_gamma=max(0.05,float(raw.get('world_post_gamma') or 1.0))
        if 'world_post_exposure' in raw: self.world_post_exposure=float(raw.get('world_post_exposure') or 0.0)
        if 'world_post_srgb' in raw: self.world_post_srgb=bool(raw.get('world_post_srgb'))
        if 'export_app_name' in raw:
            self.export_app_name = str(raw.get('export_app_name') or self.game_window_title or 'Panda3D Game')
        if 'export_executable_name' in raw:
            self.export_executable_name = str(raw.get('export_executable_name') or 'Panda3DGame')
        if 'export_version' in raw:
            self.export_version = str(raw.get('export_version') or '0.1.0')
        if 'export_company' in raw:
            self.export_company = str(raw.get('export_company') or '')
        if 'export_output_dir' in raw:
            self.export_output_dir = str(raw.get('export_output_dir') or 'build_exports').replace('\\','/').strip('/')
        if 'export_build_type' in raw:
            value = str(raw.get('export_build_type') or 'development').lower()
            self.export_build_type = value if value in {'development','release'} else 'development'
        if 'export_prefer_discrete_gpu' in raw:
            self.export_prefer_discrete_gpu = bool(raw.get('export_prefer_discrete_gpu'))
        if 'export_include_ffmpeg' in raw:
            self.export_include_ffmpeg = bool(raw.get('export_include_ffmpeg'))
        if 'export_package_format' in raw:
            value = str(raw.get('export_package_format') or 'zip').lower()
            self.export_package_format = value if value in {'zip','nsis'} else 'zip'
        if 'export_icon_path' in raw:
            self.export_icon_path = str(raw.get('export_icon_path') or '').replace('\\','/').lstrip('/')
        if 'export_description' in raw:
            self.export_description = str(raw.get('export_description') or '')
        if 'input_actions' in raw and isinstance(raw.get('input_actions'), dict):
            clean: dict[str, list[str]] = {}
            for name, keys in raw['input_actions'].items():
                n = str(name).strip()
                if not n: continue
                if isinstance(keys, str): keys = [keys]
                if not isinstance(keys, list): continue
                clean[n] = [str(k).strip().lower() for k in keys if str(k).strip()]
            self.input_actions = clean

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self) -> None:
        PROJECT_SETTINGS_PATH.write_text(json.dumps(self.to_dict(), indent=2), encoding='utf-8')
