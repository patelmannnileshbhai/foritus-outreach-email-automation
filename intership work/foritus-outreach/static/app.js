/* ForITus Outreach Desk – front end (vanilla JS, no build step, no external JS) */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function api(path, opts = {}) {
  const o = { method: opts.method || 'GET', headers: {} };
  if (opts.json !== undefined) { o.body = JSON.stringify(opts.json); o.headers['Content-Type'] = 'application/json'; }
  if (opts.form) o.body = opts.form;
  const r = await fetch(path, o);
  let data = null; try { data = await r.json(); } catch { }
  if (!r.ok) { const e = new Error((data && data.error) || r.statusText); e.data = data; throw e; }
  return data;
}
function toast(msg, err = false) {
  const t = document.createElement('div'); t.className = 'toast' + (err ? ' err' : ''); t.textContent = msg;
  $('#toasts').appendChild(t); setTimeout(() => t.remove(), err ? 6000 : 3200);
}
const guard = fn => async (...a) => { try { return await fn(...a); } catch (e) { toast(e.message, true); } };

const ICON = {
  settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/></svg>',
  block: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/></svg>',
  arrow: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>',
  spark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/></svg>',
};

/* ------------------------------------------------------------------ state & routing */
const S = { state: null, route: 'overview', leads: [], sel: new Set(), emails: [], emailTab: 'draft', emailId: null, researchId: null, jobPoll: null, leadFilter: { q: '', status: '' } };
const ROUTES = [
  { id: 'overview', n: '00', label: 'Overview', title: 'The desk, <em>at a glance</em>', sub: 'Everything moving through your outreach pipeline, today.' },
  { id: 'leads', n: '01', label: 'Leads', title: 'Who are we <em>writing to?</em>', sub: 'Import from CSV, Excel or a Google Sheet. Rows are validated, normalised and de-duplicated.' },
  { id: 'research', n: '02', label: 'Research', title: 'Know the company <em>first</em>', sub: 'Websites are read, industries inferred and every claim is logged as evidence with its source.' },
  { id: 'desk', n: '03', label: 'Review desk', title: 'Read it like <em>they will</em>', sub: 'Every email is quality-checked against its evidence. Nothing leaves without your approval.' },
  { id: 'outbox', n: '04', label: 'Send', title: 'Out the <em>door</em>, carefully', sub: 'Daily limits, duplicate guards, opt-out checks, retries. History is kept for every message.' },
  { id: 'track', n: '05', label: 'Track', title: 'What came <em>back</em>', sub: 'Replies are detected and classified. Follow-ups are drafted for you — and approved by you.' },
  { id: 'optouts', n: '', label: 'Do-not-contact', title: 'The <em>no</em> list', sub: 'Anyone here is blocked from every future send. Unsubscribe links and "stop" replies land here automatically.', foot: 'block' },
  { id: 'settings', n: '', label: 'Settings', title: 'Dials &amp; <em>wiring</em>', sub: 'Operational limits are editable here. Secrets live only in your .env file.', foot: 'settings' },
];
const R = id => ROUTES.find(r => r.id === id);

function go(id) { location.hash = '#/' + id; }
window.addEventListener('hashchange', () => render());

async function refreshState() { S.state = await api('/api/state'); renderRail(); return S.state; }

function renderRail() {
  const st = S.state; const c = id => {
    if (!st) return '';
    const e = st.emails;
    return ({
      leads: st.leads.total, research: st.leads.researched, desk: e.draft || 0, outbox: e.approved || 0,
      track: st.tracking.replied || (st.due_followups || 0), optouts: st.tracking.optouts
    })[id] ?? '';
  };
  const hotMap = { desk: (st?.emails.draft || 0) > 0, outbox: (st?.emails.approved || 0) > 0 };
  const main = ROUTES.filter(r => !r.foot).map(r => `
    <a class="step ${S.route === r.id ? 'on' : ''}" href="#/${r.id}"><span class="dot">${r.n}</span><span class="lbl">${r.label}</span><span class="cnt ${hotMap[r.id] ? 'hot' : ''}">${c(r.id)}</span></a>`).join('');
  const foot = ROUTES.filter(r => r.foot).map(r => `
    <a class="step ${S.route === r.id ? 'on' : ''}" href="#/${r.id}">${ICON[r.foot]}<span class="lbl">${r.label}</span></a>`).join('');
  const cf = st?.config;
  const chip = cf ? `<div class="mode-chip">
     <div>AI <em class="${cf.llm_available ? 'ok' : 'warn'}">${cf.llm_available ? esc(cf.llm.split(':')[0]) : 'offline composer'}</em></div>
     <div>DELIVERY <em>${cf.send_mode === 'outbox' ? '.eml outbox' : cf.smtp_configured ? 'smtp' : 'smtp ✗'}</em></div>
     <div>TEST MODE <em class="${cf.test_mode ? 'ok' : 'warn'}">${cf.test_mode ? 'on' : 'off'}</em></div></div>` : '';
  $('#rail').innerHTML = `
    <div class="brand"><b>For<i>IT</i>us</b></div><div class="brand-sub">Outreach Desk</div>
    <nav class="steps">${main}</nav>
    <div class="rail-foot">${foot}${chip}</div>`;
}

function renderTop() {
  const r = R(S.route);
  $('#topbar').innerHTML = `<div><div class="eyebrow">${r.n ? 'Stage ' + r.n + ' · ' : ''}${r.label}</div><h1 class="title">${r.title}</h1><p class="sub">${r.sub}</p></div><div class="actions" id="topActions"></div>`;
}

async function render() {
  const id = (location.hash.replace('#/', '') || 'overview').split('?')[0];
  S.route = R(id) ? id : 'overview';
  closeDrawer();
  renderTop();
  const v = $('#view'); v.classList.remove('view'); void v.offsetWidth; v.classList.add('view');
  try {
    await refreshState();
    await PAGES[S.route]();
  } catch (e) { toast(e.message, true); }
  window.scrollTo(0, 0);
}

/* ------------------------------------------------------------------ small components */
const fmtTime = iso => { if (!iso) return ''; const d = new Date(iso); return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); };
const fmtDT = iso => { if (!iso) return '—'; const d = new Date(iso); return d.toLocaleDateString([], { day: '2-digit', month: 'short' }) + ' ' + fmtTime(iso); };
const host = u => { try { return new URL(u).host.replace(/^www\./, ''); } catch { return u || '—'; } };
const pill = (s, label) => `<span class="pill ${esc(s)}">${esc((label || s || '').replace('_', ' '))}</span>`;
const scoreEl = (s, l) => `<span class="score ${esc(l || 'cold')}" title="Lead score ${s}">${s ?? 0}</span>`;
function ring(score, blocking) {
  const c = blocking ? 'var(--rose)' : score >= 85 ? 'var(--lime)' : score >= 70 ? 'var(--amber)' : 'var(--vermilion)';
  return `<div class="ring" style="--p:${score};--c:${c}"><b>${score}</b></div>`;
}
function countUp(root = document) {
  $$('[data-count]', root).forEach(el => {
    const to = +el.dataset.count, t0 = performance.now(), d = 700;
    const f = t => { const p = Math.min(1, (t - t0) / d); el.textContent = Math.round(to * (1 - Math.pow(1 - p, 3))); if (p < 1) requestAnimationFrame(f); };
    requestAnimationFrame(f);
  });
}
function openDrawer(html) { const d = $('#drawer'); d.innerHTML = `<button class="btn sm ghost x" onclick="closeDrawer()">Close ✕</button>${html}`; d.classList.add('open'); d.setAttribute('aria-hidden', 'false'); }
function closeDrawer() { const d = $('#drawer'); d.classList.remove('open'); d.setAttribute('aria-hidden', 'true'); }
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });

