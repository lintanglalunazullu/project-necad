/**
 * Aksaraku Admin — Panel Pengaturan AI
 * Clean, Simple, Professional, To the Point.
 */
(async function () {
  const access = await window.requireAksarakuRole(['admin'], './login.html');
  if (!access) return;

  const API_BASE_URL = window.AKSARAKU_CONFIG.API_BASE_URL;

  // State
  let providersData = {};
  let currentTab = 'gemini';
  let scannedModelsCache = {};
  let keyHealthCache = {}; 

  const DEFAULT_FALLBACK_MODELS = {
    gemini: [
      { id: 'gemini-3.5-flash-lite', name: 'Gemini 3.5 Flash-Lite (Ultra Cepat & Anti-Overload)' },
      { id: 'gemini-3.6-flash', name: 'Gemini 3.6 Flash (Utama & Cerdas)' },
      { id: 'gemini-3.5-flash', name: 'Gemini 3.5 Flash (Stabil & Cepat)' }
    ],
    groq: [
      { id: 'llama-3.3-70b-versatile', name: 'Llama 3.3 70B Versatile' },
      { id: 'llama-3.1-8b-instant', name: 'Llama 3.1 8B Instant' },
      { id: 'deepseek-r1-distill-llama-70b', name: 'DeepSeek R1 Distill 70B' }
    ],
    openrouter: [
      { id: 'meta-llama/llama-3.3-70b-instruct:free', name: 'Llama 3.3 70B (Free)' },
      { id: 'deepseek/deepseek-r1:free', name: 'DeepSeek R1 (Free)' },
      { id: 'qwen/qwen-2.5-72b-instruct:free', name: 'Qwen 2.5 72B (Free)' }
    ]
  };

  const PROVIDER_METADATA = {
    gemini: { name: 'Google Gemini', help: 'Dapatkan key di aistudio.google.com' },
    groq: { name: 'Groq LPU', help: 'Dapatkan key di console.groq.com' },
    openrouter: { name: 'OpenRouter', help: 'Dapatkan key di openrouter.ai' }
  };

  // Helper HTTP request
  async function apiRequest(path, options = {}) {
    let token = access?.session?.access_token;
    if (!token && access?.client?.auth) {
      try {
        const { data: { session } } = await access.client.auth.getSession();
        token = session?.access_token;
      } catch (err) {}
    }

    const headers = {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    };

    const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(result.detail || result.error || result.message || `HTTP ${response.status}`);
    }
    return result;
  }

  function showNotification(message, isError = false) {
    let container = document.getElementById('toastContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toastContainer';
      container.className = 'fixed top-4 right-4 z-50 flex flex-col gap-2 pointer-events-none';
      document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = `px-4 py-3 rounded-lg shadow-lg text-sm font-medium transform transition-all duration-300 translate-x-full opacity-0 ${
      isError ? 'bg-red-500 text-white shadow-red-500/20' 
              : 'bg-emerald-500 text-white shadow-emerald-500/20'
    }`;
    toast.textContent = message;
    container.appendChild(toast);
    
    // Animate in
    setTimeout(() => toast.classList.remove('translate-x-full', 'opacity-0'), 10);
    
    // Animate out and remove
    setTimeout(() => {
      toast.classList.add('opacity-0', 'translate-x-full');
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }

  async function loadProviders() {
    try {
      const res = await apiRequest('/admin/ai/providers');
      const list = res.providers || [];
      providersData = {};
      list.forEach((p) => { providersData[p.name] = p; });
      renderWorkspace(currentTab);
    } catch (err) {
      showNotification(`Gagal memuat konfigurasi: ${err.message}`, true);
    }
  }

  function switchTab(providerName) {
    currentTab = providerName;
    document.querySelectorAll('[data-provider-tab]').forEach((btn) => {
      const isTarget = btn.dataset.providerTab === providerName;
      if (isTarget) {
        btn.className = 'px-4 py-2 rounded text-sm font-medium bg-white/10 text-white shadow-sm transition-all';
      } else {
        btn.className = 'px-4 py-2 rounded text-sm font-medium text-slate-400 hover:text-white transition-all';
      }
    });

    const input = document.getElementById('inputNewApiKey');
    if (input) {
      if (providerName === 'gemini') {
        input.placeholder = 'AIzaSy... atau AQ.Ab...';
      } else if (providerName === 'groq') {
        input.placeholder = 'gsk_...';
      } else if (providerName === 'openrouter') {
        input.placeholder = 'sk-or-...';
      } else {
        input.placeholder = 'sk-...';
      }
    }

    renderWorkspace(providerName);
  }

  function renderWorkspace(providerName) {
    const p = providersData[providerName] || { enabled: true, priority: 1, model: '', temperature: 0.2, max_tokens: 600, keys: [] };
    const meta = PROVIDER_METADATA[providerName] || { name: providerName, help: '' };

    document.getElementById('activeProviderTitle').textContent = meta.name;
    document.getElementById('providerHelpUrl').textContent = meta.help;
    document.getElementById('provider_enabled_toggle').checked = !!p.enabled;
    document.getElementById('provider_priority_select').value = String(p.priority || 1);
    
    // Nearest mapping for style/length
    document.getElementById('style_select').value = p.temperature >= 0.7 ? "0.7" : (p.temperature <= 0.1 ? "0.0" : "0.2");
    document.getElementById('length_select').value = p.max_tokens >= 1000 ? "1200" : (p.max_tokens <= 400 ? "300" : "600");

    document.getElementById('testResultIndicator').textContent = '';

    renderKeysTable(providerName);
    populateModelSelect(providerName);
  }

  function renderKeysTable(providerName) {
    const container = document.getElementById('keysContainer');
    if (!container) return;

    const p = providersData[providerName];
    let keysList = p?.keys || [];
    if (keysList.length === 0 && p?.masked_api_key) {
      keysList = [{ id: 0, label: 'Kunci Utama', masked: p.masked_api_key }];
    }

    if (keysList.length === 0) {
      container.innerHTML = `<p class="text-xs text-slate-500 p-2">Belum ada API key.</p>`;
      return;
    }

    container.innerHTML = keysList.map((k, idx) => {
      const health = keyHealthCache[`${providerName}_${idx}`];
      let healthText = '<span class="text-slate-500">Belum diuji</span>';
      
      if (health) {
        if (health.success) {
          healthText = `<span class="text-emerald-400 font-medium">✓ Normal (${health.latency_ms}ms)</span>`;
        } else {
          healthText = `<span class="text-red-400 font-medium" title="${health.error || ''}">✗ ${health.status_label || 'Gagal'}</span>`;
        }
      }

      const label = k.label || (idx === 0 ? 'Kunci Utama' : `Kunci Cadangan #${idx}`);

      return `
        <div class="flex items-center justify-between p-2.5 rounded-lg bg-white/5 border border-white/10 hover:border-white/20 transition-colors">
          <div class="flex items-center gap-3">
            <span class="text-[11px] px-2 py-0.5 rounded bg-blue-500/20 text-blue-300 font-medium">${label}</span>
            <span class="text-xs font-mono text-slate-200 tracking-wider">${k.masked || '••••••••'}</span>
            <span class="text-[11px]">${healthText}</span>
          </div>
          <div class="flex items-center gap-2">
            <button type="button" data-test-key-idx="${idx}" class="text-xs px-2 py-1 rounded bg-white/5 hover:bg-white/10 text-slate-300 hover:text-white transition-colors">Uji</button>
            <button type="button" data-delete-key-idx="${idx}" class="text-xs px-2 py-1 rounded bg-red-500/10 hover:bg-red-500/20 text-red-400 hover:text-red-300 transition-colors">Hapus</button>
          </div>
        </div>
      `;
    }).join('');

    container.querySelectorAll('[data-test-key-idx]').forEach(btn => {
      btn.addEventListener('click', () => testSingleKey(providerName, parseInt(btn.dataset.testKeyIdx, 10)));
    });
    container.querySelectorAll('[data-delete-key-idx]').forEach(btn => {
      btn.addEventListener('click', () => deleteKey(providerName, parseInt(btn.dataset.deleteKeyIdx, 10)));
    });
  }

  function populateModelSelect(providerName) {
    const select = document.getElementById('active_model_select');
    if (!select) return;

    const p = providersData[providerName];
    if (p?.model && (p.model.includes('3.8') || p.model.includes('3.7') || p.model.includes('2.5'))) {
      p.model = 'gemini-3.5-flash-lite';
    }

    const models = scannedModelsCache[providerName] || DEFAULT_FALLBACK_MODELS[providerName] || [];
    const onlyFree = document.getElementById('filterOnlyFreeModels')?.checked;

    let filteredModels = models.filter(m => {
      const mid = String(m.id || '').toLowerCase();
      if (mid.includes('3.8') || mid.includes('3.7') || mid.includes('2.5')) return false;
      return true;
    });

    if (onlyFree) {
      filteredModels = filteredModels.filter(m => {
        const mid = String(m.id || '').toLowerCase();
        const mname = String(m.name || '').toLowerCase();
        const isFree = m.tier === 'free' || mid.includes(':free') || mid.includes('flash') || mname.includes('gratis') || providerName === 'groq';
        return isFree;
      });
    }

    select.innerHTML = filteredModels.map(m => {
      const mid = String(m.id || '').toLowerCase();
      const mname = String(m.name || '').toLowerCase();
      const isFree = m.tier === 'free' || mid.includes(':free') || mid.includes('flash') || mname.includes('gratis') || providerName === 'groq';
      const tag = isFree ? '[Gratis]' : '[Pro]';
      return `<option value="${m.id}">${m.name || m.id} ${tag}</option>`;
    }).join('');
    
    if (p?.model) {
      const exists = Array.from(select.options).some(opt => opt.value === p.model);
      if (!exists) {
        select.innerHTML += `<option value="${p.model}">${p.model} (Tersimpan)</option>`;
      }
      select.value = p.model;
    }
  }

  document.getElementById('filterOnlyFreeModels')?.addEventListener('change', () => {
    populateModelSelect(currentTab);
  });

  // Priority Auto-Swap
  document.getElementById('provider_priority_select')?.addEventListener('change', (e) => {
    const newPriority = parseInt(e.target.value, 10);
    const currentP = providersData[currentTab];
    if (!currentP) return;

    const oldPriority = currentP.priority || 1;
    currentP.priority = newPriority;

    Object.keys(providersData).forEach((otherName) => {
      if (otherName !== currentTab && providersData[otherName].priority === newPriority) {
        providersData[otherName].priority = oldPriority;
      }
    });
  });

  // Keys Ops
  async function handleAddApiKey() {
    const input = document.getElementById('inputNewApiKey');
    const newKey = input ? input.value.trim() : '';
    if (!newKey) return;

    const btn = document.getElementById('btnAddApiKey');
    const p = providersData[currentTab];
    let keysList = p?.keys || [];
    if (keysList.length === 0 && p?.masked_api_key) {
      keysList = [{ id: 0, masked: p.masked_api_key }];
    }
    const existingKeys = keysList.map(k => ({ id: k.id, masked: k.masked }));
    const allKeysToSend = [...existingKeys, { value: newKey }];

    try {
      if (btn) {
        btn.disabled = true;
        btn.textContent = '...';
      }
      await apiRequest(`/admin/ai/providers/${currentTab}`, {
        method: 'PUT',
        body: JSON.stringify({ api_keys: allKeysToSend }),
      });
      if (input) input.value = '';
      showNotification('Kunci API baru berhasil ditambahkan!');
      await loadProviders();
    } catch (err) {
      showNotification(`Gagal menambahkan: ${err.message}`, true);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Tambah';
      }
    }
  }

  document.getElementById('btnAddApiKey')?.addEventListener('click', handleAddApiKey);
  document.getElementById('inputNewApiKey')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleAddApiKey();
    }
  });

  async function deleteKey(providerName, index) {
    if (!confirm(`Hapus Kunci API ke-${index + 1}?`)) return;
    const p = providersData[providerName];
    let keysList = p?.keys || [];
    if (keysList.length === 0 && p?.masked_api_key) {
      keysList = [{ id: 0, masked: p.masked_api_key }];
    }
    const remainingKeys = keysList
      .filter((_, idx) => idx !== index)
      .map(k => ({ id: k.id, masked: k.masked }));

    try {
      await apiRequest(`/admin/ai/providers/${providerName}`, {
        method: 'PUT',
        body: JSON.stringify({ api_keys: remainingKeys }),
      });
      delete keyHealthCache[`${providerName}_${index}`];
      showNotification('Kunci berhasil dihapus.');
      await loadProviders();
    } catch (err) {
      showNotification(`Gagal menghapus: ${err.message}`, true);
    }
  }

  async function testSingleKey(providerName, index) {
    try {
      const res = await apiRequest(`/admin/ai/providers/${providerName}/test-keys`, { method: 'POST' });
      if (res.results && res.results[index]) {
        keyHealthCache[`${providerName}_${index}`] = res.results[index];
        if (!res.results[index].success) {
          showNotification(`Uji kunci ke-${index + 1} gagal: ${res.results[index].error || 'Tidak valid'}`, true);
        } else {
          showNotification(`Uji kunci ke-${index + 1} berhasil! (${res.results[index].latency_ms}ms)`);
        }
      }
      renderKeysTable(providerName);
    } catch (err) {
      showNotification(`Gagal menguji: ${err.message}`, true);
    }
  }

  document.getElementById('btnTestAllKeys')?.addEventListener('click', async (e) => {
    const btn = e.target;
    try {
      btn.textContent = 'Menguji...';
      const res = await apiRequest(`/admin/ai/providers/${currentTab}/test-keys`, { method: 'POST' });
      let failedCount = 0;
      let totalCount = (res.results || []).length;
      (res.results || []).forEach((item, idx) => {
        keyHealthCache[`${currentTab}_${idx}`] = item;
        if (!item.success) failedCount++;
      });
      if (failedCount > 0) {
        showNotification(`${failedCount} dari ${totalCount} kunci gagal terhubung!`, true);
      } else if (totalCount > 0) {
        showNotification(`Semua ${totalCount} kunci aktif dan normal!`);
      }
      renderKeysTable(currentTab);
    } catch (err) {
      showNotification(`Gagal menguji: ${err.message}`, true);
    } finally {
      btn.textContent = '↻ Uji Koneksi Semua Kunci';
    }
  });

  document.getElementById('btnScanModels')?.addEventListener('click', async (e) => {
    const btn = e.target;
    try {
      btn.textContent = 'Memindai...';
      const res = await apiRequest(`/admin/ai/providers/${currentTab}/scan-models`, { method: 'POST' });
      if (res.models && res.models.length > 0) {
        scannedModelsCache[currentTab] = res.models;
        populateModelSelect(currentTab);
        showNotification(`Ditemukan ${res.models.length} model.`);
      }
    } catch (err) {
      showNotification(`Gagal memindai: ${err.message}`, true);
    } finally {
      btn.textContent = '↻ Pindai Model Terbaru';
    }
  });

  document.getElementById('btnSaveActiveProvider')?.addEventListener('click', async (e) => {
    const btn = e.target;
    const enabled = document.getElementById('provider_enabled_toggle').checked;
    const priority = parseInt(document.getElementById('provider_priority_select').value, 10);
    let model = document.getElementById('active_model_select').value;
    if (model && (model.includes('3.8') || model.includes('3.7') || model.includes('2.5'))) {
      model = 'gemini-3.5-flash-lite';
    }
    const temperature = parseFloat(document.getElementById('style_select').value);
    const max_tokens = parseInt(document.getElementById('length_select').value, 10);

    const input = document.getElementById('inputNewApiKey');
    const pendingNewKey = input ? input.value.trim() : '';

    try {
      btn.disabled = true;
      btn.textContent = 'Menyimpan...';

      const updatePayload = { enabled, priority, model, temperature, max_tokens };

      // Jika user mengisi input key tapi langsung klik "Simpan Pengaturan"
      if (pendingNewKey) {
        const p = providersData[currentTab];
        let keysList = p?.keys || [];
        if (keysList.length === 0 && p?.masked_api_key) {
          keysList = [{ id: 0, masked: p.masked_api_key }];
        }
        const existingKeys = keysList.map(k => ({ id: k.id, masked: k.masked }));
        updatePayload.api_keys = [...existingKeys, { value: pendingNewKey }];
      }

      await apiRequest(`/admin/ai/providers/${currentTab}`, {
        method: 'PUT',
        body: JSON.stringify(updatePayload),
      });

      if (pendingNewKey && input) {
        input.value = '';
      }

      for (const [pName, pData] of Object.entries(providersData)) {
        if (pName !== currentTab) {
          await apiRequest(`/admin/ai/providers/${pName}`, {
            method: 'PUT',
            body: JSON.stringify({ priority: pData.priority }),
          }).catch(() => {});
        }
      }

      showNotification('Pengaturan berhasil disimpan.');
      await loadProviders();
    } catch (err) {
      showNotification(`Gagal menyimpan: ${err.message}`, true);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Simpan Pengaturan';
    }
  });

  document.getElementById('btnLiveChatTest')?.addEventListener('click', async (e) => {
    const btn = e.target;
    const ind = document.getElementById('testResultIndicator');
    try {
      btn.disabled = true;
      ind.className = 'text-sm font-medium text-slate-400';
      ind.textContent = 'Mengirim pesan...';
      
      const model = document.getElementById('active_model_select').value;
      const res = await apiRequest('/admin/ai/providers/test', {
        method: 'POST',
        body: JSON.stringify({ provider: currentTab, model, prompt: 'Test koneksi singkat' }),
      });

      if (res.success) {
        ind.className = 'text-sm font-medium text-emerald-400';
        ind.textContent = `Sukses (${res.latency_ms}ms)`;
      } else {
        ind.className = 'text-sm font-medium text-red-400';
        ind.textContent = `Gagal: ${res.error || 'Unknown Error'}`;
      }
    } catch (err) {
      ind.className = 'text-sm font-medium text-red-400';
      ind.textContent = `Error: ${err.message}`;
    } finally {
      btn.disabled = false;
    }
  });

  document.getElementById('btnReloadFromDb')?.addEventListener('click', async (e) => {
    const btn = e.target;
    try {
      btn.disabled = true;
      btn.textContent = '...';
      await apiRequest('/admin/ai/reload', { method: 'POST' });
      showNotification('Berhasil sinkronisasi dengan Database.');
      await loadProviders();
    } catch (err) {
      showNotification(`Gagal sinkronisasi: ${err.message}`, true);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Sinkronisasi Ulang';
    }
  });

  // Bind tab clicks
  document.querySelectorAll('[data-provider-tab]').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.providerTab));
  });

  // Sidebar mobile
  document.querySelector('[data-mobile-menu-toggle]')?.addEventListener('click', () => {
    document.querySelector('[data-mobile-sidebar]')?.classList.toggle('hidden');
    document.querySelector('[data-mobile-sidebar-overlay]')?.classList.toggle('hidden');
  });
  document.querySelector('[data-mobile-sidebar-overlay]')?.addEventListener('click', () => {
    document.querySelector('[data-mobile-sidebar]')?.classList.add('hidden');
    document.querySelector('[data-mobile-sidebar-overlay]')?.classList.add('hidden');
  });

  // ==========================================
  // Auto-Smart Learned Synonyms Management
  // ==========================================
  let learnedSynonymsList = [];

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function renderLearnedTable(items) {
    const tbody = document.getElementById('learnedWordsTableBody');
    if (!tbody) return;

    if (!items || items.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="5" class="py-8 text-center text-slate-400 font-sans">
            <span class="block text-2xl mb-1">🌱</span>
            Belum ada kosakata baru yang tersimpan di memori. AI akan secara otomatis mempelajari kosakata gaul dan daerah dari obrolan pengguna!
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = items.map((item) => {
      const isAuto = (item.source || '').toLowerCase().includes('auto');
      const badgeClass = isAuto
        ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
        : 'bg-blue-500/10 text-blue-400 border-blue-500/20';
      const badgeLabel = isAuto ? '🤖 Auto-Smart AI' : '👤 Admin';
      const count = item.occurrences || 1;

      return `
        <tr class="hover:bg-white/[0.02] transition-colors group">
          <td class="py-3 px-4 font-mono font-medium text-white text-xs">
            <span class="px-2 py-0.5 rounded bg-white/5 border border-white/10 text-amber-300">${escapeHtml(item.slang_word)}</span>
          </td>
          <td class="py-3 px-4 font-sans text-xs text-slate-200">
            ${escapeHtml(item.canonical_word)}
          </td>
          <td class="py-3 px-4 text-center font-mono text-xs text-slate-300">
            <span class="px-1.5 py-0.5 rounded bg-white/5 text-slate-300">${count}x</span>
          </td>
          <td class="py-3 px-4 font-sans text-xs">
            <span class="inline-block px-2 py-0.5 text-[10px] rounded-full border ${badgeClass}">
              ${badgeLabel}
            </span>
          </td>
          <td class="py-3 px-4 text-right">
            <button type="button" data-delete-slang="${escapeHtml(item.slang_word)}" class="px-2.5 py-1 text-[11px] rounded bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 transition-colors">
              Hapus
            </button>
          </td>
        </tr>
      `;
    }).join('');
  }

  async function loadLearnedSynonyms() {
    try {
      const res = await apiRequest('/admin/ai/learned-synonyms');
      learnedSynonymsList = res.synonyms || [];
      const badge = document.getElementById('learnedCountBadge');
      if (badge) {
        badge.textContent = `${learnedSynonymsList.length} Kata Aktif`;
      }
      const filterVal = (document.getElementById('filterLearnedInput')?.value || '').toLowerCase().trim();
      if (filterVal) {
        renderLearnedTable(learnedSynonymsList.filter(it => 
          (it.slang_word || '').toLowerCase().includes(filterVal) || 
          (it.canonical_word || '').toLowerCase().includes(filterVal)
        ));
      } else {
        renderLearnedTable(learnedSynonymsList);
      }
    } catch (err) {
      console.warn('Gagal memuat memori kosakata:', err);
    }
  }

  // Filter input
  document.getElementById('filterLearnedInput')?.addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase().trim();
    if (!q) {
      renderLearnedTable(learnedSynonymsList);
      return;
    }
    const filtered = learnedSynonymsList.filter(it => 
      (it.slang_word || '').toLowerCase().includes(q) || 
      (it.canonical_word || '').toLowerCase().includes(q)
    );
    renderLearnedTable(filtered);
  });

  // Refresh button
  document.getElementById('btnRefreshLearnedWords')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    try {
      btn.disabled = true;
      btn.innerHTML = '<span>↻</span> Memperbarui...';
      await apiRequest('/admin/ai/trigger-learning', { method: 'POST' });
      await loadLearnedSynonyms();
      showNotification('Memori kosakata berhasil disinkronkan.');
    } catch (err) {
      showNotification(`Gagal memperbarui: ${err.message}`, true);
    } finally {
      btn.disabled = false;
      btn.innerHTML = '<span>↻</span> Segarkan Memori';
    }
  });

  // Form add
  document.getElementById('formAddLearnedWord')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const slangInput = document.getElementById('inputSlangWord');
    const canonicalInput = document.getElementById('inputCanonicalWord');
    const slang_word = (slangInput?.value || '').trim();
    const canonical_word = (canonicalInput?.value || '').trim();

    if (!slang_word || !canonical_word) {
      showNotification('Silakan isi kata gaul dan padanannya.', true);
      return;
    }

    const submitBtn = document.getElementById('btnAddLearnedWord');
    try {
      if (submitBtn) submitBtn.disabled = true;
      await apiRequest('/admin/ai/learned-synonyms', {
        method: 'POST',
        body: JSON.stringify({ slang_word, canonical_word })
      });
      showNotification(`Kata "${slang_word}" berhasil disimpan ke memori AI.`);
      if (slangInput) slangInput.value = '';
      if (canonicalInput) canonicalInput.value = '';
      await loadLearnedSynonyms();
    } catch (err) {
      showNotification(`Gagal menyimpan: ${err.message}`, true);
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  });

  // Event delegation for delete buttons
  document.getElementById('learnedWordsTableBody')?.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-delete-slang]');
    if (!btn) return;
    const slang = btn.getAttribute('data-delete-slang');
    if (!confirm(`Hapus kata "${slang}" dari memori AI?`)) return;

    try {
      btn.disabled = true;
      btn.textContent = '...';
      await apiRequest(`/admin/ai/learned-synonyms/${encodeURIComponent(slang)}`, {
        method: 'DELETE'
      });
      showNotification(`Kata "${slang}" berhasil dihapus dari memori AI.`);
      await loadLearnedSynonyms();
    } catch (err) {
      showNotification(`Gagal menghapus: ${err.message}`, true);
      btn.disabled = false;
      btn.textContent = 'Hapus';
    }
  });

  await loadProviders();
  await loadLearnedSynonyms();
})();
