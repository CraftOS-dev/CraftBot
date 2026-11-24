"""Spotting MCP servers that run a package without a fixed version."""

import pytest

from app.security.mcp_pins import unpinned_package, unpinned_servers


@pytest.mark.parametrize(
    "command,args,unpinned",
    [
        ("npx", ["-y", "@modelcontextprotocol/server-filesystem", "."], "@modelcontextprotocol/server-filesystem"),
        ("npx", ["-y", "@modelcontextprotocol/server-filesystem@2025.8.21", "."], None),
        ("npx", ["mcp-remote@latest", "https://x"], "mcp-remote@latest"),
        ("npx", ["mcp-remote@^0.1.0"], "mcp-remote@^0.1.0"),
        ("npx.cmd", ["-y", "pkg@1.2.3"], None),
        ("npx", ["--package=pkg@1.0.0", "pkg-bin"], None),
        ("npx", ["-p", "pkg", "pkg-bin"], "pkg"),
        ("pnpm", ["dlx", "pkg"], "pkg"),
        ("bunx", ["pkg@2.0.0"], None),
        ("uvx", ["mcp-server-fetch"], "mcp-server-fetch"),
        ("uvx", ["mcp-server-fetch==2025.4.7"], None),
        ("uvx", ["--from", "mcp-server-git==1.0.0", "mcp-server-git"], None),
        ("pipx", ["run", "some-server"], "some-server"),
        ("npx", ["./local-server"], None),
        ("node", ["server.js"], None),
        ("python", ["-m", "server"], None),
    ],
)
def test_launcher_packages(command, args, unpinned):
    assert unpinned_package(command, args) == unpinned


def test_only_enabled_stdio_servers_are_reported():
    servers = [
        {"name": "fs", "command": "npx", "args": ["-y", "pkg"], "enabled": True},
        {"name": "off", "command": "npx", "args": ["-y", "pkg"], "enabled": False},
        {"name": "remote", "transport": "sse", "url": "https://x", "enabled": True},
    ]
    assert unpinned_servers(servers) == [("fs", "pkg")]