/* ------------------------------------------------------------------ job tray */
function runJob(job, title, onDone) {
  const tray = $('#tray'); tray.hidden = false;
  clearInterval(S.jobPoll);
  const draw = j => {
    const pct = j.total ? Math.round(100 * j.done / j.total) : (j.status === 'running' ? 8 : 100);
    tray.innerHTML = `<h4><span>${esc(title)}</span><span>${j.status === 'running' ? (j.total ? j.done + '/' + j.total : '…') : j.status === 'done' ? 'done' : 'error'}</span></h4>
      <div class="progress"><i style="width:${pct}%"></i></div>
      <div class="log">${j.log.slice(-6).map(esc).join('<br>') || 'starting…'}</div>
      ${j.status === 'running' ? `<div style="margin-top:10px"><button class="btn sm" onclick="api('/api/jobs/${j.id}/stop',{method:'POST'})">Stop</button></div>` : ''}`;
  };
  draw(job);
  S.jobPoll = setInterval(async () => {
    const j = await api('/api/jobs/' + job.id).catch(() => null); if (!j) return;
    draw(j);
    if (j.status !== 'running') {
      clearInterval(S.jobPoll);
      setTimeout(() => { tray.hidden = true; }, j.status === 'error' ? 7000 : 3500);
      if (j.status === 'error') toast(j.result?.error || 'Job failed', true);
      if (onDone) await onDone(j);
      await refreshState(); if (PAGES[S.route]) PAGES[S.route]();
    }
  }, 600);
}

/* ------------------------------------------------------------------ PAGES */
const PAGES = {};

