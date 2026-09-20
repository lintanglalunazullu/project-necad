-- ==============================================================================
-- AKSARAKU / PROJECT NECAD — ULTIMATE SUPABASE SETUP & SCHEMA
-- ==============================================================================
-- File ini menyatukan SELURUH kebutuhan database Supabase:
-- 1. Extensions (pgvector, uuid-ossp, pg_trgm)
-- 2. Tables & Column Alignment (profiles, chat_sessions, chat_messages, ai_provider_config, pdf_documents)
-- 3. Helper Functions & Triggers (is_admin, is_teacher_or_admin, updated_at, handle_new_user)
-- 4. RPC Search Functions (match_pdf_documents, search_pdf_documents_keyword, search_pdf_documents_exact)
-- 5. Row Level Security (RLS) & Security Policies (Zero Infinite Recursion)
-- 6. Performance Indexes (HNSW vector index, GIN text search, B-Trees)
-- 7. Seed Data (AI providers config + 28 dokumen sekolah)
-- 8. Safe Sequence Synchronization
--
-- CATATAN KOMPATIBILITAS (Zero Failure):
-- - Aman dijalankan di database kosong (fresh) maupun database yang SUDAH ADA datanya.
-- - Secara otomatis menambahkan kolom-kolom baru (ADD COLUMN IF NOT EXISTS) jika tabel lama belum lengkap.
-- - Secara otomatis membersihkan fungsi lama (DROP FUNCTION) sebelum memasang fungsi baru (bebas error 42P13).
-- - Kebijakan RLS menggunakan fungsi SECURITY DEFINER sehingga bebas error infinite recursion.
-- ==============================================================================

-- ==============================================================================
-- BAGIAN 1: EXTENSIONS
-- ==============================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ==============================================================================
-- BAGIAN 2: TABEL-TABEL UTAMA & SINKRONISASI STRUKTUR KOLOM
-- ==============================================================================

