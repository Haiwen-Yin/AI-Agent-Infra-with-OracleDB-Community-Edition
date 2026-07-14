#!/usr/bin/env python3.14
"""AI Agent Infra v3.9.0 - MCP Server Entry Point

Starts the MCP server in stdio or SSE mode.

Usage:
    python mcp_server_main.py                          # stdio mode (default)
    python mcp_server_main.py --transport stdio        # stdio mode (explicit)
    python mcp_server_main.py --transport sse           # SSE mode on default port 9000
    python mcp_server_main.py --transport sse --port 8080  # SSE on custom port
"""

import argparse
import asyncio
import logging
import sys
import os

# Set up project root path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from lib.config import get_config

logging.basicConfig(
    level=logging.INFO,
    format="[mcp] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


async def run_stdio():
    """Run MCP server in stdio mode (for Claude Desktop, Cursor, etc.)."""
    from lib.mcp_server import server
    from mcp.server.stdio import stdio_server

    logger.info("Starting MCP server in stdio mode")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


async def run_sse(port: int):
    """Run MCP server in SSE mode (for remote connections)."""
    from lib.mcp_server import server
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.responses import Response
    import uvicorn

    sse = SseServerTransport("/sse")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())
        return Response()

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/messages", endpoint=sse.handle_post_message, methods=["POST"]),
        ]
    )

    logger.info("Starting MCP server in SSE mode on port %d", port)
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    uvicorn_server = uvicorn.Server(config)
    await uvicorn_server.serve()


def main():
    parser = argparse.ArgumentParser(description="AI Agent Infra MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default=None,
        help="Transport mode (default: from config or stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port for SSE mode (default: from config or 9000)",
    )
    args = parser.parse_args()

    cfg = get_config()
    transport = args.transport or cfg.mcp.transport
    port = args.port or cfg.mcp.sse_port

    if not cfg.mcp.enabled:
        logger.warning("MCP server is disabled in config. Set mcp.enabled=true to enable.")
        logger.info("Starting anyway with default settings...")

    if transport == "stdio":
        asyncio.run(run_stdio())
    elif transport == "sse":
        asyncio.run(run_sse(port))
    else:
        logger.error("Unknown transport: %s", transport)
        sys.exit(1)


if __name__ == "__main__":
    main()
