/**
 * Aksaraku Admin — Panel Manajemen AI Engine & Fallback
 * Standar Senior AI Fullstack Engineer:
 * - Runtime configuration update tanpa restart server
 * - Live connection & latency test runner
 * - Visualisasi model catalog Free vs Pro
 * - Token auth injection aman
 */
(async function () {
  const access = await window.requireAksarakuRole(['admin'], './login.html');
  if (!access) return;

  const API_BASE_URL = window.AKSARAKU_CONFIG.API_BASE_URL;
  let allModels = [];
  let providersData = {};

  // Helper untuk otorisasi API
  async function apiRequest(path, options = {}) {
    let token = access?.session?.access_token;
    if (!token && access?.client?.auth) {
      try {
        const { data: { session } } = await access.client.auth.getSession();
        token = session?.access_token;
      } catch (err) {
        console.warn('Gagal mengambil session token:', err);
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
    if (!response.ok) {
      throw new Error(result.detail || result.error || result.message || `HTTP ${response.status}`);
    }
    return result;
  }

  function showNotification(message, isError = false) {
    const el = document.getElementById('statusNotification');
    if (!el) return;
    el.textContent = message;
    el.className = `rounded-xl border p-4 text-sm transition-all duration-300 ${
      isError
        ? 'border-red-500/30 bg-red-500/10 text-red-200 block'
        : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200 block'
    }`;
    setTimeout(() => {
      el.className = 'hidden';
    }, 5000);
  }

  // Bind input sliders to value display
  ['gemini', 'groq', 'openrouter'].forEach((p) => {
    const tempInput = document.getElementById(`${p}_temp`);
    const tempVal = document.getElementById(`${p}_temp_val`);
    if (tempInput && tempVal) {
      tempInput.addEventListener('input', (e) => {
        tempVal.textContent = e.target.value;
      });
    }

    const tokensInput = document.getElementById(`${p}_tokens`);
    const tokensVal = document.getElementById(`${p}_tokens_val`);
    if (tokensInput && tokensVal) {
      tokensInput.addEventListener('input', (e) => {
        tokensVal.textContent = e.target.value;
      });
    }
  });

  // Toggle show/hide password
  document.querySelectorAll('[data-toggle-pass]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const targetId = btn.dataset.togglePass;
      const input = document.getElementById(targetId);
      if (input) {
        input.type = input.type === 'password' ? 'text' : 'password';
      }
    });
  });

  // Load Providers Data
  async function loadProviders() {
    try {
      const res = await apiRequest('/admin/ai/providers');
      const list = res.providers || [];
      providersData = {};
      list.forEach((p) => {
        providersData[p.name] = p;
        populateProviderCard(p);
      });

      updateFallbackSummary(list);
    } catch (err) {
      showNotification(`Gagal memuat konfigurasi provider AI: ${err.message}`, true);
    }
  }

  function populateProviderCard(p) {
    const name = p.name;
    const enabledCheck = document.getElementById(`${name}_enabled`);
    if (enabledCheck) enabledCheck.checked = !!p.enabled;

    const prioritySelect = document.getElementById(`${name}_priority`);
    if (prioritySelect) prioritySelect.value = String(p.priority || 1);

    const modelSelect = document.getElementById(`${name}_model`);
    if (modelSelect && p.model) modelSelect.value = p.model;

    const tempInput = document.getElementById(`${name}_temp`);
    const tempVal = document.getElementById(`${name}_temp_val`);
    if (tempInput && tempVal && p.temperature !== undefined) {
      tempInput.value = p.temperature;
      tempVal.textContent = p.temperature;
    }

    const tokensInput = document.getElementById(`${name}_tokens`);
    const tokensVal = document.getElementById(`${name}_tokens_val`);
    if (tokensInput && tokensVal && p.max_tokens !== undefined) {
      tokensInput.value = p.max_tokens;
      tokensVal.textContent = p.max_tokens;
    }

    const keyStatus = document.getElementById(`${name}_key_status`);
    const keyInput = document.getElementById(`${name}_api_key`);
    if (keyStatus) {
      if (p.has_api_key) {
        keyStatus.textContent = `Aktif (${p.masked_api_key || 'Tersimpan'})`;
        keyStatus.className = 'text-[10px] font-mono text-emerald-400 font-semibold';
        if (keyInput && p.masked_api_key) {
          keyInput.placeholder = p.masked_api_key;
        }
      } else {
        keyStatus.textContent = 'Belum diisi';
        keyStatus.className = 'text-[10px] font-mono text-amber-400 font-semibold';
      }
    }
  }

  function updateFallbackSummary(providers) {
    const active = providers
      .filter((p) => p.enabled && p.has_api_key)
      .sort((a, b) => a.priority - b.priority);

    const chainText = document.getElementById('fallbackChainText');
    const countText = document.getElementById('activeProviderCount');

    if (chainText) {
      chainText.textContent = active.length
        ? active.map((p) => p.name.toUpperCase()).join(' → ')
        : 'Semua nonaktif / API key belum diset';
    }

    if (countText) {
      countText.textContent = `${active.length} / ${providers.length}`;
    }
  }

  // Load Curated Models Catalog
  async function loadModels() {
    try {
      const res = await apiRequest('/admin/ai/models');
      allModels = res.models || [];
      renderModelsCatalog('all');
    } catch (err) {
      console.warn('Gagal memuat katalog model:', err);
    }
  }

  function renderModelsCatalog(filterTier = 'all') {
    const grid = document.getElementById('modelsCatalogGrid');
    if (!grid) return;

    const filtered = allModels.filter((m) => {
      if (filterTier === 'free') return m.tier === 'free';
      if (filterTier === 'pro') return m.tier === 'pro';
      return true;
    });

    grid.innerHTML = filtered
      .map((m) => `
        <div class="rounded-xl border border-white/5 bg-black/20 p-4 space-y-2 hover:border-white/10 transition-colors">
          <div class="flex items-center justify-between">
            <span class="text-[10px] font-mono uppercase px-2 py-0.5 rounded ${
              m.tier === 'free' ? 'badge-free' : 'badge-pro'
            }">
              ${m.tier.toUpperCase()} TIER
            </span>
            <span class="text-[11px] font-mono text-slate-400">${m.speed}</span>
          </div>

          <div>
            <h4 class="text-xs font-bold text-white font-mono">${m.id}</h4>
            <p class="text-[11px] text-[#9CA3AF] mt-1">${m.desc}</p>
          </div>

          <div class="flex items-center justify-between text-[10px] text-slate-500 pt-2 border-t border-white/5">
            <span>Konteks: ${m.context}</span>
            <span class="text-purple-400 font-semibold">${m.badge}</span>
          </div>
        </div>
      `)
      .join('');
  }

  // Filter Buttons
  document.querySelectorAll('[data-filter-tier]').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-filter-tier]').forEach((b) => {
        b.className = 'px-3 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-slate-300 text-xs font-semibold';
      });
      btn.className = 'px-3 py-1 rounded-lg bg-purple-600 text-white text-xs font-semibold';
      renderModelsCatalog(btn.dataset.filterTier);
    });
  });

  // Save Provider Config
  async function saveProvider(providerName) {
    const enabled = document.getElementById(`${providerName}_enabled`)?.checked ?? true;
    const priority = parseInt(document.getElementById(`${providerName}_priority`)?.value || '1', 10);
    const model = document.getElementById(`${providerName}_model`)?.value;
    const temperature = parseFloat(document.getElementById(`${providerName}_temp`)?.value || '0.2');
    const max_tokens = parseInt(document.getElementById(`${providerName}_tokens`)?.value || '600', 10);
    const keyInput = document.getElementById(`${providerName}_api_key`);
    const rawKey = keyInput?.value?.trim();

    const payload = {
      enabled,
      priority,
      model,
      temperature,
      max_tokens,
    };

    // Sertakan API key hanya jika diisi dan bukan masked
    if (rawKey && !rawKey.startsWith('••••')) {
      payload.api_key = rawKey;
    }

    try {
      const saveBtn = document.querySelector(`[data-save-provider="${providerName}"]`);
      if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<i data-lucide="loader" class="w-3.5 h-3.5 animate-spin"></i> Menyimpan...';
      }

      const res = await apiRequest(`/admin/ai/providers/${providerName}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });

      showNotification(`Konfigurasi ${providerName.toUpperCase()} berhasil disimpan dan aktif.`);
      if (rawKey && keyInput) {
        keyInput.value = '';
      }
      await loadProviders();
    } catch (err) {
      showNotification(`Gagal menyimpan ${providerName}: ${err.message}`, true);
    } finally {
      const saveBtn = document.querySelector(`[data-save-provider="${providerName}"]`);
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<i data-lucide="save" class="w-3.5 h-3.5"></i> Simpan';
        if (window.lucide) window.lucide.createIcons();
      }
    }
  }

  // Test Provider Live
  async function testProvider(providerName) {
    const resultBox = document.getElementById(`${providerName}_test_result`);
    const model = document.getElementById(`${providerName}_model`)?.value;
    const keyInput = document.getElementById(`${providerName}_api_key`);
    const rawKey = keyInput?.value?.trim();

    if (resultBox) {
      resultBox.classList.remove('hidden');
      resultBox.innerHTML = '<span class="text-amber-400">Menguji koneksi & mengukur latency...</span>';
    }

    const payload = {
      provider: providerName,
      model,
      prompt: 'Sebutkan 1 moto pendidikan singkat untuk SMPN 2 Cibungbulang!',
    };
    if (rawKey && !rawKey.startsWith('••••')) {
      payload.api_key = rawKey;
    }

    try {
      const testBtn = document.querySelector(`[data-test-provider="${providerName}"]`);
      if (testBtn) {
        testBtn.disabled = true;
        testBtn.innerHTML = '<i data-lucide="loader" class="w-3.5 h-3.5 animate-spin"></i> Testing...';
      }

      const res = await apiRequest('/admin/ai/providers/test', {
        method: 'POST',
        body: JSON.stringify(payload),
      });

      if (resultBox) {
        if (res.success) {
          resultBox.innerHTML = `
            <div class="space-y-1 text-emerald-300">
              <div class="flex items-center justify-between font-bold">
                <span>✅ KONEKSI BERHASIL</span>
                <span class="text-white">${res.latency_ms} ms</span>
              </div>
              <p class="text-[11px] text-slate-300 line-clamp-2 italic">"${res.answer || ''}"</p>
            </div>
          `;
        } else {
          resultBox.innerHTML = `
            <div class="space-y-1 text-red-300">
              <div class="font-bold">❌ KONEKSI GAGAL (${res.latency_ms || '-'} ms)</div>
              <p class="text-[10px] text-red-200 break-words">${res.error || 'Terjadi kesalahan'}</p>
            </div>
          `;
        }
      }
    } catch (err) {
      if (resultBox) {
        resultBox.innerHTML = `<span class="text-red-400">Error: ${err.message}</span>`;
      }
    } finally {
      const testBtn = document.querySelector(`[data-test-provider="${providerName}"]`);
      if (testBtn) {
        testBtn.disabled = false;
        testBtn.innerHTML = '<i data-lucide="zap" class="w-3.5 h-3.5"></i> Test Koneksi';
        if (window.lucide) window.lucide.createIcons();
      }
    }
  }

  // Bind Click Handlers
  document.querySelectorAll('[data-save-provider]').forEach((btn) => {
    btn.addEventListener('click', () => {
      saveProvider(btn.dataset.saveProvider);
    });
  });

  document.querySelectorAll('[data-test-provider]').forEach((btn) => {
    btn.addEventListener('click', () => {
      testProvider(btn.dataset.testProvider);
    });
  });

  const reloadBtn = document.getElementById('btnReloadFromDb');
  if (reloadBtn) {
    reloadBtn.addEventListener('click', async () => {
      try {
        reloadBtn.disabled = true;
        await apiRequest('/admin/ai/reload', { method: 'POST' });
        showNotification('Konfigurasi berhasil disinkronkan dari database Supabase.');
        await loadProviders();
      } catch (err) {
        showNotification(`Gagal reload dari DB: ${err.message}`, true);
      } finally {
        reloadBtn.disabled = false;
      }
    });
  }

  // Mobile sidebar toggle
  const mobileToggle = document.querySelector('[data-mobile-menu-toggle]');
  const sidebar = document.querySelector('[data-mobile-sidebar]');
  const overlay = document.querySelector('[data-mobile-sidebar-overlay]');

  if (mobileToggle && sidebar && overlay) {
    mobileToggle.addEventListener('click', () => {
      sidebar.classList.toggle('hidden');
      overlay.classList.toggle('hidden');
    });
    overlay.addEventListener('click', () => {
      sidebar.classList.add('hidden');
      overlay.classList.add('hidden');
    });
  }

  // Initial Load
  await Promise.all([loadProviders(), loadModels()]);
})();
