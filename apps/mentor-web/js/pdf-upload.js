const CHUNK_SIZE = 350;
const CHUNK_OVERLAP = 60;
const EMBED_UPSERT_URL = `${window.AKSARAKU_CONFIG.API_BASE_URL}/embed-upsert`;
const pdfFileInput = document.getElementById('pdfFile');
const processBtn = document.getElementById('processBtn');
const statusOutput = document.getElementById('status');

function logStatus(message) {
  const now = new Date().toLocaleTimeString('id-ID');
  statusOutput.textContent += `[${now}] ${message}\n`;
  statusOutput.scrollTop = statusOutput.scrollHeight;
}

function chunkText(text, size = CHUNK_SIZE, overlap = CHUNK_OVERLAP) {
  // Pemotongan pintar: pisahkan per paragraf terlebih dahulu agar konteks ide tidak terpotong
  const paragraphs = text.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  const chunks = [];
  let currentWords = [];

  for (const para of paragraphs) {
    const words = para.split(/\s+/).filter(Boolean);
    if (!words.length) continue;

    if (words.length > size) {
      let start = 0;
      while (start < words.length) {
        const end = Math.min(start + size, words.length);
        chunks.push(words.slice(start, end).join(' '));
        start += (size - overlap);
      }
      currentWords = [];
      continue;
    }

    if (currentWords.length + words.length <= size) {
      currentWords.push(...words);
    } else {
      if (currentWords.length > 0) {
        chunks.push(currentWords.join(' '));
        const keep = Math.min(overlap, currentWords.length);
        currentWords = currentWords.slice(currentWords.length - keep);
      }
      currentWords.push(...words);
    }
  }

  if (currentWords.length > 0) {
    chunks.push(currentWords.join(' '));
  }

  return chunks.length > 0 ? chunks : [text.trim()];
}

async function extractPagesFromPDF(file) {
  logStatus('Memuat file PDF...');
  const arrayBuffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;

  const pages = [];
  for (let pageNum = 1; pageNum <= pdf.numPages; pageNum += 1) {
    logStatus(`Mengekstrak teks halaman ${pageNum}/${pdf.numPages}...`);
    const page = await pdf.getPage(pageNum);
    const content = await page.getTextContent();
    const pageText = content.items.map((item) => item.str).join(' ').trim();
    if (pageText) {
      pages.push({ pageNum, text: pageText });
    }
  }

  return pages;
}

async function processPdfFile(documentName = '', category = 'public') {
  const file = pdfFileInput.files[0];
  if (!file) {
    logStatus('Silakan pilih file PDF terlebih dahulu.');
    return;
  }

  try {
    statusOutput.textContent = '';
    const pages = await extractPagesFromPDF(file);
    if (!pages.length) {
      throw new Error('Tidak ada teks yang dapat diekstrak dari PDF. Pastikan file bukan hasil scan gambar murni.');
    }

    const docTitle = documentName.trim() || file.name.replace(/\.[^/.]+$/, '');
    const finalCategory = category === 'private' ? 'private' : 'public';
    const allChunks = [];

    logStatus('Membuat chunk teks terstruktur dengan header konteks...');
    for (const p of pages) {
      const pageChunks = chunkText(p.text, CHUNK_SIZE, CHUNK_OVERLAP);
      for (const rawChunk of pageChunks) {
        const chunkWithHeader = `[DOKUMEN: ${docTitle} | HALAMAN: ${p.pageNum} | KATEGORI: ${finalCategory}]\n${rawChunk}`;
        allChunks.push({
          text: chunkWithHeader,
          pdf_name: docTitle,
          category: finalCategory,
          metadata: { page: p.pageNum, total_pages: pages.length },
        });
      }
    }

    logStatus(`Dibuat ${allChunks.length} chunk presisi tinggi (ukuran ~${CHUNK_SIZE} kata).`);

    const payload = {
      chunks: allChunks,
    };

    logStatus('Mengirim chunks ke server backend untuk embedding dan penyimpanan...');
    const result = await uploadChunksToBackend(payload);
    logStatus(`Selesai! ${result.length} chunk beserta embedding tersimpan di Supabase.`);
    return result;
  } catch (error) {
    console.error(error);
    logStatus(`Terjadi kesalahan: ${error.message}`);
    throw error;
  }
}

window.processPdfFile = processPdfFile;

if (processBtn) {
  processBtn.addEventListener('click', processPdfFile);
}

// 2. Fungsi unggah ke backend untuk embedding dan penyimpanan Supabase
async function uploadChunksToBackend(payload) {
  let token = null;
  try {
    const supabaseClient = window.createAksarakuClient
      ? window.createAksarakuClient()
      : (window.supabase && window.AKSARAKU_CONFIG
          ? window.supabase.createClient(window.AKSARAKU_CONFIG.SUPABASE_URL, window.AKSARAKU_CONFIG.SUPABASE_ANON_KEY)
          : null);
    if (supabaseClient) {
      const { data: { session } } = await supabaseClient.auth.getSession();
      token = session?.access_token;
    }
  } catch (e) {
    console.warn('Gagal mengambil session Supabase untuk upload:', e);
  }

  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  const response = await fetch(EMBED_UPSERT_URL, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  });

  const result = await response.json();
  if (!response.ok) {
    console.error('Backend embed-upsert error:', result);
    throw new Error(result.detail || result.error || result.message || 'Gagal melakukan embed-upsert ke backend.');
  }

  if (!result.data || !Array.isArray(result.data)) {
    throw new Error('Respons backend tidak valid: data embedding tidak ditemukan.');
  }

  return result.data;
}
