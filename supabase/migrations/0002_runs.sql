-- Promo Finder, Phase 2: persistent runs.
-- Run once in the Supabase dashboard: SQL Editor, New query, paste, Run. It only creates things that
-- do not exist yet; it changes and deletes nothing, and leaves the reviews table untouched.
--
-- A finished run is kept as files in the private bucket "promo-data", under <owner_hash>/<run_id>/,
-- plus one row here. The row is written only after every file is stored, so a row means a complete copy.
-- Security model as for reviews: Row Level Security on, no policies, so only the app's server (secret key)
-- can read or write. The app lists and opens only the runs whose owner_hash matches the visitor's private link.

create table if not exists public.runs (
    id                  text primary key check (char_length(id) between 1 and 200),
    owner_hash          text not null check (owner_hash ~ '^[0-9a-f]{64}$'),
    created_at          timestamptz not null default now(),
    mode                text not null check (mode in ('basic', 'ai_assisted')),
    title               text not null default '',
    input_file          text not null default '',
    complete            boolean not null default true,
    stopped_because     text,
    episodes_in_pack    integer,
    episodes_processed  integer,
    recommended_clips   integer,
    processing_seconds  numeric,
    files               text[] not null
);

create index if not exists runs_by_owner on public.runs (owner_hash, created_at desc);

alter table public.runs enable row level security;
revoke all on table public.runs from anon, authenticated;

-- The private bucket for run files. Not public: files are reachable only with the secret key.
insert into storage.buckets (id, name, public, file_size_limit)
values ('promo-data', 'promo-data', false, 10485760)
on conflict (id) do nothing;
