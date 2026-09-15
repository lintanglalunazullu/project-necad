(async function () {
  try {
    const client = window.createAksarakuClient();
    const { data: { session } = {} } = client
      ? await client.auth.getSession()
      : { data: {} };
    if (session?.user) await window.ensureAksarakuProfile(client, session.user);
    const role = await window.getAksarakuUserRole(client, session?.user);

    if (!session?.user) {
      window.location.replace('./login.html');
    } else if (role === 'admin') {
      window.location.replace('./admin/index.html');
    } else if (role === 'teacher') {
      window.location.replace('./teacher/chat.html');
    } else if (role !== 'user') {
      await client.auth.signOut();
      window.location.replace('./login.html');
    }
  } catch (error) {
    console.error('Gagal memeriksa akses dashboard user:', error);
    window.location.replace('./login.html');
  }
})();
