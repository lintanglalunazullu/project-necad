const SUPABASE_URL = 'https://pwohquppbydpycpqwxtg.supabase.co';
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InB3b2hxdXBwYnlkcHljcHF3eHRnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODU1MjYyNTUsImV4cCI6MjEwMTEwMjI1NX0.QUmKNTzaw88NZqb7ihR9Mgm7laJzm6_-M7Ktz0hNcGU';

const form = document.getElementById('adminLoginForm');
const emailInput = document.getElementById('email');
const passwordInput = document.getElementById('password');
const loginButton = document.getElementById('loginButton');
const loginMessage = document.getElementById('loginMessage');
const togglePassword = document.getElementById('togglePassword');
const supabaseClient = window.supabase
  ? window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY)
  : null;

function showMessage(message, isError = true) {
  loginMessage.textContent = message;
  loginMessage.className = `rounded-lg border px-3 py-2 text-sm ${isError
    ? 'border-red-400/20 bg-red-400/10 text-red-200'
    : 'border-emerald-400/20 bg-emerald-400/10 text-emerald-200'}`;
}

function isEmailProvider(user) {
  const providers = user?.app_metadata?.providers || [];
  const provider = user?.app_metadata?.provider;
  return provider === 'email' || providers.includes('email');
}

async function redirectIfLoggedIn() {
  if (!supabaseClient) return;

  const { data: { session } } = await supabaseClient.auth.getSession();
  const role = await window.getAksarakuUserRole(supabaseClient, session?.user);
  if (isEmailProvider(session?.user) && role === 'admin') {
    window.location.replace('./index.html');
  } else if (session && role !== 'admin') {
    await supabaseClient.auth.signOut();
  }
}

togglePassword.addEventListener('click', () => {
  const isPassword = passwordInput.type === 'password';
  passwordInput.type = isPassword ? 'text' : 'password';
  togglePassword.textContent = isPassword ? 'Sembunyikan' : 'Tampilkan';
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();

  if (!supabaseClient) {
    showMessage('Layanan login belum siap. Muat ulang halaman dan coba lagi.');
    return;
  }

  loginButton.disabled = true;
  loginButton.querySelector('span').textContent = 'Memeriksa...';
  loginMessage.className = 'hidden';

  const { data, error } = await supabaseClient.auth.signInWithPassword({
    email: emailInput.value.trim(),
    password: passwordInput.value,
  });

  if (error) {
    showMessage(error.message.includes('Email not confirmed')
      ? 'Email akun belum dikonfirmasi di Supabase.'
      : 'Email atau kata sandi tidak sesuai.');
    loginButton.disabled = false;
    loginButton.querySelector('span').textContent = 'Masuk ke dashboard';
    return;
  }

  const role = await window.getAksarakuUserRole(supabaseClient, data.user);
  if (!isEmailProvider(data.user) || role !== 'admin') {
    await supabaseClient.auth.signOut();
    showMessage('Akun ini tidak memiliki role admin.');
    loginButton.disabled = false;
    loginButton.querySelector('span').textContent = 'Masuk ke dashboard';
    return;
  }

  window.location.replace('./index.html');
});

redirectIfLoggedIn().catch(() => {
  showMessage('Sesi login tidak dapat diperiksa.');
});