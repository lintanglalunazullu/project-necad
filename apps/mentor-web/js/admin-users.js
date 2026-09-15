(async function () {
  const access = await window.requireAksarakuRole(['admin'], './login.html');
  if (!access) return;

  const { client } = access;
  const signupClient = window.supabase.createClient(
    window.AKSARAKU_CONFIG.SUPABASE_URL,
    window.AKSARAKU_CONFIG.SUPABASE_ANON_KEY,
    { auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false } },
  );
  const form = document.getElementById('userForm');
  const table = $('#usersTable').DataTable({
    language: {
      search: 'Cari:',
      lengthMenu: 'Tampilkan _MENU_ user',
      info: 'Menampilkan _START_ sampai _END_ dari _TOTAL_ user',
      infoEmpty: 'Belum ada user',
      zeroRecords: 'User tidak ditemukan',
      paginate: { previous: 'Sebelumnya', next: 'Berikutnya' },
    },
    columns: [
      { title: 'Nama' },
      { title: 'Email' },
      { title: 'Role' },
      { title: 'Provider' },
      { title: 'Aksi', orderable: false, searchable: false },
    ],
  });
  const status = document.getElementById('status');
  const deleteUserButton = document.getElementById('deleteUserButton');
  const apiBaseUrl = window.AKSARAKU_CONFIG.API_BASE_URL;
  const fields = {
    email: document.getElementById('email'),
    password: document.getElementById('password'),
    passwordField: document.getElementById('passwordField'),
    passwordHint: document.getElementById('passwordHint'),
    fullName: document.getElementById('fullName'),
    provider: document.getElementById('provider'),
    role: document.getElementById('role'),
  };
  let profiles = [];
  let editingProfileId = null;

  function showStatus(text, isError = false) {
    status.textContent = text;
    status.className = `mt-5 rounded-lg border px-4 py-3 text-sm ${isError ? 'border-red-400/30 bg-red-400/10 text-red-200' : 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200'}`;
  }

  function normalizeEmail(value) {
    return String(value || '')
      .replace(/[\u0000-\u001F\u007F\u200B-\u200D\uFEFF]/g, '')
      .trim()
      .toLowerCase();
  }

  function openForm(profile = null) {
    form.classList.remove('hidden');
    editingProfileId = profile?.id || null;
    const passwordField = document.getElementById('passwordField');
    const roleHint = document.getElementById('roleHint');
    deleteUserButton.classList.toggle('hidden', !profile);
    const canEditPassword = !!profile
      && profile.provider === 'email'
      && ['admin', 'teacher'].includes(profile.role);
    passwordField.classList.toggle('hidden', !!profile && !canEditPassword);
    fields.password.value = '';
    fields.password.required = !profile;
    fields.password.placeholder = profile ? 'Kosongkan jika tidak diubah' : 'Minimal 6 karakter';
    fields.passwordHint.textContent = profile
      ? 'Hanya untuk akun admin atau teacher yang login melalui email.'
      : 'Akun Auth dan profil dibuat otomatis.';
    roleHint.textContent = profile ? 'Role dapat diubah oleh admin.' : 'Pilih role akun saat dibuat.';
    document.getElementById('formTitle').textContent = profile ? 'Edit profil' : 'Tambah profil';
    fields.email.value = profile?.email || '';
    fields.fullName.value = profile?.full_name || '';
    fields.provider.value = profile?.provider || 'email';
    fields.role.value = profile?.role || 'user';
    fields.email.disabled = !!profile;
    fields.provider.disabled = !profile;
    fields.role.disabled = false;
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>'"]/g, (character) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
    }[character]));
  }

  function render() {
    table.clear().rows.add(profiles.map((profile) => [
      escapeHtml(profile.full_name || 'Tanpa nama'),
      escapeHtml(profile.email || 'Email belum tersedia'),
      `<span class="rounded-full bg-purple-500/15 px-2.5 py-1 text-xs font-semibold text-purple-300">${escapeHtml(profile.role || 'user')}</span>`,
      escapeHtml(profile.provider || 'unknown'),
      `<button type="button" data-edit-id="${escapeHtml(profile.id)}" class="rounded-md border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-white/5">Edit</button>`,
    ])).draw();
  }

  async function loadProfiles() {
    const { data, error } = await client.from('profiles').select('id,email,full_name,role,provider').order('full_name');
    if (error) {
      showStatus(`Gagal memuat user: ${error.message}`, true);
      return;
    }
    profiles = data || [];
    render();
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    let error = null;
    const email = normalizeEmail(fields.email.value);
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      showStatus('Format email tidak valid. Contoh: nama@gmail.com', true);
      return;
    }
    if (!fields.email.disabled) {
      const result = await signupClient.auth.signUp({
        email,
        password: fields.password.value,
        options: { data: { full_name: fields.fullName.value.trim() } },
      });
      error = result.error;
      if (!error && result.data.user) {
        const profileResult = await client.from('profiles').upsert({
          id: result.data.user.id,
          email,
          full_name: fields.fullName.value.trim(),
          provider: 'email',
          role: fields.role.value,
        }, { onConflict: 'id' });
        error = profileResult.error;
      }
    } else {
      const profile = { id: editingProfileId, email, full_name: fields.fullName.value.trim(), provider: fields.provider.value, role: fields.role.value };
      if (!profile.id) {
        showStatus('Profil yang akan diedit tidak ditemukan.', true);
        return;
      }
      if (fields.password.value) {
        const canEditPassword = profile.provider === 'email'
          && ['admin', 'teacher'].includes(profile.role);
        if (!canEditPassword) {
          showStatus('Password hanya dapat diubah untuk admin atau teacher dengan provider email.', true);
          return;
        }
        if (fields.password.value.length < 6) {
          showStatus('Password minimal 6 karakter.', true);
          return;
        }
      }
      ({ error } = await client.from('profiles').update(profile).eq('id', profile.id));
      if (!error && fields.password.value) {
        try {
          if (profile.id === access.session.user.id) {
            const result = await client.auth.updateUser({ password: fields.password.value });
            if (result.error) throw result.error;
          } else {
            const response = await fetch(`${apiBaseUrl}/admin/users/${encodeURIComponent(profile.id)}/password`, {
              method: 'PATCH',
              headers: {
                Authorization: `Bearer ${access.session.access_token}`,
                'Content-Type': 'application/json',
              },
              body: JSON.stringify({ password: fields.password.value }),
            });
            const result = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(result.detail || result.error || 'Gagal mengubah password.');
          }
        } catch (passwordError) {
          showStatus(`Profil tersimpan, tetapi password gagal diubah: ${passwordError.message}`, true);
          return;
        }
      }
    }
    if (error) {
      const message = error.code === 'over_email_send_rate_limit'
        ? 'Email konfirmasi Supabase sedang terkena rate limit. Matikan Confirm email di Authentication > Providers > Email, lalu coba lagi.'
        : `Gagal menyimpan user: ${error.message}`;
      showStatus(message, true);
      return;
    }
    showStatus(fields.email.disabled ? 'Profil user berhasil diperbarui.' : 'Akun Auth dan profil berhasil dibuat.');
    form.classList.add('hidden');
    await loadProfiles();
  });

  document.getElementById('newUserButton').addEventListener('click', () => openForm());
  document.getElementById('cancelButton').addEventListener('click', () => form.classList.add('hidden'));
  deleteUserButton.addEventListener('click', async () => {
    if (!editingProfileId) return;
    const profile = profiles.find((item) => item.id === editingProfileId);
    if (!profile) return;
    const confirmed = window.confirm(`Hapus akun ${profile.email || 'ini'} secara permanen?`);
    if (!confirmed) return;

    deleteUserButton.disabled = true;
    try {
      const response = await fetch(`${apiBaseUrl}/admin/users/${encodeURIComponent(editingProfileId)}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${access.session.access_token}` },
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || result.error || 'Gagal menghapus akun.');
      showStatus('Akun berhasil dihapus.');
      form.classList.add('hidden');
      editingProfileId = null;
      await loadProfiles();
    } catch (error) {
      showStatus(`Gagal menghapus akun: ${error.message}`, true);
    } finally {
      deleteUserButton.disabled = false;
    }
  });
  document.getElementById('roleFilters').addEventListener('click', (event) => {
    const button = event.target.closest('[data-role-filter]');
    if (!button) return;
    table.column(2).search(button.dataset.roleFilter).draw();
    document.querySelectorAll('[data-role-filter]').forEach((filter) => filter.classList.toggle('bg-purple-600', filter === button));
  });
  document.querySelector('#usersTable tbody').addEventListener('click', (event) => {
    const button = event.target.closest('[data-edit-id]');
    const profile = profiles.find((item) => item.id === button?.dataset.editId);
    if (profile) openForm(profile);
  });
  lucide.createIcons();
  await loadProfiles();
})();
