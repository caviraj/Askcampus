-- ============================================================================
-- CAMPUSASK COMPLETE SUPABASE SCHEMA (Migrations 0001 to 0007)
-- Run this in Supabase Dashboard -> SQL Editor -> Run
-- ============================================================================

-- ============================================================================
-- 1. EXTENSIONS & INITIAL SCHEMA (0001_initial_schema.sql)
-- ============================================================================

create extension if not exists vector;

create table if not exists profiles (
  id uuid primary key references auth.users on delete cascade,
  full_name text,
  role text not null default 'staff' check (role in ('staff','admin'))
);

create table if not exists documents (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  category text not null check (category in
    ('examinations','admissions','departments','events','academic_processes','general')),
  academic_year text,
  department text,
  file_path text not null,
  file_type text not null,
  content_hash text,
  status text not null default 'uploaded'
    check (status in ('uploaded','processing','ready','failed')),
  is_active boolean not null default true,
  error_message text,
  uploaded_by uuid references profiles(id) on delete set null,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references documents(id) on delete cascade,
  chunk_index int not null,
  page_number int,
  section_heading text,
  content text not null,
  category text not null,
  embedding vector(768),
  fts tsvector generated always as (to_tsvector('english', content)) stored
);
create index if not exists chunks_embedding_idx on chunks using hnsw (embedding vector_cosine_ops);
create index if not exists chunks_fts_idx on chunks using gin (fts);
create index if not exists chunks_doc_idx on chunks (document_id);

create table if not exists queries (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null,
  question text not null,
  normalized_hash text not null,
  category text,
  answer text,
  answered boolean not null,
  top_score real,
  latency_ms int,
  created_at timestamptz default now()
);
create index if not exists queries_normalized_hash_idx on queries (normalized_hash);
create index if not exists queries_created_at_idx on queries (created_at desc);

create table if not exists query_sources (
  query_id uuid not null references queries(id) on delete cascade,
  rank int not null,
  chunk_id uuid references chunks(id) on delete set null,
  score real,
  document_id uuid,
  document_title text,
  page_number int,
  section_heading text,
  primary key (query_id, rank)
);

create table if not exists unanswered_queries (
  id uuid primary key default gen_random_uuid(),
  query_id uuid references queries(id) on delete cascade,
  normalized_hash text not null,
  question text not null,
  category text,
  status text not null default 'open' check (status in ('open','resolved')),
  resolved_by_document uuid references documents(id) on delete set null,
  created_at timestamptz default now()
);
create index if not exists unanswered_hash_idx on unanswered_queries (normalized_hash);
create index if not exists unanswered_status_created_idx on unanswered_queries (status, created_at desc);

create table if not exists feedback (
  query_id uuid primary key references queries(id) on delete cascade,
  helpful boolean not null,
  created_at timestamptz default now()
);

alter table profiles           enable row level security;
alter table documents          enable row level security;
alter table chunks             enable row level security;
alter table queries            enable row level security;
alter table query_sources      enable row level security;
alter table unanswered_queries enable row level security;
alter table feedback           enable row level security;

revoke all on profiles, documents, chunks, queries, query_sources,
  unanswered_queries, feedback from anon, authenticated;

-- Triggers
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, full_name)
  values (new.id, new.raw_user_meta_data ->> 'full_name')
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists documents_set_updated_at on public.documents;
create trigger documents_set_updated_at
  before update on public.documents
  for each row execute function public.set_updated_at();

create or replace function public.sync_chunk_category()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  update public.chunks
     set category = new.category
   where document_id = new.id
     and category <> new.category;
  return new;
end;
$$;

drop trigger if exists documents_sync_chunk_category on public.documents;
create trigger documents_sync_chunk_category
  after update of category on public.documents
  for each row execute function public.sync_chunk_category();

-- ============================================================================
-- 2. HYBRID SEARCH (0002_hybrid_search.sql)
-- ============================================================================

