// apps/mentor-web/js/pdf-upload.js — Smart Layout-Aware, Table-Preserved & OCR Vision PDF Processor
const CHUNK_SIZE = 350;
const CHUNK_OVERLAP = 60;
const API_BASE_URL = window.AKSARAKU_CONFIG ? window.AKSARAKU_CONFIG.API_BASE_URL : '';
const EMBED_UPSERT_URL = `${API_BASE_URL}/embed-upsert`;
const OCR_PAGE_URL = `${API_BASE_URL}/documents/ocr-page`;
const SUMMARIZE_URL = `${API_BASE_URL}/documents/summarize-and-suggest`;

const pdfFileInput = document.getElementById('pdfFile');
const processBtn = document.getElementById('processBtn');
const statusOutput = document.getElementById('status');

function logStatus(message) {
  if (!statusOutput) return;
  statusOutput.classList.remove('hidden');
  const now = new Date().toLocaleTimeString('id-ID');
  statusOutput.textContent += `[${now}] ${message}\n`;
  statusOutput.scrollTop = statusOutput.scrollHeight;
}

// 1. Rekonstruksi teks berbasis koordinat Y (Line & Table aware)
function formatPageItemsToStructuredText(items) {
  if (!items || !items.length) return '';

  const valid = items.filter((it) => it.str && it.str.trim());
  if (!valid.length) return '';

  // Urutkan vertikal (Y descending), lalu horizontal (X ascending)
  valid.sort((a, b) => {
    const yDiff = b.transform[5] - a.transform[5];
    if (Math.abs(yDiff) > 3) return yDiff;
    return a.transform[4] - b.transform[4];
  });

  const lines = [];
  let currentLine = [];
  let currentY = null;

  for (const item of valid) {
    const y = item.transform[5];
    if (currentY === null || Math.abs(currentY - y) <= 4) {
      currentLine.push(item);
      if (currentY === null) currentY = y;
    } else {
      lines.push(currentLine);
      currentLine = [item];
      currentY = y;
    }
  }
  if (currentLine.length) lines.push(currentLine);

  const formattedLines = [];
  for (const line of lines) {
    line.sort((a, b) => a.transform[4] - b.transform[4]);
    let lineStr = '';
    let lastXEnd = null;
    let hasColumnGaps = false;

    for (let i = 0; i < line.length; i++) {
      const it = line[i];
      const x = it.transform[4];
      const text = it.str.trim();
      if (!text) continue;

      if (lastXEnd !== null) {
        const gap = x - lastXEnd;
        // Jarak antar kolom tabel (> 22pt)
        if (gap > 22) {
          lineStr += ' | ' + text;
          hasColumnGaps = true;
        } else if (gap > 2) {
          lineStr += ' ' + text;
        } else {
          lineStr += text;
        }
      } else {
        lineStr += text;
      }
      lastXEnd = x + (it.width || (text.length * 6));
    }

    if (hasColumnGaps) {
      if (!lineStr.startsWith('|')) lineStr = '| ' + lineStr;
      if (!lineStr.endsWith('|')) lineStr = lineStr + ' |';
    }

    if (lineStr.trim()) {
      formattedLines.push(lineStr.trim());
    }
  }

  return formattedLines.join('\n');
}

// 2. Auth Helper
async function getAuthToken() {
  try {
    const supabaseClient = window.createAksarakuClient
      ? window.createAksarakuClient()
      : (window.supabase && window.AKSARAKU_CONFIG
          ? window.supabase.createClient(window.AKSARAKU_CONFIG.SUPABASE_URL, window.AKSARAKU_CONFIG.SUPABASE_ANON_KEY)
          : null);
    if (supabaseClient) {
      const { data: { session } } = await supabaseClient.auth.getSession();
      return session?.access_token || null;
    }
  } catch (e) {
    console.warn('Gagal mengambil session auth:', e);
  }
  return null;
}

