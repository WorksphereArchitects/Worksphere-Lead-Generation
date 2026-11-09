-- Additive annual-report processing queue and durable document metadata.
-- Execute this migration in Supabase before deploying the application changes.

alter table if exists public.annual_reports
    add column if not exists document_storage_bucket text,
    add column if not exists document_storage_path text,
    add column if not exists document_size_bytes bigint,
    add column if not exists document_sha256 text;

create table if not exists public.report_processing_jobs (
    id uuid primary key default gen_random_uuid(),
    annual_report_id uuid not null references public.annual_reports(id) on delete cascade,
    company_id uuid not null references public.companies(id) on delete cascade,
    status text not null default 'queued' check (status in ('queued', 'processing', 'completed', 'failed')),
    attempts integer not null default 0 check (attempts >= 0),
    max_attempts integer not null default 3 check (max_attempts between 1 and 10),
    worker_id text,
    github_run_id bigint,
    processing_run_id uuid,
    queued_at timestamptz not null default now(),
    started_at timestamptz,
    completed_at timestamptz,
    last_activity_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    last_error text,
    metadata jsonb not null default '{}'::jsonb
);

alter table public.report_processing_jobs
    add column if not exists worker_id text,
    add column if not exists github_run_id bigint,
    add column if not exists processing_run_id uuid,
    add column if not exists queued_at timestamptz not null default now(),
    add column if not exists started_at timestamptz,
    add column if not exists completed_at timestamptz,
    add column if not exists last_activity_at timestamptz not null default now(),
    add column if not exists updated_at timestamptz not null default now(),
    add column if not exists last_error text,
    add column if not exists metadata jsonb not null default '{}'::jsonb;

create index if not exists ix_report_processing_jobs_report_created
    on public.report_processing_jobs (annual_report_id, queued_at desc);
create index if not exists ix_report_processing_jobs_queue
    on public.report_processing_jobs (status, queued_at)
    where status = 'queued';
create unique index if not exists ux_report_jobs_one_active_report
    on public.report_processing_jobs (annual_report_id)
    where status in ('queued', 'processing');

