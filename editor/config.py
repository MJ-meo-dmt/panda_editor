from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
USER_DATA = ROOT / 'user_data'
SETTINGS_PATH = USER_DATA / 'settings.json'


@dataclass
class EditorSettings:
    theme: str = 'midnight'
    font_scale: float = 1.0
    ui_scale: float = 1.0
    left_width: int = 260
    right_width: int = 340
    bottom_height: int = 235
    show_grid: bool = True
    snap_enabled: bool = False
    snap_size: float = 1.0
    recent_project: str = ''

    @classmethod
    def load(cls) -> 'EditorSettings':
        USER_DATA.mkdir(parents=True, exist_ok=True)
        if not SETTINGS_PATH.exists():
            obj = cls()
            obj.save()
            return obj
        try:
            raw = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
            known = {k: v for k, v in raw.items() if k in cls.__annotations__}
            return cls(**known)
        except Exception:
            return cls()

    def save(self) -> None:
        USER_DATA.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(asdict(self), indent=2), encoding='utf-8')
