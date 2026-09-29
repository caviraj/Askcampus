-- Test-only stand-in for Supabase's auth schema.
--
-- The migrations reference auth.users, which does not exist on a bare Postgres.
-- This file creates the minimum needed to apply them. It lives under tests/ and
-- deliberately NOT under supabase/migrations/, so it can never shadow the real
-- auth.users on a Supabase project.

create schema if not exists auth;

create table if not exists auth.users (
  id uuid primary key default gen_random_uuid(),
  email text,
  raw_user_meta_data jsonb default '{}'::jsonb,
  created_at timestamptz default now()
);

-- The Supabase API roles. Needed because the migrations grant to and revoke from
-- them by name, and a bare Postgres has none of them: `revoke all on ... from
-- anon` fails with 'role "anon" does not exist' before any table is created.
-- Guarded so re-running is harmless.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin noinherit;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin noinherit;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role nologin noinherit bypassrls;
  end if;
end
$$;
