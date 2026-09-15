(function () {
  const signOutLinks = Array.from(document.querySelectorAll('[data-auth-menu="signout"]'));
  if (!signOutLinks.length) return;

  var style = document.createElement('style');
  style.textContent =
    '@keyframes lmoFadeIn{from{opacity:0}to{opacity:1}}' +
    '@keyframes lmoScaleIn{from{opacity:0;transform:scale(.96) translateY(8px)}to{opacity:1;transform:scale(1) translateY(0)}}';
  document.head.appendChild(style);

  var overlay = document.createElement('div');
  overlay.id = 'logoutModalOverlay';
  overlay.className =
    'hidden fixed inset-0 z-[100] items-center justify-center p-4 bg-black/70 backdrop-blur-sm';
  overlay.style.animation = 'lmoFadeIn .2s ease-out';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-labelledby', 'logoutModalTitle');

  overlay.innerHTML =
    '<div class="w-full max-w-md p-8 rounded-2xl bg-[#161B26] border border-slate-800 text-center shadow-2xl flex flex-col items-center" style="animation:lmoScaleIn .25s cubic-bezier(.16,1,.3,1)">' +
    '<div class="w-16 h-16 rounded-full bg-[#202538] flex items-center justify-center mb-6">' +
    '<svg class="w-7 h-7 text-[#9BD1FF]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>' +
    '</div>' +
    '<h2 id="logoutModalTitle" class="text-xl md:text-2xl font-bold text-white mb-3 text-center">Apakah Anda yakin ingin keluar?</h2>' +
    '<p class="text-sm text-slate-400 mb-8 max-w-xs leading-relaxed text-center">Sesi akun Anda akan diakhiri pada perangkat ini.</p>' +
    '<button id="confirmLogoutBtn" type="button" class="w-full py-3 px-4 rounded-xl bg-[#0B2545] text-white font-medium flex items-center justify-center gap-2 hover:bg-[#123A63] transition-all mb-3">Ya, Keluar</button>' +
    '<button id="cancelLogoutBtn" type="button" class="w-full py-3 px-4 rounded-xl bg-[#1D2332] border border-slate-700/60 text-slate-300 font-medium hover:bg-slate-800 transition-all">Batal</button>' +
    '</div>';

  document.body.appendChild(overlay);

  var confirmBtn = document.getElementById('confirmLogoutBtn');
  var cancelBtn = document.getElementById('cancelLogoutBtn');

  var spinnerSvg =
    '<svg class="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
    '<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>' +
    '<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"></path>' +
    '</svg>';

  function openModal() {
    overlay.classList.remove('hidden');
    overlay.classList.add('flex');
    overlay.style.animation = 'none';
    void overlay.offsetWidth;
    overlay.style.animation = 'lmoFadeIn .2s ease-out';
    document.body.classList.add('overflow-hidden');
    confirmBtn.focus();
    document.addEventListener('keydown', handleEscKey);
  }

  function closeModal() {
    overlay.classList.add('hidden');
    overlay.classList.remove('flex');
    document.body.classList.remove('overflow-hidden');
    document.removeEventListener('keydown', handleEscKey);
  }

  function handleEscKey(event) {
    if (event.key === 'Escape') closeModal();
  }

  signOutLinks.forEach(function (link) {
    link.addEventListener('click', function (event) {
      event.preventDefault();
      openModal();
    });
  });

  cancelBtn.addEventListener('click', closeModal);
  overlay.addEventListener('click', function (event) {
    if (event.target === overlay) closeModal();
  });

  confirmBtn.addEventListener('click', function () {
    confirmBtn.disabled = true;
    confirmBtn.classList.add('opacity-70', 'cursor-not-allowed');
    confirmBtn.innerHTML = spinnerSvg + ' Keluar...';
    performLogout().catch(function () {
      confirmBtn.disabled = false;
      confirmBtn.classList.remove('opacity-70', 'cursor-not-allowed');
      confirmBtn.textContent = 'Ya, Keluar';
    });
  });

  function clearLocalSession() {
    var config = window.AKSARAKU_CONFIG || {};
    if (config.SUPABASE_URL) {
      try {
        var host = new URL(config.SUPABASE_URL).hostname.split('.')[0];
        if (host) {
          var key = 'sb-' + host + '-auth-token';
          window.localStorage.removeItem(key);
          window.sessionStorage.removeItem(key);
        }
      } catch (error) {
        /* ignore */
      }
    }
    window.localStorage.removeItem('aksaraku_chat_session_id');
  }

  function getLoginPath(role) {
    var path = window.location.pathname;
    var inAdmin = /\/admin\//.test(path);
    var inTeacher = /\/teacher\//.test(path);
    var inPages = /\/pages\//.test(path);

    if (inAdmin) return role === 'admin' ? './login.html' : '../login.html';
    if (inTeacher) return role === 'teacher' ? './login.html' : '../login.html';

    if (inPages) {
      if (role === 'admin') return '../admin/login.html';
      if (role === 'teacher') return '../teacher/login.html';
      return '../login.html';
    }

    if (role === 'admin') return './admin/login.html';
    if (role === 'teacher') return './teacher/login.html';
    return './login.html';
  }

  async function performLogout() {
    var client = window.createAksarakuClient ? window.createAksarakuClient() : null;
    var role = 'user';

    if (client) {
      var sessionResult = await client.auth.getSession();
      var user = sessionResult.data && sessionResult.data.session ? sessionResult.data.session.user : null;
      if (user) {
        try {
          var profile = await client
            .from('profiles')
            .select('role')
            .eq('id', user.id)
            .maybeSingle();
          if (profile && profile.data) role = profile.data.role;
        } catch (error) {
          /* fallback ke user */
        }
      }
    }

    if (client) {
      var result = await client.auth.signOut({ scope: 'global' });
      if (result.error) {
        alert('Gagal Logout: ' + result.error.message);
        throw result.error;
      }
    }

    clearLocalSession();
    window.location.replace(getLoginPath(role));
  }
})();