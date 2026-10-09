/* ============================================================
   Markets — draws data/summary.json (written by daily_summary.py).
   Every section is a list of generic blocks, so a new data source
   needs no change here:
     chart  {series:[{name, points:[[date, value]]}], unit}
     tiles  {items:[{label, value, change_pct, period, points}], unit}
     table  {columns:[{label, kind}], rows:[[...]], caption}
            kind: text | num | change | link (cell = [text, url])
   Used by index.html and prices.html:
     Markets.mount({sections, updated, tabs, compact})
   ============================================================ */
(function(){
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const vnd = new Intl.NumberFormat('vi-VN', {maximumFractionDigits: 2});
  const compact = new Intl.NumberFormat('en', {notation: 'compact', maximumFractionDigits: 1});
  let SUMMARY = null;
  let RANGE = 30;
  try{ RANGE = Number(localStorage.getItem('markets_range')) || 30; }catch(e){}

  function el(tag, cls, text){
    const n = document.createElement(tag);
    if(cls) n.className = cls;
    if(text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function svg(tag, attrs){
    const n = document.createElementNS(SVG_NS, tag);
    for(const k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  }
  const toDate = s => new Date(s.length > 10 ? s.replace(' ', 'T') : s + 'T00:00:00');
  const shortDate = d => `${String(d.getDate()).padStart(2,'0')}/${String(d.getMonth()+1).padStart(2,'0')}`;

  function inRange(points){
    if(!points || !points.length) return [];
    const last = toDate(points[points.length-1][0]);
    const cutoff = new Date(last.getTime() - RANGE * 86400000);
    return points.filter(p => toDate(p[0]) >= cutoff);
  }

  function niceTicks(min, max, count){
    const span = max - min || Math.abs(max) || 1;
    const raw = span / count;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw) || raw;
    const ticks = [];
    for(let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) ticks.push(v);
    return ticks;
  }

  function deltaEl(pct, period){
    if(pct === null || pct === undefined) return el('span', 'delta flat', 'chưa đủ dữ liệu');
    const dir = pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat';
    const arrow = pct > 0 ? '▲' : pct < 0 ? '▼' : '■';
    return el('span', `delta ${dir}`, `${arrow} ${pct > 0 ? '+' : ''}${pct.toFixed(2)}%${period ? ' ' + period : ''}`);
  }

  /* Line chart with crosshair + tooltip. series: [{name, color, points:[[date, value]]}]
     opts.compact = sparkline (no axes, one muted series, accent end dot). */
  function lineChart(container, series, opts){
    opts = opts || {};
    const isCompact = !!opts.compact;
    const fmt = opts.fmt || (v => vnd.format(v));
    const wrap = el('div', 'chart');
    wrap.tabIndex = 0;
    wrap.setAttribute('role', 'img');
    wrap.setAttribute('aria-label', opts.ariaLabel || 'line chart');
    container.appendChild(wrap);

    const W = Math.max(container.clientWidth || 300, 120);
    const H = opts.height || (isCompact ? 44 : 220);
    const endLabels = !isCompact && series.length <= 3 && W > 480;
    const m = isCompact ? {t: 6, r: 6, b: 4, l: 2} : {t: 10, r: endLabels ? 120 : 14, b: 24, l: 52};

    const dates = [...new Set(series.flatMap(s => s.points.map(p => p[0])))].sort();
    const all = series.flatMap(s => s.points.map(p => p[1]));
    if(!dates.length || !all.length){ wrap.appendChild(el('div', 'm-empty', 'không có dữ liệu trong khoảng này')); return; }
    let lo = Math.min(...all), hi = Math.max(...all);
    const pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.01 || 1;
    lo -= pad; hi += pad;
    const t0 = toDate(dates[0]).getTime(), t1 = toDate(dates[dates.length-1]).getTime();
    const x = d => m.l + (t1 === t0 ? (W - m.l - m.r) / 2 : (toDate(d).getTime() - t0) / (t1 - t0) * (W - m.l - m.r));
    const y = v => m.t + (hi - v) / (hi - lo) * (H - m.t - m.b);

    const root = svg('svg', {viewBox: `0 0 ${W} ${H}`, height: H, 'aria-hidden': 'true'});
    if(!isCompact){
      niceTicks(lo, hi, 3).forEach(v => {
        root.appendChild(svg('line', {x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: 'var(--grid)', 'stroke-width': 1}));
        const t = svg('text', {x: m.l - 8, y: y(v) + 3.5, 'text-anchor': 'end', class: 'tick'});
        t.textContent = compact.format(v);
        root.appendChild(t);
      });
      root.appendChild(svg('line', {x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, stroke: 'var(--axis)', 'stroke-width': 1}));
      const xs = dates.length > 2 ? [dates[0], dates[Math.floor(dates.length/2)], dates[dates.length-1]] : dates;
      [...new Set(xs)].forEach((d, i, arr) => {
        const t = svg('text', {x: x(d), y: H - 6, class: 'tick',
          'text-anchor': arr.length > 1 && i === 0 ? 'start' : (i === arr.length - 1 && arr.length > 1 ? 'end' : 'middle')});
        t.textContent = shortDate(toDate(d));
        root.appendChild(t);
      });
    }

    const lineColor = s => isCompact ? 'var(--spark)' : s.color;
    series.forEach(s => {
      if(s.points.length > 1){
        const dPath = s.points.map((p, i) => `${i ? 'L' : 'M'}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join('');
        root.appendChild(svg('path', {d: dPath, fill: 'none', stroke: lineColor(s), 'stroke-width': 2,
          'stroke-linejoin': 'round', 'stroke-linecap': 'round'}));
      }
      const last = s.points[s.points.length - 1];
      root.appendChild(svg('circle', {cx: x(last[0]), cy: y(last[1]), r: 4,
        fill: isCompact ? 'var(--series-1)' : s.color, stroke: 'var(--bg)', 'stroke-width': 2}));
      if(endLabels){
        const t = svg('text', {x: x(last[0]) + 10, y: y(last[1]) + 4, class: 'end-label'});
        t.textContent = s.name.length > 18 ? s.name.slice(0, 17) + '…' : s.name;
        root.appendChild(t);
      }
    });

    // Hover layer: crosshair snaps to the nearest date; one tooltip lists every series.
    const cross = svg('line', {y1: m.t, y2: H - m.b, stroke: 'var(--axis)', 'stroke-width': 1, visibility: 'hidden'});
    const hoverDots = series.map(s => {
      const c = svg('circle', {r: 4, fill: isCompact ? 'var(--series-1)' : s.color, stroke: 'var(--bg)', 'stroke-width': 2, visibility: 'hidden'});
      root.appendChild(c);
      return c;
    });
    root.insertBefore(cross, root.firstChild);
    wrap.appendChild(root);
    const tip = el('div', 'm-tip');
    wrap.appendChild(tip);

    let idx = dates.length - 1;
    function show(i){
      idx = Math.max(0, Math.min(dates.length - 1, i));
      const d = dates[idx], cx = x(d);
      cross.setAttribute('x1', cx); cross.setAttribute('x2', cx); cross.setAttribute('visibility', 'visible');
      tip.replaceChildren(el('div', 'tip-date', toDate(d).toLocaleDateString('vi-VN')));
      series.forEach((s, k) => {
        const p = s.points.find(p => p[0] === d);
        if(!p){ hoverDots[k].setAttribute('visibility', 'hidden'); return; }
        hoverDots[k].setAttribute('cx', cx); hoverDots[k].setAttribute('cy', y(p[1]));
        hoverDots[k].setAttribute('visibility', 'visible');
        const row = el('div', 'tip-row');
        const key = el('span', 'key'); key.style.background = isCompact ? 'var(--series-1)' : s.color;
        row.append(key, el('b', null, fmt(p[1])), el('span', null, s.name));
        tip.appendChild(row);
      });
      tip.style.display = 'block';
      const tw = tip.offsetWidth;
      tip.style.left = Math.min(Math.max(cx - tw / 2, 0), W - tw) + 'px';
      tip.style.top = (isCompact ? H + 6 : m.t) + 'px';
    }
    function hide(){
      cross.setAttribute('visibility', 'hidden');
      hoverDots.forEach(c => c.setAttribute('visibility', 'hidden'));
      tip.style.display = 'none';
    }
    function nearest(clientX){
      const r = root.getBoundingClientRect();
      const px = (clientX - r.left) * (W / r.width);
      let best = 0, bestDist = Infinity;
      dates.forEach((d, i) => { const dist = Math.abs(x(d) - px); if(dist < bestDist){ best = i; bestDist = dist; } });
      return best;
    }
    wrap.addEventListener('pointermove', e => show(nearest(e.clientX)));
    wrap.addEventListener('pointerleave', hide);
    wrap.addEventListener('focus', () => show(idx));
    wrap.addEventListener('blur', hide);
    wrap.addEventListener('keydown', e => {
      if(e.key === 'ArrowLeft'){ show(idx - 1); e.preventDefault(); }
      if(e.key === 'ArrowRight'){ show(idx + 1); e.preventDefault(); }
      if(e.key === 'Escape') hide();
    });
  }


  const COLORS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)', 'var(--series-5)'];
  let OPTS = {};

  function emptyMsg(body, text){
    body.replaceChildren(el('div', 'm-empty', text));
  }

  function fmtNum(v){
    if(v === null || v === undefined || v === '') return '—';
    return typeof v === 'number' ? vnd.format(v) : String(v);
  }

  function cell(value, kind){
    if(kind === 'change') return deltaEl(typeof value === 'number' ? value : null);
    if(kind === 'link'){
      const [text, url] = Array.isArray(value) ? value : [value, ''];
      if(!url) return text ?? '—';
      const a = el('a', null, text); a.href = url; a.target = '_blank'; a.rel = 'noopener';
      return a;
    }
    if(kind === 'num') return fmtNum(value);
    return value ?? '—';
  }

  function table(headers, rows, numCols){
    const wrap = el('div', 'm-table-wrap');
    const t = el('table', 'm-table');
    const tr = el('tr');
    headers.forEach((h, i) => tr.appendChild(el('th', numCols.includes(i) ? 'num' : null, h)));
    const thead = el('thead'); thead.appendChild(tr); t.appendChild(thead);
    const tbody = el('tbody');
    rows.forEach(r => {
      const row = el('tr');
      r.forEach((c, i) => {
        const td = el('td', numCols.includes(i) ? 'num' : null);
        if(c instanceof Node) td.appendChild(c); else td.textContent = c ?? '—';
        row.appendChild(td);
      });
      tbody.appendChild(row);
    });
    t.appendChild(tbody); wrap.appendChild(t);
    return wrap;
  }

  /* ---- CSV export: every block can be downloaded as a spreadsheet. ---- */
  function csvOf(block){
    const q = v => { const s = Array.isArray(v) ? v[0] : (v ?? ''); return /[",\n]/.test(String(s)) ? `"${String(s).replace(/"/g, '""')}"` : String(s); };
    let rows = [];
    if(block.type === 'chart'){
      const dates = [...new Set(block.series.flatMap(s => s.points.map(p => p[0])))].sort();
      rows.push(['date', ...block.series.map(s => s.name)]);
      dates.forEach(d => rows.push([d, ...block.series.map(s => (s.points.find(p => p[0] === d) || [])[1] ?? '')]));
    } else if(block.type === 'tiles'){
      const dates = [...new Set(block.items.flatMap(i => (i.points || []).map(p => p[0])))].sort();
      rows.push(['date', ...block.items.map(i => i.label)]);
      dates.forEach(d => rows.push([d, ...block.items.map(i => ((i.points || []).find(p => p[0] === d) || [])[1] ?? '')]));
    } else if(block.type === 'table'){
      rows.push(block.columns.map(c => c.label));
      block.rows.forEach(r => rows.push(r));
    }
    return '﻿' + rows.map(r => r.map(q).join(',')).join('\n');
  }

  function downloadCsv(block, name){
    const url = URL.createObjectURL(new Blob([csvOf(block)], {type: 'text/csv;charset=utf-8'}));
    const a = el('a'); a.href = url; a.download = `${name}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function toolButton(label, title, onClick){
    const b = el('button', 'm-tool', label);
    b.type = 'button'; b.title = title; b.setAttribute('aria-label', title);
    b.addEventListener('click', onClick);
    return b;
  }

  /* ---- Full-screen view of one block, with a big chart. ---- */
  let dialog = null;
  function openLarge(section, block){
    if(!dialog){
      dialog = el('dialog', 'm-dialog');
      document.body.appendChild(dialog);
      dialog.addEventListener('click', e => { if(e.target === dialog) dialog.close(); });
      dialog.addEventListener('close', () => dialog.replaceChildren());
    }
    const head = el('div', 'm-dialog-head');
    head.append(el('h2', null, `${section.icon || ''} ${section.title}`.trim()),
      toolButton('CSV', 'Tải dữ liệu CSV', () => downloadCsv(block, section.id)),
      toolButton('✕', 'Đóng', () => dialog.close()));
    const body = el('div', 'm-dialog-body');
    dialog.replaceChildren(head, body);
    dialog.showModal();
    const height = Math.max(260, Math.min(window.innerHeight - 180, 640));
    if(block.type === 'tiles'){
      const series = block.items.map((it, i) => ({name: it.label, color: COLORS[i % COLORS.length], points: inRange(it.points)}));
      // Different scales (e.g. USD vs JPY) make one chart useless: draw each on its own.
      series.forEach(s => { body.appendChild(el('div', 'm-sub', s.name)); lineChart(body, [s], {height: 160, ariaLabel: s.name}); });
    } else if(block.type === 'chart'){
      const series = block.series.map((s, i) => ({name: s.name, color: COLORS[i % COLORS.length], points: inRange(s.points)}));
      body.appendChild(legend(series));
      lineChart(body, series, {height, ariaLabel: section.title});
    } else {
      renderBlock(body, section, block, true);
    }
  }

  function legend(series){
    const lg = el('div', 'legend');
    if(series.length < 2) return lg;
    series.forEach(s => { const it = el('span'); const k = el('span', 'key'); k.style.background = s.color; it.append(k, document.createTextNode(s.name)); lg.appendChild(it); });
    return lg;
  }

  /* ---- Blocks ---- */
  const RENDERERS = {
    chart(body, section, block){
      const series = block.series.map((s, i) => ({name: s.name, color: COLORS[i % COLORS.length], points: inRange(s.points)}));
      body.appendChild(legend(series));
      lineChart(body, series, {height: OPTS.compact ? 180 : 240, ariaLabel: section.title});
    },
    tiles(body, section, block){
      const grid = el('div', 'm-grid');
      body.appendChild(grid);
      block.items.forEach(it => {
        const tile = el('div', 'tile');
        tile.append(el('div', 't-label', it.label), el('div', 't-value', fmtNum(it.value)), deltaEl(it.change_pct, it.period || ''));
        grid.appendChild(tile);
        const pts = inRange(it.points);
        if(pts.length) lineChart(tile, [{name: it.label, points: pts}], {compact: true, ariaLabel: `${it.label} trend`});
      });
    },
    table(body, section, block, large){
      if(block.caption) body.appendChild(el('div', 'm-caption', block.caption));
      const rows = large ? block.rows : block.rows.slice(0, OPTS.compact ? 6 : 10);
      const numCols = block.columns.map((c, i) => (c.kind === 'num' || c.kind === 'change') ? i : -1).filter(i => i >= 0);
      body.appendChild(table(block.columns.map(c => c.label), rows.map(r => r.map((v, i) => cell(v, (block.columns[i] || {}).kind))), numCols));
      if(!large && rows.length < block.rows.length){
        body.appendChild(toolButton(`Xem tất cả ${block.rows.length} dòng`, 'Xem tất cả', () => openLarge(section, block)));
      }
    },
  };

  function renderBlock(body, section, block, large){
    const fn = RENDERERS[block.type];
    if(!fn){ console.warn('unknown block type', block.type); return; }
    const wrap = el('div', 'm-block');
    body.appendChild(wrap);
    if(!large){
      const tools = el('div', 'm-tools');
      tools.append(toolButton('CSV', 'Tải dữ liệu CSV', () => downloadCsv(block, section.id)));
      if(block.type !== 'table' || block.rows.length > 0) tools.append(toolButton('⤢', 'Phóng to', () => openLarge(section, block)));
      wrap.appendChild(tools);
    }
    fn(wrap, section, block, large);
  }

  // Cards are all placed first and filled afterwards: charts measure their
  // width when drawn, and the grid only settles once every card is in it.
  function renderSection(container, s){
    const card = el('div', 'm-card');
    card.id = `m-${s.id}`;
    card.appendChild(el('h2', null, `${s.icon || ''} ${s.title}`.trim()));
    const note = [s.note, s.as_of ? `cập nhật ${s.as_of}` : null].filter(Boolean).join(' · ');
    if(note) card.appendChild(el('p', 'm-note', note));
    const body = el('div', 'm-body');
    card.appendChild(body);
    container.appendChild(card);
    return () => {
      if(!s.ok) return emptyMsg(body, `Chưa có dữ liệu${s.reason ? ` (${s.reason})` : ''}.`);
      if(!(s.blocks || []).length) return emptyMsg(body, s.empty_text || 'Không có gì mới.');
      s.blocks.forEach(b => { try{ renderBlock(body, s, b); }catch(e){ console.error(s.id, e); } });
    };
  }

  function renderAll(){
    if(!SUMMARY) return;
    const when = SUMMARY.generated_at ? new Date(SUMMARY.generated_at).toLocaleString('vi-VN') : '—';
    if(OPTS.updated) OPTS.updated.textContent = `Cập nhật ${when} · làm mới mỗi 3 giờ`;
    const container = OPTS.sections;
    container.replaceChildren();
    // Bot health is for the morning email; the home page shows run status itself.
    const sections = (SUMMARY.sections || []).filter(s => s.id !== 'health');
    const only = OPTS.only ? sections.filter(s => OPTS.only.includes(s.id)) : sections;
    only.map(s => renderSection(container, s)).forEach(fill => fill());
  }

  function mount(opts){
    OPTS = opts || {};
    (OPTS.tabs || []).forEach(b => {
      b.setAttribute('aria-pressed', String(Number(b.dataset.range) === RANGE));
      b.addEventListener('click', () => {
        RANGE = Number(b.dataset.range);
        try{ localStorage.setItem('markets_range', RANGE); }catch(e){}
        OPTS.tabs.forEach(o => o.setAttribute('aria-pressed', String(o === b)));
        renderAll();
      });
    });
    let resizeTimer, lastW = window.innerWidth;
    window.addEventListener('resize', () => {
      if(window.innerWidth === lastW) return; // mobile address-bar show/hide changes only the height
      lastW = window.innerWidth;
      clearTimeout(resizeTimer); resizeTimer = setTimeout(renderAll, 150);
    });
    return fetch((OPTS.url || './data/summary.json') + '?_=' + Date.now())
      .then(r => { if(!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(data => { SUMMARY = data; renderAll(); return data; })
      .catch(e => {
        if(OPTS.updated) OPTS.updated.textContent =
          `Chưa có dữ liệu (${e.message}). Workflow Daily Summary tạo data/summary.json ở lần chạy đầu tiên.`;
      });
  }

  window.Markets = {mount, renderers: RENDERERS, csvOf};
})();
