"""WAT Framework — Tool layer with rich documentation (ACI).

Tools are deterministic, stateless Python functions that do the actual work.
Each tool registers with a ToolSpec that documents its interface for both
humans and agent orchestrator prompts.

Agents orchestrate tools. Workflows document the orchestration steps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TokenUsage:
    """Token counts for a single Claude API call."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ToolResult:
    """Standard return type for all tools."""

    success: bool
    data: Any = None
    error: str | None = None
    token_usage: TokenUsage | None = None


@dataclass
class ToolSpec:
    """Rich documentation for a tool — used in agent orchestrator prompts."""

    name: str
    description: str
    parameters: dict[str, str] = field(default_factory=dict)  # param_name → description
    returns: str = ""
    examples: list[str] = field(default_factory=list)
    edge_cases: list[str] = field(default_factory=list)


# Tool registry — tools register themselves at import time
_tool_registry: dict[str, Any] = {}
_tool_specs: dict[str, ToolSpec] = {}


def register_tool(name: str, fn: Any, spec: ToolSpec | None = None) -> Any:
    """Register a callable tool by name, with optional documentation."""
    _tool_registry[name] = fn
    if spec:
        _tool_specs[name] = spec
    return fn


def get_tool(name: str) -> Any:
    """Retrieve a registered tool by name."""
    if name not in _tool_registry:
        raise KeyError(f"Unknown tool: {name}. Available: {list(_tool_registry.keys())}")
    return _tool_registry[name]


def get_tool_spec(name: str) -> ToolSpec | None:
    """Retrieve documentation for a registered tool."""
    return _tool_specs.get(name)


def list_tools() -> list[str]:
    """List all registered tool names."""
    return list(_tool_registry.keys())


def get_tool_docs(names: list[str] | None = None) -> str:
    """Format tool documentation as markdown for injection into orchestrator prompts.

    Args:
        names: Specific tools to document. If None, documents all registered tools.

    Returns:
        Formatted markdown string describing the tools.
    """
    if names is None:
        names = list(_tool_specs.keys())

    lines = []
    for name in names:
        spec = _tool_specs.get(name)
        if not spec:
            continue

        lines.append(f"### {spec.name}")
        lines.append(spec.description)

        if spec.parameters:
            lines.append("**Parameters:**")
            for param, desc in spec.parameters.items():
                lines.append(f"  - `{param}`: {desc}")

        if spec.returns:
            lines.append(f"**Returns:** {spec.returns}")

        if spec.examples:
            lines.append("**Examples:**")
            for ex in spec.examples:
                lines.append(f"  - {ex}")

        if spec.edge_cases:
            lines.append("**Edge cases:**")
            for ec in spec.edge_cases:
                lines.append(f"  - {ec}")

        lines.append("")

    return "\n".join(lines)
