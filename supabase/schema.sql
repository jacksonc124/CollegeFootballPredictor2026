-- One-time setup: paste this whole file into the Supabase SQL Editor for your project and
-- run it once. It creates the single table pick_log.py's sync_from_supabase()/
-- sync_to_supabase() use to persist the pick log across Streamlit Cloud redeploys.
--
-- Design: one row per synced file (path -> full file content as text), not one row per
-- logged pick. This mirrors the GitHub-branch sync it replaces (whole-file push/pull), so
-- all of pick_log.py's existing local-disk logic (dedup, locking, CSV backup/restore,
-- backfill_extras) is unaffected — it still reads/writes the same local JSONL files, just
-- synced to this table instead of a git branch. It also means adding a new optional field to
-- a logged pick (e.g. closing_spread_home for CLV tracking) never needs a schema migration:
-- the content column is opaque JSONL text, not individual typed columns.

create table if not exists app_files (
    path text primary key,
    content text not null,
    updated_at timestamptz not null default now()
);

-- Row Level Security on with no policies: only a request authenticated with the
-- service_role key (which bypasses RLS entirely) can read/write this table. The anon key,
-- if one is ever used elsewhere in this project, gets no access at all.
alter table app_files enable row level security;
