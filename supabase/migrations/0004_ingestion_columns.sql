-- Ingestion metadata.
--
-- The specs describe these facts about a document -- how many pages it had, how
-- many chunks it produced, whether extraction found any text -- but never define
-- columns for them, so the admin UI had nowhere to read them from. Kept as a
-- separate migration because 0001 is applied and AGENTS.md section 14 forbids
-- editing an applied migration.

alter table public.documents
  -- The name the admin uploaded. file_path holds the random storage key
  -- (AGENTS.md section 9: "store files under random names"), which is deliberately
  -- not user-facing.
  add column original_filename text,
  add column file_size_bytes bigint,
  add column page_count int,
  add column chunk_count int,
  -- Raw characters extracted before chunking. Distinguishes "extraction found
  -- nothing" from "extraction found text that chunked away to nothing".
  add column extracted_chars int,
  -- First N characters of extracted text, so an admin can see what the pipeline
  -- actually read without opening the file.
  add column text_preview text,
  -- Set when most pages yielded almost no text, which in practice means a scanned
  -- document with no text layer. Flagged rather than failed, per PRD section 10.
  add column low_text_yield boolean not null default false,
  add column processed_at timestamptz;

-- Duplicate-upload detection. An index rather than a unique constraint on
-- purpose: a constraint would turn a re-upload into a 500 from a driver-level
-- integrity error, when the API wants to return a clean 409 that names the
-- existing document. Partial, because only active documents are duplicates --
-- a deactivated document should not block re-uploading the same file.
create index documents_content_hash_active_idx
  on public.documents (content_hash)
  where is_active and content_hash is not null;

-- GET /admin/documents lists newest first, optionally filtered by status.
create index documents_status_created_idx on public.documents (status, created_at desc);

-- chunk_index is documented as a per-document ordinal but was never enforced, so
-- a double-submitted reprocess could produce two rows claiming the same index and
-- a citation pointing at an arbitrary one. replace_document_chunks deletes before
-- it inserts, so this holds by construction.
--
-- This will fail if existing data already violates it; the only rows it can
-- affect are ones a buggy reprocess produced.
create unique index chunks_document_chunk_idx on public.chunks (document_id, chunk_index);
