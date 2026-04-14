"""GitHub Copilot SDK agent for testing MCP server variants.

Connects to a running MCP server over Streamable HTTP and runs queries.
Supports filtering to specific tools via the Copilot SDK's tools parameter.

Usage:
    # Start a server first:
    python servers/level4_typed.py

    # Run with all tools:
    python agents/copilotsdk_agent.py --query "What bees are active near SF in March?"

    # Run with specific tools:
    python agents/copilotsdk_agent.py --tools search_species,search_observations --query "..."
"""

import argparse
import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime

from copilot import CopilotClient, PermissionHandler, SessionConfig
from copilot.generated.session_events import SessionEvent, SessionEventType
from copilot.types import MCPRemoteServerConfig
from dotenv import load_dotenv

load_dotenv(override=True)

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger("bees_agent")
logger.setLevel(logging.INFO)

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")

COPILOT_MODELS = ["gpt-5", "gpt-5.3-codex", "claude-sonnet-4", "claude-sonnet-4.5", "claude-haiku-4.5"]
DEFAULT_COPILOT_MODEL = "gpt-5"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ToolCallInfo:
    """Information about a single tool call."""

    tool_name: str
    arguments: dict


@dataclass
class QueryResult:
    """Result of running a query against the agent."""

    output: str
    tool_calls: list[ToolCallInfo]
    reasoning: str | None = None
    error: str | None = None


# =============================================================================
# Query Runner
# =============================================================================


async def run_query(
    tool_names: list[str],
    query: str,
    model: str | None = None,
) -> QueryResult:
    """Run a single query against the agent with specific tools.

    Args:
        tool_names: Names of the tools the agent can use (empty = all tools)
        query: The user query to send
        model: Model name to use (default: gpt-5)

    Returns:
        QueryResult with output, tool calls, and optional reasoning
    """
    deployment = model or DEFAULT_COPILOT_MODEL

    tool_calls: list[ToolCallInfo] = []
    output_parts: list[str] = []
    reasoning_parts: list[str] = []

    def handle_event(event: SessionEvent):
        """Handle events from the Copilot session."""
        if event.type == SessionEventType.TOOL_EXECUTION_START:
            if hasattr(event, "data") and event.data:
                data = event.data
                tool_name_val = getattr(data, "mcp_tool_name", None) or getattr(data, "tool_name", None)
                args = getattr(data, "arguments", None)
                if tool_name_val:
                    tool_calls.append(ToolCallInfo(
                        tool_name=tool_name_val,
                        arguments=args if isinstance(args, dict) else {},
                    ))

        elif event.type == SessionEventType.ASSISTANT_MESSAGE:
            if hasattr(event, "data") and event.data and hasattr(event.data, "content"):
                content = event.data.content
                if content:
                    output_parts.append(str(content))

        elif event.type == SessionEventType.ASSISTANT_REASONING:
            if hasattr(event, "data") and event.data and hasattr(event.data, "content"):
                content = event.data.content
                if content:
                    reasoning_parts.append(str(content))

    mcp_config: dict = {
        "type": "http",
        "url": MCP_SERVER_URL,
    }
    if tool_names:
        mcp_config["tools"] = tool_names

    client = None
    session = None
    try:
        client = CopilotClient()

        session_config = SessionConfig(
            model=deployment,
            mcp_servers={
                "bees": MCPRemoteServerConfig(**mcp_config),
            },
            system_message={
                "mode": "replace",
                "content": (
                    "You help users explore bee biodiversity data. "
                    "The database contains observations of bee species from iNaturalist. "
                    f"Today's date is {datetime.now().strftime('%B %-d, %Y')}."
                ),
            },
            on_permission_request=PermissionHandler.approve_all,
        )

        session = await client.create_session(session_config)
        session.on(handle_event)

        await session.send_and_wait({"prompt": query})

        output = "\n".join(output_parts) if output_parts else ""
        reasoning = "\n\n".join(reasoning_parts) if reasoning_parts else None

        return QueryResult(
            output=output,
            tool_calls=tool_calls,
            reasoning=reasoning,
        )

    except Exception as e:
        logger.exception(f"Error running query with tools {tool_names}")
        return QueryResult(output="", tool_calls=[], error=str(e))
    finally:
        if session is not None:
            await session.destroy()
        if client is not None:
            await client.stop()


# =============================================================================
# CLI
# =============================================================================

DEFAULT_QUERY = "What bees are active near San Francisco in March?"


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run Copilot SDK agent against bees MCP server")
    parser.add_argument(
        "--tools",
        type=str,
        default="",
        help="Comma-separated list of allowed tools (default: all tools)",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=DEFAULT_QUERY,
        help=f"Query to send to the agent (default: '{DEFAULT_QUERY}')",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        choices=COPILOT_MODELS,
        help=f"Model to use (default: {DEFAULT_COPILOT_MODEL})",
    )
    parser.add_argument(
        "--show-tool-calls",
        action="store_true",
        help="Print extracted tool calls after the run",
    )
    parser.add_argument(
        "--show-reasoning",
        action="store_true",
        help="Print reasoning summary after the run",
    )
    return parser.parse_args()


async def main():
    """Run the agent with command line arguments."""
    args = parse_args()

    tool_names = [t.strip() for t in args.tools.split(",") if t.strip()] if args.tools else []
    logger.info(f"Using tools: {tool_names or '(all)'}")

    result = await run_query(
        tool_names=tool_names,
        query=args.query,
        model=args.model,
    )

    if result.error:
        print(f"Error: {result.error}")
    else:
        print(f"Result: {result.output}")

        if args.show_tool_calls:
            print("Tool calls:")
            for call in result.tool_calls:
                print(f"  {call.tool_name}: {json.dumps(call.arguments, default=str)}")

        if args.show_reasoning:
            print("Reasoning:")
            print(result.reasoning if result.reasoning else "(none)")


if __name__ == "__main__":
    asyncio.run(main())