/* ---------- overview ---------- */
PAGES.overview = async () => {
  const st = S.state, L = st.leads, E = st.emails, T = st.tracking, Q = st.quota;
  const ticks = Math.min(Q.limit, 50);
  const onTicks = Math.round(ticks * (Q.limit ? Q.sent_today / Q.limit : 0));
  // next best action
  let next = { big: 'All caught up.', btn: 'Review settings', to: 'settings', note: 'Nothing is waiting on you right now.' };
  if (L.total === 0) next = { big: 'Start by importing your leads.', btn: 'Import leads', to: 'leads', note: 'CSV, Excel or a shared Google Sheet.' };
  else if (L.total - L.researched > 0) next = { big: `Research ${L.total - L.researched} compan${L.total - L.researched > 1 ? 'ies' : 'y'}.`, btn: 'Open research', to: 'research', note: 'Websites are read and turned into evidence.' };
  else if (L.researched - L.drafted > 0) next = { big: `Draft ${L.researched - L.drafted} personalised email${L.researched - L.drafted > 1 ? 's' : ''}.`, btn: 'Generate drafts', to: 'research', note: 'Each one cites the facts it is based on.' };
  else if ((E.draft || 0) > 0) next = { big: `${E.draft} draft${E.draft > 1 ? 's' : ''} waiting for your eyes.`, btn: 'Open review desk', to: 'desk', note: 'Edit, approve or reject.' };
  else if ((E.approved || 0) > 0) next = { big: `${E.approved} approved, ready to send.`, btn: 'Go to send', to: 'outbox', note: `${Q.remaining} slot${Q.remaining === 1 ? '' : 's'} left in today's limit.` };
  else if (st.due_followups > 0) next = { big: `${st.due_followups} follow-up${st.due_followups > 1 ? 's are' : ' is'} due.`, btn: 'Open tracking', to: 'track', note: 'No reply yet — draft a gentle nudge.' };
  const stages = [['Imported', L.total], ['Researched', L.researched], ['Drafted', L.drafted], ['Approved', (E.approved || 0) + (E.sent || 0) + (E.sending || 0)], ['Sent', E.sent || 0], ['Opened', T.opened], ['Replied', T.replied]];
  const max = Math.max(1, L.total);
  $('#view').innerHTML = `
  <div class="grid g-hero stagger">
    <div class="card">
      <h3>Today's quota <span class="mono">${Q.sent_today} of ${Q.limit} sent</span></h3>
      <div class="quota-num"><span data-count="${Q.sent_today}">0</span><small>/ ${Q.limit}</small></div>
      <div class="ticks">${Array.from({ length: ticks }, (_, i) => `<i class="${i < onTicks ? 'on' : ''}"></i>`).join('')}</div>
      <div class="small mute">${Q.remaining} remaining today · limit is configurable in Settings</div>
    </div>
    <div class="card next">
      <div><h3>Next best move ${ICON.spark.replace('<svg', '<svg width="16" height="16"')}</h3><div class="big">${esc(next.big)}</div><p class="small mute" style="margin:10px 0 0">${esc(next.note)}</p></div>
      <div><button class="btn primary" onclick="go('${next.to}')">${esc(next.btn)} ${ICON.arrow}</button></div>
    </div>
  </div>
  <div class="kpis stagger" style="margin-top:16px">
    <div class="kpi"><span>Leads</span><b data-count="${L.total}">0</b></div>
    <div class="kpi"><span>Sent</span><b data-count="${E.sent || 0}">0</b></div>
    <div class="kpi"><span>Open rate</span><b>${Math.round(T.open_rate * 100)}<small style="font-size:.5em">%</small></b></div>
    <div class="kpi"><span>Replies</span><b data-count="${T.replied}">0</b>${T.positive ? `<em>${T.positive} warm</em>` : ''}</div>
  </div>
  <div class="grid g-split" style="margin-top:16px">
    <div class="card"><h3>Pipeline funnel</h3><div class="funnel">${stages.map(([n, v]) => `
      <div class="frow"><span>${n}</span><div class="bar"><i style="width:${Math.round(100 * v / max)}%"></i></div><span class="n">${v}</span></div>`).join('')}</div>
      <div style="margin-top:20px"><h3>Lead temperature</h3>${tempBar(st.scores)}</div></div>
    <div class="card"><h3>Last 14 days <span class="legend"><span><i style="background:var(--vermilion)"></i>sent</span><span><i style="background:var(--lime)"></i>opened</span><span><i style="background:var(--sky)"></i>replies</span></span></h3>${chart(st.series)}</div>
  </div>
  <div class="grid g-split" style="margin-top:16px">
    <div class="card"><h3>Activity</h3><div class="feed">${st.recent.length ? st.recent.map(ev => `
      <div class="row"><span class="t">${fmtTime(ev.ts)}</span><span><b>${esc(ev.company || '—')}</b> <span class="mute small">${esc(ev.meta || '')}</span></span><span class="evt ${esc(ev.type)}">${esc(ev.type)}</span></div>`).join('') : '<div class="empty"><b>Quiet so far</b>Events appear here as the pipeline runs.</div>'}</div></div>
    <div class="card"><h3>System</h3>${sysRows(st.config)}</div>
  </div>`;
  countUp($('#view'));
};
function tempBar(sc) {
  const h = sc.hot || 0, w = sc.warm || 0, c = sc.cold || 0, t = Math.max(1, h + w + c);
  return `<div style="display:flex;height:14px;border-radius:7px;overflow:hidden;gap:2px">
   <i style="flex:${h};background:var(--vermilion)"></i><i style="flex:${w};background:var(--amber)"></i><i style="flex:${c};background:var(--sky)"></i></div>
   <div class="legend" style="margin-top:10px"><span>${h} hot</span><span>${w} warm</span><span>${c} cold</span></div>`;
}
function sysRows(cf) {
  const row = (k, v, ok) => `<div style="display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px solid var(--line)"><span class="mute">${k}</span><span class="mono" style="color:${ok === false ? 'var(--amber)' : ok ? 'var(--lime)' : 'var(--bone)'}">${v}</span></div>`;
  return row('AI provider', cf.llm_available ? esc(cf.llm) : 'none → offline composer', cf.llm_available) +
    row('Delivery', cf.send_mode === 'outbox' ? '.eml outbox (nothing leaves this machine)' : (cf.smtp_configured ? 'SMTP configured' : 'SMTP missing'), cf.send_mode === 'outbox' ? true : cf.smtp_configured) +
    row('Test mode', cf.test_mode ? `on · ${cf.test_allowlist} allowlisted` : 'OFF — real recipients allowed', cf.test_mode) +
    row('Reply detection', cf.imap_configured ? 'IMAP configured' : 'manual log only', cf.imap_configured) +
    row('Follow-up cadence', cf.followups.length ? 'day ' + cf.followups.join(' → ') : 'off', true);
}
function chart(series) {
  const W = 620, H = 190, pad = 26, n = series.length, max = Math.max(3, ...series.map(s => Math.max(s.sent, s.opens, s.replies)));
  const bw = (W - pad * 2) / n, y = v => H - 24 - (H - 48) * v / max;
  let g = '';
  for (let i = 0; i <= 3; i++) { const v = Math.round(max * i / 3), yy = y(v); g += `<line x1="${pad}" x2="${W - pad}" y1="${yy}" y2="${yy}" stroke="#2a2720"/><text x="2" y="${yy + 3}">${v}</text>`; }
  const bars = series.map((s, i) => `<rect x="${pad + i * bw + bw * .18}" y="${y(s.sent)}" width="${bw * .64}" height="${H - 24 - y(s.sent)}" rx="3" fill="#ff5a36" opacity=".9"><title>${s.day}: ${s.sent} sent</title></rect>`).join('');
  const line = (k, col) => `<polyline fill="none" stroke="${col}" stroke-width="2.2" stroke-linejoin="round" points="${series.map((s, i) => `${pad + i * bw + bw / 2},${y(s[k])}`).join(' ')}"/>` + series.map((s, i) => s[k] ? `<circle cx="${pad + i * bw + bw / 2}" cy="${y(s[k])}" r="3.4" fill="${col}"/>` : '').join('');
  const lbl = series.map((s, i) => i % 3 === 0 ? `<text x="${pad + i * bw + bw / 2}" y="${H - 6}" text-anchor="middle">${s.day.slice(5)}</text>` : '').join('');
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${g}${bars}${line('opens', '#d4f06a')}${line('replies', '#7cc7ff')}${lbl}</svg>`;
}

/* ---------- leads ---------- */
PAGES.leads = async () => {
  const f = S.leadFilter;
  S.leads = await api(`/api/leads?q=${encodeURIComponent(f.q)}&status=${f.status}`);
  const total = S.state.leads.total;
  $('#view').innerHTML = `
  <div class="grid g-split stagger">
    <div class="card">
      <h3>Import <span class="mono mute">CSV · XLSX · Google Sheet</span></h3>
      <div class="dropzone" id="drop"><b>Drop a file here</b><span class="mute">or click to browse — columns: Name, Email, Designation, Company, Website, Country</span>
        <input type="file" id="file" accept=".csv,.xlsx,.xlsm,.tsv" hidden></div>
      <div style="display:flex;gap:10px;margin-top:12px"><input type="url" id="sheet" placeholder="https://docs.google.com/spreadsheets/d/…  (shared: anyone with link)"><button class="btn" onclick="importSheet()">Import</button></div>
      <div class="tip">Sample file includes 10 real public companies across 8 countries. Replace the placeholder addresses with your authorised test inboxes before sending.</div>
      <div id="report"></div>
    </div>
    <div class="card"><h3>Quick start</h3>
      <p style="margin:0 0 14px;color:var(--bone-2)">No file handy? Load the bundled sample set and walk the whole pipeline in a minute.</p>
      <button class="btn primary" onclick="loadSample()">${ICON.plus} Load sample leads</button>
      <hr style="border:0;border-top:1px solid var(--line);margin:18px 0">
      <h3>What gets cleaned</h3>
      <div class="small mute" style="line-height:1.8">✓ Headers auto-mapped (“Client Name”, “E-mail”, “Company website”…)<br>✓ Emails validated · duplicates dropped<br>✓ Websites normalised to https://<br>✓ Countries unified (USA → United States)<br>✓ Opted-out addresses flagged on arrival</div>
    </div>
  </div>
  <div style="margin-top:22px" class="toolbar">
    <input type="search" id="q" class="grow" placeholder="Search name, company, email, country…" value="${esc(f.q)}">
    <select id="fstatus" style="width:auto"><option value="">All statuses</option>${['new', 'researched', 'drafted', 'approved', 'sent', 'replied', 'opted_out', 'bounced'].map(s => `<option ${f.status === s ? 'selected' : ''}>${s}</option>`).join('')}</select>
    <button class="btn" id="bResearch">Research ${S.sel.size ? S.sel.size + ' selected' : 'new'}</button>
    <button class="btn primary" id="bDraft">Draft ${S.sel.size ? S.sel.size + ' selected' : 'all'} →</button>
  </div>
  ${S.leads.length ? `<div class="tablewrap"><table><thead><tr><th style="width:36px"><input type="checkbox" id="selAll"></th><th>Contact</th><th>Company</th><th>Country</th><th>Score</th><th>Status</th><th>Research</th><th>Email</th></tr></thead><tbody>
  ${S.leads.map(l => `<tr class="click" data-id="${l.id}">
    <td><input type="checkbox" class="sel" data-id="${l.id}" ${S.sel.has(l.id) ? 'checked' : ''}></td>
    <td><div class="l1">${esc(l.name || '—')}</div><div class="l2">${esc(l.designation || '')}${l.designation ? ' · ' : ''}${esc(l.email)}</div></td>
    <td><div class="l1">${esc(l.company)}</div><div class="l2">${esc(host(l.website))}</div></td>
    <td>${esc(l.country || '—')}</td><td>${scoreEl(l.score, l.score_label)}</td><td>${pill(l.status)}</td>
    <td>${l.research_status ? pill(l.research_status) : '<span class="mute">—</span>'}</td>
    <td>${l.last_email_status ? pill(l.last_email_status) : '<span class="mute">—</span>'}</td></tr>`).join('')}</tbody></table></div>` :
      `<div class="empty"><b>${total ? 'No leads match that filter' : 'No leads yet'}</b>${total ? 'Try clearing the search.' : 'Import a file above or load the sample set.'}</div>`}`;
  const drop = $('#drop'), file = $('#file');
  drop.onclick = () => file.click();
  file.onchange = () => file.files[0] && uploadFile(file.files[0]);
  ['dragover', 'dragenter'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', ev => ev.dataTransfer.files[0] && uploadFile(ev.dataTransfer.files[0]));
  let t; $('#q').oninput = e => { clearTimeout(t); t = setTimeout(() => { S.leadFilter.q = e.target.value; PAGES.leads().then(() => { const q = $('#q'); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }); }, 300); };
  $('#fstatus').onchange = e => { S.leadFilter.status = e.target.value; PAGES.leads(); };
  const selAll = $('#selAll'); if (selAll) selAll.onchange = () => { S.leads.forEach(l => selAll.checked ? S.sel.add(l.id) : S.sel.delete(l.id)); PAGES.leads(); };
  $$('tr.click').forEach(tr => tr.onclick = e => { if (e.target.closest('input')) return; showLead(+tr.dataset.id); });
  $$('.sel').forEach(cb => cb.onchange = () => { cb.checked ? S.sel.add(+cb.dataset.id) : S.sel.delete(+cb.dataset.id); $('#bResearch').textContent = 'Research ' + (S.sel.size ? S.sel.size + ' selected' : 'new'); $('#bDraft').textContent = 'Draft ' + (S.sel.size ? S.sel.size + ' selected' : 'all') + ' →'; });
  $('#bResearch').onclick = guard(() => startResearch(false));
  $('#bDraft').onclick = guard(() => startDraft());
};
function showReport(r) {
  $('#report').innerHTML = `<div class="report"><div class="stat"><b>${r.added}</b>added</div><div class="stat"><b>${r.duplicates.length}</b>duplicates skipped</div><div class="stat"><b>${r.invalid.length}</b>flagged</div>${r.opted_out.length ? `<div class="stat"><b>${r.opted_out.length}</b>on opt-out list</div>` : ''}</div>
  ${r.invalid.length ? `<div class="tip">${r.invalid.slice(0, 5).map(i => `row ${i.row}: ${esc(i.reason)} ${esc(i.email)}`).join('<br>')}</div>` : ''}`;
}
const uploadFile = guard(async f => { const fd = new FormData(); fd.append('file', f); const r = await api('/api/leads/import', { method: 'POST', form: fd }); toast(`Imported ${r.added} lead(s)`); await PAGES.leads(); showReport(r); await refreshState(); });
const importSheet = guard(async () => { const u = $('#sheet').value.trim(); if (!u) return toast('Paste a Google Sheet link first', true); const r = await api('/api/leads/import', { method: 'POST', json: { sheet_url: u } }); toast(`Imported ${r.added} lead(s)`); await PAGES.leads(); showReport(r); await refreshState(); });
const loadSample = guard(async () => { const r = await api('/api/leads/import', { method: 'POST', json: { sample: true } }); toast(r.added ? `Loaded ${r.added} sample leads` : 'Sample leads already loaded'); await PAGES.leads(); showReport(r); await refreshState(); });
async function startResearch(force) {
  const body = S.sel.size ? { ids: [...S.sel], force } : { all: true, force };
  const j = await api('/api/research', { method: 'POST', json: body });
  if (!j.total) return toast('Nothing to research — everything is already done');
  runJob(j, 'Researching companies');
}
async function startDraft(force = false) {
  const body = S.sel.size ? { ids: [...S.sel], force } : { all: true, force };
  const j = await api('/api/generate', { method: 'POST', json: body });
  runJob(j, 'Writing personalised emails', () => { toast('Drafts ready — opening the review desk'); setTimeout(() => go('desk'), 500); });
}
const showLead = guard(async id => {
  const d = await api('/api/leads/' + id); const l = d.lead;
  openDrawer(`<div class="eyebrow">${esc(l.country || '')} · ${pill(l.status)}</div>
   <h2 style="font:400 32px var(--serif);margin:8px 0 2px;letter-spacing:-.02em">${esc(l.name || l.email)}</h2>
   <div class="mute">${esc(l.designation || '')} at <b style="color:var(--bone)">${esc(l.company)}</b> · ${esc(l.email)}</div>
   <div class="card" style="margin:18px 0"><h3>Lead score <span>${scoreEl(l.score, l.score_label)}</span></h3>
     ${(l.score_detail || []).map(p => `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--line)"><span>${esc(p.factor)} <span class="mute small">· ${esc(p.note)}</span></span><span class="mono">+${p.points}</span></div>`).join('') || '<span class="mute">Run research to score this lead.</span>'}</div>
   ${d.research ? dossier(d.research, l) : '<div class="empty"><b>Not researched yet</b></div>'}
   ${d.emails.length ? `<div class="card" style="margin-top:16px"><h3>Emails</h3>${d.emails.map(e => `<div style="padding:8px 0;border-bottom:1px solid var(--line)"><div style="display:flex;justify-content:space-between;gap:10px"><b>${e.step ? 'Follow-up ' + e.step : 'First email'}</b>${pill(e.status)}</div><div class="small mute">${esc(e.subject)}</div></div>`).join('')}<button class="btn sm" style="margin-top:12px" onclick="go('desk')">Open in review desk</button></div>` : ''}
   ${d.replies.length ? `<div class="card" style="margin-top:16px"><h3>Replies</h3>${d.replies.map(r => `<div class="reply">${pill(r.classification)}<p>${esc(r.body.slice(0, 300))}</p></div>`).join('')}</div>` : ''}
   <div style="margin-top:20px;display:flex;gap:10px"><button class="btn danger sm" onclick="delLead(${l.id})">Delete lead</button></div>`);
});
const delLead = guard(async id => { if (!confirm('Delete this lead and its emails?')) return; await api('/api/leads/' + id, { method: 'DELETE' }); closeDrawer(); toast('Lead deleted'); render(); });

/* ---------- dossier (shared by drawer & research page) ---------- */
function dossier(r, lead) {
  const svc = S.state.config.services || {};
  if (r.status === 'failed') return `<div class="card dossier"><h3>Research</h3>${pill('failed')}<p style="margin-top:10px">Could not analyse the website: <b>${esc(r.error || 'unknown error')}</b></p><p class="small mute">Emails for this lead are generated in "light" mode — no site-specific claims — and flagged for manual review.</p>${(r.facts || []).map(f => `<div class="fact"><span class="fid">${f.id}</span>${esc(f.text)}</div>`).join('')}</div>`;
  const ind = r.industry_detail || {}; const conf = Math.round((r.confidence || 0) * 100);
  return `<div class="card dossier">
    <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:center"><div class="eyebrow">${esc(r.industry || 'Industry unclear')}${ind.confidence ? ' · ' + Math.round(ind.confidence * 100) + '% match' : ''}</div>
      <div style="display:flex;gap:10px;align-items:center">${pill(r.status)}<span class="small mute">confidence ${conf}%</span><div class="conf"><i style="width:${conf}%"></i></div></div></div>
    <div class="quote">${esc(r.summary || '—')}</div>
    ${r.offerings?.length ? `<h3>Offerings spotted</h3><div>${r.offerings.map(o => `<span class="chip">${esc(o)}</span>`).join('')}</div>` : ''}
    <h3 style="margin-top:18px">Opportunities for ForITus ${r.llm_used ? `<span class="mono" style="color:var(--lime)">refined by ${esc(r.llm_used.split(':')[0])}</span>` : '<span class="mono">rule-based</span>'}</h3>
    ${(r.opportunities || []).map(o => `<div class="opp"><div><div class="dots">${[1, 2, 3].map(i => `<i class="${i <= o.strength ? 'on' : ''}"></i>`).join('')}</div></div>
       <div><b>${esc(svc[o.service] || o.service)}</b><p>${esc(o.rationale)}</p>${o.evidence.map(e => `<span class="fid">${e}</span>`).join('')}</div></div>`).join('') || '<p class="mute">No clear opportunity found.</p>'}
    <h3 style="margin-top:18px">Evidence ledger <span class="mono">every claim traces here</span></h3>
    <div class="ledger"><table><tbody>${(r.facts || []).map(f => `<tr><td style="width:44px"><span class="fid">${f.id}</span></td><td>${esc(f.text)}${f.inferred ? ' <span class="mute small">(inferred)</span>' : ''}</td><td style="width:140px"><a class="src" href="${esc(f.source)}" target="_blank" rel="noopener">${esc(host(f.source))}</a></td></tr>`).join('')}</tbody></table></div>
    <h3 style="margin-top:18px">Pages read</h3>${(r.pages || []).map(p => `<div class="small"><a class="src" href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.url)}</a> <span class="mute">· ${esc(p.title)}</span></div>`).join('')}
  </div>`;
}

/* ---------- research ---------- */
PAGES.research = async () => {
  const leads = await api('/api/leads'); S.leads = leads;
  const done = leads.filter(l => l.research_status).length;
  $('#topActions').innerHTML = `<button class="btn" id="rAgain">Re-run all</button><button class="btn primary" id="rRun">Research ${leads.length - done} pending</button><button class="btn lime" id="rDraft">Draft emails →</button>`;
  $('#rRun').onclick = guard(() => { S.sel.clear(); return startResearch(false); });
  $('#rAgain').onclick = guard(() => { S.sel.clear(); return startResearch(true); });
  $('#rDraft').onclick = guard(() => { S.sel.clear(); return startDraft(); });
  if (!leads.length) { $('#view').innerHTML = `<div class="empty"><b>No leads to research</b>Import leads first.<br><br><button class="btn primary" onclick="go('leads')">Go to leads</button></div>`; return; }
  if (!S.researchId || !leads.find(l => l.id === S.researchId)) S.researchId = (leads.find(l => l.research_status) || leads[0]).id;
  $('#view').innerHTML = `<div class="split"><div class="list" id="rlist">${leads.map(l => `
    <div class="li ${l.id === S.researchId ? 'on' : ''}" data-id="${l.id}"><div class="r1"><b>${esc(l.company)}</b>${l.research_status ? pill(l.research_status) : '<span class="pill new">pending</span>'}</div>
    <div class="small mute">${esc(l.industry || host(l.website) || '—')} · ${esc(l.country || '')}</div></div>`).join('')}</div><div id="rdetail"></div></div>`;
  $$('#rlist .li').forEach(el => el.onclick = () => { S.researchId = +el.dataset.id; $$('#rlist .li').forEach(x => x.classList.toggle('on', x === el)); showResearch(); });
  showResearch();
};
const showResearch = guard(async () => {
  const d = await api('/api/leads/' + S.researchId); const l = d.lead;
  $('#rdetail').innerHTML = `<div class="dossier"><h2>${esc(l.company)}</h2><div class="mute" style="margin:6px 0 16px">${l.website ? `<a class="src" href="${esc(l.website)}" target="_blank" rel="noopener">${esc(l.website)}</a> · ` : ''}${esc(l.country || '')} · ${esc(l.name || '')} ${l.designation ? '(' + esc(l.designation) + ')' : ''}</div>
    ${d.research ? dossier(d.research, l) : `<div class="empty"><b>Not researched yet</b><button class="btn primary" onclick="researchOne(${l.id})">Research this company</button></div>`}
    ${d.research ? `<div style="margin-top:14px"><button class="btn sm" onclick="researchOne(${l.id},true)">Re-run research</button></div>` : ''}</div>`;
});
const researchOne = guard(async (id, force) => { const j = await api('/api/research', { method: 'POST', json: { ids: [id], force: !!force } }); if (!j.total) return toast('Already researched'); runJob(j, 'Researching'); });

/* ---------- review desk ---------- */
const TABS = [['draft', 'Needs review'], ['approved', 'Approved'], ['rejected,blocked,failed', 'Held'], ['sent', 'Sent']];
PAGES.desk = async () => {
  S.emails = await api('/api/emails?status=' + S.emailTab);
  const counts = S.state.emails;
  $('#topActions').innerHTML = `<button class="btn" id="dAll">Approve all passing</button><button class="btn lime" onclick="go('outbox')">Go to send →</button>`;
  $('#dAll').onclick = guard(async () => { const r = await api('/api/emails/approve-all', { method: 'POST', json: {} }); toast(`${r.approved} approved${r.skipped ? ` · ${r.skipped} need a human look` : ''}`); await refreshState(); PAGES.desk(); });
  if (!S.emails.find(e => e.id === S.emailId)) S.emailId = S.emails[0]?.id || null;
  const tabCount = k => k.split(',').reduce((a, s) => a + (counts[s] || 0), 0);
  $('#view').innerHTML = `<div class="desk">
    <div><div class="tabs">${TABS.map(([k, l]) => `<button data-k="${k}" class="${S.emailTab === k ? 'on' : ''}">${l} ${tabCount(k)}</button>`).join('')}</div>
      <div class="list" id="elist">${S.emails.map(e => `<div class="li ${e.id === S.emailId ? 'on' : ''}" data-id="${e.id}"><div class="r1"><b>${esc(e.company)}</b><span class="score ${e.quality_score >= 85 ? 'cold' : e.quality_score >= 70 ? 'warm' : 'hot'}" style="width:30px;height:30px;font-size:11px">${e.quality_score}</span></div>
        <div class="small" style="color:var(--bone-2)">${esc(e.subject)}</div><div class="small mute">${e.step ? 'Follow-up ' + e.step : 'First email'} · ${esc(e.region || '')} · ${esc((e.generator || '').split(':')[0])}</div></div>`).join('') || '<div class="empty"><b>Nothing here</b>Drafts appear after you generate emails.</div>'}</div></div>
    <div id="letter"></div><div class="side" id="dside"></div></div>`;
  $$('.tabs button').forEach(b => b.onclick = () => { S.emailTab = b.dataset.k; S.emailId = null; PAGES.desk(); });
  $$('#elist .li').forEach(el => el.onclick = () => { S.emailId = +el.dataset.id; $$('#elist .li').forEach(x => x.classList.toggle('on', x === el)); showLetter(); });
  if (S.emailId) showLetter(); else { $('#letter').innerHTML = ''; $('#dside').innerHTML = ''; }
};
const showLetter = guard(async () => {
  const e = await api('/api/emails/' + S.emailId);
  const locked = ['sent', 'sending'].includes(e.status);
  const stamp = ['approved', 'sent', 'rejected', 'blocked', 'failed'].includes(e.status) ? `<div class="stamp ${e.status}">${e.status}</div>` : '';
  $('#letter').innerHTML = `<div class="letter-wrap"><div class="letter">${stamp}
    <div class="meta"><span>TO</span><input value="${esc(e.name || '')} <${esc(e.to_email)}>" disabled>
      <span>SUBJ</span><input class="subj" id="subj" value="${esc(e.subject)}" ${locked ? 'disabled' : ''}></div>
    <textarea id="body" ${locked ? 'disabled' : ''} spellcheck="true">${esc(e.body)}</textarea></div>
    <div class="tip" style="margin-top:12px"><span class="mono">{{UNSUB_URL}}</span> becomes a personal one-click opt-out link when sent · ${esc(e.language || '')} · generated by ${esc(e.generator || '')}</div>
    ${e.error ? `<div class="tip" style="color:var(--rose)">⚠ ${esc(e.error)}</div>` : ''}
    <div class="letter-actions">
      ${locked ? '' : `<button class="btn lime" id="aApprove">Approve ✓</button><button class="btn" id="aSave">Save edits</button><button class="btn" id="aRegen">${ICON.spark} Rewrite</button><button class="btn danger" id="aReject">Reject</button>`}
      ${e.status === 'approved' ? `<button class="btn" id="aUn">Move back to review</button>` : ''}
      ${['failed', 'blocked'].includes(e.status) ? `<button class="btn" id="aRetry">Re-queue</button>` : ''}
    </div></div>`;
  const q = e.quality || { score: 0, issues: [] };
  $('#dside').innerHTML = `
    <div class="card"><h3>Quality check</h3><div style="display:flex;gap:16px;align-items:center">${ring(q.score, q.blocking)}<div class="small mute">${q.stats ? `${q.stats.words} words · ${q.stats.subject_chars}-char subject · ${q.stats.facts_used} fact${q.stats.facts_used === 1 ? '' : 's'} cited` : ''}<br>${q.blocking ? '<b style="color:var(--rose)">Blocked — fix critical issues</b>' : q.score >= 85 ? '<b style="color:var(--lime)">Ready to approve</b>' : '<b style="color:var(--amber)">Review suggested</b>'}</div></div>
      <div style="margin-top:12px">${q.issues.length ? q.issues.map(i => `<div class="issue ${i.severity}"><i>${i.severity === 'critical' ? '✕' : i.severity === 'warn' ? '!' : 'i'}</i><span>${esc(i.msg)}</span></div>`).join('') : '<div class="issue good"><i>✓</i><span>No issues found: grounded, personal, compliant.</span></div>'}</div></div>
    <div class="card" style="margin-top:14px"><h3>Evidence behind this email</h3>${e.facts.length ? e.facts.map(f => `<div class="fact"><span class="fid">${f.id}</span>${esc(f.text)}<br><a class="src" href="${esc(f.source)}" target="_blank" rel="noopener">${esc(host(f.source))}</a></div>`).join('') : `<div class="small mute">${e.research_status === 'failed' ? 'Website could not be analysed, so this email makes no site-specific claims.' : 'No researched fact is cited.'}</div>`}</div>
    <div class="card" style="margin-top:14px"><h3>Send me a test copy</h3><div style="display:flex;gap:8px"><input type="email" id="testTo" placeholder="your-authorised@address.com"><button class="btn" id="aTest">Send</button></div><div class="tip">Only allowed for addresses in TEST_ALLOWLIST (or any, in .eml outbox mode).</div></div>`;
  const ta = $('#body'); const fit = () => { ta.style.height = 'auto'; ta.style.height = ta.scrollHeight + 'px'; }; fit(); ta.oninput = fit;
  const save = async () => { const r = await api('/api/emails/' + e.id, { method: 'PATCH', json: { subject: $('#subj').value, body: $('#body').value } }); return r; };
  if (!locked) {
    $('#aSave').onclick = guard(async () => { await save(); toast('Saved & re-checked'); await refreshState(); showLetter(); });
    $('#aApprove').onclick = guard(async () => {
      await save();
      try { await api(`/api/emails/${e.id}/approve`, { method: 'POST', json: {} }); }
      catch (err) { if (err.data?.can_override && confirm(err.message + '\n\nApprove anyway?')) await api(`/api/emails/${e.id}/approve`, { method: 'POST', json: { override: true } }); else throw err; }
      toast('Approved'); await refreshState(); PAGES.desk();
    });
    $('#aReject').onclick = guard(async () => { await api(`/api/emails/${e.id}/reject`, { method: 'POST' }); toast('Rejected'); await refreshState(); PAGES.desk(); });
    $('#aRegen').onclick = guard(async () => { await api(`/api/emails/${e.id}/regenerate`, { method: 'POST', json: {} }); toast('Rewritten'); await refreshState(); showLetter(); PAGES.desk(); });
  }
  if ($('#aUn')) $('#aUn').onclick = guard(async () => { await api(`/api/emails/${e.id}/unapprove`, { method: 'POST' }); await refreshState(); PAGES.desk(); });
  if ($('#aRetry')) $('#aRetry').onclick = guard(async () => { await api(`/api/emails/${e.id}/retry`, { method: 'POST' }); await refreshState(); PAGES.desk(); });
  $('#aTest').onclick = guard(async () => { const to = $('#testTo').value.trim(); const r = await api(`/api/emails/${e.id}/test-send`, { method: 'POST', json: { to } }); toast('Test copy sent via ' + r.via); });
});

/* ---------- outbox ---------- */
PAGES.outbox = async () => {
  const st = S.state, Q = st.quota, E = st.emails;
  const hist = await api('/api/history');
  $('#topActions').innerHTML = `<a class="btn" href="/api/history.csv">Export CSV</a>`;
  $('#view').innerHTML = `
  <div class="grid g-split stagger">
    <div class="card"><h3>Send queue <span class="mono">${st.config.test_mode ? 'test mode on' : 'LIVE'}</span></h3>
      <div class="gauge"><div class="quota-num" style="font-size:84px"><span data-count="${E.approved || 0}">0</span><small>approved</small></div>
      <div class="small mute" style="line-height:1.9">${Q.sent_today}/${Q.limit} sent today · <b style="color:var(--bone)">${Q.remaining}</b> left<br>Delay between sends: ${st.config.tunables.SEND_DELAY_SECONDS}s<br>Mode: ${st.config.send_mode === 'outbox' ? '.eml files in data/outbox/' : 'SMTP'}</div></div>
      <div class="ticks">${Array.from({ length: Math.min(Q.limit, 50) }, (_, i) => `<i class="${i < Math.round(Math.min(Q.limit, 50) * Q.sent_today / Math.max(1, Q.limit)) ? 'on' : ''}"></i>`).join('')}</div>
      <div style="display:flex;gap:10px;align-items:center;margin-top:16px"><button class="btn primary" id="bSend" ${(E.approved || 0) && Q.remaining ? '' : 'disabled'}>Send approved emails ${ICON.arrow}</button>
      <span class="small mute">${!(E.approved || 0) ? 'Approve drafts in the review desk first.' : !Q.remaining ? 'Daily limit reached. Resumes tomorrow.' : `Will send up to ${Math.min(E.approved, Q.remaining)} now.`}</span></div></div>
    <div class="card"><h3>Safety rails</h3><div class="small" style="line-height:2">
      <span class="fid">✓</span>Approval required for every email<br><span class="fid">✓</span>Duplicate guard: one email per lead per step<br><span class="fid">✓</span>Opt-out list checked at send time<br><span class="fid">✓</span>Test-mode recipient allowlist<br><span class="fid">✓</span>Retries (3×) for temporary errors, hard-fail on rejections<br><span class="fid">✓</span>One-click unsubscribe header + link</div></div>
  </div>
  <div class="h3" style="margin:26px 0 12px">History <span>${hist.length} message${hist.length === 1 ? '' : 's'}</span></div>
  ${hist.length ? `<div class="tablewrap"><table><thead><tr><th>When</th><th>Recipient</th><th>Subject</th><th>Status</th><th>Opens</th><th>Reply</th><th></th></tr></thead><tbody>
  ${hist.map(h => `<tr><td class="mono small">${fmtDT(h.sent_at || h.created_at)}</td><td><div class="l1">${esc(h.company)}</div><div class="l2">${esc(h.to_email)}</div></td>
    <td style="max-width:300px"><div class="l1" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(h.subject)}</div><div class="l2">${h.step ? 'follow-up ' + h.step : 'first email'}${h.attempts > 1 ? ' · ' + h.attempts + ' attempts' : ''}${h.error ? ' · <span style="color:var(--rose)">' + esc(h.error) + '</span>' : ''}</div></td>
    <td>${pill(h.status)}</td><td><span class="eye">${h.opens ? '👁 ' + h.opens : '<span class="mute">—</span>'}</span></td><td>${h.reply ? pill(h.reply) : '<span class="mute">—</span>'}</td>
    <td style="white-space:nowrap">${h.status === 'sent' ? `<a class="btn sm ghost" href="/api/emails/${h.id}/render?as=recipient" target="_blank" title="Opens the delivered HTML — the tracking pixel logs an open">Open as recipient ↗</a>` : ''}${['failed', 'blocked'].includes(h.status) ? `<button class="btn sm" onclick="retryMail(${h.id})">Re-queue</button>` : ''}</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty"><b>Nothing sent yet</b>Approved emails will be logged here with status, opens and replies.</div>'}`;
  countUp($('#view'));
  $('#bSend').onclick = guard(async () => { const j = await api('/api/send', { method: 'POST', json: {} }); runJob(j, 'Sending approved emails', jj => { const r = jj.result || {}; toast(`Sent ${r.sent || 0}${r.failed ? ' · ' + r.failed + ' failed' : ''}${r.blocked ? ' · ' + r.blocked + ' blocked' : ''}${r.aborted ? ' · stopped: ' + r.aborted : ''}`, !!r.aborted); }); });
};
const retryMail = guard(async id => { await api(`/api/emails/${id}/retry`, { method: 'POST' }); toast('Re-queued as approved'); render(); });

