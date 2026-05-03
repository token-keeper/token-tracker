(function () {
  const dataCurrent = JSON.parse(document.getElementById('data-current').textContent);
  const dataAll = JSON.parse(document.getElementById('data-all').textContent);
  const i18n = JSON.parse(document.getElementById('i18n').textContent);

  const COLUMNS = [
    { key: 'index',    label: i18n.col_history_index,    sortable: true },
    { key: 'time',     label: i18n.col_history_time,     sortable: true },
    { key: 'prompt',   label: i18n.col_history_prompt,   sortable: false },
    { key: 'model',    label: i18n.col_history_model,    sortable: true },
    { key: 'cost',     label: i18n.col_history_cost,     sortable: true },
    { key: 'in',       label: i18n.col_history_in,       sortable: true },
    { key: 'out',      label: i18n.col_history_out,      sortable: true },
    { key: 'cc',       label: i18n.col_history_cc,       sortable: true },
    { key: 'elapsed',  label: i18n.col_history_elapsed,  sortable: true },
  ];
  const SESSION_COL = { key: 'session', label: i18n.col_history_session, sortable: true };

  const state = {
    tab: 'current',
    sortKey: 'time',
    sortDir: 1,
    search: '',
    model: '',
    session: '',
    expanded: new Set(),
  };

  function shortModel(rawId) {
    if (!rawId) return '';
    const m = /^claude-([a-z]+)-(\d+)-(\d+)/.exec(rawId);
    return m ? `${m[1]} ${m[2]}.${m[3]}` : rawId;
  }

  function modelDisplay(entry) {
    const primary = entry.models_used && entry.models_used[0]
      ? shortModel(entry.models_used[0]) : '';
    return entry.has_subagent_other_model ? primary + '+ⓢ' : primary;
  }

  function dataset() {
    return state.tab === 'current' ? dataCurrent : dataAll;
  }

  function filtered() {
    const q = state.search.toLowerCase();
    return dataset().filter(e => {
      if (q && !(e.user_prompt && (e.user_prompt.text || '').toLowerCase().includes(q))) return false;
      if (state.model && (!e.models_used || e.models_used[0] !== state.model)) return false;
      if (state.tab === 'all' && state.session && e.session_id !== state.session) return false;
      return true;
    });
  }

  function rowValue(e, key) {
    switch (key) {
      case 'time': return e.started_at || 0;
      case 'model': return modelDisplay(e);
      case 'cost': return e.summary?.total_cost ?? 0;
      case 'in': return e.summary?.total_input_tokens ?? 0;
      case 'out': return e.summary?.total_output_tokens ?? 0;
      case 'cc': return e.summary?.cache_hit_rate ?? 0;
      case 'elapsed': return e.summary?.total_elapsed ?? 0;
      case 'session': return e.session_id || '';
      case 'index':
      default: return 0;
    }
  }

  function sorted(rows) {
    if (state.sortKey === 'index') return rows;
    const dir = state.sortDir;
    return [...rows].sort((a, b) => {
      const av = rowValue(a, state.sortKey);
      const bv = rowValue(b, state.sortKey);
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    });
  }

  function fmtTime(ts) {
    return new Date(ts * 1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
  }

  function fmtCost(c) { return '$' + (c || 0).toFixed(4); }
  function fmtNum(n) { return Number(n || 0).toLocaleString(); }
  function fmtPct(p) { return Math.round((p || 0) * 100) + '%'; }
  function fmtElapsed(s) { return (s || 0).toFixed(1) + 's'; }

  function renderTotals(rows) {
    const t = rows.reduce((acc, e) => {
      const s = e.summary || {};
      acc.cost += s.total_cost || 0;
      acc.in += s.total_input_tokens || 0;
      acc.out += s.total_output_tokens || 0;
      acc.elapsed += s.total_elapsed || 0;
      const inp = (s.total_input_tokens || 0);
      acc.cacheNum += (s.cache_hit_rate || 0) * inp;
      acc.cacheDen += inp;
      return acc;
    }, {cost:0, in:0, out:0, elapsed:0, cacheNum:0, cacheDen:0});
    const cachePct = t.cacheDen > 0 ? (t.cacheNum / t.cacheDen) : 0;
    document.getElementById('totals').textContent =
      `${i18n.total_label}  ${fmtCost(t.cost)} · ${fmtNum(t.in + t.out)} toks · ${fmtPct(cachePct)} cache · ${fmtElapsed(t.elapsed)}`;
  }

  function renderTable(rows) {
    const cols = state.tab === 'all' ? [...COLUMNS, SESSION_COL] : COLUMNS;
    const host = document.getElementById('table-host');
    host.innerHTML = '';
    if (!rows.length) {
      document.getElementById('empty').hidden = false;
      return;
    }
    document.getElementById('empty').hidden = true;
    const table = document.createElement('table');
    const thead = document.createElement('thead');
    const tr = document.createElement('tr');
    cols.forEach(c => {
      const th = document.createElement('th');
      th.textContent = c.label + (state.sortKey === c.key ? (state.sortDir > 0 ? ' ▲' : ' ▼') : '');
      if (c.sortable) {
        th.style.cursor = 'pointer';
        th.onclick = () => {
          if (state.sortKey === c.key) state.sortDir *= -1;
          else { state.sortKey = c.key; state.sortDir = c.key === 'time' ? -1 : 1; }
          render();
        };
      }
      tr.appendChild(th);
    });
    thead.appendChild(tr);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    rows.forEach((e, i) => {
      const row = document.createElement('tr');
      row.dataset.promptId = e.prompt_id;
      const cells = {
        index: i + 1,
        time: fmtTime(e.started_at || 0),
        prompt: (e.user_prompt && e.user_prompt.text) || '',
        model: modelDisplay(e),
        cost: fmtCost(e.summary?.total_cost),
        in: fmtNum(e.summary?.total_input_tokens),
        out: fmtNum(e.summary?.total_output_tokens),
        cc: fmtPct(e.summary?.cache_hit_rate),
        elapsed: fmtElapsed(e.summary?.total_elapsed),
        session: (e.session_id || '').slice(0, 8),
      };
      cols.forEach(c => {
        const td = document.createElement('td');
        const val = cells[c.key];
        if (c.key === 'prompt') {
          td.title = val;
          td.style.maxWidth = '40ch';
          td.style.overflow = 'hidden';
          td.style.textOverflow = 'ellipsis';
          td.style.whiteSpace = 'nowrap';
        }
        td.textContent = val;
        row.appendChild(td);
      });
      row.style.cursor = 'pointer';
      row.onclick = () => toggleExpand(e.prompt_id);
      tbody.appendChild(row);

      if (state.expanded.has(e.prompt_id)) {
        const expandRow = document.createElement('tr');
        const expandCell = document.createElement('td');
        expandCell.colSpan = cols.length;
        expandCell.className = 'row-expand';
        expandCell.appendChild(renderExpand(e));
        expandRow.appendChild(expandCell);
        tbody.appendChild(expandRow);
      }
    });
    table.appendChild(tbody);
    host.appendChild(table);
  }

  function isLong(text) {
    if (!text) return false;
    return text.length > 500 || text.split('\n').length > 5;
  }

  function makePre(text) {
    const wrap = document.createElement('div');
    const pre = document.createElement('pre');
    if (isLong(text)) {
      pre.classList.add('long');
      wrap.classList.add('collapsed');
      const toggle = document.createElement('button');
      toggle.textContent = i18n.expand_show_full;
      toggle.onclick = (ev) => {
        ev.stopPropagation();
        const collapsed = wrap.classList.toggle('collapsed');
        toggle.textContent = collapsed ? i18n.expand_show_full : i18n.expand_collapse;
      };
      wrap.appendChild(pre);
      wrap.appendChild(toggle);
    } else {
      wrap.appendChild(pre);
    }
    pre.textContent = text;
    return wrap;
  }

  function renderExpand(e) {
    const root = document.createElement('div');
    const userSection = document.createElement('section');
    const userH = document.createElement('h4');
    userH.textContent = i18n.expand_user_prompt;
    userSection.appendChild(userH);
    userSection.appendChild(makePre((e.user_prompt && e.user_prompt.text) || ''));
    root.appendChild(userSection);

    const ai = (e.transcript_entries || []).filter(x => x.type === 'assistant_text').map(x => x.text).join('\n\n');
    if (ai) {
      const sec = document.createElement('section');
      const h = document.createElement('h4'); h.textContent = i18n.expand_ai_response;
      sec.appendChild(h); sec.appendChild(makePre(ai));
      root.appendChild(sec);
    }

    const thinking = (e.transcript_entries || []).filter(x => x.type === 'thinking').map(x => x.text).join('\n\n');
    if (thinking) {
      const sec = document.createElement('section');
      const h = document.createElement('h4'); h.textContent = i18n.expand_thinking;
      sec.appendChild(h); sec.appendChild(makePre(thinking));
      root.appendChild(sec);
    }

    const tools = (e.transcript_entries || []).filter(x => x.type === 'tool_call' || x.type === 'tool_result');
    if (tools.length) {
      const sec = document.createElement('section');
      const h = document.createElement('h4');
      h.textContent = i18n.expand_tool_calls.replace('{n}', tools.length);
      sec.appendChild(h);
      tools.forEach(t => {
        const li = document.createElement('div');
        if (t.type === 'tool_call') {
          li.textContent = `▸ ${t.name}: ${JSON.stringify(t.input).slice(0, 200)}`;
        } else {
          li.textContent = `  ↳ result${t.is_error ? ' (error)' : ''}: ${(t.content || '').slice(0, 200)}`;
        }
        sec.appendChild(li);
      });
      root.appendChild(sec);
    }

    return root;
  }

  function toggleExpand(pid) {
    if (state.expanded.has(pid)) state.expanded.delete(pid);
    else state.expanded.add(pid);
    render();
  }

  function rebuildFilters() {
    const ds = dataset();
    const models = new Set();
    const sessions = new Set();
    ds.forEach(e => {
      if (e.models_used && e.models_used[0]) models.add(e.models_used[0]);
      if (e.session_id) sessions.add(e.session_id);
    });

    const modelSel = document.getElementById('filter-model');
    modelSel.innerHTML = `<option value="">${i18n.filter_model_all}</option>`;
    [...models].sort().forEach(m => {
      const o = document.createElement('option');
      o.value = m; o.textContent = shortModel(m);
      modelSel.appendChild(o);
    });
    modelSel.value = state.model;

    const sessionSel = document.getElementById('filter-session');
    sessionSel.style.display = state.tab === 'all' ? '' : 'none';
    sessionSel.innerHTML = `<option value="">${i18n.filter_session_all}</option>`;
    [...sessions].sort().forEach(s => {
      const o = document.createElement('option');
      o.value = s; o.textContent = s.slice(0, 8);
      sessionSel.appendChild(o);
    });
    sessionSel.value = state.session;
  }

  function render() {
    rebuildFilters();
    const rows = sorted(filtered());
    renderTotals(rows);
    renderTable(rows);
  }

  // Wire events
  document.querySelectorAll('nav.tabs button').forEach(b => {
    b.onclick = () => {
      state.tab = b.dataset.tab;
      state.sortKey = 'time'; state.sortDir = -1;
      state.search = ''; state.model = ''; state.session = '';
      state.expanded.clear();
      document.getElementById('search').value = '';
      document.querySelectorAll('nav.tabs button').forEach(x => x.classList.toggle('active', x === b));
      render();
    };
  });
  document.getElementById('search').addEventListener('input', (ev) => {
    state.search = ev.target.value;
    render();
  });
  document.getElementById('filter-model').addEventListener('change', (ev) => {
    state.model = ev.target.value;
    render();
  });
  document.getElementById('filter-session').addEventListener('change', (ev) => {
    state.session = ev.target.value;
    render();
  });

  // Initial sort: most recent first
  state.sortDir = -1;
  render();
})();
