-- Promo Finder, Phase 1: persistent human reviews.
-- Run once in the Supabase dashboard: SQL Editor, New query, paste, Run.
--
-- Security model: Row Level Security is on and there are NO policies, so the public
-- (publishable / anon) key can neither read nor write this table. Only the app's server,
-- using its secret key from Streamlit secrets, can reach it. The app itself checks that a
-- visitor only reads their own reviews (reviewer_hash = sha256 of their private link code).
--
-- Rows are only ever added. Saving a clip again adds a newer row; the newest one counts.

create table if not exists public.reviews (
    review_id           uuid primary key,
    saved_at            timestamptz not null default now(),
    schema_version      text not null,
    reviewer_name       text not null check (char_length(reviewer_name) between 1 and 80),
    reviewer_hash       text not null check (reviewer_hash ~ '^[0-9a-f]{64}$'),
    run_id              text not null check (char_length(run_id) between 1 and 200),
    promos_sha256       text not null,
    selection_method    text not null,
    clip_key            text not null,
    promo_id            text not null,
    episode             integer not null,
    start_timestamp     text not null,
    end_timestamp       text not null,
    hook_quality        smallint not null check (hook_quality between 1 and 5),
    cliffhanger_quality smallint not null check (cliffhanger_quality between 1 and 5),
    clarity             smallint not null check (clarity between 1 and 5),
    overall_quality     smallint not null check (overall_quality between 1 and 5),
    would_publish       text not null check (would_publish in ('yes', 'no', 'maybe')),
    comments            text not null default '' check (char_length(comments) <= 5000)
);

create index if not exists reviews_by_reviewer
    on public.reviews (reviewer_hash, run_id, clip_key, saved_at desc);
create index if not exists reviews_by_run
    on public.reviews (run_id, clip_key, saved_at desc);

alter table public.reviews enable row level security;
revoke all on table public.reviews from anon, authenticated;

-- The current review per run, clip and reviewer: for reading in the dashboard and exporting.
create or replace view public.latest_reviews
with (security_invoker = true) as
select distinct on (run_id, clip_key, reviewer_hash) *
from public.reviews
order by run_id, clip_key, reviewer_hash, saved_at desc;

revoke all on table public.latest_reviews from anon, authenticated;
