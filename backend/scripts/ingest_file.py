"""CLI script to ingest documents directly into Supabase and run the RAG pipeline."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID

# Ensure backend root is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.config import get_settings
from app.db.client import close_db_client, init_db_client
from app.providers.gemini import GeminiProvider
from app.services.documents import SupabaseDocumentRepository
from app.services.embedding import EmbeddingService, SupabaseEmbeddingCache
from app.services.filetypes import content_type_for, normalise_extension
from app.services.hashing import sha256_hex
from app.services.ingestion import IngestionService
from app.services.storage import SupabaseFileStorage, build_object_path


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python ingest_file.py <path_to_file> [title] [category] [department]")
        sys.exit(1)

    file_path = Path(sys.argv[1]).resolve()
    if not file_path.exists():
        print(f"Error: File not found at {file_path}")
        sys.exit(1)

    title = sys.argv[2] if len(sys.argv) > 2 else file_path.stem.replace("-", " ").replace("_", " ").title()
    category = sys.argv[3] if len(sys.argv) > 3 else "general"
    department = sys.argv[4] if len(sys.argv) > 4 else None

    print(f"Loading file: {file_path.name} ({file_path.stat().st_size} bytes)")
    print(f"Title: {title} | Category: {category} | Department: {department}")

    settings = get_settings()
    await init_db_client(settings)

    repo = SupabaseDocumentRepository()
    storage = SupabaseFileStorage(settings.storage_bucket)
    provider = GeminiProvider(settings)
    embeddings = EmbeddingService(
        provider=provider,
        settings=settings,
        cache=SupabaseEmbeddingCache(),
    )
    ingestion = IngestionService(repo, storage, embeddings, settings)

    data = file_path.read_bytes()
    digest = sha256_hex(data)
    ext = file_path.suffix.lstrip(".").lower()
    file_type = normalise_extension(ext)

    existing = await repo.find_by_hash(digest)
    if existing:
        doc_id = UUID(str(existing["id"]))
        print(f"Document already exists with ID: {doc_id} (Status: {existing.get('status')})")
        print("Re-running ingestion pipeline...")
        await ingestion.process(doc_id, data=data)
        doc = await repo.get(doc_id)
        if doc:
            print(f"Done! Status: {doc.get('status')}, Chunks: {doc.get('chunk_count')}")
            if doc.get("error_message"):
                print(f"Error: {doc.get('error_message')}")
        await close_db_client()
        return

    storage_path = build_object_path(file_type)
    print(f"Uploading file to Supabase Storage: {storage_path}...")
    await storage.put(storage_path, data, content_type_for(file_type))

    row = await repo.insert(
        {
            "title": title,
            "category": category,
            "academic_year": None,
            "department": department,
            "file_path": storage_path,
            "file_type": file_type,
            "original_filename": file_path.name,
            "file_size_bytes": len(data),
            "content_hash": digest,
            "status": "uploaded",
            "is_active": True,
        }
    )
    doc_id = UUID(str(row["id"]))
    print(f"Document registered in Supabase documents table with ID: {doc_id}")
    print("Running ingestion (extract -> clean -> chunk -> embed -> save chunks)...")

    await ingestion.process(doc_id, data=data)

    doc = await repo.get(doc_id)
    if doc:
        print(f"Result Status: {doc.get('status')}")
        print(f"Chunks created: {doc.get('chunk_count')}")
        print(f"Extracted characters: {doc.get('extracted_chars')}")
        if doc.get("error_message"):
            print(f"Ingestion error: {doc.get('error_message')}")
    else:
        print("Warning: Document could not be re-fetched.")

    await close_db_client()
    print("Ingestion complete!")


if __name__ == "__main__":
    asyncio.run(main())