-- 1. Tabel Profiles (Manajemen Pengguna & Role: user, teacher, admin)
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT,
    full_name TEXT,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'teacher', 'user')),
    provider TEXT DEFAULT 'email',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS full_name TEXT;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user';
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS provider TEXT DEFAULT 'email';
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- 2. Tabel Chat Sessions (Riwayat Percakapan AI Mentor)
CREATE TABLE IF NOT EXISTS public.chat_sessions (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'Sesi chat baru',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.chat_sessions ADD COLUMN IF NOT EXISTS user_id UUID;
ALTER TABLE public.chat_sessions ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT 'Sesi chat baru';
ALTER TABLE public.chat_sessions ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE public.chat_sessions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- 3. Tabel Chat Messages (Pesan Chat Tiap Sesi)
CREATE TABLE IF NOT EXISTS public.chat_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.chat_messages ADD COLUMN IF NOT EXISTS session_id TEXT;
ALTER TABLE public.chat_messages ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user';
ALTER TABLE public.chat_messages ADD COLUMN IF NOT EXISTS content TEXT NOT NULL DEFAULT '';
ALTER TABLE public.chat_messages ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE public.chat_messages ADD COLUMN IF NOT EXISTS inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
-- Sinkronkan created_at dan inserted_at bila salah satu kolom masih kosong di database lama
UPDATE public.chat_messages SET created_at = inserted_at WHERE created_at IS NULL AND inserted_at IS NOT NULL;
UPDATE public.chat_messages SET inserted_at = created_at WHERE inserted_at IS NULL AND created_at IS NOT NULL;

-- 4. Tabel AI Provider Config (Pengaturan Model, Suhu, Timeout, Priority & Fallback)
CREATE TABLE IF NOT EXISTS public.ai_provider_config (
    id TEXT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT true,
    model TEXT NOT NULL,
    temperature FLOAT NOT NULL DEFAULT 0.2,
    max_tokens INT NOT NULL DEFAULT 600,
    priority INT NOT NULL DEFAULT 1,
    timeout FLOAT NOT NULL DEFAULT 30.0,
    system_prompt_extra TEXT DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.ai_provider_config ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE public.ai_provider_config ADD COLUMN IF NOT EXISTS model TEXT NOT NULL DEFAULT 'gemini-2.0-flash';
ALTER TABLE public.ai_provider_config ADD COLUMN IF NOT EXISTS temperature FLOAT NOT NULL DEFAULT 0.2;
ALTER TABLE public.ai_provider_config ADD COLUMN IF NOT EXISTS max_tokens INT NOT NULL DEFAULT 600;
ALTER TABLE public.ai_provider_config ADD COLUMN IF NOT EXISTS priority INT NOT NULL DEFAULT 1;
ALTER TABLE public.ai_provider_config ADD COLUMN IF NOT EXISTS timeout FLOAT NOT NULL DEFAULT 30.0;
ALTER TABLE public.ai_provider_config ADD COLUMN IF NOT EXISTS system_prompt_extra TEXT DEFAULT '';
ALTER TABLE public.ai_provider_config ADD COLUMN IF NOT EXISTS api_key TEXT DEFAULT '';
ALTER TABLE public.ai_provider_config ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- 5. Tabel PDF Documents (Knowledge Base RAG & Vector Embeddings)
CREATE TABLE IF NOT EXISTS public.pdf_documents (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    pdf_name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'public' CHECK (category IN ('public', 'private')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    embedding vector(384)
);
ALTER TABLE public.pdf_documents ADD COLUMN IF NOT EXISTS pdf_name TEXT NOT NULL DEFAULT 'document';
ALTER TABLE public.pdf_documents ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'public';
ALTER TABLE public.pdf_documents ADD COLUMN IF NOT EXISTS content TEXT NOT NULL DEFAULT '';
ALTER TABLE public.pdf_documents ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE public.pdf_documents ADD COLUMN IF NOT EXISTS embedding vector(384);

-- Jika tabel pdf_documents lama menggunakan nama kolom 'text' bukannya 'content', migrasikan otomatis:
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'pdf_documents' AND column_name = 'text'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'pdf_documents' AND column_name = 'content'
    ) THEN
        ALTER TABLE public.pdf_documents RENAME COLUMN text TO content;
    END IF;
END $$;

-- ==============================================================================
-- BAGIAN 3: HELPER FUNCTIONS & AUTOMATION TRIGGERS
-- ==============================================================================

-- 1. Helper Function: Cek status Admin (SECURITY DEFINER agar bebas infinite recursion di RLS)
CREATE OR REPLACE FUNCTION public.is_admin(user_id uuid)
RETURNS boolean
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.profiles
        WHERE id = user_id AND role = 'admin'
    );
$$;

-- 2. Helper Function: Cek status Teacher atau Admin
CREATE OR REPLACE FUNCTION public.is_teacher_or_admin(user_id uuid)
RETURNS boolean
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.profiles
        WHERE id = user_id AND role IN ('admin', 'teacher')
    );
$$;

-- 3. Fungsi helper untuk update kolom updated_at otomatis
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger updated_at untuk profiles
DROP TRIGGER IF EXISTS tr_profiles_updated_at ON public.profiles;
CREATE TRIGGER tr_profiles_updated_at
    BEFORE UPDATE ON public.profiles
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

-- Trigger updated_at untuk chat_sessions
DROP TRIGGER IF EXISTS tr_chat_sessions_updated_at ON public.chat_sessions;
CREATE TRIGGER tr_chat_sessions_updated_at
    BEFORE UPDATE ON public.chat_sessions
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

-- Trigger updated_at untuk ai_provider_config
DROP TRIGGER IF EXISTS tr_ai_provider_config_updated_at ON public.ai_provider_config;
CREATE TRIGGER tr_ai_provider_config_updated_at
    BEFORE UPDATE ON public.ai_provider_config
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

