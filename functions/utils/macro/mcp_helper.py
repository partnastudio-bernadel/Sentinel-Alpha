import os
import sys
import json
import asyncio
import threading
import traceback
from concurrent.futures import Future
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from functions.utils.macro.scheduler import RateLimitError, MCPConnectionError

# Network timeout enforced on every MCP session call (TRD: 10-second threshold)
_MCP_TIMEOUT: float = 10.0

# Resolve sentiment directory relative to this file's location
# Path: sentiment/functions/utils/macro/mcp_helper.py -> sentiment/
current_file_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.abspath(os.path.join(current_file_dir, "..", "..", ".."))

def run_async_in_thread(coro):
    """Run an async coroutine in a background thread with Windows subprocess support."""
    future = Future()
    def run():
        try:
            if sys.platform == 'win32':
                loop = asyncio.ProactorEventLoop()
            else:
                loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(coro)
            future.set_result(result)
        except Exception as e:
            future.set_exception(e)
        finally:
            loop.close()
    threading.Thread(target=run).start()
    return future.result()

async def async_query_alpha_vantage_mcp(tool_name: str, arguments: dict, api_key: str) -> dict:
    """Query the remote Alpha Vantage MCP server using Streamable HTTP transport."""
    server_url = f"https://mcp.alphavantage.co/mcp?apikey={api_key}"
    try:
        async with streamable_http_client(server_url) as (read, write, get_session_id):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                # Check if we are invoking an API indicator directly (not the meta-tools)
                if tool_name not in ["TOOL_LIST", "TOOL_GET", "TOOL_CALL"]:
                    if "datatype" not in arguments:
                        arguments["datatype"] = "json"
                    
                    wrapped_arguments = {
                        "tool_name": tool_name,
                        "arguments": arguments
                    }
                    mcp_tool = "TOOL_CALL"
                else:
                    wrapped_arguments = arguments
                    mcp_tool = tool_name
                
                result = await asyncio.wait_for(
                    session.call_tool(mcp_tool, wrapped_arguments),
                    timeout=_MCP_TIMEOUT
                )
                if isinstance(result.content, list) and len(result.content) > 0:
                    first_text = result.content[0].text
                    if first_text.strip().startswith("["):
                        return json.loads(first_text)
                    if len(result.content) == 1:
                        return json.loads(first_text)
                    return [json.loads(content.text) for content in result.content if content.text]
                return {"status": "error", "error_msg": "Empty tool response"}
    except asyncio.TimeoutError:
        raise asyncio.TimeoutError(f"Alpha Vantage MCP call exceeded {_MCP_TIMEOUT}s timeout.")
    except (ConnectionError, OSError) as e:
        raise MCPConnectionError(f"Alpha Vantage MCP connection failed: {e}") from e
    except Exception as e:
        # Use traceback to fully unroll nested ExceptionGroups
        full_traceback = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        err_str = full_traceback.lower()
                
        if "429" in err_str or "403" in err_str or "rate limit" in err_str:
            raise RateLimitError(f"Alpha Vantage rate limit: {e}") from e
        raise MCPConnectionError(f"Alpha Vantage MCP unexpected error:\n{full_traceback}") from e

async def async_query_forexfactory_mcp(tool_name: str, arguments: dict) -> dict:
    """Query the local ForexFactory MCP server using stdio transport."""
    mcp_rel_path = os.getenv("FOREXFACTORY_MCP_PATH", "forexfactory-mcp")
    server_script_path = os.path.abspath(
        os.path.join(sentiment_dir, mcp_rel_path, "src", "forexfactory_mcp", "server.py")
    )
    
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[
            server_script_path,
            "--transport", "stdio"
        ],
        env=None
    )
    try:
        async with stdio_client(server_params, errlog=sys.__stderr__) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments),
                    timeout=_MCP_TIMEOUT
                )
                if isinstance(result.content, list) and len(result.content) > 0:
                    first_text = result.content[0].text
                    if first_text.strip().startswith("["):
                        return json.loads(first_text)
                    if len(result.content) == 1:
                        return json.loads(first_text)
                    return [json.loads(content.text) for content in result.content if content.text]
                return {"status": "error", "error_msg": "Empty tool response"}
    except asyncio.TimeoutError:
        raise asyncio.TimeoutError(f"ForexFactory MCP call exceeded {_MCP_TIMEOUT}s timeout.")
    except (ConnectionError, OSError) as e:
        raise MCPConnectionError(f"ForexFactory stdio server connection failed: {e}") from e
    except Exception as e:
        raise MCPConnectionError(f"ForexFactory stdio server unexpected error: {e}") from e
