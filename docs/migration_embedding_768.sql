-- ============================================================
-- SQL: Migrasi embedding dari 384 dimensi (HuggingFace)
-- ke 768 dimensi (Gemini text-embedding-004)
--
-- JALANKAN HANYA JIKA:
-- - Kamu set EXPECTED_EMBEDDING_DIMENSION=768 di .env
-- - Ada data lama yang ter-embed dengan dimensi 384
--
-- Jika set EXPECTED_EMBEDDING_DIMENSION=384, SKIP script ini.
-- ============================================================

-- Langkah 1: Cek dimensi kolom vector saat ini
-- Sesuaikan kolom vector kalau dimensinya masih 384
ALTER TABLE pdf_documents
  ALTER COLUMN embedding TYPE vector(768);

-- Langkah 2: Reset semua embedding lama ke NULL
-- (harus di-generate ulang via API /embed-upsert)
UPDATE pdf_documents SET embedding = NULL;

-- Langkah 3: Update fungsi match_pdf_documents kalau perlu
-- (sesuaikan dimensi di definisi fungsi RPC-mu di Supabase)
-- Contoh (sesuaikan dengan fungsi aktual kamu):
/*
CREATE OR REPLACE FUNCTION match_pdf_documents(
  query_embedding vector(768),   -- <- ubah dari 384 ke 768
  match_threshold float,
  match_count int
) ...
*/

-- ============================================================
-- CATATAN: Setelah jalankan script ini, semua embedding
-- di database akan kosong (NULL). Kamu harus re-embed
-- semua dokumen via endpoint POST /embed-upsert.
-- ============================================================
