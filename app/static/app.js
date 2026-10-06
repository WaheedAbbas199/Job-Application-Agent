/* Vanilla JS SPA. All dynamic text is inserted via textContent (XSS-safe). Token kept in sessionStorage. */ 
const API = '/api/v1'; 
const $ = (s) => document.querySelector(s); 
const S = { token: sessionStorage.getItem('jaa_token'), user: null }; 
 
function h(tag, props, ...kids) { 
  const el = document.createElement(tag); 
  for (const [k, v] of Object.entries(props || {})) { 
    if (k === 'class') el.className = v; 
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v); 
    else if (v !== false && v != null) el.setAttribute(k, v === true ? '' : v); 
  } 
  for (const c of kids.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : document.createTextNode(String(c))); 
  return el; 
} 
function toast(msg, bad) { const t = $('#toast'); t.textContent = msg; t.style.display = 'block'; t.style.background = bad ? 'var(--bad)' : ''; clearTimeout(toast.t); toast.t = setTimeout(() => (t.style.display = 'none'), 4000); } 
async function api(path, { method = 'GET', body, form } = {}) { 
  const headers = {}; if (S.token) headers.Authorization = 'Bearer ' + S.token; 
  if (body) headers['Content-Type'] = 'application/json'; 
  const r = await fetch(API + path, { method, headers, body: form || (body ? JSON.stringify(body) : undefined) }); 
  if (r.status === 204) return null; 
  const data = await r.json().catch(() => ({})); 
  if (r.status === 401 && S.token) { logout(true); throw new Error('Session expired'); } 
  if (!r.ok) throw new Error(data.error?.details ? data.error.details.map((d) => d.field + ': ' + d.message).join('; ') : data.error?.message || 'Request failed'); 
  return data; 
} 
const run = async (fn) => { try { return await fn(); } catch (e) { toast(e.message, true); } }; 
const pill = (t, c) => h('span', { class: 'pill ' + (c || '') }, t); 
const recClass = (r) => ({ Excellent: 'ok', Strong: 'ok', Good: 'ok', Weak: 'warn' }[r] || 'bad'); 
const fmt = (d) => (d ? new Date(d).toLocaleString() : ''); 
const loading = () => h('p', { class: 'muted' }, h('span', { class: 'spinner' }), ' Loading…'); 
const empty = (t) => h('div', { class: 'empty' }, t); 
async function poll(fn, done, tries = 40, ms = 1500) { for (let i = 0; i < tries; i++) { const r = await fn(); if (done(r)) return r; await new Promise((x) => setTimeout(x, ms)); } return null; } 
 
function logout(expired) { sessionStorage.removeItem('jaa_token'); S.token = null; S.user = null; if (expired) toast('Session expired, please sign in again', true); location.hash = '#/login'; } 
function nav() { 
  const cur = location.hash.split('/')[1] || ''; 
  const links = S.token ? [['dashboard', 'Dashboard'], ['profile', 'Profile'], ['resume', 'Resume'], ['jobs', 'Jobs'], ['applications', 'Applications'], ['analytics', 'Analytics'], ['notifications', 'Notifications'], ['settings', 'Settings']] : []; 
  $('#nav').replaceChildren(h('span', { class: 'brand' }, 'Job Application Agent'), 
    ...links.map(([k, l]) => h('a', { href: '#/' + k, class: cur === k ? 'active' : '', 'aria-current': cur === k ? 'page' : false }, l)), h('span', { class: 'sp' }), 
    S.token ? h('button', { class: 'sec', onclick: () => run(async () => { await api('/auth/logout', { method: 'POST' }); logout(); }) }, 'Log out') : h('a', { href: '#/login', class: 'btn' }, 'Sign in')); 
} 
 
/* ---------- pages ---------- */ 
const pages = {}; 
pages.landing = (m) => m.append(h('div', { class: 'hero' }, h('h1', {}, 'Find better jobs. Apply honestly.'), 
  h('p', { class: 'muted' }, 'Match your CV to real job postings, see your skill gaps, prepare truthful applications and stay in control: nothing is submitted without your approval.'), 
  h('a', { class: 'btn', href: '#/register' }, 'Get started'), ' ', h('a', { class: 'btn sec', href: '#/login' }, 'Sign in'))); 
 
