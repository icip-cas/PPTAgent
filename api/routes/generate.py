"""/generate (SSE) and /generate/ws (WebSocket) endpoints.

The frontend may use either transport. SSE is simpler and plays nicely with
plain `fetch` streaming; WebSocket is used when we need bidirectional
messages (cancel, resume, attachment chunking) later.
"""

from __future__ import annotations

import contextlib
import json
import re
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from sse_starlette.sse import EventSourceResponse

from ..core import AgentBridge
from ..schemas import GenerateJob, GenerateRequest
from ..settings import Settings, get_settings
from .deps import get_bridge, require_auth, require_auth_ws

router = APIRouter(prefix="/generate", tags=["generate"])


_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str | None) -> str:
    """Strip directory separators and restrict to a conservative charset."""
    base = (name or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    clean = _FILENAME_SAFE.sub("_", base)[:120]
    return clean or "upload"


@router.post("", response_model=GenerateJob)
async def create_job(
    request: GenerateRequest,
    bridge: AgentBridge = Depends(get_bridge),
    auth: dict = Depends(require_auth),
) -> GenerateJob:
    owner_sub = auth.get("sub") if isinstance(auth, dict) else None
    job = bridge.start(request, owner_sub=owner_sub)
    return GenerateJob(
        job_id=job.job_id,
        status=job.status,  # type: ignore[arg-type]
        workspace=str(job.workspace),
        created_at=job.created_at,
    )


@router.get("/{job_id}/events")
async def stream_events(
    job_id: str,
    bridge: AgentBridge = Depends(get_bridge),
    _auth: dict = Depends(require_auth),
) -> EventSourceResponse:
    # Fall back to Postgres restore so reconnects after a cold-stop still work.
    job = bridge.get(job_id) or await bridge.restore(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    async def event_gen() -> AsyncIterator[dict[str, str]]:
        async for ev in bridge.events(job_id):
            yield {
                "event": ev.stage,
                "data": ev.model_dump_json(exclude_none=True),
            }

    return EventSourceResponse(event_gen())


@router.websocket("/ws/{job_id}")
async def websocket_events(
    websocket: WebSocket,
    job_id: str,
    bridge: AgentBridge = Depends(get_bridge),
) -> None:
    # WebSocket auth piggybacks on the query string (`?token=...`) because
    # browsers can't attach an Authorization header to native WebSockets.
    ok = await require_auth_ws(websocket)
    if not ok:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    job = bridge.get(job_id)
    if not job:
        await websocket.send_text(json.dumps({"stage": "error", "message": "job not found"}))
        await websocket.close()
        return
    try:
        async for ev in bridge.events(job_id):
            await websocket.send_text(ev.model_dump_json(exclude_none=True))
            if ev.stage in ("done", "error"):
                break
    except WebSocketDisconnect:
        return
    finally:
        with contextlib.suppress(Exception):
            await websocket.close()


@router.post("/attachment", tags=["generate"])
async def upload_attachment(
    file: UploadFile,
    settings: Settings = Depends(get_settings),
    _auth: dict = Depends(require_auth),
) -> dict[str, str]:
    """Accept a user attachment and forward it to Supabase Storage.

    The client-supplied filename is sanitized and prefixed with a server-
    generated UUID, so a malicious actor can't overwrite other objects or
    escape the `uploads/` namespace.
    """
    from ..core.supabase import StorageClient

    limit = settings.max_upload_mb * 1024 * 1024
    # Stream-read with a hard cap - don't rely on declared Content-Length.
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail="attachment too large")

    name = _safe_filename(file.filename)
    object_path = f"uploads/{uuid.uuid4().hex[:12]}/{name}"
    client = StorageClient(settings)
    await client.upload(object_path, data, file.content_type or "application/octet-stream")
    signed = await client.signed_url(object_path, expires_in=3600)
    return {"object_path": object_path, "signed_url": signed}
