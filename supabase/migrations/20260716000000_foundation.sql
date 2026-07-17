create table workspaces (id text primary key, created_at timestamptz not null default now());
create table evidence_items (id uuid primary key default gen_random_uuid(), workspace_id text not null references workspaces(id), quote text not null, created_at timestamptz not null default now());
create table decisions (id uuid primary key default gen_random_uuid(), workspace_id text not null references workspaces(id), statement text not null, category text not null, review_status text not null check (review_status in ('pending','confirmed','rejected')), evidence_id uuid not null references evidence_items(id), created_at timestamptz not null default now());
create table jobs (id uuid primary key default gen_random_uuid(), type text not null, idempotency_key text not null, status text not null default 'queued', payload jsonb not null default '{}', run_after timestamptz not null default now(), unique(type, idempotency_key));
create unique index current_memory_per_statement on decisions(workspace_id, statement) where review_status = 'confirmed';
insert into workspaces(id) values ('default') on conflict do nothing;
