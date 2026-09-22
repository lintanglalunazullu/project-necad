(function () {
  const sidebar = document.querySelector('[data-mobile-sidebar]');
  const toggleBtn = document.querySelector('[data-mobile-menu-toggle]');
  const overlay = document.querySelector('[data-mobile-sidebar-overlay]');

  if (!sidebar || !toggleBtn) return;

  function openSidebar() {
    sidebar.classList.remove('hidden');
    sidebar.classList.add('flex');
    sidebar.style.display = 'flex';
    toggleBtn.setAttribute('aria-expanded', 'true');
    if (overlay) {
      overlay.classList.remove('hidden');
    }
    document.body.classList.add('overflow-hidden');
  }

  function closeSidebar() {
    sidebar.classList.add('hidden');
    sidebar.classList.remove('flex');
    sidebar.style.removeProperty('display');
    toggleBtn.setAttribute('aria-expanded', 'false');
    if (overlay) {
      overlay.classList.add('hidden');
    }
    document.body.classList.remove('overflow-hidden');
  }

  toggleBtn.addEventListener('click', () => {
    const isOpen = !sidebar.classList.contains('hidden');
    if (isOpen) {
      closeSidebar();
    } else {
      openSidebar();
    }
  });

  if (overlay) {
    overlay.addEventListener('click', closeSidebar);
  }

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeSidebar();
    }
  });

  window.addEventListener('resize', () => {
    if (window.innerWidth >= 768) {
      closeSidebar();
    }
  });
})();