create or replace function hybrid_search(
  query_text text,
  query_embedding vector(768),
  match_count int default 5,
  filter_category text default null
) returns table (
  chunk_id uuid,
  document_id uuid,
  score float,
  similarity float
)
language sql
stable
as $$
  with semantic as (
    select
      c.id,
      row_number() over (order by c.embedding <=> query_embedding) as r,
      1 - (c.embedding <=> query_embedding) as sim
    from chunks c
    join documents d on d.id = c.document_id
    where d.is_active
      and d.status = 'ready'
      and c.embedding is not null
      and (filter_category is null or d.category = filter_category)
    order by c.embedding <=> query_embedding
    limit 20
  ),
  keyword as (
    select
      c.id,
      row_number() over (
        order by ts_rank(c.fts, websearch_to_tsquery('english', query_text)) desc
      ) as r
    from chunks c
    join documents d on d.id = c.document_id
    where d.is_active
      and d.status = 'ready'
      and c.fts @@ websearch_to_tsquery('english', query_text)
      and (filter_category is null or d.category = filter_category)
    order by ts_rank(c.fts, websearch_to_tsquery('english', query_text)) desc
    limit 20
  )
  select
    c.id,
    c.document_id,
    coalesce(1.0 / (60 + s.r), 0) + coalesce(1.0 / (60 + k.r), 0) as score,
    s.sim as similarity
  from chunks c
  left join semantic s on s.id = c.id
  left join keyword k on k.id = c.id
  where s.id is not null or k.id is not null
  order by score desc
  limit match_count;
$$;

-- ============================================================================
-- 3. STORAGE BUCKET (0003_documents_bucket.sql)
-- ============================================================================

do $$
begin
  if not exists (select 1 from information_schema.schemata where schema_name = 'storage') then
    raise notice 'storage schema absent; skipping bucket creation';
    return;
  end if;

  insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
  values (
    'documents',
    'documents',
    false,
    20971520,
    array[
      'application/pdf',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'text/plain'
    ]
  )
  on conflict (id) do update
    set public = excluded.public,
        file_size_limit = excluded.file_size_limit,
        allowed_mime_types = excluded.allowed_mime_types;
end
$$;

-- ============================================================================
-- 4. INGESTION COLUMNS & INDEXES (0004_ingestion_columns.sql)
-- ============================================================================

alter table public.documents
  add column if not exists original_filename text,
  add column if not exists file_size_bytes bigint,
  add column if not exists page_count int,
  add column if not exists chunk_count int,
  add column if not exists extracted_chars int,
  add column if not exists text_preview text,
  add column if not exists low_text_yield boolean not null default false,
  add column if not exists processed_at timestamptz;

create index if not exists documents_content_hash_active_idx
  on public.documents (content_hash)
  where is_active and content_hash is not null;

create index if not exists documents_status_created_idx on public.documents (status, created_at desc);

create unique index if not exists chunks_document_chunk_idx on public.chunks (document_id, chunk_index);

-- ============================================================================
-- 5. EMBEDDING CACHE (0005_embedding_cache.sql)
-- ============================================================================

create table if not exists public.embedding_cache (
  content_hash text not null,
  model text not null,
  dimensions int not null,
  embedding vector(768) not null,
  created_at timestamptz not null default now(),
  last_used_at timestamptz not null default now(),
  primary key (content_hash, model, dimensions)
);

create index if not exists embedding_cache_last_used_idx on public.embedding_cache (last_used_at);

alter table public.embedding_cache enable row level security;
revoke all on public.embedding_cache from anon, authenticated;

-- ============================================================================
-- 6. REPLACE DOCUMENT CHUNKS RPC (0006_replace_document_chunks.sql)
-- ============================================================================

create or replace function public.replace_document_chunks(
  p_document_id uuid,
  p_chunks jsonb,
  p_metadata jsonb default '{}'::jsonb,
  p_mark_ready boolean default true
) returns int
language plpgsql
set search_path = public, extensions, pg_temp
as $$
declare
  v_category text;
  v_count int;
