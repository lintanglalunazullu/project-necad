(async function () {
  try {
    await window.requireAksarakuRole(['admin'], './login.html');
  } catch (error) {
    window.location.replace('./login.html');
  }
})();
