const SUPABASE_URL = 'https://pwohquppbydpycpqwxtg.supabase.co';
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InB3b2hxdXBwYnlkcHljcHF3eHRnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODU1MjYyNTUsImV4cCI6MjEwMTEwMjI1NX0.QUmKNTzaw88NZqb7ihR9Mgm7laJzm6_-M7Ktz0hNcGU';

let supabaseClient = null;

try {
  if (window.supabase) {
    supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  }
} catch (error) {
  console.error('Gagal menginisialisasi Supabase:', error);
}

// Gunakan supabaseClient untuk panggil fungsi
async function loginWithGoogle() {
  if (!supabaseClient) {
    console.error('Supabase belum siap.');
    return;
  }

  const { error } = await supabaseClient.auth.signInWithOAuth({
    provider: 'google',
    options: {
      redirectTo: window.location.origin
    }
  });

  if (error) console.error(error.message);
}

// 3. Cek jika user ternyata SUDAH login saat membuka login.html
async function checkIfLoggedIn() {
  if (!supabaseClient) return;

  try {
    const { data: { session } } = await supabaseClient.auth.getSession();

    if (session) {
      if (window.ensureAksarakuProfile) {
        await window.ensureAksarakuProfile(supabaseClient, session.user);
      }
      const role = window.getAksarakuUserRole
        ? await window.getAksarakuUserRole(supabaseClient, session.user)
        : null;
      const paths = {
        admin: './admin/index.html',
        teacher: './teacher/chat.html',
        user: './index.html',
      };
      if (paths[role]) {
        window.location.href = paths[role];
      } else {
        await supabaseClient.auth.signOut();
      }
    }
  } catch (error) {
    console.error('Gagal memeriksa sesi login:', error);
  }
}

// Jalankan pengecekan saat pertama kali dibuka
checkIfLoggedIn();