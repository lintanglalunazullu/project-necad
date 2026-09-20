-- MIGRATION: Auto-Smart Self-Learning AI Engine (Tabel ai_learned_synonyms)
-- Dijalankan di Supabase SQL Editor atau via script migrasi

CREATE TABLE IF NOT EXISTS ai_learned_synonyms (
    id BIGSERIAL PRIMARY KEY,
    slang_word TEXT UNIQUE NOT NULL,
    canonical_word TEXT NOT NULL,
    occurrences INT DEFAULT 1,
    confidence FLOAT DEFAULT 1.0,
    source TEXT DEFAULT 'auto_chat', -- 'auto_chat' atau 'manual'
    learned_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_learned_synonyms_slang ON ai_learned_synonyms(slang_word);
CREATE INDEX IF NOT EXISTS idx_learned_synonyms_occurrences ON ai_learned_synonyms(occurrences DESC);

ALTER TABLE ai_learned_synonyms ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access on ai_learned_synonyms"
    ON ai_learned_synonyms
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Authenticated users can read ai_learned_synonyms"
    ON ai_learned_synonyms
    FOR SELECT
    TO authenticated
    USING (true);
