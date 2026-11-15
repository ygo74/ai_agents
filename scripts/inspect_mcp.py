"""Inspect the tools exposed by a Streamable HTTP MCP endpoint."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


@dataclass(frozen=True, slots=True)
class ToolDescription:
    """Hold the public metadata declared for one MCP tool."""

    name: str
    description: str | None
    input_schema: dict[str, Any]


class McpInspectionError(Exception):
    """Describe a failed inspection without retaining transport error details."""

    def __init__(self, phase: str, error_type: str) -> None:
        """Record the operation stage and exception class, never its message."""
        self.phase = phase
        self.error_type = error_type
        super().__init__(f"{phase} failed ({error_type})")


def headers_from_environment(
    specifications: Sequence[str],
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Resolve ``HEADER_NAME=ENVIRONMENT_VARIABLE`` entries to request headers.

    Args:
        specifications: Header mappings supplied through repeatable CLI options.
        environment: Optional environment mapping, useful for deterministic callers.

    Returns:
        Request header names and values without exposing values to command output.

    Raises:
        ValueError: If a mapping is malformed, duplicated, or its value is missing.
    """
    values = os.environ if environment is None else environment
    headers: dict[str, str] = {}
    seen_names: set[str] = set()
    header_name_pattern = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")

    # Resolve each mapping only after validating its shape, so errors never echo
    # secret values and duplicate names cannot silently replace credentials.
    for specification in specifications:
        header_name, separator, environment_name = specification.partition("=")
        if not separator:
            raise ValueError("header mapping must use NAME=ENVIRONMENT_VARIABLE")
        if not header_name_pattern.fullmatch(header_name):
            raise ValueError("invalid header name")
        if not environment_name:
            raise ValueError("environment variable name is required")
        if header_name.casefold() in seen_names:
            raise ValueError(f"duplicate header name: {header_name}")

        value = values.get(environment_name)
        if value is None or not value.strip():
            raise ValueError(f"environment variable {environment_name} is not set or empty")

        headers[header_name] = value
        seen_names.add(header_name.casefold())

    return headers


def _argument_type(definition: Mapping[str, Any]) -> str:
    """Render a JSON Schema type value for one top-level argument."""
    value = definition.get("type", "unspecified")
    if isinstance(value, list):
        return " | ".join(str(item) for item in value)
    return str(value)


def render_tools(tools: Sequence[ToolDescription]) -> str:
    """Render names, descriptions, argument summaries, and complete schemas.

    Args:
        tools: Tool declarations returned by the remote MCP server.

    Returns:
        A readable report that retains all input schema fields as JSON.
    """
    lines = [f"Exposed tools: {len(tools)}"]

    for tool in tools:
        lines.extend(("", f"Tool: {tool.name}", f"Description: {tool.description or '(not provided)'}"))
        properties = tool.input_schema.get("properties", {})
        required = set(tool.input_schema.get("required", []))
        if isinstance(properties, Mapping) and properties:
            lines.append("Arguments:")
            for name, raw_definition in properties.items():
                definition = raw_definition if isinstance(raw_definition, Mapping) else {}
                required_label = "required" if name in required else "optional"
                lines.append(f"  - {name} ({_argument_type(definition)}, {required_label})")
                description = definition.get("description")
                if description:
                    lines.append(f"      {description}")
        else:
            lines.append("Arguments: (none declared)")

        # The summary is convenient for the common case; the full schema keeps
        # nested, optional, and vendor-specific constraints visible as declared.
        lines.append("Input schema:")
        lines.extend(f"  {line}" for line in json.dumps(tool.input_schema, indent=2, ensure_ascii=False).splitlines())

    return "\n".join(lines)


async def inspect_tools(url: str, headers: Mapping[str, str]) -> list[ToolDescription]:
    """Initialize one MCP session, list tools, and close all transport resources.

    Args:
        url: Streamable HTTP endpoint to inspect.
        headers: Authentication and other request headers for the endpoint.

    Returns:
        The tools declared by the endpoint.

    Raises:
        McpInspectionError: If HTTP connection, MCP initialization, or listing fails.
    """
    phase = "opening HTTP client"
    try:
        # Normal certificate verification is explicit; both contexts keep the
        # HTTP client and MCP session scoped to this one read-only inspection.
        async with httpx.AsyncClient(headers=dict(headers), verify=True) as http_client:
            phase = "opening MCP transport"
            async with streamable_http_client(url, http_client=http_client) as (read_stream, write_stream, _):
                phase = "initializing MCP session"
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    phase = "listing MCP tools"
                    listing = await session.list_tools()

        return [
            ToolDescription(
                name=tool.name,
                description=tool.description,
                input_schema=dict(tool.inputSchema),
            )
            for tool in sorted(listing.tools, key=lambda item: item.name)
        ]
    except Exception as error:  # noqa: BLE001 - sanitize errors from any MCP/HTTP transport implementation.
        # Exception messages can contain request details. Report only the stage
        # and exception class so configured credentials cannot reach the console.
        raise McpInspectionError(phase, type(error).__name__) from None


def _argument_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for endpoint and environment settings."""
    parser = argparse.ArgumentParser(
        description="List tools and input schemas exposed by a Streamable HTTP MCP endpoint."
    )
    parser.add_argument("--url", required=True, help="MCP endpoint URL, such as https://127.0.0.1:8123/mcp.")
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        metavar="NAME=ENVIRONMENT_VARIABLE",
        help="Add a request header using a value read from the named environment variable; repeat as needed.",
    )
    return parser


def main(
    arguments: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Run the MCP inspection command and return its process exit status.

    Args:
        arguments: Optional argument vector, excluding the executable name.
        environment: Optional environment mapping used to resolve header values.

    Returns:
        Zero after a successful listing, two for invalid configuration, or one
        when a remote inspection fails.
    """
    parser = _argument_parser()
    parsed = parser.parse_args(arguments)
    try:
        headers = headers_from_environment(parsed.header, environment)
    except ValueError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2

    try:
        tools = asyncio.run(inspect_tools(parsed.url, headers))
    except McpInspectionError as error:
        print(
            f"MCP inspection failed while {error.phase} ({error.error_type}). "
            "Check the endpoint, authentication settings, and server availability.",
            file=sys.stderr,
        )
        return 1

    print(render_tools(tools))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