function authPage(kind) { 
  return (m) => { 
    const err = h('p', { class: 'err', role: 'alert' }); 
    const email = h('input', { id: 'em', type: 'email', required: true, autocomplete: 'email' }); 
    const pw = h('input', { id: 'pw', type: 'password', required: true, minlength: kind === 'register' ? 10 : 1, autocomplete: kind === 'register' ? 'new-password' : 'current-password' }); 
    const btn = h('button', { type: 'submit' }, kind === 'register' ? 'Create account' : 'Sign in'); 
    const f = h('form', { class: 'card auth', onsubmit: async (e) => { e.preventDefault(); btn.disabled = true; err.textContent = ''; 
      try { 
        if (kind === 'register') await api('/auth/register', { method: 'POST', body: { email: email.value, password: pw.value } }); 
        const t = await api('/auth/login', { method: 'POST', body: { email: email.value, password: pw.value } }); 
        S.token = t.access_token; sessionStorage.setItem('jaa_token', S.token); location.hash = kind === 'register' ? '#/onboarding' : '#/dashboard'; 
      } catch (x) { err.textContent = x.message; } btn.disabled = false; } }, 
      h('h1', {}, kind === 'register' ? 'Create account' : 'Sign in'), h('label', { for: 'em' }, 'Email'), email, 
      h('label', { for: 'pw' }, 'Password' + (kind === 'register' ? ' (min 10 characters)' : '')), pw, err, h('p', {}, btn), 
      h('p', { class: 'muted' }, kind === 'register' ? h('a', { href: '#/login' }, 'Already registered? Sign in') : h('a', { href: '#/register' }, 'New here? Create an account'))); 
    m.append(f); 
  }; 
} 
pages.login = authPage('login'); pages.register = authPage('register'); 
 
pages.onboarding = (m) => m.append(h('div', { class: 'card' }, h('h1', {}, 'Welcome 👋'), 
  h('ol', {}, h('li', {}, 'Upload your CV on the ', h('a', { href: '#/resume' }, 'Resume page'), ' and apply it to your profile.'), 
    h('li', {}, 'Review your ', h('a', { href: '#/profile' }, 'Profile'), ' and set job preferences.'), 
    h('li', {}, 'Run discovery on the ', h('a', { href: '#/jobs' }, 'Jobs page'), '.')), 
  h('p', { class: 'muted' }, 'The system never invents skills or experience, and never submits an application without your explicit approval.'))); 
 
pages.dashboard = async (m) => { 
  m.append(h('h1', {}, 'Dashboard'), loading()); 
  const [o, apps, jobs, st] = await Promise.all([api('/analytics/overview'), api('/applications?page_size=5'), api('/jobs?page_size=5'), api('/analytics/strategy')]); 
  const stat = (v, l) => h('div', { class: 'card stat' }, h('b', {}, v ?? '—'), h('span', {}, l)); 
  m.replaceChildren(h('h1', {}, 'Dashboard'), h('div', { class: 'grid' }, stat(o.jobs_matched, 'Jobs matched'), stat(o.recommended_jobs, 'Recommended jobs'), stat(o.applications, 'Applications'), 
    stat(o.interviews, 'Interviews'), stat(o.offers, 'Offers'), stat(o.average_match_score, 'Avg match score'), stat(o.interview_rate == null ? null : o.interview_rate + '%', 'Interview rate')), 
    h('div', { class: 'two' }, 
      h('div', { class: 'card' }, h('h2', {}, 'Top skill gaps'), o.common_missing_skills.length ? o.common_missing_skills.map(([s, n]) => pill(`${s} (${n})`, 'warn')) : empty('No data yet')), 
      h('div', { class: 'card' }, h('h2', {}, 'Career strategy'), st.recommendations.length ? h('ul', {}, st.recommendations.map((r) => h('li', {}, r))) : h('p', { class: 'muted' }, st.message))), 
    h('div', { class: 'card' }, h('h2', {}, 'Top recommended jobs'), jobs.items.length ? jobs.items.map(jobCard) : empty('No jobs yet. Run discovery on the Jobs page.')), 
    h('div', { class: 'card' }, h('h2', {}, 'Recent applications'), apps.length ? apps.map((a) => h('div', { class: 'row sb' }, h('a', { href: '#/application/' + a.id }, `${a.job?.title} — ${a.job?.company}`), pill(a.status))) : empty('No applications yet'))); 
}; 
 
