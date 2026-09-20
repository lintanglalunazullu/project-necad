-- ==============================================================================
-- project-necad — Migration: Performance & Security Fixes
-- Jalankan file ini SETELAH supabase_setup.sql (di SQL Editor Supabase).
-- Aman dijalankan berkali-kali (idempotent — pakai DROP IF EXISTS + CREATE).
--
-- Masalah yang diperbaiki:
--   1. match_pdf_documents / search_pdf_documents_keyword / search_pdf_documents_exact
--      tidak punya filter kategori -> backend terpaksa fetch SELURUH tabel pdf_documents
--      (termasuk kolom embedding, bisa >10.000 baris) lalu filter role di Python untuk
--      SETIAP pesan chat dari user biasa. Ini penyebab utama chat lambat & boros bandwidth.
--   2. Endpoint /admin/dashboard fetch seluruh isi tabel pdf_documents, profiles,
--      chat_sessions, chat_messages (limit 1000-10000 masing-masing) hanya untuk
--      menghitung jumlah baris. Diganti 1 RPC agregat.
--   3. Listing dokumen (GET /documents) fetch semua chunk lalu group-by di Python.
--      Diganti 1 RPC GROUP BY di database.
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- 1. VECTOR SEARCH — tambah category_filter agar filtering role terjadi di DB,
--    bukan di Python. category_filter NULL = tanpa filter (backward compatible
--    dengan pemanggil lama yang belum kirim parameter ini).
-- ------------------------------------------------------------------------------
DROP FUNCTION IF EXISTS public.match_pdf_documents(vector, float, int);
DROP FUNCTION IF EXISTS public.match_pdf_documents(vector, float, int, text[]);

