"""
HTTP Server wrapper for MCP Obsidian
Allows HTTP access to MCP tools for integration with n8n and other HTTP clients
Supports both REST API and SSE (Server-Sent Events) for MCP protocol
"""
import json
import logging
from typing import Any, Dict
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()

from . import tools

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-obsidian-http")

app = FastAPI(
    title="MCP Obsidian HTTP API",
    description="HTTP wrapper for MCP Obsidian tools",
    version="0.2.1"
)

# Initialize tool handlers
tool_handlers = {}

def add_tool_handler(tool_class: tools.ToolHandler):
    global tool_handlers
    tool_handlers[tool_class.name] = tool_class

# Register all tools
add_tool_handler(tools.ListFilesInDirToolHandler())
add_tool_handler(tools.ListFilesInVaultToolHandler())
add_tool_handler(tools.GetFileContentsToolHandler())
add_tool_handler(tools.SearchToolHandler())
add_tool_handler(tools.PatchContentToolHandler())
add_tool_handler(tools.AppendContentToolHandler())
add_tool_handler(tools.PutContentToolHandler())
add_tool_handler(tools.DeleteFileToolHandler())
add_tool_handler(tools.ComplexSearchToolHandler())
add_tool_handler(tools.BatchGetFileContentsToolHandler())
add_tool_handler(tools.PeriodicNotesToolHandler())
add_tool_handler(tools.RecentPeriodicNotesToolHandler())
add_tool_handler(tools.RecentChangesToolHandler())


class ToolCallRequest(BaseModel):
    name: str
    arguments: Dict[str, Any]


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "MCP Obsidian HTTP API",
        "version": "0.2.1",
        "endpoints": {
            "health": "/health",
            "list_tools": "/tools/list",
            "call_tool": "/tools/call"
        }
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy", "service": "mcp-obsidian"}


@app.get("/tools/list")
async def list_tools():
    """List all available tools"""
    tools_list = []
    for name, handler in tool_handlers.items():
        tool_desc = handler.get_tool_description()
        tools_list.append({
            "name": tool_desc.name,
            "description": tool_desc.description,
            "inputSchema": tool_desc.inputSchema
        })
    return {"tools": tools_list}


@app.post("/tools/call")
async def call_tool(request: ToolCallRequest):
    """
    Call an MCP tool
    
    Request body:
    {
        "name": "tool_name",
        "arguments": {
            "arg1": "value1",
            "arg2": "value2"
        }
    }
    """
    try:
        logger.info(f"Calling tool: {request.name} with arguments: {request.arguments}")
        
        if request.name not in tool_handlers:
            raise HTTPException(
                status_code=404, 
                detail=f"Tool '{request.name}' not found. Available tools: {list(tool_handlers.keys())}"
            )
        
        handler = tool_handlers[request.name]
        result = handler.run_tool(request.arguments)
        
        # Convert result to dict if it's a list of TextContent objects
        if result and hasattr(result[0], 'text'):
            result_text = result[0].text
            try:
                # Try to parse as JSON
                result_data = json.loads(result_text)
            except:
                # If not JSON, return as plain text
                result_data = result_text
        else:
            result_data = result
        
        return JSONResponse(content={
            "success": True,
            "tool": request.name,
            "result": result_data
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calling tool {request.name}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sse")
async def sse_endpoint(request: Request):
    """
    SSE endpoint for MCP protocol compatibility with n8n MCP Client node
    Implements Server-Sent Events for streaming MCP messages
    """
    async def event_generator():
        try:
            # Send initial connection message
            yield f"data: {json.dumps({'type': 'connection', 'status': 'connected'})}\n\n"
            
            # Keep connection alive and wait for disconnect
            while True:
                if await request.is_disconnected():
                    break
                await asyncio.sleep(1)
                # Send keep-alive ping
                yield f": keep-alive\n\n"
                
        except Exception as e:
            logger.error(f"SSE error: {str(e)}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/sse")
async def sse_call_tool(request: Request):
    """
    Handle MCP tool calls via SSE POST
    This endpoint receives JSON-RPC 2.0 formatted requests
    """
    try:
        body = await request.json()
        
        # JSON-RPC 2.0 format
        if "jsonrpc" in body and body["jsonrpc"] == "2.0":
            method = body.get("method", "")
            params = body.get("params", {})
            request_id = body.get("id")
            
            # Handle different MCP methods
            if method == "tools/list":
                tools_list = []
                for name, handler in tool_handlers.items():
                    tool_desc = handler.get_tool_description()
                    tools_list.append({
                        "name": tool_desc.name,
                        "description": tool_desc.description,
                        "inputSchema": tool_desc.inputSchema
                    })
                
                return JSONResponse(content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"tools": tools_list}
                })
            
            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                
                if tool_name not in tool_handlers:
                    return JSONResponse(
                        status_code=200,
                        content={
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {
                                "code": -32601,
                                "message": f"Tool not found: {tool_name}"
                            }
                        }
                    )
                
                handler = tool_handlers[tool_name]
                result = handler.run_tool(arguments)
                
                # Convert result to proper format
                if result and hasattr(result[0], 'text'):
                    result_text = result[0].text
                    try:
                        result_data = json.loads(result_text)
                    except:
                        result_data = result_text
                else:
                    result_data = result
                
                return JSONResponse(content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result_data) if isinstance(result_data, (dict, list)) else result_data
                            }
                        ]
                    }
                })
            
            elif method == "initialize":
                # Handle MCP initialization
                return JSONResponse(content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {}
                        },
                        "serverInfo": {
                            "name": "mcp-obsidian",
                            "version": "0.2.1"
                        }
                    }
                })
            
            else:
                return JSONResponse(
                    status_code=200,
                    content={
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32601,
                            "message": f"Method not found: {method}"
                        }
                    }
                )
        
        # Fallback to simple format
        tool_name = body.get("name")
        arguments = body.get("arguments", {})
        
        if tool_name not in tool_handlers:
            raise HTTPException(status_code=404, detail=f"Tool not found: {tool_name}")
        
        handler = tool_handlers[tool_name]
        result = handler.run_tool(arguments)
        
        return JSONResponse(content={"success": True, "result": result})
        
    except Exception as e:
        logger.error(f"Error in SSE call: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "jsonrpc": "2.0",
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }
        )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("HTTP_PORT", "3000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
