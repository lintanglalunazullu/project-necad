(function () {
  const SUPABASE_URL = 'https://pwohquppbydpycpqwxtg.supabase.co';
  const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InB3b2hxdXBwYnlkcHljcHF3eHRnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODU1MjYyNTUsImV4cCI6MjEwMTEwMjI1NX0.QUmKNTzaw88NZqb7ihR9Mgm7laJzm6_-M7Ktz0hNcGU';

  const avatarWrappers = Array.from(document.querySelectorAll('[data-navbar-avatar]'));
  const loginButtons = Array.from(document.querySelectorAll('[data-navbar-login-btn]'));
  const profileAvatarImage = document.querySelector('[data-profile-avatar]');
  const profileNameEl = document.querySelector('[data-profile-name]');
  const profileRoleEl = document.querySelector('[data-profile-role]');
  const profileEmailEl = document.querySelector('[data-profile-email]');
  const profileProviderEl = document.querySelector('[data-profile-provider]');
  const profileStatusEl = document.querySelector('[data-profile-status]');
  const profileBadgesEl = document.querySelector('[data-profile-badges]');
  const headerNameEl = document.querySelector('[data-profile-header-name]');

  let supabaseClient = null;

  try {
    if (window.supabase) {
      supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
    }
  } catch (error) {
    console.error('Gagal menginisialisasi Supabase untuk navbar:', error);
  }

  function getInitials(name) {
    if (!name) return 'U';
    const parts = name.split(/\s+/).filter(Boolean);
    if (!parts.length) return 'U';
    return parts.slice(0, 2).map((part) => part[0]).join('').toUpperCase();
  }

  function getDisplayName(user) {
    return user?.user_metadata?.full_name || user?.user_metadata?.name || user?.email || 'User';
  }

  function getProvider(user) {
    const provider = user?.app_metadata?.provider || user?.app_metadata?.providers?.[0] || 'google';
    return provider.charAt(0).toUpperCase() + provider.slice(1);
  }

  function setAvatarUI(user) {
    if (!user) {
      // User belum login: sembunyikan avatar, tampilkan tombol login
      avatarWrappers.forEach((wrapper) => {
        wrapper.classList.add('hidden');
      });
      loginButtons.forEach((btn) => {
        btn.classList.remove('hidden');
        btn.classList.add('flex');
      });
      if (profileAvatarImage) {
        profileAvatarImage.src = 'https://ui-avatars.com/api/?name=User&background=7c3aed&color=fff';
        profileAvatarImage.alt = 'User';
      }
      if (window.lucide && typeof window.lucide.createIcons === 'function') {
        try { window.lucide.createIcons(); } catch (_) {}
      }
      return;
    }

    // User sudah login: tampilkan avatar, sembunyikan tombol login
    loginButtons.forEach((btn) => {
      btn.classList.add('hidden');
      btn.classList.remove('flex');
    });

    const fullName = getDisplayName(user);
    const avatarUrl = user?.user_metadata?.avatar_url || user?.user_metadata?.picture || '';
    const initials = getInitials(fullName);
    const fallbackAvatar = `https://ui-avatars.com/api/?name=${encodeURIComponent(fullName)}&background=7c3aed&color=fff`;

    avatarWrappers.forEach((wrapper) => {
      wrapper.classList.remove('hidden');
      const img = wrapper.querySelector('[data-navbar-avatar-img]');
      const initialsEl = wrapper.querySelector('[data-navbar-avatar-initials]');
      const link = wrapper.querySelector('a');

      if (!img) return;

      if (avatarUrl) {
        img.src = avatarUrl;
        img.alt = fullName;
        img.classList.remove('hidden');
        if (initialsEl) initialsEl.classList.add('hidden');
      } else if (initialsEl) {
        img.classList.add('hidden');
        initialsEl.textContent = initials;
        initialsEl.classList.remove('hidden');
      } else {
        img.src = fallbackAvatar;
        img.alt = fullName;
        img.classList.remove('hidden');
      }

      if (link) {
        link.setAttribute('aria-label', fullName);
        link.setAttribute('href', link.getAttribute('data-profile-link') || './pages/profile.html');
      }
    });

    if (profileAvatarImage) {
      profileAvatarImage.src = avatarUrl || fallbackAvatar;
      profileAvatarImage.alt = fullName;
    }
  }

  function setProfileUI(user) {
    const fullName = getDisplayName(user);
    const provider = getProvider(user);
    const email = user?.email || 'email belum tersedia';

    if (profileNameEl) profileNameEl.textContent = fullName;
    if (profileRoleEl) profileRoleEl.textContent = `Akun ${provider}`;
    if (profileEmailEl) profileEmailEl.textContent = email;
    if (profileProviderEl) profileProviderEl.textContent = provider;
    if (profileStatusEl) profileStatusEl.textContent = user ? 'Aktif' : 'Belum login';
    if (headerNameEl) headerNameEl.textContent = fullName;

    if (profileBadgesEl) {
      profileBadgesEl.innerHTML = `
        <span class="text-xs font-medium bg-[#202538] text-[#0B2545] px-3 py-1 rounded-full">${provider}</span>
        <span class="text-xs font-medium bg-[#202538] text-[#0B2545] px-3 py-1 rounded-full">Supabase</span>
      `;
    }
  }

  async function syncProfile() {
    if (!supabaseClient) {
      setAvatarUI(null);
      setProfileUI(null);
      return;
    }

    try {
      const { data: { session } } = await supabaseClient.auth.getSession();
      const user = session?.user || null;
      setAvatarUI(user);
      setProfileUI(user);
    } catch (error) {
      console.error('Gagal mengambil sesi untuk navbar:', error);
      setAvatarUI(null);
      setProfileUI(null);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', syncProfile, { once: true });
  } else {
    syncProfile();
  }

  if (supabaseClient) {
    supabaseClient.auth.onAuthStateChange((_event, session) => {
      const user = session?.user || null;
      setAvatarUI(user);
      setProfileUI(user);
    });
  }
})();