function listEditor(title, items, fields, newItem) { 
  const wrap = h('div', {}); const rows = items.map((x) => ({ ...x })); 
  const draw = () => wrap.replaceChildren(h('h2', {}, title), ...rows.map((r, i) => h('div', { class: 'card' }, 
    ...fields.map((f) => [h('label', {}, f.label), (f.area ? h('textarea', { 'aria-label': f.label }) : h('input', { 'aria-label': f.label })), ]).map(([l, inp], j) => { const f = fields[j]; inp.value = f.list ? (r[f.k] || []).join(', ') : r[f.k] || ''; inp.oninput = () => (r[f.k] = f.list ? inp.value.split(',').map((s) => s.trim()).filter(Boolean) : inp.value); return [l, inp]; }).flat(), 
    h('p', {}, h('button', { type: 'button', class: 'sec', onclick: () => { rows.splice(i, 1); draw(); } }, 'Remove')))), 
    h('button', { type: 'button', class: 'sec', onclick: () => { rows.push(newItem()); draw(); } }, '+ Add')); 
  draw(); wrap.get = () => rows.filter((r) => Object.values(r).some((v) => (Array.isArray(v) ? v.length : v))); return wrap; 
} 
pages.profile = async (m) => { 
  m.append(h('h1', {}, 'Profile'), loading()); const p = await api('/profile'); const pr = p.preferences || {}; 
  const inp = (id, label, val, type = 'text') => [h('label', { for: id }, label), h('input', { id, type, value: val ?? '' })]; 
  const sel = h('select', { id: 'remote' }, ['any', 'remote', 'hybrid', 'onsite'].map((o) => h('option', { value: o, selected: (pr.remote_type || 'any') === o }, o))); 
  const exp = listEditor('Experience', p.experiences, [{ k: 'title', label: 'Title' }, { k: 'company', label: 'Company' }, { k: 'start', label: 'Start' }, { k: 'end', label: 'End' }, { k: 'description', label: 'Description', area: 1 }], () => ({})); 
  const edu = listEditor('Education', p.education, [{ k: 'degree', label: 'Degree' }, { k: 'institution', label: 'Institution' }, { k: 'year', label: 'Year' }], () => ({})); 
  const prj = listEditor('Projects', p.projects, [{ k: 'name', label: 'Name' }, { k: 'description', label: 'Description', area: 1 }, { k: 'technologies', label: 'Technologies (comma separated)', list: 1 }], () => ({})); 
  const v = (id) => $('#' + id).value.trim(); const list = (id) => v(id).split(',').map((s) => s.trim()).filter(Boolean); 
  m.replaceChildren(h('h1', {}, 'Profile'), h('form', { class: 'card', onsubmit: (e) => { e.preventDefault(); run(async () => { 
    await api('/profile', { method: 'PUT', body: { full_name: v('fn') || null, headline: v('hl') || null, location: v('loc') || null, summary: v('sum') || null, years_experience: v('yrs') ? Number(v('yrs')) : null, 
      skills: list('skills'), certifications: p.certifications, languages: p.languages, experiences: exp.get(), education: edu.get(), projects: prj.get(), 
      preferences: { roles: list('roles'), locations: list('locs'), remote_type: $('#remote').value, min_salary: v('sal') ? Number(v('sal')) : null, industries: [], employment_types: [] } } }); 
    toast('Profile saved'); }); } }, 
    ...inp('fn', 'Full name', p.full_name), ...inp('hl', 'Headline', p.headline), ...inp('loc', 'Location', p.location), ...inp('yrs', 'Years of experience', p.years_experience, 'number'), 
    h('label', { for: 'sum' }, 'Summary'), h('textarea', { id: 'sum' }, p.summary || ''), ...inp('skills', 'Skills (comma separated)', p.skills.join(', ')), 
    h('h2', {}, 'Job preferences'), ...inp('roles', 'Target roles (comma separated)', (pr.roles || []).join(', ')), ...inp('locs', 'Preferred locations', (pr.locations || []).join(', ')), 
    h('label', { for: 'remote' }, 'Work type'), sel, ...inp('sal', 'Minimum salary (yearly)', pr.min_salary, 'number'), exp, edu, prj, h('p', {}, h('button', { type: 'submit' }, 'Save profile')))); 
}; 
 
