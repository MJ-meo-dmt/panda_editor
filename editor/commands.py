from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class Command(Protocol):
    label: str
    def do(self) -> None: ...
    def undo(self) -> None: ...


class CommandStack:
    def __init__(self) -> None:
        self._undo: list[Command] = []
        self._redo: list[Command] = []

    def execute(self, command: Command) -> None:
        command.do()
        self._undo.append(command)
        self._redo.clear()

    def undo(self) -> str | None:
        if not self._undo:
            return None
        command = self._undo.pop()
        command.undo()
        self._redo.append(command)
        return command.label

    def redo(self) -> str | None:
        if not self._redo:
            return None
        command = self._redo.pop()
        command.do()
        self._undo.append(command)
        return command.label

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)


@dataclass
class LambdaCommand:
    label: str
    _do: callable
    _undo: callable

    def do(self) -> None:
        self._do()

    def undo(self) -> None:
        self._undo()
