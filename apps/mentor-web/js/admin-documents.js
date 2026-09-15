(async function () {
  const access = await window.requireAksarakuRole(['admin'], './login.html');
  if (!access) return;

  const API_BASE_URL = window.AKSARAKU_CONFIG.API_BASE_URL;
  const table = $('#documentsTable').DataTable({
    language: {
      search: 'Cari:',
      lengthMenu: 'Tampilkan _MENU_ dokumen',
      info: 'Menampilkan _START_ sampai _END_ dari _TOTAL_ dokumen',
      infoEmpty: 'Belum ada dokumen',
      zeroRecords: 'Dokumen tidak ditemukan',
      paginate: { previous: 'Sebelumnya', next: 'Berikutnya' },
    },
    columns: [
      { title: 'Nama dokumen' },
      { title: 'Category' },
      { title: 'Jumlah chunk' },
      { title: 'Dibuat' },
      { title: 'Status' },
      { title: 'Aksi', orderable: false, searchable: false },
    ],
  });

  const status = document.getElementById('documentStatus');
  const modal = document.getElementById('documentModal');
  const form = document.getElementById('documentForm');
  const formTitle = document.getElementById('documentFormTitle');
  const documentId = document.getElementById('documentId');
  const documentName = document.getElementById('documentName');
  const documentCategory = document.getElementById('documentCategory');
  const fileInput = document.getElementById('pdfFile');
  const submitButton = document.getElementById('documentSubmitButton');
  const fileSection = document.getElementById('documentFileSection');
  let documents = [];

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, (character) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
    }[character]));
  }

  function showStatus(message, isError = false) {
    status.textContent = message;
    status.className = `mt-5 rounded-lg border px-4 py-3 text-sm ${isError
      ? 'border-red-400/30 bg-red-400/10 text-red-200'
      : 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200'}`;
  }

  function formatDate(value) {
    if (!value) return '-';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' });
  }

  function openModal(item = null) {
    form.reset();
    documentId.value = item?.id || '';
    documentName.value = item?.pdf_name || item?.name || '';
    documentCategory.value = String(item?.category || 'public').toLowerCase() === 'private' ? 'private' : 'public';
    formTitle.textContent = item ? 'Ubah dokumen' : 'Tambah dokumen';
    submitButton.textContent = item ? 'Simpan perubahan' : 'Upload dokumen';
    fileSection.classList.toggle('hidden', !!item);
    modal.classList.remove('hidden');
    documentName.focus();
    document.body.classList.add('overflow-hidden');
  }

  function closeModal() {
    modal.classList.add('hidden');
    document.body.classList.remove('overflow-hidden');
  }

  function render() {
    table.clear().rows.add(documents.map((item) => [
      `<div class="font-semibold text-white">${escapeHtml(item.pdf_name || item.name || 'Tanpa nama')}</div><div class="mt-1 text-xs text-slate-500">ID: ${escapeHtml(item.id || '-')}</div>`,
      `<span class="rounded-full ${String(item.category || 'public').toLowerCase() === 'private' ? 'bg-amber-500/15 text-amber-300' : 'bg-sky-500/15 text-sky-300'} px-2.5 py-1 text-xs font-semibold">${escapeHtml(item.category || 'public')}</span>`,
      escapeHtml(item.chunk_count ?? item.chunks ?? '-'),
      formatDate(item.created_at || item.inserted_at),
      `<span class="rounded-full bg-emerald-500/15 px-2.5 py-1 text-xs font-semibold text-emerald-300">${escapeHtml(item.status || 'Aktif')}</span>`,
      `<div class="flex gap-2"><button type="button" data-edit-id="${escapeHtml(item.id)}" class="rounded-md border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-white/5">Edit</button><button type="button" data-delete-id="${escapeHtml(item.id)}" class="rounded-md border border-red-400/30 px-3 py-1.5 text-xs font-semibold text-red-300 hover:bg-red-400/10">Hapus</button></div>`,
    ])).draw();
  }

  async function request(path, options = {}) {
    let token = access?.session?.access_token;
    if (!token && access?.client?.auth) {
      try {
        const { data: { session } } = await access.client.auth.getSession();
        token = session?.access_token;
      } catch (err) {
        console.warn('Gagal mengambil session auth:', err);
      }
    }

    const headers = {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    };

    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers,
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || result.error || result.message || `Request gagal (${response.status})`);
    return result;
  }

  async function loadDocuments() {
    try {
      const result = await request('/documents');
      documents = Array.isArray(result) ? result : (result.data || result.documents || []);
      render();
    } catch (error) {
      showStatus(`Gagal memuat dokumen: ${error.message}`, true);
    }
  }

  async function deleteDocument(item) {
    if (!item?.id || !window.confirm(`Hapus dokumen "${item.pdf_name || item.name || 'tanpa nama'}" beserta datanya?`)) return;
    try {
      await request(`/documents/${encodeURIComponent(item.id)}`, { method: 'DELETE' });
      showStatus('Dokumen berhasil dihapus.');
      await loadDocuments();
    } catch (error) {
      showStatus(`Gagal menghapus dokumen: ${error.message}`, true);
    }
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    submitButton.disabled = true;
    try {
      if (documentId.value) {
        await request(`/documents/${encodeURIComponent(documentId.value)}`, {
          method: 'PUT',
          body: JSON.stringify({ pdf_name: documentName.value.trim(), category: documentCategory.value }),
        });
        showStatus('Dokumen berhasil diperbarui.');
      } else {
        if (!fileInput.files[0]) throw new Error('Pilih file PDF terlebih dahulu.');
        if (!documentName.value.trim()) documentName.value = fileInput.files[0].name;
        await window.processPdfFile(documentName.value.trim() || fileInput.files[0].name, documentCategory.value);
        showStatus('Dokumen berhasil di-upload.');
      }
      closeModal();
      await loadDocuments();
    } catch (error) {
      showStatus(`Gagal menyimpan dokumen: ${error.message}`, true);
    } finally {
      submitButton.disabled = false;
    }
  });

  document.getElementById('newDocumentButton').addEventListener('click', () => openModal());
  document.getElementById('cancelDocumentButton').addEventListener('click', closeModal);
  document.getElementById('closeDocumentModalButton').addEventListener('click', closeModal);
  modal.addEventListener('click', (event) => {
    if (event.target === modal) closeModal();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !modal.classList.contains('hidden')) closeModal();
  });
  document.querySelector('#documentsTable tbody').addEventListener('click', (event) => {
    const editButton = event.target.closest('[data-edit-id]');
    const deleteButton = event.target.closest('[data-delete-id]');
    if (editButton) openModal(documents.find((item) => String(item.id) === editButton.dataset.editId));
    if (deleteButton) deleteDocument(documents.find((item) => String(item.id) === deleteButton.dataset.deleteId));
  });

  lucide.createIcons();
  await loadDocuments();
})();
