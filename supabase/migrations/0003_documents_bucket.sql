-- Storage bucket for uploaded documents.
--
-- ARCHITECTURE.md section 2 names the bucket `documents` but never creates it, so
-- the first upload would fail with "Bucket not found" -- an error that names
-- neither the bucket nor the fact that a migration was missing.
--
-- No policies on storage.objects: the backend uses the service role, which
-- bypasses storage RLS, and no browser ever talks to Storage directly. The bucket
-- is private, so an object URL is not a capability.

-- Guarded because this migration is also applied to a bare pgvector Postgres by
-- tests/test_migrations_integration.py, where the `storage` schema does not exist.
do $$
begin
  if not exists (select 1 from information_schema.schemata where schema_name = 'storage') then
    raise notice 'storage schema absent (not a Supabase database); skipping bucket creation';
    return;
  end if;

  -- file_size_limit mirrors MAX_UPLOAD_MB in app/config.py. Storage is the outer
  -- guard; the API enforces the same limit by counting bytes as it reads.
  --
  -- allowed_mime_types must stay in step with the content-type that
  -- app/services/storage.py sends, which it derives from the validated extension.
  -- A mismatch makes every upload of that type fail with an opaque
  -- "mime type ... is not supported".
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
