-- Atomic query logging, and feedback that can only be given by the session it belongs to.
--
-- Two reasons this is a function rather than three inserts from the backend.
--
-- The first is AGENTS.md section 6: a fallback must write a `queries` row AND an
-- `unanswered_queries` row, "No exception". PostgREST exposes one statement per
-- request, so doing that from the backend is two round trips, and a crash between
-- them shows a student a fallback whose question never reached the admin queue --
-- the one row the entire unanswered workflow exists to collect. A query that
-- answered is worse in a subtler way: the `queries` row lands with no
-- `query_sources`, so the admin history names a question and no source for it.
-- A function body is one transaction, which is exactly the fix migration 0006
-- applied to chunk replacement and for the same reason.
--
-- The second is that `feedback.query_id` is a primary key reached from a public
-- route with no authentication on it. The session check therefore has to be part
-- of the write rather than a read in front of it, or the check and the write can
-- disagree.
--
-- Its own file because `create or replace function` cannot change a return type,
-- so any future signature change has to be a new migration.

create or replace function public.log_query(
  -- Minted by the backend rather than defaulted here, so that the id it returns
  -- to the student does not depend on this insert having succeeded. The logging
  -- write is best-effort (a database that refuses the log must not also refuse
  -- the answer the student already has), and a response shaped differently on
  -- that path would push the branch into every caller.
  p_query_id uuid,
  p_session_id uuid,
  p_question text,
  p_normalized_hash text,
  -- NULL when the question matched no category. Deliberately distinct from the
  -- real 'general' category: conflating them would let "we could not classify
  -- this" filter every general-filed document out of retrieval.
  p_category text,
  p_answer text,
  p_answered boolean,
  p_top_score real,
  p_latency_ms int,
  -- The retrieved sources that were actually cited, as
  -- [{"rank":1,"chunk_id":..,"score":..,"document_id":..,"document_title":..,
  --   "page_number":..,"section_heading":..}]. Empty for a fallback.
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
    -- Not a foreign key by design (migration 0001): history has to outlive a
    -- deleted document, so this is a copied value, not a reference.
    nullif(entry ->> 'document_id', '')::uuid,
    entry ->> 'document_title',
    -- ->> yields SQL NULL for a JSON null, so a DOCX or TXT chunk, which
    -- genuinely has no page, stores NULL rather than a fabricated number.
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

comment on function public.log_query(
  uuid, uuid, text, text, text, text, boolean, real, int, jsonb, boolean
) is
  'Records one answered or unanswered question, its cited sources and, when '
  'p_unanswered, an open unanswered_queries row -- all in one transaction, so a '
  'fallback can never end up with one row written and the other missing. The '
  'caller supplies p_query_id; the function returns it.';


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
  -- The ownership predicate is inside the insert, not a select before it. A
  -- public route has nothing but this session id to authorise with, so a check
  -- that ran as a separate statement could be answering a question about a row
  -- state that no longer holds by the time the write happens.
  insert into public.feedback (query_id, helpful)
  select q.id, p_helpful
    from public.queries q
   where q.id = p_query_id
     and q.session_id = p_session_id
  -- feedback.query_id is the primary key, so re-rating replaces the previous
  -- answer rather than failing or accumulating rows.
  on conflict (query_id) do update
    set helpful = excluded.helpful,
        -- Moved to the latest rating: this column records when the *current*
        -- rating was given, not when the first one was.
        created_at = now()
  returning feedback.query_id into v_recorded;

  return v_recorded is not null;
end;
$$;

comment on function public.record_feedback(uuid, uuid, boolean) is
  'Records or replaces the helpful/not-helpful rating for a query, but only when '
  'the query belongs to p_session_id. Returns false when it does not, or when no '
  'such query exists -- the two are deliberately indistinguishable to the caller.';

-- The default EXECUTE grant is to PUBLIC, which anon and authenticated both
-- inherit; revoking from those two roles alone would leave the hole open. Writes
-- go through the backend's service role, which bypasses RLS.
revoke all on function public.log_query(
  uuid, uuid, text, text, text, text, boolean, real, int, jsonb, boolean
) from public;
grant execute on function public.log_query(
  uuid, uuid, text, text, text, text, boolean, real, int, jsonb, boolean
) to service_role;

revoke all on function public.record_feedback(uuid, uuid, boolean) from public;
grant execute on function public.record_feedback(uuid, uuid, boolean) to service_role;