begin
  select d.category into v_category
    from public.documents d
   where d.id = p_document_id;

  if not found then
    raise exception 'Document % does not exist', p_document_id
      using errcode = 'no_data_found';
  end if;

  delete from public.chunks where document_id = p_document_id;

  insert into public.chunks (
    document_id, chunk_index, page_number, section_heading, content, category, embedding
  )
  select
    p_document_id,
    (c ->> 'chunk_index')::int,
    nullif(c ->> 'page_number', '')::int,
    nullif(c ->> 'section_heading', ''),
    c ->> 'content',
    v_category,
    nullif(replace(c ->> 'embedding', ' ', ''), '')::vector
  from jsonb_array_elements(p_chunks) as c;

  get diagnostics v_count = row_count;

  update public.documents d
     set status = case when p_mark_ready then 'ready' else d.status end,
         error_message = case when p_mark_ready then null else d.error_message end,
         chunk_count = v_count,
         page_count = coalesce((p_metadata ->> 'page_count')::int, d.page_count),
         extracted_chars = coalesce((p_metadata ->> 'extracted_chars')::int, d.extracted_chars),
         text_preview = coalesce(p_metadata ->> 'text_preview', d.text_preview),
         low_text_yield = coalesce((p_metadata ->> 'low_text_yield')::boolean, d.low_text_yield),
         processed_at = case when p_mark_ready then now() else d.processed_at end
   where d.id = p_document_id;

  return v_count;
end;
$$;

revoke all on function public.replace_document_chunks(uuid, jsonb, jsonb, boolean) from public;
grant execute on function public.replace_document_chunks(uuid, jsonb, jsonb, boolean)
  to service_role;

-- ============================================================================
-- 7. QUERY LOGGING & FEEDBACK RPC (0007_query_logging.sql)
-- ============================================================================

create or replace function public.log_query(
  p_query_id uuid,
  p_session_id uuid,
  p_question text,
  p_normalized_hash text,
  p_category text,
  p_answer text,
  p_answered boolean,
  p_top_score real,
  p_latency_ms int,
  p_sources jsonb default '[]'::jsonb,
  p_unanswered boolean default false
) returns uuid
language plpgsql
set search_path = public, extensions, pg_temp
as $$
begin
  insert into public.queries (
    id, session_id, question, normalized_hash, category, answer, answered, top_score, latency_ms
  ) values (
    p_query_id, p_session_id, p_question, p_normalized_hash, p_category, p_answer, p_answered,
    p_top_score, p_latency_ms
  );

  insert into public.query_sources (
    query_id, rank, chunk_id, score, document_id, document_title, page_number, section_heading
  )
  select
    p_query_id,
    (entry ->> 'rank')::int,
    nullif(entry ->> 'chunk_id', '')::uuid,
    (entry ->> 'score')::real,
    nullif(entry ->> 'document_id', '')::uuid,
    entry ->> 'document_title',
    nullif(entry ->> 'page_number', '')::int,
    nullif(entry ->> 'section_heading', '')
  from jsonb_array_elements(p_sources) as entry
  where entry ->> 'rank' is not null;

  if p_unanswered then
    insert into public.unanswered_queries (query_id, normalized_hash, question, category)
    values (p_query_id, p_normalized_hash, p_question, p_category);
  end if;

  return p_query_id;
end;
$$;

create or replace function public.record_feedback(
  p_query_id uuid,
  p_session_id uuid,
  p_helpful boolean
) returns boolean
language plpgsql
set search_path = public, extensions, pg_temp
as $$
declare
  v_recorded uuid;
begin
  insert into public.feedback (query_id, helpful)
  select q.id, p_helpful
    from public.queries q
   where q.id = p_query_id
     and q.session_id = p_session_id
  on conflict (query_id) do update
    set helpful = excluded.helpful,
        created_at = now()
  returning feedback.query_id into v_recorded;

  return v_recorded is not null;
end;
$$;

revoke all on function public.log_query(
  uuid, uuid, text, text, text, text, boolean, real, int, jsonb, boolean
) from public;
grant execute on function public.log_query(
  uuid, uuid, text, text, text, text, boolean, real, int, jsonb, boolean
) to service_role;

revoke all on function public.record_feedback(uuid, uuid, boolean) from public;
grant execute on function public.record_feedback(uuid, uuid, boolean) to service_role;