pages.resume = async (m) => { 
  const box = h('div', {}); const file = h('input', { type: 'file', id: 'cv', accept: '.pdf,.docx,.txt' }); 
  const refresh = async () => { box.replaceChildren(loading()); const rs = await api('/resumes'); 
    box.replaceChildren(...(rs.length ? rs.map((r) => h('div', { class: 'card' }, h('div', { class: 'row sb' }, h('b', {}, r.filename), pill(r.status || 'pending', r.status === 'parsed' ? 'ok' : r.status === 'failed' ? 'bad' : 'warn')), 
      r.error ? h('p', { class: 'err' }, r.error) : null, 
      h('div', { class: 'row' }, h('button', { class: 'sec', onclick: () => run(async () => { const d = await api('/resumes/' + r.id); showParsed(d); }) }, 'View parsed data'), 
        h('button', { disabled: r.status !== 'parsed', onclick: () => run(async () => { await api(`/resumes/${r.id}/apply-to-profile`, { method: 'POST' }); toast('Merged into profile'); }) }, 'Apply to profile'), 
        h('button', { class: 'danger', onclick: () => confirm('Delete this CV permanently?') && run(async () => { await api('/resumes/' + r.id, { method: 'DELETE' }); refresh(); }) }, 'Delete')))) : [empty('No CV uploaded yet')])); }; 
  const parsed = h('div', {}); const showParsed = (d) => parsed.replaceChildren(h('div', { class: 'card' }, h('h2', {}, 'Parsed CV (' + (d.parser || '?') + ')'), h('p', { class: 'muted' }, 'Only facts found in your CV are extracted; unknown fields stay empty.'), h('pre', { class: 'doc' }, JSON.stringify(d.structured, null, 2)))); 
  m.append(h('h1', {}, 'Resume'), h('div', { class: 'card' }, h('label', { for: 'cv' }, 'Upload CV (PDF, DOCX or TXT, max 5 MB)'), file, h('p', {}, h('button', { onclick: () => run(async () => { 
    if (!file.files[0]) return toast('Choose a file first', true); const fd = new FormData(); fd.append('file', file.files[0]); 
    const r = await api('/resumes', { method: 'POST', form: fd }); toast(r.duplicate ? 'This CV was already uploaded' : 'Uploaded, parsing…'); await refresh(); 
    if (!r.duplicate) { await poll(() => api('/resumes/' + r.id), (x) => x.status !== 'pending', 20, 1000); refresh(); } }) }, 'Upload'))), box, parsed); 
  refresh(); 
}; 
 
