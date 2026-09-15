window.AKSARAKU_ROLES = Object.freeze({
  ADMIN: 'admin',
  USER: 'user',
  TEACHER: 'teacher',
});

window.createAksarakuClient = function createAksarakuClient() {
  const config = window.AKSARAKU_CONFIG || {};
  if (!window.supabase || !config.SUPABASE_URL || !config.SUPABASE_ANON_KEY) return null;
  return window.supabase.createClient(config.SUPABASE_URL, config.SUPABASE_ANON_KEY);
};

window.ensureAksarakuProfile = async function ensureAksarakuProfile(client, user) {
  if (!client || !user) return null;

  const { data: existing, error: readError } = await client
    .from('profiles')
    .select('id,email,full_name,role,provider')
    .eq('id', user.id)
    .maybeSingle();

  if (readError) throw readError;
  if (existing) return existing;

  const provider = user.app_metadata?.provider
    || user.app_metadata?.providers?.[0]
    || 'email';
  const fullName = user.user_metadata?.full_name
    || user.user_metadata?.name
    || user.email?.split('@')[0]
    || 'User';

  const { data: created, error: insertError } = await client
    .from('profiles')
    .insert({
      id: user.id,
      email: user.email || '',
      full_name: fullName,
      provider,
      role: 'user',
    })
    .select('id,email,full_name,role,provider')
    .single();

  if (!insertError) return created;
  if (insertError.code === '23505') {
    const { data: profile } = await client
      .from('profiles')
      .select('id,email,full_name,role,provider')
      .eq('id', user.id)
      .single();
    return profile;
  }

  throw insertError;
};

window.getAksarakuUserRole = async function getAksarakuUserRole(client, user) {
  if (!client || !user) return null;

  const { data } = await client
    .from('profiles')
    .select('role')
    .eq('id', user.id)
    .maybeSingle();

  return data?.role || user.user_metadata?.role || user.app_metadata?.role || null;
};

window.requireAksarakuRole = async function requireAksarakuRole(allowedRoles, loginPath) {
  document.documentElement.style.visibility = 'hidden';
  const client = window.createAksarakuClient();
  const { data: { session } = {} } = client
    ? await client.auth.getSession()
    : { data: {} };
  if (session?.user) await window.ensureAksarakuProfile(client, session.user);
  const role = await window.getAksarakuUserRole(client, session?.user);

  if (!session?.user || !allowedRoles.includes(role)) {
    if (client && session) await client.auth.signOut();
    window.location.replace(loginPath);
    return null;
  }

  document.documentElement.style.visibility = 'visible';
  return { client, session, role };
};
