(function () {
  try {
    var k = 'scholar-ai.theme';
    var saved = localStorage.getItem(k);
    var isAgentSidebar = window.location.pathname === '/agent-sidebar'
      || window.location.pathname.indexOf('/agent-sidebar/') === 0;
    var mode = isAgentSidebar
      ? 'system'
      : (saved === 'light' || saved === 'dark' || saved === 'system') ? saved : 'system';
    var dark = mode === 'dark' || (mode === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    var root = document.documentElement;
    if (dark) root.classList.add('dark'); else root.classList.remove('dark');
    root.dataset.theme = dark ? 'dark' : 'light';
  } catch (e) { /* localStorage unavailable */ }
})();
