-- Jobs + job_events tables.
--
-- Replaces the in-memory AgentBridge._jobs dict so a cold-stopped Fly
-- machine doesn't lose jobs between POST /generate and the SSE reconnect.
--
-- Run via `supabase db push` after `supabase link`. Idempotent.

create extension if not exists "pgcrypto";

create table if not exists public.jobs (
    id              text primary key,
    status          text not null check (status in ('queued','running','succeeded','failed')),
    prompt          text not null,
    pages           text,
    output_name     text not null default 'presentation.pptx',
    models          jsonb not null default '{}'::jsonb,
    attachments     jsonb not null default '[]'::jsonb,
    workspace       text,
    owner_sub       text,
    created_at      timestamptz not null default now(),
    started_at      timestamptz,
    finished_at     timestamptz,
    pptx_url        text,
    error           text
);

create index if not exists jobs_owner_created_idx
    on public.jobs (owner_sub, created_at desc);

create index if not exists jobs_status_idx
    on public.jobs (status)
    where status in ('queued','running');

create table if not exists public.job_events (
    id              bigserial primary key,
    job_id          text not null references public.jobs(id) on delete cascade,
    seq             int  not null,
    stage           text not null,
    message         text not null,
    percent         real,
    slide_index     int,
    slide_preview_url text,
    pptx_url        text,
    error           text,
    created_at      timestamptz not null default now(),
    unique (job_id, seq)
);

create index if not exists job_events_job_idx
    on public.job_events (job_id, seq);

-- Row-level security.
alter table public.jobs        enable row level security;
alter table public.job_events  enable row level security;

-- Service role bypasses RLS by default, so FastAPI (running with the service
-- role key) has full access. Authenticated users see only their own jobs.
drop policy if exists "read own jobs" on public.jobs;
create policy "read own jobs" on public.jobs
    for select to authenticated
    using (owner_sub = auth.jwt() ->> 'sub');

drop policy if exists "read own job events" on public.job_events;
create policy "read own job events" on public.job_events
    for select to authenticated
    using (
        exists (
            select 1 from public.jobs j
            where j.id = job_events.job_id and j.owner_sub = auth.jwt() ->> 'sub'
        )
    );

-- Enable Realtime so the frontend can optionally subscribe directly.
alter publication supabase_realtime add table public.job_events;
