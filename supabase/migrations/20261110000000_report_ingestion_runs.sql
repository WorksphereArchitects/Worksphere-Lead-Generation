-- Durable company-level annual-report discovery jobs.
-- Discovery is separate from report_processing_jobs because it runs before
-- an annual_reports row necessarily exists.

create table if not exists public.report_ingestion_runs (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references public.companies(id) on delete cascade,
    status text not null default 'processing' check (status in ('processing', 'completed', 'failed')),
    report_id uuid references public.annual_reports(id) on delete set null,
    result jsonb,
    failure_reason text,
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.report_ingestion_runs
    add column if not exists report_id uuid references public.annual_reports(id) on delete set null,
    add column if not exists result jsonb,
    add column if not exists failure_reason text,
    add column if not exists started_at timestamptz not null default now(),
    add column if not exists completed_at timestamptz,
    add column if not exists created_at timestamptz not null default now(),
    add column if not exists updated_at timestamptz not null default now();

create index if not exists ix_report_ingestion_runs_company_created
    on public.report_ingestion_runs (company_id, created_at desc);

create index if not exists ix_report_ingestion_runs_report
    on public.report_ingestion_runs (report_id)
    where report_id is not null;

create unique index if not exists ux_report_ingestion_runs_one_processing_per_company
    on public.report_ingestion_runs (company_id)
    where status = 'processing';

notify pgrst, 'reload schema';
