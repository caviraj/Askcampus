-- Embedding cache.
--
-- PRD section 10 names "cache embeddings" as the free-tier mitigation, but gives
-- it no schema. Without it, reprocessing a document re-embeds every chunk, and
-- re-uploading a document that is already in the corpus embeds it twice more --
-- the exact quota burn the mitigation exists to prevent.
--
-- Keyed on the chunk text rather than the document, so a shared sentence between
-- two documents (a fee table repeated in a handbook and a prospectus) is embedded
-- once.

create table public.embedding_cache (
  -- sha256 of the exact text that was embedded, hex.
  content_hash text not null,
  model text not null,
  -- Part of the key, not just a record: if EMBEDDING_DIMENSIONS changes, entries
  -- written at the old width must not be served into a column of a different
  -- width. Keying on the width makes the change self-invalidating instead of
  -- producing a cast error at insert time.
  dimensions int not null,
  embedding vector(768) not null,
  created_at timestamptz not null default now(),
  last_used_at timestamptz not null default now(),
  primary key (content_hash, model, dimensions)
);

-- Supports pruning by age if the table grows. Not used by any query yet.
create index embedding_cache_last_used_idx on public.embedding_cache (last_used_at);

alter table public.embedding_cache enable row level security;
revoke all on public.embedding_cache from anon, authenticated;
