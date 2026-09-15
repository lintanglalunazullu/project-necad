const CHUNK_SIZE = 800;
const CHUNK_OVERLAP = 100;
const EMBED_UPSERT_URL = `${window.AKSARAKU_CONFIG.API_BASE_URL}/embed-upsert`;
const pdfFileInput = document.getElementById('pdfFile');
const processBtn = document.getElementById('processBtn');
const statusOutput = document.getElementById('status');

function logStatus(message) {
  const now = new Date().toLocaleTimeString('id-ID');
  statusOutput.textContent += `[${now}] ${message}\n`;
  statusOutput.scrollTop = statusOutput.scrollHeight;
}

function chunkText(text, size, overlap) {
  const tokens = text.split(/\s+/);
  const chunks = [];
  let start = 0;

  while (start < tokens.length) {
    const end = Math.min(start + size, tokens.length);
    chunks.push(tokens.slice(start, end).join(' '));
    start += size - overlap;
  }

  return chunks;
}

async function extractTextFromPDF(file) {
  logStatus('Memuat file PDF...');
  const arrayBuffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;

  let allText = '';
  for (let pageNum = 1; pageNum <= pdf.numPages; pageNum += 1) {
    logStatus(`Mengekstrak teks halaman ${pageNum}/${pdf.numPages}...`);
    const page = await pdf.getPage(pageNum);
    const content = await page.getTextContent();
    const pageText = content.items.map((item) => item.str).join(' ');
    allText += `${pageText}\n\n`;
  }

  return allText.trim();
}

async function processPdfFile(documentName = '', category = 'public') {
  const file = pdfFileInput.files[0];
  if (!file) {
    logStatus('Silakan pilih file PDF terlebih dahulu.');
    return;
  }

  try {
    statusOutput.textContent = '';
    const text = await extractTextFromPDF(file);
    logStatus('Membuat chunk teks...');
    const chunks = chunkText(text, CHUNK_SIZE, CHUNK_OVERLAP);
    logStatus(`Dibuat ${chunks.length} chunk.`);

    const payload = {
      chunks: chunks.map((chunk) => ({
        text: chunk,
        pdf_name: documentName.trim() || file.name,
        category: category === 'private' ? 'private' : 'public',
      })),
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
