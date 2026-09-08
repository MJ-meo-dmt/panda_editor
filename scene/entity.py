from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Transform:
    position: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    scale: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])


@dataclass
class Entity:
    name: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    parent: str | None = None
    enabled: bool = True
    visible: bool = True
    transform: Transform = field(default_factory=Transform)
    components: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Entity':
        data = dict(data)
        data['transform'] = Transform(**data.get('transform', {}))
        return cls(**data)
