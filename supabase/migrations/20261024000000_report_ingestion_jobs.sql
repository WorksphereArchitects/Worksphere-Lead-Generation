create table if not exists public.report_ingestion_runs (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references public.companies(id) on delete cascade,
    status text not null check (status in ('processing', 'completed', 'failed')),
    report_id uuid references public.annual_reports(id) on delete set null,
    result jsonb,
    failure_reason text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists ix_report_ingestion_runs_company_created
    on public.report_ingestion_runs (company_id, created_at desc);

create unique index if not exists ux_report_ingestion_runs_one_processing_per_company
    on public.report_ingestion_runs (company_id)
    where status = 'processing';

alter table public.report_ingestion_runs enable row level security;