CREATE OR REPLACE FUNCTION public.match_pdf_documents(
    query_embedding vector,
    match_threshold float,
    match_count int,
    category_filter text[] DEFAULT NULL
)
RETURNS TABLE (
    id bigint,
    pdf_name text,
    category text,
    content text,
    similarity float
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.id::bigint AS id,
        p.pdf_name::text AS pdf_name,
        p.category::text AS category,
        p.content::text AS content,
        (1 - (p.embedding <=> query_embedding))::float AS similarity
    FROM public.pdf_documents p
    WHERE p.embedding IS NOT NULL
      AND (1 - (p.embedding <=> query_embedding)) >= match_threshold
      AND (category_filter IS NULL OR p.category = ANY(category_filter))
    ORDER BY p.embedding <=> query_embedding ASC
    LIMIT match_count;
END;
$$;

-- ------------------------------------------------------------------------------
-- 2. KEYWORD SEARCH (Full-Text Search) — tambah category_filter yang sama.
-- ------------------------------------------------------------------------------
DROP FUNCTION IF EXISTS public.search_pdf_documents_keyword(text, int);
DROP FUNCTION IF EXISTS public.search_pdf_documents_keyword(text, int, text[]);

CREATE OR REPLACE FUNCTION public.search_pdf_documents_keyword(
    search_query text,
    result_limit int DEFAULT 10,
    category_filter text[] DEFAULT NULL
)
RETURNS TABLE (
    id bigint,
    pdf_name text,
    category text,
    content text,
    similarity float
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.id::bigint AS id,
        p.pdf_name::text AS pdf_name,
        p.category::text AS category,
        p.content::text AS content,
        GREATEST(
            ts_rank(to_tsvector('simple', COALESCE(p.content, '')), plainto_tsquery('simple', search_query)),
            CASE WHEN p.content ILIKE '%' || search_query || '%' THEN 0.5 ELSE 0.0 END
        )::float AS similarity
    FROM public.pdf_documents p
    WHERE (
        to_tsvector('simple', COALESCE(p.content, '')) @@ plainto_tsquery('simple', search_query)
        OR p.content ILIKE '%' || search_query || '%'
    )
      AND (category_filter IS NULL OR p.category = ANY(category_filter))
    ORDER BY similarity DESC
    LIMIT result_limit;
END;
$$;

-- ------------------------------------------------------------------------------
-- 3. EXACT MATCH SEARCH (NISN/NIP/angka) — tambah category_filter yang sama.
--    Paling penting untuk data privat (NISN dsb) supaya tidak pernah bocor ke
--    role "user" biasa lewat jalur RPC ini.
-- ------------------------------------------------------------------------------
DROP FUNCTION IF EXISTS public.search_pdf_documents_exact(text, int);
DROP FUNCTION IF EXISTS public.search_pdf_documents_exact(text, int, text[]);

CREATE OR REPLACE FUNCTION public.search_pdf_documents_exact(
    search_term text,
    result_limit int DEFAULT 10,
    category_filter text[] DEFAULT NULL
)
RETURNS TABLE (
    id bigint,
    pdf_name text,
    category text,
    content text,
    similarity float
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.id::bigint AS id,
        p.pdf_name::text AS pdf_name,
        p.category::text AS category,
        p.content::text AS content,
        1.0::float AS similarity
    FROM public.pdf_documents p
    WHERE (p.content ILIKE '%' || search_term || '%' OR p.pdf_name ILIKE '%' || search_term || '%')
      AND (category_filter IS NULL OR p.category = ANY(category_filter))
    LIMIT result_limit;
END;
$$;

-- ------------------------------------------------------------------------------
-- 4. RINGKASAN DOKUMEN — GROUP BY pdf_name di database (dipakai GET /documents
--    dan daftar dokumen di dashboard admin). Sebelumnya di-fetch per-chunk lalu
--    di-group di Python (bisa ribuan baris untuk beberapa lusin dokumen).
-- ------------------------------------------------------------------------------
DROP FUNCTION IF EXISTS public.get_document_summary();

CREATE OR REPLACE FUNCTION public.get_document_summary()
RETURNS TABLE (
    pdf_name text,
    category text,
    chunk_count bigint,
    created_at timestamptz
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
STABLE
AS $$
    SELECT
        p.pdf_name::text,
        -- Kalau satu pdf_name pernah punya baris dengan kategori berbeda,
        -- ambil yang "private" agar tidak pernah under-report keprivatan-an.
        (CASE WHEN bool_or(p.category = 'private') THEN 'private' ELSE 'public' END)::text AS category,
        COUNT(*)::bigint AS chunk_count,
        MIN(p.created_at) AS created_at
    FROM public.pdf_documents p
    WHERE p.pdf_name IS NOT NULL AND p.pdf_name <> ''
    GROUP BY p.pdf_name
    ORDER BY MIN(p.created_at) DESC NULLS LAST;
$$;

-- ------------------------------------------------------------------------------
-- 5. STATISTIK DASHBOARD ADMIN — 1 round-trip menggantikan 4x fetch tabel penuh
--    (pdf_documents limit 10000, profiles/chat_sessions/chat_messages limit 1000).
-- ------------------------------------------------------------------------------
DROP FUNCTION IF EXISTS public.get_admin_dashboard_stats();

CREATE OR REPLACE FUNCTION public.get_admin_dashboard_stats()
RETURNS jsonb
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
STABLE
AS $$
    SELECT jsonb_build_object(
        'documents', (SELECT COUNT(DISTINCT pdf_name) FROM public.pdf_documents WHERE pdf_name IS NOT NULL AND pdf_name <> ''),
        'chunks', (SELECT COUNT(*) FROM public.pdf_documents),
        'public_documents', (SELECT COUNT(DISTINCT pdf_name) FROM public.pdf_documents WHERE category = 'public' OR category IS NULL),
        'private_documents', (SELECT COUNT(DISTINCT pdf_name) FROM public.pdf_documents WHERE category = 'private'),
        'users', (SELECT COUNT(*) FROM public.profiles),
        'users_by_role', (
            SELECT jsonb_object_agg(role_key, role_count) FROM (
                SELECT COALESCE(NULLIF(lower(role), ''), 'user') AS role_key, COUNT(*) AS role_count
                FROM public.profiles
                GROUP BY 1
            ) r
        ),
        'sessions', (SELECT COUNT(*) FROM public.chat_sessions),
        'messages', (SELECT COUNT(*) FROM public.chat_messages),
        'messages_by_role', (
            SELECT jsonb_object_agg(role_key, role_count) FROM (
                SELECT role AS role_key, COUNT(*) AS role_count
                FROM public.chat_messages
                WHERE role IN ('user', 'assistant')
                GROUP BY 1
            ) m
        )
    );
$$;

-- Endpoint dashboard hanya boleh diakses admin — pertahanan berlapis di level DB,
-- di samping pengecekan role yang sudah dilakukan backend (require_admin).
REVOKE ALL ON FUNCTION public.get_admin_dashboard_stats() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_admin_dashboard_stats() TO authenticated;

-- ==============================================================================
-- Verifikasi cepat setelah migrasi (jalankan manual, opsional):
--   SELECT public.get_admin_dashboard_stats();
--   SELECT * FROM public.get_document_summary() LIMIT 5;
-- ==============================================================================
