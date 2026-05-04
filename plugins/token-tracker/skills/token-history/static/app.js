(function(){
  'use strict';

  // ---------- i18n ----------
  const I18N = JSON.parse(document.getElementById('i18n').textContent);
  const LANG = (navigator.language || 'ko').toLowerCase().startsWith('en') ? 'en' : 'ko';
  const t = (path, vars) => {
    const v = path.split('.').reduce((o, k) => (o ? o[k] : undefined), I18N[LANG]) ?? path;
    if (!vars) return v;
    return v.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? '');
  };
  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.getAttribute('data-i18n'));
  });

  // ---------- data ----------
  const dataCurrent = JSON.parse(document.getElementById('data-current').textContent);
  const dataAll = JSON.parse(document.getElementById('data-all').textContent);
  const META = JSON.parse(document.getElementById('meta').textContent);

  // ---------- header ----------
  document.getElementById('page-title').textContent = t('title');
  document.getElementById('page-sub').innerHTML = t('subtitleFmt', { ts: escape(META.ts), ver: escape(META.ver) })
    .replace(/·/g, '<span class="dot">·</span>');

  // ---------- theme ----------
  const themeBtns = document.querySelectorAll('[data-theme-btn]');
  document.getElementById('t-light').textContent = t('themeLight');
  document.getElementById('t-auto').textContent = t('themeAuto');
  document.getElementById('t-dark').textContent = t('themeDark');
  function applyTheme(mode){
    if (mode === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', mode);
    themeBtns.forEach(b => b.setAttribute('aria-pressed', b.dataset.themeBtn === mode ? 'true' : 'false'));
    try { localStorage.setItem('tt-theme', mode); } catch(_){}
  }
  themeBtns.forEach(b => b.addEventListener('click', () => applyTheme(b.dataset.themeBtn)));
  let initTheme = 'auto';
  try { initTheme = localStorage.getItem('tt-theme') || 'auto'; } catch(_){}
  applyTheme(initTheme);

  // ---------- state ----------
  const state = {
    tab: 'current',
    q: '',
    model: 'all',
    session: 'all',
    sortKey: 'time',
    sortDir: 'desc',
    expanded: new Set()
  };

  // ---------- counts ----------
  document.getElementById('count-current').textContent = dataCurrent.length;
  document.getElementById('count-all').textContent = dataAll.length;

  // ---------- filter dropdowns ----------
  function uniq(arr, key){ return [...new Set(arr.map(r => r[key]))]; }
  function fillSelect(sel, options, allLabel){
    sel.innerHTML = '';
    const allOpt = document.createElement('option');
    allOpt.value = 'all';
    allOpt.textContent = allLabel;
    sel.appendChild(allOpt);
    options.forEach(o => {
      const opt = document.createElement('option');
      opt.value = o; opt.textContent = o;
      sel.appendChild(opt);
    });
  }
  const allRows = [...dataCurrent, ...dataAll];
  fillSelect(document.getElementById('model'), uniq(allRows, 'model'), t('modelAll'));
  fillSelect(document.getElementById('session'), uniq(dataAll, 'session'), t('sessionAll'));

  // ---------- listeners ----------
  document.getElementById('q').placeholder = t('search');
  document.getElementById('q').addEventListener('input', e => { state.q = e.target.value; render(); });
  document.getElementById('model').addEventListener('change', e => { state.model = e.target.value; render(); });
  document.getElementById('session').addEventListener('change', e => { state.session = e.target.value; render(); });

  document.querySelectorAll('[data-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      state.tab = btn.dataset.tab;
      document.querySelectorAll('[data-tab]').forEach(b => b.setAttribute('aria-selected', b === btn ? 'true' : 'false'));
      document.getElementById('session').style.display = state.tab === 'all' ? '' : 'none';
      render();
    });
  });

  document.querySelectorAll('thead th[data-key]').forEach(th => {
    const btn = th.querySelector('button');
    btn.addEventListener('click', () => {
      const k = th.dataset.key;
      if (state.sortKey === k) state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
      else { state.sortKey = k; state.sortDir = (k === 'time' || k === 'cost' || k === 'in' || k === 'out' || k === 'elapsed') ? 'desc' : 'asc'; }
      render();
    });
  });

  // ---------- format helpers ----------
  const fmtCost = c => '$' + c.toFixed(4);
  const fmtToks = n => n.toLocaleString('en-US');
  const fmtPct = p => Math.round(p * 100) + '%';
  const fmtSec = s => s.toFixed(1) + 's';

  // ---------- render ----------
  function getRows(){
    const src = state.tab === 'current' ? dataCurrent : dataAll;
    const q = state.q.trim().toLowerCase();
    let rows = src.filter(r => {
      if (q && !r.prompt.toLowerCase().includes(q)) return false;
      if (state.model !== 'all' && r.model !== state.model) return false;
      if (state.tab === 'all' && state.session !== 'all' && r.session !== state.session) return false;
      return true;
    });
    const k = state.sortKey, dir = state.sortDir === 'asc' ? 1 : -1;
    rows = [...rows].sort((a, b) => {
      const av = a[k], bv = b[k];
      if (typeof av === 'number') return (av - bv) * dir;
      return String(av).localeCompare(String(bv)) * dir;
    });
    return rows;
  }

  function render(){
    document.querySelectorAll('thead th[data-key]').forEach(th => {
      const isActive = th.dataset.key === state.sortKey;
      th.setAttribute('aria-sort', isActive ? (state.sortDir === 'asc' ? 'ascending' : 'descending') : 'none');
      const ind = th.querySelector('.sort-ind');
      ind.textContent = isActive ? (state.sortDir === 'asc' ? '▲' : '▼') : '·';
    });

    const rows = getRows();
    const tbody = document.getElementById('tbody');
    tbody.innerHTML = '';

    const totalCost = rows.reduce((s, r) => s + r.cost, 0);
    const totalToks = rows.reduce((s, r) => s + r.in + r.out, 0);
    const totalIn = rows.reduce((s, r) => s + r.in, 0);
    const weightedCache = totalIn ? rows.reduce((s, r) => s + r.cache * r.in, 0) / totalIn : 0;
    const totalElapsed = rows.reduce((s, r) => s + r.elapsed, 0);
    document.getElementById('summary-line').innerHTML =
      t('summaryFmt', {
        cost: '<strong>' + fmtCost(totalCost) + '</strong>',
        toks: '<strong>' + fmtToks(totalToks) + '</strong>',
        cache: '<strong>' + fmtPct(weightedCache) + '</strong>',
        elapsed: '<strong>' + fmtSec(totalElapsed) + '</strong>'
      });
    document.getElementById('rows-count').textContent = t('rowsFmt', { n: rows.length });

    if (rows.length === 0) {
      const tr = document.createElement('tr');
      tr.innerHTML = '<td colspan="10" class="empty">' + escape(t('empty')) + '</td>';
      tbody.appendChild(tr);
      return;
    }

    const maxCost = Math.max(...rows.map(r => r.cost));

    rows.forEach((r, i) => {
      const isExp = state.expanded.has(r.n);
      const ccClass = r.cache >= 0.9 ? '' : (r.cache >= 0.75 ? 'is-cc-warn' : 'is-cc-bad');
      const isHot = r.cost >= maxCost * 0.6 && rows.length > 1;
      const costPct = Math.max(4, Math.round((r.cost / maxCost) * 100));

      const tr = document.createElement('tr');
      tr.className = 'row' + (isExp ? ' expanded' : '');
      tr.tabIndex = 0;
      tr.dataset.n = r.n;
      tr.innerHTML = `
        <td class="c-n">${i + 1}</td>
        <td class="c-time">${escape(r.timeLabel)}</td>
        <td class="c-prompt"><span class="prompt-text" title="${escapeAttr(r.prompt)}">${escape(r.prompt)}</span></td>
        <td class="c-model"><span class="pill">${escape(r.model)}</span></td>
        <td class="c-cost ${isHot ? 'is-hot' : ''}">
          <div class="cost-cell">
            <span class="cost-bar"><span style="width:${costPct}%"></span></span>
            <span class="cost-num">${fmtCost(r.cost)}</span>
          </div>
        </td>
        <td class="c-in">${fmtToks(r.in)}</td>
        <td class="c-out">${fmtToks(r.out)}</td>
        <td class="c-cc ${ccClass}"><span class="cc-cell"><span class="cc-dot"></span><span class="cc-num">${fmtPct(r.cache)}</span></span></td>
        <td class="c-elapsed">${fmtSec(r.elapsed)}</td>
        <td class="c-chev">${isExp ? '▾' : '▸'}</td>
      `;
      tr.addEventListener('click', () => toggle(r.n));
      tr.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(r.n); }
      });
      tbody.appendChild(tr);

      if (isExp) {
        const er = document.createElement('tr');
        er.className = 'expand-row';
        const cap = (s) => (s || '').slice(0, 50 * 1024);
        er.innerHTML = `
          <td colspan="10">
            <div class="expand-inner">
              <div class="expand-block">
                <div class="label">${escape(t('userPrompt'))}</div>
                <div class="body">${escape(cap(r.prompt))}</div>
              </div>
              <div class="expand-block">
                <div class="label">${escape(t('aiResponse'))}</div>
                <div class="body">${escape(cap(r.response || ''))}</div>
              </div>
            </div>
          </td>
        `;
        tbody.appendChild(er);
      }
    });
  }

  function toggle(n){
    if (state.expanded.has(n)) state.expanded.delete(n);
    else state.expanded.add(n);
    render();
  }

  function escape(s){
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  function escapeAttr(s){ return escape(s); }

  render();
})();
