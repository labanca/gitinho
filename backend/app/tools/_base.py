"""Tool registry with mode (READ/WRITE) and metadata."""

from __future__ import annotations

import enum
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class ToolMode(str, enum.Enum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


@dataclass
class ToolSpec:
    name: str
    description: str
    func: Callable[..., Any]
    mode: ToolMode
    signature: inspect.Signature = field(init=False)

    def __post_init__(self) -> None:
        self.signature = inspect.signature(self.func)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        *,
        name: str | None = None,
        mode: ToolMode = ToolMode.READ,
        description: str | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name or func.__name__
            doc = description or (func.__doc__ or "").strip()
            if tool_name in self._tools:
                raise ValueError(f"Tool '{tool_name}' is already registered")
            self._tools[tool_name] = ToolSpec(
                name=tool_name,
                description=doc,
                func=func,
                mode=mode,
            )
            return func

        return decorator

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def all(self, *, include_write: bool = False) -> list[ToolSpec]:
        if include_write:
            return list(self._tools.values())
        return [t for t in self._tools.values() if t.mode == ToolMode.READ]


registry = ToolRegistry()
