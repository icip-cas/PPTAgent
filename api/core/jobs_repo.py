"""Postgres-backed job + event repository.

All persistence goes through the Supabase REST API (PostgREST) so we don't
pin a psycopg dependency. The service-role key bypasses RLS so FastAPI can
read and write any row.

The repo is intentionally thin - it owns persistence only, not orchestration.
`AgentBridge` still schedules work and translates ChatMessages; it just
checkpoints each state transition here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from ..schemas import GenerateEvent, GenerateRequest
from ..settings import Settings, get_settings

logger = logging.getLogger("api.jobs_repo")

_TERMINAL = ("succeeded", "failed")


@dataclass(slots=True)
class JobRecord:
    id: str
    status: str
    request: GenerateRequest
    workspace: str | None
    owner_sub: str | None
    pptx_url: str | None = None
    error: str | None = None


class JobsRepo:
    """PostgREST client for the public.jobs and public.job_events tables."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._base = f"{self.settings.supabase_url.rstrip('/')}/rest/v1" if self.settings.supabase_url else ""
        self._headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
            "content-type": "application/json",
            "Prefer": "return=representation",
        }

    @property
    def enabled(self) -> bool:
        """Repo is a no-op when Supabase isn't configured (local dev)."""
        return bool(self._base and self.settings.supabase_service_role_key)

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    async def insert_job(
        self,
        *,
        job_id: str,
        request: GenerateRequest,
        workspace: str,
        owner_sub: str | None,
    ) -> None:
        if not self.enabled:
            return
        payload = {
            "id": job_id,
            "status": "queued",
            "prompt": request.prompt,
            "pages": request.pages,
            "output_name": request.output_name,
            "models": request.models.model_dump(exclude_none=True),
            "attachments": request.attachments,
            "workspace": workspace,
            "owner_sub": owner_sub,
        }
        await self._post("/jobs", payload)

    async def mark_status(
        self,
        job_id: str,
        status: str,
        *,
        pptx_url: str | None = None,
        error: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        patch: dict[str, Any] = {"status": status}
        if status == "running":
            patch["started_at"] = "now()"
        if status in _TERMINAL:
            patch["finished_at"] = "now()"
        if pptx_url is not None:
            patch["pptx_url"] = pptx_url
        if error is not None:
            patch["error"] = error
        await self._patch(f"/jobs?id=eq.{job_id}", patch)

    async def load_job(self, job_id: str) -> JobRecord | None:
        if not self.enabled:
            return None
        rows = await self._get(f"/jobs?id=eq.{job_id}&select=*&limit=1")
        if not rows:
            return None
        row = rows[0]
        req = GenerateRequest.model_validate(
            {
                "prompt": row["prompt"],
                "pages": row.get("pages"),
                "output_name": row.get("output_name", "presentation.pptx"),
                "models": row.get("models") or {},
                "attachments": row.get("attachments") or [],
            }
        )
        return JobRecord(
            id=row["id"],
            status=row["status"],
            request=req,
            workspace=row.get("workspace"),
            owner_sub=row.get("owner_sub"),
            pptx_url=row.get("pptx_url"),
            error=row.get("error"),
        )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def append_event(self, job_id: str, seq: int, event: GenerateEvent) -> None:
        if not self.enabled:
            return
        payload = {
            "job_id": job_id,
            "seq": seq,
            "stage": event.stage,
            "message": event.message,
            "percent": event.percent,
            "slide_index": event.slide_index,
            "slide_preview_url": event.slide_preview_url,
            "pptx_url": event.pptx_url,
            "error": event.error,
        }
        await self._post("/job_events", payload)

    async def load_events(self, job_id: str, after_seq: int = 0) -> list[GenerateEvent]:
        if not self.enabled:
            return []
        rows = await self._get(
            f"/job_events?job_id=eq.{job_id}&seq=gt.{after_seq}&order=seq.asc&select=*"
        )
        out: list[GenerateEvent] = []
        for row in rows:
            out.append(
                GenerateEvent(
                    job_id=job_id,
                    stage=row["stage"],
                    message=row["message"],
                    percent=row.get("percent"),
                    slide_index=row.get("slide_index"),
                    slide_preview_url=row.get("slide_preview_url"),
                    pptx_url=row.get("pptx_url"),
                    error=row.get("error"),
                )
            )
        return out

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------

    async def _post(self, path: str, body: Any) -> Any:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(self._base + path, json=body, headers=self._headers)
        if res.status_code >= 400:
            logger.warning("jobs_repo POST %s failed: %s %s", path, res.status_code, res.text[:200])
            res.raise_for_status()
        return res.json() if res.content else None

    async def _patch(self, path: str, body: Any) -> Any:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.patch(self._base + path, json=body, headers=self._headers)
        if res.status_code >= 400:
            logger.warning("jobs_repo PATCH %s failed: %s %s", path, res.status_code, res.text[:200])
            res.raise_for_status()
        return res.json() if res.content else None

    async def _get(self, path: str) -> list[Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(self._base + path, headers=self._headers)
        if res.status_code >= 400:
            logger.warning("jobs_repo GET %s failed: %s %s", path, res.status_code, res.text[:200])
            res.raise_for_status()
        return res.json() if res.content else []