/* ---------- track ---------- */
PAGES.track = async () => {
  const [reps, due, hist] = await Promise.all([api('/api/replies'), api('/api/followups/due'), api('/api/history')]);
  const sentLeads = [...new Map(hist.filter(h => h.status === 'sent').map(h => [h.to_email, h])).values()];
  const st = S.state, T = st.tracking;
  $('#topActions').innerHTML = `<button class="btn" id="tImap">Check inbox (IMAP)</button>`;
  $('#tImap').onclick = guard(async () => { const r = await api('/api/replies/check', { method: 'POST' }); toast(`Scanned ${r.scanned} · matched ${r.matched}`); render(); });
  $('#view').innerHTML = `
  <div class="kpis stagger"><div class="kpi"><span>Sent</span><b>${T.sent}</b></div><div class="kpi"><span>Opened</span><b>${T.opened}</b><em>${Math.round(T.open_rate * 100)}%</em></div><div class="kpi"><span>Replied</span><b>${T.replied}</b><em>${Math.round(T.reply_rate * 100)}%</em></div><div class="kpi"><span>Opted out</span><b>${T.optouts}</b></div></div>
  <div class="grid g2" style="margin-top:16px">
    <div class="card"><h3>Replies <span class="mono">${reps.length}</span></h3>
      ${reps.length ? reps.map(r => `<div class="reply"><div style="display:flex;justify-content:space-between;gap:10px;align-items:center"><b>${esc(r.company || r.from_addr)}</b>${pill(r.classification)}</div><div class="small mute">${esc(r.from_addr)} · ${fmtDT(r.ts)}</div><p>${esc(r.body.slice(0, 400))}</p></div>`).join('') : '<div class="empty"><b>No replies yet</b>Replies are matched by Message-ID and sender, then classified.</div>'}
      <hr style="border:0;border-top:1px solid var(--line);margin:18px 0"><h3>Log a reply manually</h3>
      <select id="rFrom">${sentLeads.length ? sentLeads.map(h => `<option value="${esc(h.to_email)}">${esc(h.company)} — ${esc(h.to_email)}</option>`).join('') : '<option value="">(no sent emails yet)</option>'}</select>
      <div class="preset">${[['Interested', 'Thanks for reaching out, this sounds interesting. Can you send more details and pricing?'], ['Not interested', 'Thanks, but we are not interested at the moment.'], ['Stop', 'Please stop emailing me and remove me from your list.'], ['Out of office', 'Automatic reply: I am out of office until next Monday.']].map(([l, t]) => `<button class="btn sm ghost" data-t="${esc(t)}">${l}</button>`).join('')}</div>
      <textarea id="rBody" rows="3" placeholder="Reply text…"></textarea><div style="margin-top:10px"><button class="btn" id="rLog">Log reply</button></div></div>
    <div class="card"><h3>Follow-ups <span class="mono">cadence: day ${st.config.followups.join(' → ') || 'off'}</span></h3>
      <p style="margin:0 0 14px;color:var(--bone-2)">${due.length ? `<b>${due.length}</b> lead${due.length > 1 ? 's are' : ' is'} due a follow-up (no reply, not opted out).` : 'No follow-ups are due yet. Leads qualify after the first email has aged past the cadence.'}</p>
      ${due.map(d => `<div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--line)"><span>${esc(d.company)}</span><span class="mono small mute">step ${d.step} · ${d.age_days}d</span></div>`).join('')}
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:16px"><button class="btn primary" id="fPlan" ${due.length ? '' : 'disabled'}>Draft due follow-ups</button>
        <button class="btn" id="fForce" title="For demos: pretend the wait has passed">Demo: treat all sent as due</button></div>
      <div class="tip">Follow-ups go through the same review → approve → send gate. Replies and opt-outs cancel queued follow-ups automatically.</div>
      <hr style="border:0;border-top:1px solid var(--line);margin:18px 0"><h3>Tracking pixel &amp; links</h3>
      <div class="small mute" style="line-height:1.7">Opens are logged by a 1×1 pixel served from <span class="mono">${esc(st.config.tunables.BASE_URL)}</span>. For recipients on the internet, expose <b>only</b> <span class="mono">/t/</span> and <span class="mono">/u/</span> through a free tunnel (cloudflared / ngrok) and set BASE_URL. Admin routes stay local-only.</div></div>
  </div>`;
  $$('.preset button').forEach(b => b.onclick = () => $('#rBody').value = b.dataset.t);
  $('#rLog').onclick = guard(async () => { const r = await api('/api/replies/manual', { method: 'POST', json: { from: $('#rFrom').value, subject: 'Re: your note', body: $('#rBody').value } }); toast('Classified as: ' + r.classification); render(); });
  const plan = force => guard(async () => { const r = await api('/api/followups/plan', { method: 'POST', json: { force } }); toast(`${r.filter(x => x.email_id).length} follow-up draft(s) created`); await refreshState(); go('desk'); S.emailTab = 'draft'; });
  $('#fPlan').onclick = plan(false); $('#fForce').onclick = plan(true);
};

/* ---------- opt-outs ---------- */
PAGES.optouts = async () => {
  const rows = await api('/api/optouts');
  $('#view').innerHTML = `<div class="grid g-split"><div>${rows.length ? `<div class="tablewrap"><table><thead><tr><th>Address</th><th>Source</th><th>Reason</th><th>Added</th><th></th></tr></thead><tbody>
    ${rows.map(o => `<tr><td class="mono">${esc(o.email)}</td><td>${pill(o.source === 'link' ? 'sent' : o.source === 'reply' ? 'replied' : 'new', o.source)}</td><td class="mute">${esc(o.reason || '')}</td><td class="mono small">${fmtDT(o.created_at)}</td><td><button class="btn sm ghost" data-e="${esc(o.email)}">Remove</button></td></tr>`).join('')}</tbody></table></div>` : '<div class="empty"><b>Nobody has opted out</b>Unsubscribe-link clicks and “stop” replies are added here automatically.</div>'}</div>
    <div class="card"><h3>Add an address</h3><label class="f">Email<input type="email" id="oEmail" placeholder="person@company.com"></label><label class="f" style="margin-top:12px">Reason<input type="text" id="oReason" placeholder="optional"></label><div style="margin-top:14px"><button class="btn primary" id="oAdd">Block address</button></div>
    <div class="tip">Blocking cancels any pending drafts for that lead and prevents every future send.</div></div></div>`;
  $('#oAdd').onclick = guard(async () => { await api('/api/optouts', { method: 'POST', json: { email: $('#oEmail').value, reason: $('#oReason').value || 'added manually' } }); toast('Blocked'); render(); });
  $$('[data-e]').forEach(b => b.onclick = guard(async () => { await api('/api/optouts/' + encodeURIComponent(b.dataset.e), { method: 'DELETE' }); toast('Removed'); render(); }));
};

/* ---------- settings ---------- */
PAGES.settings = async () => {
  const t = S.state.config.tunables, cf = S.state.config;
  const num = (k, l, hint) => `<label class="f">${l}<input type="number" step="any" data-k="${k}" value="${esc(t[k])}"><small>${hint || ''}</small></label>`;
  const txt = (k, l, hint) => `<label class="f">${l}<input type="text" data-k="${k}" value="${esc(t[k])}"><small>${hint || ''}</small></label>`;
  const sw = (k, l, hint) => `<label class="switch"><input type="checkbox" data-k="${k}" ${t[k] ? 'checked' : ''}><span><b>${l}</b><br><span class="small mute">${hint}</span></span></label>`;
  $('#view').innerHTML = `<div class="grid g-split">
   <div class="card"><h3>Operational dials</h3><div class="grid g2">
     ${num('DAILY_LIMIT', 'Daily sending limit', 'Max emails per calendar day')}${num('SEND_DELAY_SECONDS', 'Delay between sends (s)', 'Be gentle with SMTP providers')}
     ${num('MIN_QUALITY_TO_APPROVE', 'Min quality to approve', 'Below this needs an explicit override')}${txt('FOLLOWUP_DAYS', 'Follow-up days', 'e.g. 3,7 = day 3 and day 7')}
     ${txt('SENDER_NAME', 'Sender name')}${txt('SENDER_TITLE', 'Sender title')}${txt('BASE_URL', 'Public base URL', 'For tracking pixel & unsubscribe link')}
     <label class="f">Delivery mode<select data-k="SEND_MODE"><option value="outbox" ${t.SEND_MODE === 'outbox' ? 'selected' : ''}>outbox — write .eml files (safe)</option><option value="smtp" ${t.SEND_MODE === 'smtp' ? 'selected' : ''}>smtp — really send</option></select></label></div>
     <div style="display:grid;gap:14px;margin-top:20px">${sw('TEST_MODE', 'Test mode', 'In SMTP mode only addresses in TEST_ALLOWLIST may receive email')}${sw('TRACK_OPENS', 'Track opens', 'Adds a 1×1 pixel to the HTML part')}</div>
     <div style="margin-top:20px"><button class="btn primary" id="sSave">Save settings</button></div></div>
   <div><div class="card"><h3>Wiring <span class="mono">from .env</span></h3>${sysRows(cf)}<div class="tip">Secrets (API keys, SMTP password) are read from <span class="mono">.env</span> only — never stored in the database or shown here. See README.</div></div>
   <div class="card" style="margin-top:16px"><h3>Danger zone</h3><p class="small mute" style="margin:0 0 12px">Delete all leads, emails, research and opt-outs from the local database.</p><button class="btn danger" id="sReset">Reset all data</button></div></div></div>`;
  $('#sSave').onclick = guard(async () => { const d = {}; $$('[data-k]').forEach(el => d[el.dataset.k] = el.type === 'checkbox' ? el.checked : el.value); await api('/api/settings', { method: 'PUT', json: d }); toast('Settings saved'); render(); });
  $('#sReset').onclick = guard(async () => { if (prompt('Type RESET to delete everything') !== 'RESET') return; await api('/api/reset', { method: 'POST', json: { confirm: 'RESET' } }); S.sel.clear(); toast('All data cleared'); render(); });
};

render();
