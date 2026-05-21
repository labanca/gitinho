"""Bridge our internal ToolRegistry to OpenAI function-calling schema."""

from __future__ import annotations

import inspect
from typing import Any, get_args, get_origin

from app.tools._base import ToolMode, ToolSpec, registry


def _python_to_jsonschema(annotation: Any) -> dict[str, Any]:
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {"type": "string"}
    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    origin = get_origin(annotation)
    if origin is list:
        inner = get_args(annotation)
        item = _python_to_jsonschema(inner[0]) if inner else {"type": "string"}
        return {"type": "array", "items": item}
    if origin is dict:
        return {"type": "object"}
    # Optional[X] / X | None
    args = get_args(annotation)
    if args:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _python_to_jsonschema(non_none[0])
    return {"type": "string"}


def build_openai_tools(*, include_write: bool = False) -> list[dict[str, Any]]:
    """Return tools formatted for the OpenAI Chat Completions API."""
    out: list[dict[str, Any]] = []
    for tool in registry.all(include_write=include_write):
        out.append(_tool_to_openai(tool))
    return out


def _tool_to_openai(tool: ToolSpec) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []
    for pname, param in tool.signature.parameters.items():
        if pname == "ctx":
            continue
        schema = _python_to_jsonschema(param.annotation)
        if param.default is inspect.Parameter.empty:
            required.append(pname)
        else:
            schema["default"] = (
                param.default
                if not callable(param.default)
                else None
            )
        props[pname] = schema
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description[:1024] or tool.name,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


def get_tool(name: str) -> ToolSpec | None:
    spec = registry.get(name)
    if spec is None:
        return None
    if spec.mode != ToolMode.READ:
        return None  # Write tools never callable in phase 1.
    return spec
