-- Hybrid retrieval: semantic (pgvector cosine) + keyword (full-text), merged with
-- Reciprocal Rank Fusion.
--
-- Kept in its own migration because `create or replace function` cannot change a
-- return type. This is the piece most likely to be re-tuned in Phase 3 (TOP_K,
-- candidate limits, RRF constant), and separating it means tuning never requires
-- touching the applied schema file (AGENTS.md section 14).

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
      -- CORRECTION B2: the raw cosine similarity, which the fallback threshold
      -- needs. RRF scores are on a ~1/60 scale and are not comparable to
      -- SIMILARITY_THRESHOLD, so without this column FR-8 is unimplementable.
      1 - (c.embedding <=> query_embedding) as sim
    from chunks c
    join documents d on d.id = c.document_id
    where d.is_active
      and d.status = 'ready'
      -- CORRECTION B9: embedding is nullable, and NULL-distance rows would
      -- otherwise occupy candidate slots.
      and c.embedding is not null
      -- CORRECTION B7: filter on d.category, not c.category, so a category edit
      -- on the document takes effect immediately.
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
    -- CORRECTION B3: this ORDER BY was missing. LIMIT without ORDER BY returns an
    -- arbitrary 20 rows, so the candidate set fed to RRF was nondeterministic --
    -- the same question could retrieve different chunks run to run, which would
    -- have made the Phase 6 eval harness unreproducible.
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

comment on function hybrid_search(text, vector, int, text) is
  'Hybrid retrieval with RRF. `similarity` is the raw cosine similarity and is NULL '
  'for keyword-only hits -- the fallback decision must use max(similarity) over the '
  'returned rows, not the similarity of the top-scoring row, because that row can be '
  'a keyword-only hit. Known limitation: a high-cosine chunk can rank below '
  'match_count in RRF and be excluded entirely; if the Phase 6 eval shows spurious '
  'fallbacks, take the similarity from a separate lookup.';
