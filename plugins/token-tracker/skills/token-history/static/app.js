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
    expanded: new Set(),
    expandedTurns: new Map() // rowN -> Set of turn n
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
  const formatK = n => {
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return String(n);
  };

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
        const turns = Array.isArray(r.turns) ? r.turns : [];
        const expandedSet = state.expandedTurns.get(r.n) || new Set();
        state.expandedTurns.set(r.n, expandedSet);
        const totalToolCalls = turns.reduce((s, t) => s + (t.tools ? t.tools.reduce((a, x) => a + (x.count || 1), 0) : 0), 0);
        const turnsTotalCost = turns.reduce((s, t) => s + t.cost, 0);
        const maxTurnCost = turns.length ? Math.max(...turns.map(t => t.cost)) : 0;

        const er = document.createElement('tr');
        er.className = 'expand-row';
        const td = document.createElement('td');
        td.colSpan = 10;
        const inner = document.createElement('div');
        inner.className = 'expand-inner';

        const toolbar = document.createElement('div');
        toolbar.className = 'turns-toolbar';
        toolbar.innerHTML = `
          <span class="meta">${t('turnsHeader', {
            n: '<strong>' + turns.length + '</strong>',
            cost: '<strong>' + fmtCost(turnsTotalCost) + '</strong>',
            tools: '<strong>' + totalToolCalls + '</strong>'
          })}</span>
          <span class="actions">
            <button type="button" data-act="expand-all">${escape(t('expandAll'))}</button>
            <button type="button" data-act="collapse-all">${escape(t('collapseAll'))}</button>
          </span>
        `;
        toolbar.addEventListener('click', e => {
          const act = e.target.closest('button')?.dataset.act;
          if (!act) return;
          e.stopPropagation();
          if (act === 'expand-all') turns.forEach(tn => expandedSet.add(tn.n));
          else expandedSet.clear();
          render();
        });
        inner.appendChild(toolbar);

        const headBar = document.createElement('div');
        headBar.className = 'turn-head-bar';
        headBar.innerHTML = `
          <span class="col th-n">#</span>
          <span class="col th-model">model</span>
          <span class="col th-tools">${escape(t('turnColTools'))}</span>
          <span class="col th-request">request</span>
          <span class="col th-cost">cost</span>
          <span class="col th-input">${escape(t('turnColInput'))}</span>
          <span class="col th-cc">${escape(t('turnColCC'))}</span>
          <span class="col th-cr">${escape(t('turnColCR'))}</span>
          <span class="col th-output">${escape(t('turnColOutput'))}</span>
          <span class="col th-elapsed">elapsed</span>
          <span class="col th-chev"></span>
        `;
        inner.appendChild(headBar);

        const list = document.createElement('div');
        list.className = 'turn-list';

        turns.forEach(tn => {
          const tnExp = expandedSet.has(tn.n);
          const isHotTurn = tn.cost >= maxTurnCost * 0.6 && turns.length > 1;
          const ccPct = tn.cr > 0 ? tn.cc / tn.cr : 1;
          const ccClassT = ccPct >= 0.9 ? '' : (ccPct >= 0.75 ? 'is-warn' : 'is-bad');
          const toolsHtml = (tn.tools && tn.tools.length)
            ? tn.tools.map(x => `<span class="tool-pill">${escape(x.name)}${x.count > 1 ? '×' + x.count : ''}</span>`).join('')
            : `<span class="none">${escape(t('noTools'))}</span>`;
          const requestPreview = (() => {
            if (tn.tool_pairs && tn.tool_pairs[0] && tn.tool_pairs[0].input) {
              const input = tn.tool_pairs[0].input;
              const keys = Object.keys(input);
              if (keys.length > 0) {
                const k = keys[0];
                let v = input[k];
                if (v === null) v = 'null';
                else if (typeof v === 'object') v = JSON.stringify(v);
                else v = String(v);
                if (v.length > 18) v = v.slice(0, 17) + '…';
                return `<code>${escape(k)}: ${escape(v)}</code>`;
              }
            }
            const fallback = (tn.assistant_text || tn.thinking || '').trim();
            if (fallback) {
              const oneLine = fallback.replace(/\s+/g, ' ');
              const clipped = oneLine.length > 28 ? oneLine.slice(0, 27) + '…' : oneLine;
              return `<span class="text-prev">${escape(clipped)}</span>`;
            }
            return `<span class="none">—</span>`;
          })();

          const card = document.createElement('div');
          card.className = 'turn-card' + (tnExp ? ' expanded' : '') + (isHotTurn ? ' is-hot' : '');
          card.innerHTML = `
            <span class="accent"></span>
            <div class="turn-head" tabindex="0" role="button" aria-expanded="${tnExp}">
              <span class="col th-n">${tn.n}</span>
              <span class="col th-model">${escape(tn.model)}</span>
              <span class="col th-tools">${toolsHtml}</span>
              <span class="col th-request">${requestPreview}</span>
              <span class="col th-cost ${isHotTurn ? 'is-hot' : ''}">${fmtCost(tn.cost)}</span>
              <span class="col th-input">${fmtToks(tn.input)}</span>
              <span class="col th-cc ${ccClassT}">${fmtToks(tn.cc)}</span>
              <span class="col th-cr">${formatK(tn.cr)}</span>
              <span class="col th-output">${fmtToks(tn.output)}</span>
              <span class="col th-elapsed">${fmtSec(tn.elapsed)}</span>
              <span class="col th-chev">${tnExp ? '▾' : '▸'}</span>
            </div>
          `;
          if (tnExp) {
            const body = document.createElement('div');
            body.className = 'turn-body';
            const cap = (s) => (s || '').slice(0, 50 * 1024);
            const sections = [];
            if (tn.thinking) sections.push(`
              <div class="turn-section thinking">
                <div class="label">${escape(t('thinking'))}</div>
                <div class="body">${escape(cap(tn.thinking))}</div>
              </div>`);
            if (tn.assistant_text) sections.push(`
              <div class="turn-section assistant">
                <div class="label">${escape(t('assistantText'))}</div>
                <div class="body">${escape(cap(tn.assistant_text))}</div>
              </div>`);
            (tn.tool_pairs || []).forEach(pair => {
              sections.push(`
                <div class="turn-section tool-call">
                  <div class="label">${escape(t('toolCall'))} · ${escape(pair.name || '')}</div>
                  <div class="body">${escape(JSON.stringify(pair.input || {}, null, 2))}</div>
                </div>
              `);
              if (pair.has_result) {
                sections.push(`
                  <div class="turn-section tool-result ${pair.is_error ? 'is-error' : ''}">
                    <div class="label">${escape(t('toolResult'))}${pair.is_error ? ' <span class="err">' + escape(t('errorBadge')) + '</span>' : ''}</div>
                    <div class="body">${escape(cap(pair.content || ''))}</div>
                  </div>
                `);
              }
            });
            if (sections.length === 0) sections.push(`
              <div class="turn-section">
                <div class="body" style="color:var(--fg-muted);font-style:italic">${escape(t('noContent'))}</div>
              </div>`);
            body.innerHTML = sections.join('');
            card.appendChild(body);
          }
          const headEl = card.querySelector('.turn-head');
          const onToggle = () => {
            if (expandedSet.has(tn.n)) expandedSet.delete(tn.n);
            else expandedSet.add(tn.n);
            render();
          };
          headEl.addEventListener('click', onToggle);
          headEl.addEventListener('keydown', ev => {
            if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); onToggle(); }
          });
          list.appendChild(card);
        });

        inner.appendChild(list);
        td.appendChild(inner);
        er.appendChild(td);
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