-- 4. Fungsi & Trigger otomatis membuat profil saat user baru mendaftar di auth.users
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, email, full_name, role, provider)
    VALUES (
        NEW.id,
        COALESCE(NEW.email, ''),
        COALESCE(
            NEW.raw_user_meta_data->>'full_name',
            NEW.raw_user_meta_data->>'name',
            split_part(NEW.email, '@', 1),
            'User'
        ),
        COALESCE(NEW.raw_user_meta_data->>'role', 'user'),
        COALESCE(NEW.raw_app_meta_data->>'provider', 'email')
    )
    ON CONFLICT (id) DO UPDATE SET
        email = EXCLUDED.email,
        full_name = CASE 
            WHEN public.profiles.full_name IS NULL OR public.profiles.full_name = 'User' 
            THEN EXCLUDED.full_name 
            ELSE public.profiles.full_name 
        END,
        updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ==============================================================================
-- BAGIAN 4: RPC FUNCTIONS (HYBRID SEARCH PIPELINE)
-- ==============================================================================

-- Hapus fungsi lama jika sudah ada (mencegah error 42P13 saat mengganti signature)
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (
        SELECT proname, oid::regprocedure AS func_sig
        FROM pg_proc
        WHERE proname IN ('match_pdf_documents', 'search_pdf_documents_keyword', 'search_pdf_documents_exact')
          AND pronamespace = 'public'::regnamespace
    ) LOOP
        EXECUTE 'DROP FUNCTION IF EXISTS ' || r.func_sig || ' CASCADE;';
    END LOOP;
END $$;

DROP FUNCTION IF EXISTS public.match_pdf_documents;
DROP FUNCTION IF EXISTS public.search_pdf_documents_keyword;
DROP FUNCTION IF EXISTS public.search_pdf_documents_exact;