function jobCard(j) { 
  const mt = j.match; 
  return h('div', { class: 'card' }, h('div', { class: 'row sb' }, h('div', {}, h('b', {}, j.title), h('div', { class: 'muted' }, [j.company, j.location, j.remote_type, j.salary_min ? `${j.salary_currency || ''} ${j.salary_min}-${j.salary_max}` : null, j.posted_at ? fmt(j.posted_at) : null].filter(Boolean).join(' · '))), 
    mt ? h('div', {}, h('span', { class: 'score' }, mt.overall_score), pill(mt.recommendation, recClass(mt.recommendation))) : null), 
    mt ? h('div', {}, (mt.matched_skills || []).slice(0, 8).map((s) => pill(s, 'ok')), (mt.missing_skills || []).slice(0, 6).map((s) => pill('missing: ' + s, 'bad'))) : null, 
    h('div', { class: 'row' }, h('a', { class: 'btn sec', href: '#/job/' + j.id }, 'View / Analyze'), 
      h('button', { class: 'sec', onclick: () => run(async () => { const r = await api(`/jobs/${j.id}/save`, { method: 'POST' }); toast('Saved'); location.hash = '#/application/' + r.application_id; }) }, 'Save'), 
      h('button', { onclick: () => run(async () => { const r = await api(`/jobs/${j.id}/save`, { method: 'POST' }).catch(async () => (await api('/applications?page_size=100')).find((a) => a.job_id === j.id)); const id = r.application_id || r.id; await api(`/applications/${id}/prepare`, { method: 'POST' }).catch(() => {}); location.hash = '#/application/' + id; }) }, 'Prepare application'))); 
} 
pages.jobs = async (m) => { 
  const q = h('input', { id: 'q', placeholder: 'e.g. machine learning engineer', 'aria-label': 'Search query' }); const loc = h('input', { id: 'l', placeholder: 'Location (optional)', 'aria-label': 'Location' }); 
  const status = h('p', { class: 'muted', 'aria-live': 'polite' }); const list = h('div', {}); 
  const refresh = async () => { list.replaceChildren(loading()); const d = await api('/jobs?page_size=50'); list.replaceChildren(...(d.items.length ? d.items.map(jobCard) : [empty('No jobs yet. Run discovery above (requires a saved profile).')])); }; 
  m.append(h('h1', {}, 'Job search'), h('div', { class: 'card' }, h('div', { class: 'two' }, h('div', {}, h('label', { for: 'q' }, 'Search'), q), h('div', {}, h('label', { for: 'l' }, 'Location'), loc)), 
    h('p', {}, h('button', { id: 'go', onclick: () => run(async () => { const b = $('#go'); b.disabled = true; status.textContent = 'Discovering and matching…'; 
      try { const r = await api('/agents/discover', { method: 'POST', body: { query: q.value || null, location: loc.value || null, limit: 30 } }); 
        const done = await poll(() => api('/agents/runs/' + r.id), (x) => !['queued', 'running'].includes(x.status), 80, 1500); 
        if (!done) status.textContent = 'Still running; check back shortly.'; else if (done.status !== 'completed') { status.textContent = ''; toast(done.error || 'Run failed', true); } else { const s = done.result.stats; status.textContent = `Fetched ${s.fetched} (${s.new} new), recommended ${s.recommended}.` + (done.result.warnings.length ? ' Warnings: ' + done.result.warnings.join('; ') : ''); } 
      } finally { b.disabled = false; } refresh(); }) }, 'Discover & match jobs')), status), list); refresh(); 
}; 
pages.job = async (m, id) => { 
  m.append(loading()); let j = await api('/jobs/' + id); const a = j.analysis; 
  const mt = await api('/matches/job/' + id).catch(() => null); 
  const draw = (mt) => m.replaceChildren(h('a', { href: '#/jobs' }, '← Jobs'), h('h1', {}, j.title), h('p', { class: 'muted' }, `${j.company} · ${j.location || 'n/a'} · ${j.remote_type}`), 
    h('div', { class: 'row' }, h('button', { onclick: () => run(async () => { draw(await api('/matches/job/' + id, { method: 'POST' })); }) }, mt ? 'Re-run match' : 'Analyze match'), j.application_url ? h('a', { class: 'btn sec', href: j.application_url, target: '_blank', rel: 'noopener noreferrer' }, 'Original posting') : null), 
    mt ? h('div', { class: 'card' }, h('h2', {}, 'Match analysis'), h('p', {}, h('span', { class: 'score' }, mt.overall_score), ' ', pill(mt.recommendation, recClass(mt.recommendation)), ' ', pill('confidence ' + mt.confidence)), 
      ...[['Skills', 'skill_score'], ['Experience', 'experience_score'], ['Role', 'role_score'], ['Education', 'education_score'], ['Location', 'location_score'], ['Salary', 'salary_score'], ['Preferences', 'preference_score']].map(([l, k]) => h('div', {}, h('div', { class: 'row sb' }, h('span', {}, l), h('span', {}, mt[k])), h('div', { class: 'bar' }, h('i', { style: `width:${mt[k]}%` })))), 
      h('h2', {}, 'Skills'), mt.matched_skills.map((s) => pill(s, 'ok')), mt.missing_skills.map((s) => pill('missing: ' + s, 'bad')), mt.weak_skills.map((s) => pill('weak evidence: ' + s, 'warn')), 
      h('h2', {}, 'Why'), h('p', {}, mt.explanation.llm_summary || mt.explanation.why), (mt.explanation.risks || []).length ? h('ul', {}, mt.explanation.risks.map((r) => h('li', {}, r))) : null) : null, 
    a ? h('div', { class: 'card' }, h('h2', {}, 'Extracted requirements'), h('p', {}, 'Required: ', a.required_skills.map((s) => pill(s))), h('p', {}, 'Preferred: ', a.preferred_skills.map((s) => pill(s))), h('p', { class: 'muted' }, `Min experience: ${a.min_years_experience ?? 'n/a'} · Seniority: ${a.seniority ?? 'n/a'} · Education: ${a.education_level ?? 'n/a'}`), a.injection_suspected ? h('p', { class: 'err' }, '⚠ This posting contains instruction-like text, which was ignored.') : null) : null, 
    h('div', { class: 'card' }, h('h2', {}, 'Description'), h('pre', { class: 'doc' }, j.description))); 
  draw(mt); 
}; 
 
