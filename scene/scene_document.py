from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .entity import Entity


class SceneDocument:
    VERSION = 1

    def __init__(self, name: str = 'Untitled') -> None:
        self.name = name
        self.entities: dict[str, Entity] = {}
        self.file_path: Path | None = None
        self.dirty = False

    def add(self, entity: Entity) -> Entity:
        self.entities[entity.id] = entity
        self.dirty = True
        return entity

    def remove(self, entity_id: str) -> Entity | None:
        ent = self.entities.pop(entity_id, None)
        if ent:
            for child in self.entities.values():
                if child.parent == entity_id:
                    child.parent = None
            self.dirty = True
        return ent

    def to_dict(self) -> dict[str, Any]:
        return {
            'scene_version': self.VERSION,
            'name': self.name,
            'entities': [entity.to_dict() for entity in self.entities.values()],
        }

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path else self.file_path
        if target is None:
            raise ValueError('No scene path was provided.')
        if target.suffix.lower() != '.pscene':
            target = target.with_suffix('.pscene')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2), encoding='utf-8')
        self.file_path = target
        self.name = target.stem
        self.dirty = False
        return target

    @classmethod
    def load(cls, path: str | Path) -> 'SceneDocument':
        target = Path(path)
        data = json.loads(target.read_text(encoding='utf-8'))
        doc = cls(data.get('name', target.stem))
        for raw in data.get('entities', []):
            ent = Entity.from_dict(raw)
            doc.entities[ent.id] = ent
        doc.file_path = target
        doc.dirty = False
        return doc