-- 1. Vector Search Function (Cosine Distance)
CREATE OR REPLACE FUNCTION public.match_pdf_documents(
    query_embedding vector,
    match_threshold float,
    match_count int
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
    ORDER BY p.embedding <=> query_embedding ASC
    LIMIT match_count;
END;
$$;

-- 2. Keyword Search Function (Full-Text Search + ILIKE Fallback)
CREATE OR REPLACE FUNCTION public.search_pdf_documents_keyword(
    search_query text,
    result_limit int DEFAULT 10
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
    WHERE to_tsvector('simple', COALESCE(p.content, '')) @@ plainto_tsquery('simple', search_query)
       OR p.content ILIKE '%' || search_query || '%'
    ORDER BY similarity DESC
    LIMIT result_limit;
END;
$$;

-- 3. Exact Match Search Function (Untuk NISN, NIP, Tanggal, Angka, Istilah Pasti)
CREATE OR REPLACE FUNCTION public.search_pdf_documents_exact(
    search_term text,
    result_limit int DEFAULT 10
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
    WHERE p.content ILIKE '%' || search_term || '%'
       OR p.pdf_name ILIKE '%' || search_term || '%'
    LIMIT result_limit;
END;
$$;

-- ==============================================================================
-- BAGIAN 5: ROW LEVEL SECURITY (RLS) & POLICIES
-- ==============================================================================

-- Aktifkan RLS di semua tabel
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_provider_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pdf_documents ENABLE ROW LEVEL SECURITY;

-- --- Service Role Policies (Bypass untuk Backend FastAPI) ---
DROP POLICY IF EXISTS "service_role_profiles" ON public.profiles;
CREATE POLICY "service_role_profiles" ON public.profiles FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "service_role_chat_sessions" ON public.chat_sessions;
CREATE POLICY "service_role_chat_sessions" ON public.chat_sessions FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "service_role_chat_messages" ON public.chat_messages;
CREATE POLICY "service_role_chat_messages" ON public.chat_messages FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "service_role_ai_provider_config" ON public.ai_provider_config;
CREATE POLICY "service_role_ai_provider_config" ON public.ai_provider_config FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "service_role_pdf_documents" ON public.pdf_documents;
CREATE POLICY "service_role_pdf_documents" ON public.pdf_documents FOR ALL TO service_role USING (true) WITH CHECK (true);

-- --- Profiles Policies ---
DROP POLICY IF EXISTS "profiles_select_own" ON public.profiles;
CREATE POLICY "profiles_select_own" ON public.profiles
    FOR SELECT TO authenticated
    USING (auth.uid() = id);

DROP POLICY IF EXISTS "profiles_update_own" ON public.profiles;
CREATE POLICY "profiles_update_own" ON public.profiles
    FOR UPDATE TO authenticated
    USING (auth.uid() = id)
    WITH CHECK (auth.uid() = id);

DROP POLICY IF EXISTS "profiles_insert_own" ON public.profiles;
CREATE POLICY "profiles_insert_own" ON public.profiles
    FOR INSERT TO authenticated
    WITH CHECK (auth.uid() = id);

DROP POLICY IF EXISTS "profiles_teacher_admin_select" ON public.profiles;
CREATE POLICY "profiles_teacher_admin_select" ON public.profiles
    FOR SELECT TO authenticated
    USING (public.is_teacher_or_admin(auth.uid()));

DROP POLICY IF EXISTS "profiles_admin_all" ON public.profiles;
CREATE POLICY "profiles_admin_all" ON public.profiles
    FOR ALL TO authenticated
    USING (public.is_admin(auth.uid()));

-- --- Chat Sessions Policies ---
DROP POLICY IF EXISTS "chat_sessions_user_all" ON public.chat_sessions;
CREATE POLICY "chat_sessions_user_all" ON public.chat_sessions
    FOR ALL TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- --- Chat Messages Policies ---
DROP POLICY IF EXISTS "chat_messages_user_all" ON public.chat_messages;
CREATE POLICY "chat_messages_user_all" ON public.chat_messages
    FOR ALL TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.chat_sessions s
            WHERE s.id = chat_messages.session_id AND s.user_id = auth.uid()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.chat_sessions s
            WHERE s.id = chat_messages.session_id AND s.user_id = auth.uid()
        )
    );

-- --- PDF Documents Policies ---
DROP POLICY IF EXISTS "pdf_documents_read_public" ON public.pdf_documents;
CREATE POLICY "pdf_documents_read_public" ON public.pdf_documents
    FOR SELECT TO anon, authenticated
    USING (category = 'public');

DROP POLICY IF EXISTS "pdf_documents_read_authorized" ON public.pdf_documents;
CREATE POLICY "pdf_documents_read_authorized" ON public.pdf_documents
    FOR SELECT TO authenticated
    USING (
        category = 'public' OR public.is_teacher_or_admin(auth.uid())
    );

-- --- AI Provider Config Policies ---
DROP POLICY IF EXISTS "ai_provider_config_admin_read" ON public.ai_provider_config;
CREATE POLICY "ai_provider_config_admin_read" ON public.ai_provider_config
    FOR SELECT TO authenticated
    USING (public.is_admin(auth.uid()));

-- ==============================================================================
-- BAGIAN 6: PERFORMANCE INDEXES
-- ==============================================================================

-- Vector Cosine Index (HNSW)
CREATE INDEX IF NOT EXISTS idx_pdf_documents_embedding_hnsw 
    ON public.pdf_documents 
    USING hnsw (embedding vector_cosine_ops);

-- Full-Text Search GIN Index
CREATE INDEX IF NOT EXISTS idx_pdf_documents_content_fts 
    ON public.pdf_documents 
    USING gin (to_tsvector('simple', COALESCE(content, '')));

-- Standard B-Tree Indexes
CREATE INDEX IF NOT EXISTS idx_pdf_documents_category 
    ON public.pdf_documents (category);

CREATE INDEX IF NOT EXISTS idx_pdf_documents_pdf_name 
    ON public.pdf_documents (pdf_name);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id 
    ON public.chat_sessions (user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id 
    ON public.chat_messages (session_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_profiles_role 
    ON public.profiles (role);

-- ==============================================================================
-- BAGIAN 7: SEED DATA
-- ==============================================================================

-- 1. Seed Konfigurasi Provider AI (Gemini, Groq, OpenRouter)
INSERT INTO public.ai_provider_config (id, enabled, model, temperature, max_tokens, priority, timeout)
VALUES
    ('gemini',     true, 'gemini-2.0-flash',                        0.2, 600, 1, 30.0),
    ('groq',       true, 'llama-3.3-70b-versatile',                 0.2, 600, 2, 25.0),
    ('openrouter', true, 'meta-llama/llama-3.3-70b-instruct:free',  0.2, 600, 3, 40.0)
ON CONFLICT (id) DO UPDATE SET
    model = EXCLUDED.model,
    temperature = EXCLUDED.temperature,
    max_tokens = EXCLUDED.max_tokens,
    priority = EXCLUDED.priority,
    timeout = EXCLUDED.timeout,
    updated_at = NOW();

-- Data seed dokumen (28 dokumen profil/sarpras/guru/kalender + embedding, TERMASUK
-- data pribadi siswa seperti nama & NISN pada beberapa chunk laporan PKL) DIPINDAH
-- ke file terpisah: docs/seed_school_documents.OPTIONAL.sql
--
-- ALASAN:
--   1. File ini (supabase_setup.sql) adalah schema/setup script yang wajar untuk
--      di-commit ke Git dan dibagikan (mis. ke tim lain, atau publik di GitHub).
--      Data pribadi siswa (nama, NISN) TIDAK seharusnya ikut ter-commit di file
--      yang sama dengan schema.
--   2. File seed ini tercatat SUDAH pernah ter-commit ke riwayat Git repo ini
--      (docs/supabase_setup.sql, beberapa commit lalu). Kalau repo Anda publik
--      atau akan menjadi publik, riwayat itu perlu dibersihkan (lihat
--      AUDIT_REPORT.md bagian "Keamanan & Privasi Data" untuk langkah `git
--      filter-repo` / BFG Repo-Cleaner + rotasi apa pun yang perlu).
--   3. File seed dokumen jauh lebih sering berubah (upload materi baru) daripada
--      schema — memisahkannya membuat riwayat Git schema tetap bersih.
--
-- CARA PAKAI: setelah menjalankan file ini, jalankan
-- docs/seed_school_documents.OPTIONAL.sql secara terpisah HANYA kalau Anda
-- memang ingin memuat ulang seed data sekolah (mis. instalasi baru). File
-- tersebut sudah ditambahkan ke .gitignore — JANGAN commit ke Git.

-- 3. Sinkronisasi Sequence ID pdf_documents (PENTING: mencegah error ID collision saat upload baru)
DO $$
DECLARE
    seq_name TEXT;
    max_id BIGINT;
BEGIN
    seq_name := pg_get_serial_sequence('public.pdf_documents', 'id');
    IF seq_name IS NOT NULL THEN
        SELECT COALESCE(MAX(id), 1) INTO max_id FROM public.pdf_documents;
        PERFORM setval(seq_name, max_id + 1, false);
    END IF;
END $$;

-- ==============================================================================
-- BAGIAN 8: PANDUAN UPGRADE KE 768 DIMENSI (OPSIONAL / JIKA DIPERLUKAN)
-- ==============================================================================
-- Schema di atas memakai vector(384) agar 28 dokumen sekolah di atas langsung
-- dapat dicari seketika tanpa perlu re-embedding ulang.
--
-- Apabila Anda ingin mengubah ke 768 dimensi native (Gemini text-embedding-004):
-- 1. Jalankan perintah SQL di bawah ini di SQL Editor:
--      ALTER TABLE public.pdf_documents ALTER COLUMN embedding TYPE vector(768);
--      DROP INDEX IF EXISTS idx_pdf_documents_embedding_hnsw;
--      CREATE INDEX idx_pdf_documents_embedding_hnsw ON public.pdf_documents USING hnsw (embedding vector_cosine_ops);
--      UPDATE public.pdf_documents SET embedding = NULL;
-- 2. Set di file services/api/.env:
--      EXPECTED_EMBEDDING_DIMENSION=768
-- 3. Buka API Docs (http://localhost:3000/docs) dan jalankan endpoint POST /embed-upsert
--    untuk men-generate ulang embedding seluruh dokumen secara otomatis.
-- ==============================================================================
