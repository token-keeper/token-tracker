(function () {
  const dataCurrent = JSON.parse(document.getElementById('data-current').textContent);
  const dataAll = JSON.parse(document.getElementById('data-all').textContent);
  const i18n = JSON.parse(document.getElementById('i18n').textContent);
  const state = { tab: 'current', sortKey: 'started_at', sortDir: 1, search: '', model: '', session: '', expanded: new Set() };

  // Task 10 will implement render. Stub only mounts a placeholder.
  document.getElementById('table-host').textContent = '(rendering pending)';
})();