// 3. OCR Halaman Scan / Gambar via Gemini Vision
async function callBackendOcrPage(imageBase64, pageNum) {
  const token = await getAuthToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  const response = await fetch(OCR_PAGE_URL, {
    method: 'POST',
    headers,
    body: JSON.stringify({ image_base64: imageBase64, page_num: pageNum }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `OCR failed HTTP ${response.status}`);
  }

  return await response.json();
}

// 4. Ekstrak Halaman dengan Deteksi & Fallback OCR Vision
async function extractPageTextWithOcrFallback(page, pageNum) {
  const content = await page.getTextContent();
  let structuredText = formatPageItemsToStructuredText(content.items);

  // Jika teks kosong atau sangat sedikit (< 25 karakter), halaman adalah pindaian/scan gambar
  const cleanLen = structuredText.replace(/\s+/g, '').length;
  if (cleanLen < 25) {
    logStatus(`[Halaman ${pageNum}] Teks tidak terdeteksi (dokumen berupa foto/scan). Menjalankan Gemini Vision OCR...`);
    try {
      const viewport = page.getViewport({ scale: 1.5 });
      const canvas = document.createElement('canvas');
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      const ctx = canvas.getContext('2d');
      await page.render({ canvasContext: ctx, viewport }).promise;
      const base64Data = canvas.toDataURL('image/jpeg', 0.85);

      const ocrRes = await callBackendOcrPage(base64Data, pageNum);
      if (ocrRes && ocrRes.markdown_text) {
        logStatus(`[Halaman ${pageNum}] ✅ Gemini Vision OCR berhasil mengekstrak struktur teks & tabel.`);
        return ocrRes.markdown_text;
      }
    } catch (ocrErr) {
      logStatus(`[Halaman ${pageNum}] Peringatan OCR: ${ocrErr.message}`);
    }
  }

  return structuredText;
}

// 5. Chunking Pintar Terstruktur (Contextual Section Carry-Over)
function chunkStructuredText(text, size = CHUNK_SIZE, overlap = CHUNK_OVERLAP) {
  const lines = text.split('\n');
  const chunks = [];
  let currentSection = 'Umum';
  let currentLines = [];
  let currentWordCount = 0;

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    // Deteksi judul bagian/bab
    if (/^(#{1,4}\s+|bab\s+|pasal\s+|bagian\s+|jadwal\s+|daftar\s+)/i.test(trimmed) ||
        (/^[A-Z0-9\s\.\-]{5,60}$/.test(trimmed) && !trimmed.includes('|') && trimmed.length < 50)) {
      currentSection = trimmed.replace(/^#+\s*/, '').trim();
    }

    const words = trimmed.split(/\s+/).filter(Boolean);
    const lineWordCount = words.length;

    if (currentWordCount + lineWordCount <= size) {
      currentLines.push(line);
      currentWordCount += lineWordCount;
    } else {
      if (currentLines.length > 0) {
        chunks.push({
          section: currentSection,
          body: currentLines.join('\n'),
        });

        // Pertahankan overlap beberapa baris utuh
        let overlapWords = 0;
        const keptLines = [];
        for (let i = currentLines.length - 1; i >= 0; i--) {
          const wCount = currentLines[i].split(/\s+/).filter(Boolean).length;
          if (overlapWords + wCount <= overlap) {
            keptLines.unshift(currentLines[i]);
            overlapWords += wCount;
          } else {
            break;
          }
        }
        currentLines = [...keptLines, line];
        currentWordCount = overlapWords + lineWordCount;
      } else {
        chunks.push({
          section: currentSection,
          body: line,
        });
        currentLines = [];
        currentWordCount = 0;
      }
    }
  }

  if (currentLines.length > 0) {
    chunks.push({
      section: currentSection,
      body: currentLines.join('\n'),
    });
  }

  return chunks;
}

// 6. Alur Utama Pemrosesan Dokumen
async function processPdfFile(documentName = '', category = 'public') {
  const file = pdfFileInput?.files?.[0];
  if (!file) {
    logStatus('Silakan pilih file PDF terlebih dahulu.');
    return;
  }

  try {
    if (statusOutput) statusOutput.textContent = '';
    logStatus(`Memuat file PDF: ${file.name} (${(file.size / 1024).toFixed(1)} KB)...`);

    const arrayBuffer = await file.arrayBuffer();
    const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
    logStatus(`PDF berhasil dimuat: ${pdf.numPages} halaman.`);

    const docTitle = documentName.trim() || file.name.replace(/\.[^/.]+$/, '');
    const finalCategory = category === 'private' ? 'private' : 'public';
    const allChunks = [];
    const allExtractedTexts = [];

    for (let pageNum = 1; pageNum <= pdf.numPages; pageNum += 1) {
      logStatus(`Menganalisis tata letak halaman ${pageNum}/${pdf.numPages}...`);
      const page = await pdf.getPage(pageNum);
      const pageText = await extractPageTextWithOcrFallback(page, pageNum);

      if (pageText && pageText.trim()) {
        allExtractedTexts.push(pageText.trim());
        const structuredChunks = chunkStructuredText(pageText, CHUNK_SIZE, CHUNK_OVERLAP);
        for (const c of structuredChunks) {
          const chunkWithHeader = `[DOKUMEN: ${docTitle} | HALAMAN: ${pageNum} | BAGIAN: ${c.section} | KATEGORI: ${finalCategory}]\n${c.body}`;
          allChunks.push({
            text: chunkWithHeader,
            pdf_name: docTitle,
            category: finalCategory,
            metadata: {
              page: pageNum,
              total_pages: pdf.numPages,
              section: c.section,
            },
          });
        }
      }
    }

    if (!allChunks.length) {
      throw new Error('Tidak ada teks atau gambar dokumen yang berhasil diekstrak dari PDF.');
    }

    logStatus(`Berhasil membuat ${allChunks.length} chunk terstruktur dengan konteks judul & tabel.`);
    logStatus('Mengirim chunk ke server backend (dengan Auto Clean-Upsert & Gemini embedding)...');

    const payload = {
      chunks: allChunks,
      clean_upsert: true,
    };

    const result = await uploadChunksToBackend(payload);
    logStatus(`✅ Sukses! ${result.length} chunk tersimpan rapi di database Supabase.`);

    // Buat ringkasan dan rekomendasi pertanyaan otomatis
    try {
      logStatus('Menghasilkan ringkasan cerdas & rekomendasi pertanyaan dengan AI...');
      const sampleText = allExtractedTexts.slice(0, 3).join('\n\n').slice(0, 5000);
      const intelRes = await requestDocumentSummary(docTitle, sampleText);
      if (intelRes && intelRes.summary) {
        logStatus(`\n📄 Ringkasan AI: ${intelRes.summary}`);
        if (intelRes.suggested_questions && intelRes.suggested_questions.length) {
          logStatus(`\n💡 Contoh Pertanyaan yang Siap Ditanyakan:`);
          intelRes.suggested_questions.forEach((q, idx) => logStatus(`  ${idx + 1}. "${q}"`));
        }
      }
    } catch (intelErr) {
      console.warn('Intel summary skipped:', intelErr);
    }

    return result;
  } catch (error) {
    console.error(error);
    logStatus(`Terjadi kesalahan: ${error.message}`);
    throw error;
  }
}

// 7. Request Document Summary
async function requestDocumentSummary(documentName, sampleText) {
  const token = await getAuthToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  const response = await fetch(SUMMARIZE_URL, {
    method: 'POST',
    headers,
    body: JSON.stringify({ document_name: documentName, sample_text: sampleText }),
  });

  if (!response.ok) return null;
  return await response.json();
}

// 8. Upload chunks ke Backend
async function uploadChunksToBackend(payload) {
  const token = await getAuthToken();
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

window.processPdfFile = processPdfFile;

if (processBtn) {
  processBtn.addEventListener('click', processPdfFile);
}
