(function () {
  const SUPABASE_URL = 'https://pwohquppbydpycpqwxtg.supabase.co';
  const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InB3b2hxdXBwYnlkcHljcHF3eHRnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODU1MjYyNTUsImV4cCI6MjEwMTEwMjI1NX0.QUmKNTzaw88NZqb7ihR9Mgm7laJzm6_-M7Ktz0hNcGU';

  const signOutItems = Array.from(document.querySelectorAll('[data-auth-menu="signout"]'));
  const loginItems = Array.from(document.querySelectorAll('[data-auth-menu="login"]'));

  if (!signOutItems.length && !loginItems.length) return;

  const supabaseClient = window.supabase
    ? window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY)
    : null;

  function setAuthMenuVisibility(hasSession) {
    signOutItems.forEach((item) => {
      item.classList.toggle('hidden', !hasSession);
    });

    loginItems.forEach((item) => {
      item.classList.toggle('hidden', hasSession);
    });
  }

  async function syncAuthState() {
    if (!supabaseClient) {
      setSignOutVisibility(false);
      return;
    }

    try {
      const { data: { session } } = await supabaseClient.auth.getSession();
      setAuthMenuVisibility(!!(session && session.user));
    } catch (error) {
      console.error('Gagal membaca session Supabase:', error);
      setAuthMenuVisibility(false);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      syncAuthState();
    }, { once: true });
  } else {
    syncAuthState();
  }

  if (supabaseClient) {
    supabaseClient.auth.onAuthStateChange((_event, session) => {
      setAuthMenuVisibility(!!(session && session.user));
    });
  }
})();
