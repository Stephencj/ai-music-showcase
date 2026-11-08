"""The song tools over HTTP (``/api/tools``), for clients that aren't MCP
clients — the local AI gateway calls these. Same tools, descriptions and
argument validation as the MCP server (:mod:`src.serve.song_tools`)."""

from __future__ import annotations

import inspect

from fastapi import APIRouter, Body, HTTPException, Request

router = APIRouter(prefix="/tools")


@router.get("")
def list_tools() -> list[dict]:
    """Every tool with its description and JSON-schema arguments."""
    from mcp.server.fastmcp.utilities.func_metadata import func_metadata
    from src.serve.song_tools import TOOLS
    return [{"name": fn.__name__, "description": inspect.cleandoc(fn.__doc__ or ""),
             "input_schema": func_metadata(fn).arg_model.model_json_schema()} for fn in TOOLS]


@router.post("/{name}")
def call_tool(name: str, request: Request, args: dict = Body(default_factory=dict)) -> dict:
    """Run one tool. The body is its arguments as a JSON object. Results that
    carry a job's files also get URLs this server serves them from."""
    from src.serve.song_tools import TOOLS_BY_NAME, ToolError, call
    if name not in TOOLS_BY_NAME:
        raise HTTPException(404, f"Unknown tool {name!r}")
    try:
        result = call(name, args)
    except ToolError as exc:
        raise HTTPException(400, str(exc))
    if isinstance(result, dict) and result.get("job_id") and result.get("files"):
        base = f"{str(request.base_url).rstrip('/')}/api/jobs/{result['job_id']}"
        files = result["files"]
        result["urls"] = {k: u for k, u in (("audio", f"{base}/audio" if files.get("audio_mp3") or files.get("audio_wav") else None),
                                             ("audio_wav", f"{base}/audio.wav" if files.get("audio_wav") else None),
                                             ("midi", f"{base}/midi" if files.get("midi") else None),
                                             ("pdf_zip", f"{base}/pdf" if files.get("pdf_zip") else None)) if u}
    return {"ok": True, "result": result}
