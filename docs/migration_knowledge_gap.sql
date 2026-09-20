-- ============================================================================
-- MIGRATION: Knowledge Gap Analytics (Tabel unanswered_queries)
-- Digunakan untuk mencatat pertanyaan pengguna yang belum memiliki dokumen jawaban
-- di sistem RAG Aksaraku.
-- ============================================================================

CREATE TABLE IF NOT EXISTS unanswered_queries (
    id BIGSERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    normalized_question TEXT NOT NULL,
    role TEXT DEFAULT 'user',
    reason TEXT DEFAULT 'no_documents', -- 'no_documents' | 'low_similarity' | 'claims_no_info'
    similarity_score FLOAT DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index untuk mempercepat query analytics di Dashboard Admin
CREATE INDEX IF NOT EXISTS idx_unanswered_queries_created_at ON unanswered_queries(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_unanswered_queries_norm ON unanswered_queries(normalized_question);

-- Kebijakan RLS (Hanya service role & admin yang boleh membaca)
ALTER TABLE unanswered_queries ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access on unanswered_queries"
    ON unanswered_queries
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);
