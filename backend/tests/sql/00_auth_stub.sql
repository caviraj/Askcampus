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
