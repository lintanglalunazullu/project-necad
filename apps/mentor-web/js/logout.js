const SUPABASE_URL = 'https://pwohquppbydpycpqwxtg.supabase.co';
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InB3b2hxdXBwYnlkcHljcHF3eHRnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODU1MjYyNTUsImV4cCI6MjEwMTEwMjI1NX0.QUmKNTzaw88NZqb7ihR9Mgm7laJzm6_-M7Ktz0hNcGU';
const supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

async function logout() {
  const { data: { session } } = await supabaseClient.auth.getSession();
  let role = 'user';

  if (session?.user) {
    const { data: profile } = await supabaseClient
      .from('profiles')
      .select('role')
      .eq('id', session.user.id)
      .maybeSingle();
    role = profile?.role || session.user.user_metadata?.role || 'user';
  }

  const { error } = await supabaseClient.auth.signOut({ scope: 'global' });
  if (error) {
    alert('Gagal Logout: ' + error.message);
  } else {
    const loginPaths = {
      admin: '../admin/login.html',
      teacher: '../teacher/login.html',
      user: '../login.html',
    };
    window.location.replace(loginPaths[role] || '../login.html');
  }
}