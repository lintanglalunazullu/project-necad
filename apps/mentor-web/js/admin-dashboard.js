(async function () {
  const access = await window.requireAksarakuRole(['admin'], './login.html');
  if (!access) return;

  const API_URL = `${window.AKSARAKU_CONFIG.API_BASE_URL}/admin/dashboard`;
  const loading = document.getElementById('dashboardLoading');
  const error = document.getElementById('dashboardError');
  const content = document.getElementById('dashboardContent');

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, (character) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
    }[character]));
  }

  function relativeTime(value) {
    if (!value) return 'Baru saja';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Baru saja';
    const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
    if (seconds < 60) return 'Baru saja';
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes} menit lalu`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours} jam lalu`;
    const days = Math.floor(hours / 24);
    if (days < 30) return `${days} hari lalu`;
    return date.toLocaleDateString('id-ID', { dateStyle: 'medium' });
  }

  function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  }

  function activityIcon(label) {
    if (label === 'Dokumen') return 'file-text';
    if (label === 'Sesi chat') return 'message-circle';
    if (label === 'Pesan AI') return 'bot';
    if (label === 'Pengguna') return 'user-plus';
    return 'activity';
  }

  function activityAccent(label) {
    if (label === 'Dokumen') return 'text-purple-400 bg-purple-500/10';
    if (label === 'Sesi chat') return 'text-amber-400 bg-amber-500/10';
    if (label === 'Pesan AI') return 'text-indigo-400 bg-indigo-500/10';
    if (label === 'Pengguna') return 'text-teal-400 bg-teal-500/10';
    return 'text-slate-400 bg-white/5';
  }

  function renderActivity(items) {
    const container = document.getElementById('dashboardActivity');
    if (!container) return;
    if (!items.length) {
      container.innerHTML = '<p class="px-2 py-5 text-sm text-[#9CA3AF]">Belum ada aktivitas.</p>';
      return;
    }
    container.innerHTML = items.map((item) => `
      <div class="flex items-start gap-3 px-2 py-3">
        <div class="w-9 h-9 shrink-0 rounded-lg ${activityAccent(item.label)} flex items-center justify-center">
          <i data-lucide="${activityIcon(item.label)}" class="w-4 h-4"></i>
        </div>
        <div class="min-w-0">
          <p class="text-sm text-[#F3F4F6] leading-snug">${escapeHtml(item.label)}: <span class="font-semibold">${escapeHtml(item.name)}</span></p>
          <p class="text-xs text-[#6B7280] mt-0.5">${escapeHtml(relativeTime(item.timestamp))}</p>
        </div>
      </div>`).join('');
    lucide.createIcons();
  }

  function renderDocuments(items) {
    const container = document.getElementById('dashboardDocuments');
    if (!container) return;
    if (!items.length) {
      container.innerHTML = '<p class="py-5 text-sm text-[#9CA3AF]">Belum ada dokumen.</p>';
      return;
    }
    container.innerHTML = items.map((item) => `
      <a href="./upload.html" class="group flex items-center gap-3 rounded-xl border border-slate-800 bg-card2 hover:border-purple-500/50 p-3 transition-colors">
        <div class="w-11 h-11 shrink-0 rounded-lg bg-purple-500/10 flex items-center justify-center">
          <i data-lucide="file-text" class="w-5 h-5 text-purple-400"></i>
        </div>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold text-white">${escapeHtml(item.pdf_name || item.name)}</p>
          <p class="mt-0.5 text-xs text-[#6B7280]">${escapeHtml(item.chunk_count)} chunk
            <span class="mx-1.5">•</span>
            <span class="capitalize ${item.category === 'private' ? 'text-teal-400' : 'text-purple-400'}">${escapeHtml(item.category || 'public')}</span>
          </p>
        </div>
        <i data-lucide="chevron-right" class="w-4 h-4 shrink-0 text-[#6B7280] group-hover:text-white transition-colors"></i>
      </a>`).join('');
    lucide.createIcons();
  }

  function renderMessageStats(messageByRole) {
    const container = document.getElementById('messageStats');
    if (!container) return;
    const userCount = messageByRole?.user ?? 0;
    const assistantCount = messageByRole?.assistant ?? 0;
    const total = userCount + assistantCount;
    container.innerHTML = `
      <div class="flex items-center justify-between gap-3 rounded-lg bg-card2 border border-slate-800 p-3">
        <span class="text-xs text-[#9CA3AF] flex items-center gap-2"><i data-lucide="user" class="w-3.5 h-3.5"></i>Pertanyaan user</span>
        <span class="text-sm font-bold text-white">${userCount}</span>
      </div>
      <div class="flex items-center justify-between gap-3 rounded-lg bg-card2 border border-slate-800 p-3">
        <span class="text-xs text-[#9CA3AF] flex items-center gap-2"><i data-lucide="bot" class="w-3.5 h-3.5"></i>Jawaban AI</span>
        <span class="text-sm font-bold text-white">${assistantCount}</span>
      </div>
      <div class="flex items-center justify-between gap-3 rounded-lg bg-card2 border border-slate-800 p-3">
        <span class="text-xs text-[#9CA3AF]">Total percakapan</span>
        <span class="text-sm font-bold text-purple-400">${total}</span>
      </div>`;
    lucide.createIcons();
  }

  function renderCategoryBars(stats) {
    const publics = Number(stats.public_documents ?? 0);
    const privates = Number(stats.private_documents ?? 0);
    const total = publics + privates;
    setText('categoryPublicValue', publics);
    setText('categoryPrivateValue', privates);
    const setBar = (id, value) => {
      const bar = document.getElementById(id);
      if (bar) bar.style.setProperty('--target-width', total ? `${Math.round((value / total) * 100)}%` : '0%');
    };
    setBar('categoryPublicBar', publics);
    setBar('categoryPrivateBar', privates);
    lucide.createIcons();
  }

  function roleAccent(role) {
    if (role === 'admin') return 'bg-purple-500/15 text-purple-300';
    if (role === 'teacher') return 'bg-teal-500/15 text-teal-300';
    if (role === 'user') return 'bg-indigo-500/15 text-indigo-300';
    return 'bg-white/5 text-slate-300';
  }

  function renderRecentUsers(items) {
    const container = document.getElementById('dashboardRecentUsers');
    if (!container) return;
    if (!items.length) {
      container.innerHTML = '<p class="text-sm text-[#9CA3AF]">Belum ada pengguna.</p>';
      return;
    }
    container.innerHTML = items.map((item) => {
      const name = item.full_name || item.email || 'Pengguna';
      const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || 'U';
      return `
        <div class="flex items-center gap-3">
          <div class="w-9 h-9 shrink-0 rounded-full bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center text-[11px] font-bold text-white">${escapeHtml(initials)}</div>
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-semibold text-white">${escapeHtml(name)}</p>
            <p class="truncate text-xs text-[#6B7280] mt-0.5">${escapeHtml(item.email || '')} • ${escapeHtml(relativeTime(item.created_at))}</p>
          </div>
          <span class="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold capitalize ${roleAccent(item.role)}">${escapeHtml(item.role || 'user')}</span>
        </div>`;
    }).join('');
  }

  async function loadDashboard() {
    try {
      const { data: { session } } = await access.client.auth.getSession();
      if (!session?.access_token) throw new Error('Sesi admin tidak ditemukan. Silakan login kembali.');
      const response = await fetch(API_URL, { headers: { Authorization: `Bearer ${session.access_token}` } });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || result.message || 'Gagal memuat dashboard.');

      const stats = result.stats || {};
      const userInfo = session.user?.user_metadata?.full_name || session.user?.user_metadata?.name || session.user?.email || access.role;
      setText('dashboardName', String(userInfo).split(/\s+/).filter(Boolean).slice(0, 2).join(' '));
      setText('statDocuments', stats.documents ?? 0);
      setText('statChunks', stats.chunks ?? 0);
      setText('statUsers', stats.users ?? 0);
      setText('statSessions', stats.sessions ?? 0);
      setText('statMessages', stats.messages ?? 0);
      setText('statPublic', stats.public_documents ?? 0);
      setText('statPrivate', stats.private_documents ?? 0);

      const roleCounts = stats.users_by_role || {};
      setText('statAdmins', roleCounts.admin ?? 0);
      setText('statTeachers', roleCounts.teacher ?? 0);
      setText('statRoleUsers', roleCounts.user ?? 0);

      renderCategoryBars(stats);
      renderMessageStats(stats.messages_by_role);
      renderActivity(result.activity || []);
      renderDocuments(result.documents || []);
      renderRecentUsers(result.recent_users || []);

      loading?.classList.add('hidden');
      content?.classList.remove('hidden');
    } catch (loadError) {
      loading?.classList.add('hidden');
      if (error) {
        error.textContent = loadError.message;
        error.classList.remove('hidden');
      }
    }
  }

  await loadDashboard();
})();