pages.applications = async (m) => { 
  m.append(h('h1', {}, 'Applications'), loading()); const apps = await api('/applications?page_size=100'); 
  m.replaceChildren(h('h1', {}, 'Applications'), ...(apps.length ? apps.map((a) => h('div', { class: 'card row sb' }, h('div', {}, h('a', { href: '#/application/' + a.id }, h('b', {}, a.job?.title)), h('div', { class: 'muted' }, `${a.job?.company} · updated ${fmt(a.updated_at)}`)), h('div', {}, a.match_score != null ? pill('match ' + a.match_score) : null, pill(a.status)))) : [empty('No applications yet. Save a job to start.')])); 
}; 
const STATUSES = ['Saved', 'Recommended', 'Preparing', 'Ready for Review', 'Assessment', 'Interview', 'Rejected', 'Offer', 'Withdrawn', 'Archived']; 
pages.application = async (m, id) => { 
  const draw = async () => { 
    const a = await api('/applications/' + id); const docs = await api('/documents/application/' + id); 
    const latest = {}; docs.forEach((d) => { if (!latest[d.type] || d.version > latest[d.type].version) latest[d.type] = d; }); 
    const sel = h('select', { 'aria-label': 'Status' }, STATUSES.map((s) => h('option', { value: s, selected: s === a.status }, s))); 
    const notes = h('textarea', { 'aria-label': 'Notes' }, a.notes || ''); 
    const docCard = (d) => { const ta = h('textarea', { style: 'min-height:220px', 'aria-label': d.type }, d.content); 
      return h('div', { class: 'card' }, h('div', { class: 'row sb' }, h('b', {}, `${d.type.replace('_', ' ')} · v${d.version}`), h('span', {}, pill(d.status, d.status === 'approved' ? 'ok' : d.status === 'rejected' ? 'bad' : ''), pill(d.generator))), 
        d.unsupported_skills.length ? h('p', { class: 'err', role: 'alert' }, '⚠ Mentions skills not in your profile: ' + d.unsupported_skills.join(', ')) : null, ta, 
        h('div', { class: 'row' }, h('button', { class: 'sec', onclick: () => run(async () => { await api('/documents/' + d.id, { method: 'PATCH', body: { content: ta.value } }); toast('Saved as new version'); draw(); }) }, 'Save edit'), 
          h('button', { onclick: () => run(async () => { const go = (ack) => api(`/documents/${d.id}/approve`, { method: 'POST', body: { acknowledge_unsupported: ack } }); 
            try { await go(false); } catch (e) { if (!/not in your profile/.test(e.message) || !confirm(e.message + '\n\nApprove anyway? (Only if this is truthful.)')) throw e; await go(true); } 
            toast('Approved. You can now click “Mark as applied”.'); draw(); }) }, 'Approve'), 
          h('button', { class: 'sec', onclick: () => run(async () => { await api(`/documents/${d.id}/reject`, { method: 'POST' }); draw(); }) }, 'Reject'), 
          ['resume', 'cover_letter', 'recruiter_message'].includes(d.type) ? h('button', { class: 'sec', onclick: () => run(async () => { await api(`/documents/application/${id}/regenerate`, { method: 'POST', body: { type: d.type } }); draw(); }) }, 'Regenerate') : null)); }; 
    const iv = h('div', {}); const hasApproved = docs.some((d) => d.status === 'approved'); 
    m.replaceChildren(h('a', { href: '#/applications' }, '← Applications'), h('h1', {}, a.job?.title), h('p', { class: 'muted' }, `${a.job?.company} · ${a.job?.location || ''}`), 
      h('div', { class: 'card' }, h('div', { class: 'row' }, pill(a.status), a.match_score != null ? pill('match ' + a.match_score) : null, h('a', { href: '#/job/' + a.job_id }, 'Match analysis'), a.job?.application_url ? h('a', { href: a.job.application_url, target: '_blank', rel: 'noopener noreferrer' }, 'Original posting') : null), 
        h('div', { class: 'row' }, sel, h('button', { class: 'sec', onclick: () => run(async () => { await api(`/applications/${id}/status`, { method: 'POST', body: { status: sel.value, expected_version: a.version } }); draw(); }) }, 'Update status'), 
          h('button', { onclick: () => run(async () => { await api(`/applications/${id}/prepare`, { method: 'POST' }); toast('Preparing documents…'); await poll(() => api('/applications/' + id), (x) => x.status !== 'Preparing', 30, 1000); draw(); }) }, 'Prepare documents'), 
          h('button', { class: 'danger', disabled: !hasApproved || ['Applied', 'Assessment', 'Interview', 'Rejected', 'Offer', 'Withdrawn', 'Archived'].includes(a.status), title: hasApproved ? '' : 'Approve at least one document first', onclick: () => confirm('Mark as applied? This confirms you reviewed and approved your documents and will submit them yourself on the employer site.') && run(async () => { const r = await api(`/applications/${id}/apply`, { method: 'POST', body: { confirm: true } }); toast(r.next_step); draw(); }) }, 'Mark as applied')), hasApproved || a.status === 'Applied' ? null : h('p', { class: 'muted' }, 'To mark this as applied, first review your documents below and click “Approve” on at least one (e.g. your resume).')), 
      Object.keys(latest).length ? Object.values(latest).map(docCard) : empty('No documents yet. Click “Prepare documents”.'), 
      h('div', { class: 'card' }, h('h2', {}, 'Notes & follow-up'), notes, h('p', {}, h('button', { class: 'sec', onclick: () => run(async () => { await api('/applications/' + id, { method: 'PATCH', body: { notes: notes.value } }); toast('Notes saved'); }) }, 'Save notes'), ' ', ['Applied', 'Assessment', 'Interview'].includes(a.status) ? h('button', { class: 'sec', onclick: () => run(async () => { await api(`/documents/application/${id}/followup`, { method: 'POST' }); toast('Follow-up draft created (nothing is sent automatically)'); draw(); }) }, 'Draft follow-up message') : null)), 
      ['Interview', 'Assessment'].includes(a.status) ? h('div', { class: 'card' }, h('h2', {}, 'Interview preparation'), h('button', { onclick: () => run(async () => { const r = await api('/interviews/application/' + id, { method: 'POST' }); showInterview(iv, r.content); }) }, 'Generate preparation'), iv) : null, 
      h('div', { class: 'card' }, h('h2', {}, 'History'), h('ul', { class: 'timeline' }, a.events.map((e) => h('li', {}, `${fmt(e.timestamp)}: ${e.old_status || '∅'} → ${e.new_status}`))))); 
    if (['Interview', 'Assessment'].includes(a.status)) api('/interviews/application/' + id).then((r) => showInterview(iv, r.content)).catch(() => {}); 
  }; 
  m.append(loading()); await draw(); 
}; 
function showInterview(el, c) { 
  const qs = (t, arr) => h('div', {}, h('h2', {}, t), h('ol', {}, arr.map((q) => h('li', {}, typeof q === 'string' ? q : q.question)))); 
  el.replaceChildren(h('p', { class: 'muted' }, c.company_research.note), qs('Role questions', c.role_questions), qs('Technical questions', c.technical_questions), qs('Behavioral questions', c.behavioral_questions), qs('Project questions', c.project_questions), qs('Mock interview sequence', c.mock_interview), 
    c.skill_gaps_to_prepare.length ? h('p', {}, 'Gaps to prepare: ', c.skill_gaps_to_prepare.map((s) => pill(s, 'warn'))) : null, h('p', { class: 'muted' }, c.note)); 
} 
pages.analytics = async (m) => { 
  m.append(h('h1', {}, 'Analytics'), loading()); const [o, s] = await Promise.all([api('/analytics/overview'), api('/analytics/strategy')]); 
  const kv = (k, v) => h('div', { class: 'row sb' }, h('span', { class: 'muted' }, k), h('b', {}, v ?? '—')); 
  m.replaceChildren(h('h1', {}, 'Analytics'), h('div', { class: 'two' }, h('div', { class: 'card' }, kv('Applications', o.applications), kv('Applied', o.applied), kv('Interviews', o.interviews), kv('Offers', o.offers), kv('Rejections', o.rejections), kv('Interview rate', o.interview_rate == null ? null : o.interview_rate + '%'), kv('Offer rate', o.offer_rate == null ? null : o.offer_rate + '%'), kv('Average match score', o.average_match_score)), 
    h('div', { class: 'card' }, h('h2', {}, 'By status'), Object.keys(o.by_status).length ? Object.entries(o.by_status).map(([k, v]) => kv(k, v)) : empty('No data'))), 
    h('div', { class: 'card' }, h('h2', {}, 'Common missing skills'), o.common_missing_skills.length ? o.common_missing_skills.map(([k, n]) => pill(`${k} (${n})`, 'warn')) : empty('No data')), 
    h('div', { class: 'card' }, h('h2', {}, 'Best-performing roles & locations (interviews)'), o.best_performing_roles.map(([k, n]) => pill(`${k}: ${n}`)), o.best_performing_locations.map(([k, n]) => pill(`${k}: ${n}`)), !o.best_performing_roles.length ? empty('No interviews yet') : null), 
    h('div', { class: 'card' }, h('h2', {}, 'Career strategy'), s.recommendations.length ? h('ul', {}, s.recommendations.map((r) => h('li', {}, r))) : h('p', { class: 'muted' }, s.message))); 
}; 
pages.notifications = async (m) => { 
  m.append(h('h1', {}, 'Notifications'), loading()); const ns = await api('/notifications'); 
  m.replaceChildren(h('h1', {}, 'Notifications'), ...(ns.length ? ns.map((n) => h('div', { class: 'card row sb' }, h('div', {}, h('b', {}, n.message), h('div', { class: 'muted' }, fmt(n.created_at)), n.application_id ? h('a', { href: '#/application/' + n.application_id }, 'Open application') : null), n.read ? pill('read') : h('button', { class: 'sec', onclick: () => run(async () => { await api(`/notifications/${n.id}/read`, { method: 'POST' }); pages.notifications(m.replaceChildren() || m); }) }, 'Mark read'))) : [empty('Nothing here')])); 
}; 
pages.settings = async (m) => { 
  const me = await api('/auth/me'); const pw = h('input', { type: 'password', id: 'dp', autocomplete: 'current-password' }); 
  m.append(h('h1', {}, 'Settings'), h('div', { class: 'card' }, h('p', {}, 'Signed in as ', h('b', {}, me.email)), h('h2', {}, 'Delete account'), h('p', { class: 'muted' }, 'Permanently deletes your profile, CVs, applications and documents.'), 
    h('label', { for: 'dp' }, 'Confirm password'), pw, h('p', {}, h('button', { class: 'danger', onclick: () => confirm('This cannot be undone. Delete everything?') && run(async () => { await api('/auth/me', { method: 'DELETE', body: { password: pw.value } }); logout(); toast('Account deleted'); }) }, 'Delete my account')))); 
}; 
 
/* ---------- router ---------- */ 
async function render() { 
  const [, name = '', arg] = location.hash.split('/'); const m = $('#main'); m.replaceChildren(); nav(); 
  const open = ['', 'login', 'register']; if (!S.token && !open.includes(name)) { location.hash = '#/login'; return; } 
  if (S.token && ['', 'login', 'register'].includes(name)) { location.hash = '#/dashboard'; return; } 
  const page = pages[name || 'landing']; if (!page) return m.append(empty('Page not found')); 
  try { await page(m, arg); } catch (e) { m.replaceChildren(h('div', { class: 'card err', role: 'alert' }, 'Error: ' + e.message)); } 
  m.focus(); 
} 
addEventListener('hashchange', render); render(); 