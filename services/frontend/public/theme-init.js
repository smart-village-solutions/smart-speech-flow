// Runs before the first paint. It lives here, not inline, because the policy forbids inline script (#620).
(() => {
  try {
    const saved = localStorage.getItem('ssf-theme');
    const dark =
      saved === 'dark' || (saved !== 'light' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.classList.toggle('dark', dark);
  } catch {
    // Keep the light default if browser preferences or storage are unavailable.
  }
})();
