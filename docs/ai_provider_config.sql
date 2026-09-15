-- ============================================================
-- SQL: Tabel ai_provider_config untuk Aksaraku API v3.0
-- Jalankan di Supabase SQL Editor kalau mau config AI provider
-- survive server restart (opsional — kalau tidak dijalankan,
-- config tetap bisa diubah tapi reset ke ENV saat restart).
-- ============================================================

CREATE TABLE IF NOT EXISTS ai_provider_config (
  id          TEXT PRIMARY KEY,       -- 'gemini', 'groq', 'openrouter'
  enabled     BOOLEAN  DEFAULT true,
  model       TEXT     NOT NULL,
  temperature FLOAT    DEFAULT 0.2,
  max_tokens  INT      DEFAULT 600,
  priority    INT      DEFAULT 1,     -- 1 = tertinggi
  timeout     FLOAT    DEFAULT 30.0,
  system_prompt_extra TEXT DEFAULT '',
  updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Seed default config
INSERT INTO ai_provider_config (id, enabled, model, temperature, max_tokens, priority, timeout)
VALUES
  ('gemini',     true, 'gemini-2.0-flash',                        0.2, 600, 1, 30.0),
  ('groq',       true, 'llama-3.3-70b-versatile',                 0.2, 600, 2, 25.0),
  ('openrouter', true, 'meta-llama/llama-3.3-70b-instruct:free',  0.2, 600, 3, 40.0)
ON CONFLICT (id) DO NOTHING;

-- RLS: hanya service role yang bisa baca/tulis (bukan publik)
ALTER TABLE ai_provider_config ENABLE ROW LEVEL SECURITY;

-- Hapus policy lama kalau ada
DROP POLICY IF EXISTS "service_role_only" ON ai_provider_config;

-- Hanya service role yang bisa akses (frontend tidak bisa langsung baca)
CREATE POLICY "service_role_only" ON ai_provider_config
  FOR ALL
  USING (auth.role() = 'service_role');
