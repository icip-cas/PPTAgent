"""Async bridge between FastAPI and deeppresenter's AgentLoop.

Design notes:

* We do NOT mutate anything inside `deeppresenter/`. A `DeepPresenterConfig`
  is built at runtime pointing every `LLM.base_url` at the Supabase Edge
  Function, so the Google API key never hits this process.
* `AgentLoop.run()` is an `AsyncGenerator[str | ChatMessage, None]` - intermediate
  yields are `ChatMessage` instances, the final yield is the PPTX path.
  We consume it via `async for` and map each `ChatMessage` onto a streamed
  `GenerateEvent`.
* Jobs are kept in-memory with a TTL sweeper. A late-subscribing SSE client
  gets the terminal event replayed so races between `POST /generate` and
  `GET /generate/{id}/events` do not lose the final URL.
* Paths from the client (`attachments`, `output_name`) are sanitized before
  they are ever handed to the untrusted filesystem-touching upstream code.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, AsyncIterator

from ..schemas import GenerateEvent, GenerateRequest
from ..settings import Settings, get_settings
from .jobs_repo import JobsRepo
from .supabase import StorageClient

logger = logging.getLogger("api.bridge")

# Keep terminal jobs around this long so reconnecting SSE clients can replay
# the final event instead of hanging forever on a drained queue.
_TERMINAL_JOB_TTL_SECONDS = 60 * 60  # 1h


# ---------------------------------------------------------------------------
# Runtime config assembly
# ---------------------------------------------------------------------------

def _sanitize_filename(name: str, default: str = "presentation.pptx") -> str:
    """Return a filename safe to concatenate into a storage path.

    Strips directory components, replaces anything outside the allowlist,
    and enforces a maximum length. Rejects empty results.
    """
    if not name:
        return default
    # `PurePosixPath.name` handles both "../foo" and "C:\\bar" by taking the
    # final component.
    bare = PurePosixPath(name.replace("\\", "/")).name or default
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", bare)[:120]
    return safe or default


def _sanitize_attachment_ref(ref: str) -> str:
    """Accept only `uploads/<segment>` style references from the client.

    The client is expected to upload attachments through `/generate/attachment`,
    which returns a relative object path under `uploads/`. We refuse anything
    else to stop the client from forcing the bridge to read `/etc/passwd`.
    """
    if not ref:
        raise ValueError("empty attachment reference")
    clean = ref.replace("\\", "/").lstrip("/")
    parts = PurePosixPath(clean).parts
    if not parts or parts[0] not in ("uploads", "demo"):
        raise ValueError(f"attachment reference {ref!r} is not under uploads/")
    if any(p in ("..", "") for p in parts):
        raise ValueError(f"attachment reference {ref!r} contains a traversal segment")
    return str(PurePosixPath(*parts))


def build_runtime_config(
    req: GenerateRequest,
    settings: Settings,
    workspace: Path,
) -> dict[str, Any]:
    """Produce the dict that `DeepPresenterConfig.model_validate` expects.

    Every LLM section points at the Supabase Edge Function, so the OpenAI
    client inside deeppresenter authenticates as the Supabase service-role
    JWT and the real Google key stays out of this process.
    """
    edge_url = settings.supabase_edge_function_url.rstrip("/")
    base_url = edge_url or "http://localhost:54321/functions/v1/llm-proxy"
    api_key = settings.supabase_service_role_key
    if not api_key:
        # Fail loudly rather than silently using a fake token.
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not configured")

    def section(model_id: str) -> dict[str, Any]:
        return {"base_url": base_url, "model": model_id, "api_key": api_key}

    m = req.models
    cfg: dict[str, Any] = {
        # `file_path` is required by DeepPresenterConfig even though we load the
        # config from memory; point it at a sentinel inside the workspace.
        "file_path": str(workspace / "runtime-config.yaml"),
        "offline_mode": settings.offline_mode,
        "context_folding": True,
        "research_agent": section(m.research_agent or settings.default_chat_model),
        "design_agent": section(m.design_agent or settings.default_design_model),
        "long_context_model": section(
            m.long_context_model or settings.default_long_context_model
        ),
    }
    if m.vision_model or settings.default_vision_model:
        cfg["vision_model"] = section(m.vision_model or settings.default_vision_model)
    if m.t2i_model or settings.default_t2i_model:
        cfg["t2i_model"] = section(m.t2i_model or settings.default_t2i_model)
    return cfg


# ---------------------------------------------------------------------------
# Job bookkeeping
# ---------------------------------------------------------------------------

@dataclass
class Job:
    job_id: str
    request: GenerateRequest
    workspace: Path
    queue: asyncio.Queue[GenerateEvent] = field(default_factory=asyncio.Queue)
    task: asyncio.Task | None = None
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    # Replay buffer so late subscribers see the whole stream.
    history: list[GenerateEvent] = field(default_factory=list)
    # Monotonic sequence number for the Postgres job_events table.
    event_seq: int = 0


class BridgeError(RuntimeError):
    """Raised when the PPTAgent runtime is unavailable."""


# ---------------------------------------------------------------------------
# ChatMessage → GenerateEvent mapping
# ---------------------------------------------------------------------------

def _infer_stage(text: str, default: str) -> str:
    t = text.lower()
    if "research" in t or "manuscript" in t or "outline" in t:
        return "research"
    if "design" in t or "slide" in t or "html" in t:
        return "design"
    if "pptx" in t or "html2pptx" in t or "convert" in t:
        return "render"
    return default


def _message_to_event(job_id: str, msg: Any, *, stage: str = "log") -> GenerateEvent:
    """Best-effort translation of a deeppresenter ChatMessage into our schema.

    We don't import ChatMessage directly to keep this file importable without
    deeppresenter at hand (so `/health` and `/models` still work on a clean
    install).
    """
    text = getattr(msg, "text", None)
    if text is None:
        text = str(msg)
    resolved_stage = _infer_stage(text, stage)
    return GenerateEvent(
        job_id=job_id,
        stage=resolved_stage,  # type: ignore[arg-type]
        message=text[:400],
    )


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------

class AgentBridge:
    """Owns live jobs and drives `deeppresenter.main.AgentLoop`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._jobs: dict[str, Job] = {}
        self._storage = StorageClient(self.settings)
        self._repo = JobsRepo(self.settings)
        self._sweeper_task: asyncio.Task | None = None

    async def start_background_tasks(self) -> None:
        if self._sweeper_task is None or self._sweeper_task.done():
            self._sweeper_task = asyncio.create_task(self._ttl_sweeper(), name="ttl-sweeper")

    async def _ttl_sweeper(self) -> None:
        """Evict terminal jobs older than TTL so memory doesn't grow forever."""
        while True:
            try:
                await asyncio.sleep(300)
                cutoff = time.time() - _TERMINAL_JOB_TTL_SECONDS
                drop = [
                    jid for jid, j in self._jobs.items()
                    if j.finished_at is not None and j.finished_at < cutoff
                ]
                for jid in drop:
                    self._jobs.pop(jid, None)
                if drop:
                    logger.info("evicted %d terminal jobs", len(drop))
            except asyncio.CancelledError:
                return
            except Exception:  # noqa: BLE001 - sweeper must never die
                logger.exception("sweeper iteration failed")

    # ------------------------------------------------------------------
    # Job lifecycle
    # ------------------------------------------------------------------

    def start(self, request: GenerateRequest, owner_sub: str | None = None) -> Job:
        job_id = uuid.uuid4().hex
        workspace = self.settings.workspace_base / job_id
        workspace.mkdir(parents=True, exist_ok=True)
        job = Job(job_id=job_id, request=request, workspace=workspace)
        self._jobs[job_id] = job
        job.task = asyncio.create_task(
            self._run(job, owner_sub=owner_sub), name=f"agentloop:{job_id}"
        )
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def restore(self, job_id: str) -> Job | None:
        """Hydrate an in-memory Job from Postgres.

        Only useful when a previous machine handled `start()` and this one
        is handling the SSE reconnect. Events are replayed from the DB.
        """
        if job_id in self._jobs:
            return self._jobs[job_id]
        rec = await self._repo.load_job(job_id)
        if rec is None:
            return None
        workspace = self.settings.workspace_base / rec.id
        job = Job(job_id=rec.id, request=rec.request, workspace=workspace)
        job.status = rec.status
        past = await self._repo.load_events(rec.id)
        job.history.extend(past)
        job.event_seq = len(past)
        if rec.status in ("succeeded", "failed"):
            job.finished_at = time.time()
        self._jobs[job_id] = job
        return job

    # ------------------------------------------------------------------
    # Event streaming with replay
    # ------------------------------------------------------------------

    async def events(self, job_id: str) -> AsyncIterator[GenerateEvent]:
        job = self._jobs.get(job_id)
        if not job:
            return
        # Replay everything the job has already emitted.
        for ev in list(job.history):
            yield ev
            if ev.stage in ("done", "error"):
                return
        while True:
            try:
                ev = await asyncio.wait_for(job.queue.get(), timeout=300)
            except asyncio.TimeoutError:
                # Send a keepalive-ish log event so intermediaries don't kill
                # the SSE socket during a long silent deeppresenter phase.
                yield GenerateEvent(job_id=job_id, stage="log", message="(heartbeat)")
                continue
            yield ev
            if ev.stage in ("done", "error"):
                break

    async def _emit(self, job: Job, ev: GenerateEvent) -> None:
        job.history.append(ev)
        job.event_seq += 1
        await job.queue.put(ev)
        # Best-effort persistence - never block the pipeline on a DB hiccup.
        try:
            await self._repo.append_event(job.job_id, job.event_seq, ev)
        except Exception:  # noqa: BLE001
            logger.exception("failed to persist event seq=%d", job.event_seq)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def _run(self, job: Job, owner_sub: str | None = None) -> None:
        try:
            # Persist the queued row first so the SSE endpoint can find it
            # even if the machine dies before the first event is emitted.
            try:
                await self._repo.insert_job(
                    job_id=job.job_id,
                    request=job.request,
                    workspace=str(job.workspace),
                    owner_sub=owner_sub,
                )
            except Exception:  # noqa: BLE001
                logger.exception("failed to persist job row")

            job.status = "running"
            try:
                await self._repo.mark_status(job.job_id, "running")
            except Exception:  # noqa: BLE001
                logger.exception("failed to mark job running")
            await self._emit(
                job,
                GenerateEvent(job_id=job.job_id, stage="log", message="job queued"),
            )

            try:
                from deeppresenter.main import AgentLoop  # type: ignore
                from deeppresenter.utils.config import DeepPresenterConfig  # type: ignore
                from deeppresenter.utils.typings import (  # type: ignore
                    ConvertType,
                    InputRequest,
                )
            except Exception as exc:  # pragma: no cover - surfaced to client
                raise BridgeError(
                    "deeppresenter is not importable. Install with "
                    "`uv pip install -e .` inside WSL2 and ensure Docker "
                    "Desktop is running."
                ) from exc

            config_dict = build_runtime_config(job.request, self.settings, job.workspace)
            config = DeepPresenterConfig.model_validate(config_dict)

            # Sanitize every attachment path - the upstream layer will copy
            # these files into the workspace, so a traversal would let a
            # client read arbitrary files off the FastAPI host.
            try:
                clean_attachments = [
                    _sanitize_attachment_ref(p) for p in job.request.attachments
                ]
            except ValueError as exc:
                raise BridgeError(str(exc)) from exc
            # Resolve to absolute filesystem paths under the workspace.
            resolved = [str((job.workspace / rel).resolve()) for rel in clean_attachments]

            request = InputRequest(
                instruction=job.request.prompt,
                attachments=resolved,
                num_pages=job.request.pages,
                convert_type=ConvertType.PPTAGENT,
            )

            loop_impl = AgentLoop(
                config=config,
                session_id=job.job_id[:8],
                workspace=job.workspace,
                language="ko",
            )

            await self._emit(
                job,
                GenerateEvent(
                    job_id=job.job_id,
                    stage="research",
                    message="AgentLoop started",
                    percent=0.05,
                ),
            )

            final_path: Path | None = None
            current_stage = "research"
            async for msg in loop_impl.run(request):
                if isinstance(msg, (str, Path)):
                    final_path = Path(msg)
                    break
                ev = _message_to_event(job.job_id, msg, stage=current_stage)
                current_stage = ev.stage  # advance
                await self._emit(job, ev)

            if final_path is None or not final_path.exists():
                raise BridgeError("AgentLoop exited without producing a PPTX file")

            # Upload and emit terminal event
            safe_name = _sanitize_filename(job.request.output_name, "presentation.pptx")
            object_path = f"{job.job_id}/{safe_name}"
            await self._emit(
                job,
                GenerateEvent(
                    job_id=job.job_id,
                    stage="upload",
                    message="uploading PPTX to storage",
                    percent=0.95,
                ),
            )
            await self._storage.upload_file(
                final_path,
                object_path,
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
            url = await self._storage.signed_url(object_path, expires_in=3600)

            job.status = "succeeded"
            with contextlib.suppress(Exception):
                await self._repo.mark_status(job.job_id, "succeeded", pptx_url=url)
            await self._emit(
                job,
                GenerateEvent(
                    job_id=job.job_id,
                    stage="done",
                    message="presentation ready",
                    percent=1.0,
                    pptx_url=url,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to client
            logger.exception("job %s failed", job.job_id)
            job.status = "failed"
            with contextlib.suppress(Exception):
                await self._repo.mark_status(
                    job.job_id, "failed", error=str(exc)[:500]
                )
            # Don't leak raw exception text; callers see a generic code, full
            # detail is in the server log above.
            safe_msg = (
                str(exc)
                if isinstance(exc, BridgeError)
                else "generation failed - see server log"
            )
            await self._emit(
                job,
                GenerateEvent(
                    job_id=job.job_id,
                    stage="error",
                    message="generation failed",
                    error=safe_msg,
                ),
            )
        finally:
            job.finished_at = time.time()

    async def close(self) -> None:
        if self._sweeper_task and not self._sweeper_task.done():
            self._sweeper_task.cancel()
            with contextlib.suppress(Exception):
                await self._sweeper_task
        for job in list(self._jobs.values()):
            if job.task and not job.task.done():
                job.task.cancel()
                with contextlib.suppress(Exception):
                    await job.task
