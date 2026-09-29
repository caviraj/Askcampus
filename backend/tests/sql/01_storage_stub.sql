-- Test-only stand-in for the parts of Supabase's `storage` schema that
-- 0003_documents_bucket.sql touches.
--
-- Without it that migration's guard sees no `storage` schema, skips the bucket
-- insert, and the test can only assert that the SQL parsed -- which is not the
-- same as asserting it works. With the stub the real INSERT ... ON CONFLICT runs,
-- so the column names, the MIME array and the idempotency are all exercised.
--
-- The columns and types are the ones the migration reads or writes; Supabase's
-- table has more, and none of them are referenced here.
--
-- It lives under tests/ and deliberately NOT under supabase/migrations/, so it can
-- never shadow the real storage.buckets on a Supabase project.

create schema if not exists storage;

create table if not exists storage.buckets (
  id text primary key,
  name text not null,
  public boolean default false,
  file_size_limit bigint,
  allowed_mime_types text[]
);
