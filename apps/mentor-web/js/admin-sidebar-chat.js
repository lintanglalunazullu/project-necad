(function () {
  const newResearchBtn = document.getElementById('newResearchBtn');
  const chatUrl = newResearchBtn?.dataset?.chatUrl || './chat.html';

  if (newResearchBtn) {
    newResearchBtn.addEventListener('click', () => window.location.href = chatUrl);
  }

  const sessionList = document.getElementById('sessionList');
  const sessionStatus = document.getElementById('sessionStatus');
  if (!sessionList || !sessionStatus) return;

  (async function loadSessions() {
    const client = window.createAksarakuClient ? window.createAksarakuClient() : null;
    if (!client) {
      sessionStatus.textContent = 'Koneksi gagal dibuat.';
      return;
    }
    const { data: { session } } = await client.auth.getSession();
    if (!session?.user) {
      sessionStatus.textContent = 'Silakan login agar riwayat chat tersimpan.';
      return;
    }
    const { data, error } = await client
      .from('chat_sessions')
      .select('id,title,updated_at')
      .eq('user_id', session.user.id)
      .order('updated_at', { ascending: false })
      .limit(6);
    if (error) {
      sessionStatus.textContent = 'Gagal memuat sesi chat.';
      return;
    }
    if (!data || data.length === 0) {
      sessionStatus.textContent = 'Belum ada sesi chat. Klik Chat Baru untuk mulai.';
      return;
    }
    sessionList.innerHTML = '';
    data.forEach((item) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'w-full text-left rounded-xl border border-white/5 bg-[#111827] px-3 py-2 text-xs text-[#D1D5DB] hover:border-purple-500/40 hover:bg-white/5 transition-colors';
      button.textContent = item.title || 'Sesi chat baru';
      button.addEventListener('click', () => window.location.href = chatUrl);
      sessionList.appendChild(button);
    });
  })();
})();