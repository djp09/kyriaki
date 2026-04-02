"""WAT Framework — Tool layer.

Tools are deterministic, stateless Python functions that do the actual work:
API calls, data transformations, prompt rendering, etc.

Agents orchestrate tools. Workflows document the orchestration steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    """Standard return type for all tools."""

    success: bool
    data: Any = None
    error: str | None = None


# Tool registry — tools register themselves at import time
_tool_registry: dict[str, Any] = {}


def register_tool(name: str, fn: Any) -> Any:
    """Register a callable tool by name."""
    _tool_registry[name] = fn
    return fn


def get_tool(name: str) -> Any:
    """Retrieve a registered tool by name."""
    if name not in _tool_registry:
        raise KeyError(f"Unknown tool: {name}. Available: {list(_tool_registry.keys())}")
    return _tool_registry[name]


def list_tools() -> list[str]:
    """List all registered tool names."""
    return list(_tool_registry.keys())