create table if not exists public.report_processing_job_history (
    id bigint generated always as identity primary key,
    job_id uuid not null references public.report_processing_jobs(id) on delete cascade,
    status text not null,
    event text not null,
    attempt integer not null default 0,
    worker_id text,
    error_message text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists ix_report_job_history_job_created
    on public.report_processing_job_history (job_id, created_at desc);

insert into storage.buckets (id, name, public)
values ('annual-reports', 'annual-reports', false)
on conflict (id) do nothing;

create or replace function public.enqueue_report_processing_job(
    p_report_id uuid,
    p_retry boolean default false
)
returns public.report_processing_jobs
language plpgsql
security definer
set search_path = public
as $$
declare
    v_report public.annual_reports%rowtype;
    v_job public.report_processing_jobs%rowtype;
begin
    select * into v_report from public.annual_reports where id = p_report_id for update;
    if not found then raise exception 'annual_report_not_found'; end if;

    select * into v_job from public.report_processing_jobs
    where annual_report_id = p_report_id
    order by queued_at desc limit 1;

    if v_job.id is not null and v_job.status in ('queued', 'processing') then
        return v_job;
    end if;
    if v_job.id is not null and v_job.status = 'completed' then
        return v_job;
    end if;
    if v_job.id is not null and not p_retry then
        return v_job;
    end if;
    if v_job.id is null and v_report.processing_status = 'completed' then
        raise exception 'annual_report_already_completed';
    end if;
    if v_job.id is not null and v_job.attempts >= v_job.max_attempts then
        raise exception 'retry_limit_reached';
    end if;

    if v_job.id is not null then
        update public.report_processing_jobs
        set status = 'queued', worker_id = null, started_at = null,
            completed_at = null, last_error = null, last_activity_at = now(), updated_at = now()
        where id = v_job.id
        returning * into v_job;
    else
        insert into public.report_processing_jobs (annual_report_id, company_id)
        values (p_report_id, v_report.company_id)
        returning * into v_job;
    end if;

    update public.annual_reports set processing_status = 'pending' where id = p_report_id;
    insert into public.report_processing_job_history (job_id, status, event, attempt)
    values (v_job.id, 'queued', case when p_retry then 'retry_queued' else 'queued' end, v_job.attempts);
    return v_job;
end;
$$;

create or replace function public.claim_report_processing_job(
    p_job_id uuid,
    p_report_id uuid,
    p_worker_id text
)
returns public.report_processing_jobs
language plpgsql
security definer
set search_path = public
as $$
declare v_job public.report_processing_jobs%rowtype;
begin
    update public.report_processing_jobs
    set status = 'processing', attempts = attempts + 1, worker_id = p_worker_id,
        started_at = coalesce(started_at, now()), last_activity_at = now(), updated_at = now()
    where id = p_job_id and annual_report_id = p_report_id and status = 'queued'
    returning * into v_job;
    if v_job.id is null then return null; end if;
    update public.annual_reports set processing_status = 'processing' where id = p_report_id;
    insert into public.report_processing_job_history (job_id, status, event, attempt, worker_id)
    values (v_job.id, 'processing', 'claimed', v_job.attempts, p_worker_id);
    return v_job;
end;
$$;

create or replace function public.heartbeat_report_processing_job(
    p_job_id uuid,
    p_worker_id text
)
returns boolean
language sql
security definer
set search_path = public
as $$
    update public.report_processing_jobs
    set last_activity_at = now(), updated_at = now()
    where id = p_job_id and worker_id = p_worker_id and status = 'processing'
    returning true;
$$;

create or replace function public.complete_report_processing_job(
    p_job_id uuid,
    p_worker_id text,
    p_processing_run_id uuid default null,
    p_metadata jsonb default '{}'::jsonb
)
returns public.report_processing_jobs
language plpgsql
security definer
set search_path = public
as $$
declare v_job public.report_processing_jobs%rowtype;
begin
    update public.report_processing_jobs
    set status = 'completed', processing_run_id = coalesce(p_processing_run_id, processing_run_id),
        completed_at = now(), last_activity_at = now(), updated_at = now(), worker_id = null,
        last_error = null, metadata = coalesce(metadata, '{}'::jsonb) || coalesce(p_metadata, '{}'::jsonb)
    where id = p_job_id and worker_id = p_worker_id and status = 'processing'
    returning * into v_job;
    if v_job.id is null then return null; end if;
    update public.annual_reports set processing_status = 'completed' where id = v_job.annual_report_id;
    insert into public.report_processing_job_history (job_id, status, event, attempt, worker_id, metadata)
    values (v_job.id, 'completed', 'completed', v_job.attempts, p_worker_id, p_metadata);
    return v_job;
end;
$$;

create or replace function public.fail_report_processing_job(
    p_job_id uuid,
    p_worker_id text,
    p_error text,
    p_retryable boolean default true
)
returns public.report_processing_jobs
language plpgsql
security definer
set search_path = public
as $$
declare v_job public.report_processing_jobs%rowtype; v_status text;
begin
    select * into v_job from public.report_processing_jobs
    where id = p_job_id and worker_id = p_worker_id and status = 'processing' for update;
    if not found then return null; end if;
    v_status := case when p_retryable and v_job.attempts < v_job.max_attempts then 'queued' else 'failed' end;
    update public.report_processing_jobs
    set status = v_status, worker_id = null, completed_at = case when v_status = 'failed' then now() else null end,
        last_error = left(coalesce(p_error, 'Unknown processing failure'), 4000), last_activity_at = now(), updated_at = now()
    where id = p_job_id returning * into v_job;
    update public.annual_reports set processing_status = case when v_status = 'failed' then 'failed' else 'pending' end
    where id = v_job.annual_report_id;
    insert into public.report_processing_job_history (job_id, status, event, attempt, worker_id, error_message)
    values (v_job.id, v_status, case when v_status = 'queued' then 'retry_queued' else 'failed' end,
            v_job.attempts, p_worker_id, left(coalesce(p_error, 'Unknown processing failure'), 4000));
    return v_job;
end;
$$;

create or replace function public.recover_stale_report_processing_jobs(
    p_stale_after interval default interval '20 minutes'
)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare v_count integer;
begin
    with recovered as (
        update public.report_processing_jobs
        set status = case when attempts < max_attempts then 'queued' else 'failed' end,
            worker_id = null, last_error = 'Worker heartbeat expired', updated_at = now(), last_activity_at = now(),
            completed_at = case when attempts >= max_attempts then now() else null end
        where status = 'processing' and last_activity_at < now() - p_stale_after
        returning id, annual_report_id, status, attempts, last_error
    ), history as (
        insert into public.report_processing_job_history (job_id, status, event, attempt, error_message)
        select id, status, case when status = 'queued' then 'stale_requeued' else 'stale_failed' end,
               attempts, last_error from recovered returning job_id
    )
    update public.annual_reports r set processing_status = case when j.status = 'failed' then 'failed' else 'pending' end
    from recovered j where r.id = j.annual_report_id;
    get diagnostics v_count = row_count;
    return v_count;
end;
$$;

grant execute on function public.enqueue_report_processing_job(uuid, boolean) to service_role;
grant execute on function public.claim_report_processing_job(uuid, uuid, text) to service_role;
grant execute on function public.heartbeat_report_processing_job(uuid, text) to service_role;
grant execute on function public.complete_report_processing_job(uuid, text, uuid, jsonb) to service_role;
grant execute on function public.fail_report_processing_job(uuid, text, text, boolean) to service_role;
grant execute on function public.recover_stale_report_processing_jobs(interval) to service_role;
