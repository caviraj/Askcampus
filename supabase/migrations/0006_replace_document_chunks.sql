-- Atomic chunk replacement.
--
-- AGENTS.md section 13 requires re-processing a document to "delete its old
-- chunks and insert new ones in a single transaction". That is impossible through
-- the REST API: PostgREST exposes one statement per request, so a delete followed
-- by an insert is two round trips, and a crash between them leaves a document with
-- zero chunks -- possibly still marked `ready`, silently absent from retrieval,
-- with no error recorded anywhere. That is precisely the failure the rule exists
-- to prevent.
--
-- A function body is one transaction by definition, and supabase-py's async .rpc()
-- is a real await, so this is the whole fix. Migration 0002 already established
-- the RPC convention. The alternatives -- staging into a shadow document id, or
-- upsert-then-delete-the-tail -- are still two statements with a narrower window;
-- psycopg with an explicit BEGIN/COMMIT would add a second database driver and a
-- second way to talk to Postgres, which AGENTS.md section 11 rules out.
--
-- Its own file because `create or replace function` cannot change a return type,
-- so any future signature change has to be a new migration.

create or replace function public.replace_document_chunks(
  p_document_id uuid,
  p_chunks jsonb,
  -- Document-level facts the pipeline produced: page_count, extracted_chars,
  -- text_preview, low_text_yield. Passed as one object so the whole update stays
  -- inside this transaction instead of needing a second round trip.
  p_metadata jsonb default '{}'::jsonb,
  p_mark_ready boolean default true
) returns int
language plpgsql
-- Pinned rather than empty: an empty search_path would leave `::vector`
-- unresolvable, since pgvector may live in `extensions` (Supabase's convention)
-- or in `public` depending on how it was installed. Listing both resolves the
-- type either way while still refusing to resolve anything from a schema an
-- attacker could create.
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
    -- ->> yields SQL NULL for a JSON null, so DOCX and TXT chunks (which
    -- genuinely have no page) store NULL rather than a fabricated number.
    nullif(c ->> 'page_number', '')::int,
    nullif(c ->> 'section_heading', ''),
    c ->> 'content',
    -- Copied from the document row rather than taken from the caller, so the
    -- denormalized column can never disagree with documents.category. The
    -- sync_chunk_category trigger only fires on a later UPDATE of category, so it
    -- cannot help here.
    v_category,
    -- jsonb renders an array as "[1, 2, 3]"; the spaces are stripped because the
    -- vector input parser is strict about the surrounding syntax.
    nullif(replace(c ->> 'embedding', ' ', ''), '')::vector
  from jsonb_array_elements(p_chunks) as c;

  get diagnostics v_count = row_count;

  -- The status transition commits in the same transaction as the chunks, so
  -- "chunks exist" and "document is ready" can never disagree.
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

comment on function public.replace_document_chunks(uuid, jsonb, jsonb, boolean) is
  'Deletes a document''s chunks and inserts replacements in one transaction, then '
  'updates its derived counts and (unless p_mark_ready is false) marks it ready. '
  'Returns the number of chunks inserted. Callers must compute embeddings before '
  'calling, so a failure part-way leaves the previous version of the document '
  'intact and still searchable.';

-- The default EXECUTE grant is to PUBLIC, which anon and authenticated both
-- inherit; revoking from those two roles alone would leave the hole open. Writes
-- go through the backend's service role, which bypasses RLS.
revoke all on function public.replace_document_chunks(uuid, jsonb, jsonb, boolean) from public;
grant execute on function public.replace_document_chunks(uuid, jsonb, jsonb, boolean)
  to service_role;
