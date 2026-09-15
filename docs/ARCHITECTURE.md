# Arsitektur Sistem — Project Necad

## Diagram Komponen

```
┌─────────────────────────────────────────────────────────────┐
│                        BROWSER / CLIENT                     │
└────────────┬────────────────────────────┬───────────────────┘
             │                            │
             ▼                            ▼
┌────────────────────┐       ┌────────────────────────────────┐
│   apps/school-web  │       │        apps/mentor-web         │
│  (Website Sekolah) │       │     (Portal AI Aksaraku)       │
│                    │       │                                │
│  - Profil Sekolah  │       │  - Dashboard User/Guru/Admin   │
│  - Akademik        │       │  - Chat AI                     │
│  - PPDB            │       │  - Upload Dokumen PDF           │
│  - Kontak          │       │  - Manajemen User               │
│  - Kesiswaan       │       │                                │
│                    │       │  Auth: Supabase Google OAuth   │
│  Static HTML/CSS   │       │  Config: js/config.js          │
└────────────┬───────┘       └────────────┬───────────────────┘
             │                            │
             │  (Floating AI Widget)       │  (REST API calls)
             │  Link ke mentor-web        │
             └────────────┬───────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   services/api (FastAPI)                    │
│                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐ │
│  │    /chat    │  │  /documents  │  │  /admin/dashboard  │ │
│  │  (RAG Chat) │  │    (CRUD)    │  │  (Admin Only)      │ │
│  └──────┬──────┘  └──────┬───────┘  └─────────┬──────────┘ │
│         │                │                    │            │
│  ┌──────▼────────────────▼────────────────────▼──────────┐ │
│  │               Core RAG Pipeline                       │ │
│  │                                                       │ │
│  │  1. embed_text()        — SentenceTransformer lokal   │ │
│  │  2. hybrid_search()     — Vector + Keyword (RRF)      │ │
│  │  3. rerank_documents()  — Cosine similarity rerank    │ │
│  │  4. generate_with_fallback() — Groq → OpenRouter      │ │
│  └───────────────────────────────────────────────────────┘ │
└────────────────────────┬────────────────────────────────────┘
                         │
           ┌─────────────┼──────────────┐
           │             │              │
           ▼             ▼              ▼
┌──────────────┐  ┌──────────┐  ┌─────────────────────┐
│   Supabase   │  │  Groq    │  │    OpenRouter        │
│              │  │  (LLM)   │  │    (LLM Fallback)    │
│  - Auth      │  │          │  │                      │
│  - profiles  │  │ Llama    │  │  100+ Models         │
│  - pdf_docs  │  │ 3.3 70B  │  │  (free tier ada)     │
│  - chat_sess │  │          │  │                      │
│  - chat_msgs │  └──────────┘  └─────────────────────┘
│  - pgvector  │
└──────────────┘
```

## Alur Data: Chat AI

```
Pengguna ketik pertanyaan
         │
         ▼
[mentor-web: chat.js]
  POST /chat {question, session_id}
         │
         ▼
[services/api: /chat endpoint]
  1. Autentikasi role user (anonymous/user/teacher/admin)
  2. Load session history dari Supabase
  3. build_search_query() — gabung pertanyaan + context history
  4. save_message(user, question)
         │
         ▼
  [Embedding]
  embed_text(search_query) → SentenceTransformer → float[384]
         │
         ▼
  [Hybrid Retrieval — Reciprocal Rank Fusion]
  _table_similar_documents()   → pgvector similarity search
  _keyword_similar_documents() → Supabase keyword search
  reciprocal_rank_fusion()     → merge & rerank
         │
         ▼
  [Role Filter]
  filter_documents_for_role()  → public (user) | public+private (admin/teacher)
         │
         ▼
  [Rerank]
  rerank_documents()           → cosine similarity final sort
         │
         ▼
  [LLM Generation]
  generate_with_fallback()     → Groq (primary) → OpenRouter (fallback)
         │
         ▼
  save_message(assistant, answer)
         │
         ▼
  Response: {answer, session_id, sources, evidence, retrieval, token_optimization}
         │
         ▼
[mentor-web: chat.js]
  Render markdown answer ke UI
```

## Alur Data: Upload Dokumen PDF

```
Admin upload PDF
         │
         ▼
[mentor-web: pdf-upload.js]
  1. extractTextFromPDF()    — pdf.js local extraction
  2. chunkText(text, 800, 100) — sliding window chunks
  3. POST /embed-upsert {chunks[]}
         │
         ▼
[services/api: /embed-upsert]
  Untuk setiap chunk:
  1. embed_text(chunk.text) → vector[384]
  2. supabase.table(pdf_documents).upsert({text, embedding, pdf_name, category})
         │
         ▼
[Supabase: pdf_documents table]
  Tersimpan dengan pgvector extension
```

## Keamanan

| Aspek | Implementasi |
|---|---|
| API Keys | Tersimpan di server-side `.env`, tidak pernah ke frontend |
| Role-based Access | Setiap endpoint API memvalidasi JWT Supabase + role dari tabel profiles |
| Private Documents | Dokumen kategori `private` hanya bisa diakses role `admin` dan `teacher` |
| CORS | Dikonfigurasi di FastAPI (`allow_origins=["*"]` — perketat di production) |
| Auth State | Supabase JWT divalidasi server-side, bukan trust frontend claim |

## Skalabilitas

- **school-web & mentor-web**: Static hosting (Vercel/Cloudflare Pages) — skalabilitas otomatis tanpa batas
- **services/api**: Bisa di-scale horizontal via Railway/Fly.io, atau dibungkus Docker
- **Supabase**: Managed PostgreSQL dengan pgvector — skalabilitas vertikal & horizontal tersedia
- **LLM**: Multi-provider dengan round-robin fallback (Groq key 1→2→3, lalu OpenRouter key 1→2→3)
- **Embedding**: SentenceTransformer diload sekali saat server start, tidak per-request
