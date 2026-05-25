"""Gitinho MCP server — entry point.

Tools are auto-registered by importing `gitinho_mcp.tools`. The transport
is stdio by default; the better-chatbot frontend launches us via
`.mcp-config.json`.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("gitinho")


def main() -> None:
    # Import to trigger @mcp.tool() registrations.
    from gitinho_mcp import tools  # noqa: F401

    mcp.run()


if __name__ == "__main__":
    main()
