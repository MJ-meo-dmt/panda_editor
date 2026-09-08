from pathlib import Path
from .scene_document import SceneDocument


def load_scene(path: str | Path) -> SceneDocument:
    return SceneDocument.load(path)


def save_scene(scene: SceneDocument, path: str | Path | None = None) -> Path:
    return scene.save(path)
