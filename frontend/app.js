const state = {runs:[], activity:[], run:null, target:null, recommendation:null, estimate:null, events:[], stream:null, step:1, exploration:50, limits:null, mode:'offline', filters:{agent:'',severity:'',stage:''}};
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const json = value => esc(JSON.stringify(value, null, 2));
const tag = value => `<span class="tag ${esc(value)}">${esc(value)}</span>`;
const date = value => new Date(value).toLocaleString();
const button = (action, label, cls='', data='') => `<button type="button" class="${cls}" data-action="${action}" ${data}>${label}</button>`;
const stat = (label, value, hint='') => `<div class="stat"><label>${label}</label><strong>${esc(value)}</strong><small>${esc(hint)}</small></div>`;
const empty = (title, text) => `<div class="empty"><strong>${title}</strong>${text}</div>`;
const heading = (title, text, actions='') => `<div class="page-heading"><div><div class="eyebrow">INTEGRATION ASSURANCE</div><h1>${title}</h1><p class="muted">${text}</p></div><div class="actions">${actions}</div></div>`;

async function api(path, method='GET', body) {
  const response = await fetch('/api'+path, {method, headers:{'Content-Type':'application/json'}, ...(body !== undefined ? {body:JSON.stringify(body)} : {})});
  const data = await response.json();
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
  return data;
}
function notice(error) {const el = $('#notice'); el.textContent = error.message || error; el.hidden = false;}
function clearNotice() {$('#notice').hidden = true;}
async function refreshRuns() {const [runs,activity]=await Promise.all([api('/runs'),api('/activity')]);state.runs=runs;state.activity=activity.events;}
function routeName() {return location.hash.slice(1) || 'dashboard';}
function tableRows(runs) {
  return runs.length ? `<div class="table-scroll"><table><thead><tr><th>Target / run</th><th>Started</th><th>Strategy</th><th>Tests</th><th>Assessment</th><th>Status</th><th></th></tr></thead><tbody>${runs.map(r=>`<tr><td><strong>${esc(r.target_name)}</strong><br><span class="run-id muted">${r.id.slice(0,8)}</span></td><td>${esc(date(r.created_at))}</td><td>${r.config.exploration}% explore</td><td>${r.completed}/${r.planned || '—'}</td><td>${esc(r.report?.assessment || 'Pending')}</td><td>${tag(r.status)}</td><td>${button('open-run','Open','',`data-id="${r.id}"`)}</td></tr>`).join('')}</tbody></table></div>` : empty('No runs yet','Configure a target or try the local demonstration.');
}
function dashboard() {
  const completed = state.runs.filter(r=>r.status==='completed');
  const failures = completed.reduce((n,r)=>n+(r.report?.counts.FAIL || 0),0);
  const requests = state.runs.reduce((n,r)=>n+(r.usage?.requests || 0),0);
  const latest = completed[0];
  const trend = completed.slice(0,8).reverse();
  return heading('Security overview','Repeatable evidence for the boundaries around your LLM.',button('try-demo','Try Demo','primary')+button('new-test','New test'))+
    `<div class="stats">${stat('Completed runs',completed.length,'Saved in this workspace')}${stat('Observed failures',failures,'Across completed runs')}${stat('Pending / active',state.runs.filter(r=>['created','running','paused'].includes(r.status)).length,'Execution queue')}${stat('Target requests',requests,'Includes failed attempts')}</div>
    <div class="grid two"><section class="panel"><h2>Latest assessment</h2>${latest ? `<div class="split-label"><strong>${esc(latest.target_name)}</strong>${tag(latest.report.assessment)}</div><p class="muted">${latest.report.counts.PASS} passed · ${latest.report.counts.FAIL} failed · ${latest.report.counts.ERROR} errors</p>${button('open-run','Review findings','',`data-id="${latest.id}"`)}`:empty('Awaiting evidence','Your first run will appear here.')}</section>
    <section class="panel"><h2>Observed failure trend</h2><p class="hint">Count per completed run; coverage can differ.</p>${trend.length?`<div class="mini-chart">${trend.map((r,i)=>`<div style="height:${Math.max(4,(r.report.counts.FAIL / Math.max(1,...trend.map(x=>x.report.counts.FAIL)))*85)}%" title="${esc(r.target_name)}: ${r.report.counts.FAIL} failures"><span>${i+1}</span></div>`).join('')}</div>`:empty('No trend available','Complete runs to compare observed outcomes.')}</section></div>
    <section class="panel flush"><div class="panel-heading"><h2>Recent runs</h2><a href="#history">View history →</a></div>${tableRows(state.runs.slice(0,6))}</section>
    <div class="grid two"><section class="panel"><h2>Resource consumption</h2><p><strong>$${state.runs.reduce((n,r)=>n+(r.usage?.cost_reserved_usd||0),0).toFixed(4)}</strong> reserved cost · ${state.runs.reduce((n,r)=>n+(r.usage?.tokens_observed||0),0).toLocaleString()} observed target tokens</p><p class="hint">Paid runs use your supplied pricing ceiling; actual provider invoices may differ.</p></section><section class="panel"><h2>Recent activity</h2>${state.activity.slice(0,4).map(e=>`<p><strong>${esc(e.agent)}</strong> · ${esc(e.decision)}<br><span class="hint">${esc(date(e.timestamp))}</span></p>`).join('')||'<p class="hint">No recorded actions yet.</p>'}</section></div>
    <div class="info-box">The local demo uses synthetic records and deterministic responses. Findings are based on real endpoint execution; they do not measure a production model's vulnerability rate.</div>`;
}
function targetForm() {
  const t = state.target;
  return heading('New security test','Configure the application, confirm scope, and review the budget.',button('try-demo','Try Demo')+button('import-example','Import example.json'))+
    `<div class="wizard-step"><span class="step">01 / TARGET</span><span class="muted">02 Clarification</span><span class="muted">03 Strategy & budget</span></div>
    <section class="panel"><h2>Target configuration</h2><div class="form-grid">
    <label class="field">Application name<input id="target-name" value="${esc(t?.application?.name || '')}" placeholder="Application name" required></label>
    <label class="field">Chat endpoint<input id="target-url" type="url" value="${esc(t?.adapter?.endpoint || '')}" placeholder="http://127.0.0.1:8001/api/chat"><span class="hint">Exact POST endpoint. Redirects are never followed.</span></label>
    <label class="field">Execution adapter<select id="target-kind"><option value="http" ${t?.adapter?.kind==='http'?'selected':''}>HTTP integration</option><option value="campushelp" ${t?.adapter?.kind==='campushelp'?'selected':''}>CampusHelp local demo</option></select></label>
    <label class="field">CampusHelp protection mode<select id="target-mode"><option value="weak" ${t?.adapter?.mode==='weak'?'selected':''}>Weak</option><option value="hardened" ${t?.adapter?.mode==='hardened'?'selected':''}>Hardened</option></select></label>
    <label class="field full">Purpose<input id="target-purpose" value="${esc(t?.application?.purpose || '')}" placeholder="What does this application do?"></label>
    <label class="field">Target model provider<input id="target-provider" value="${esc(t?.llm?.provider || 'Unknown')}"></label><label class="field">Target model / version<input id="target-model" value="${esc(t?.llm?.model_version || t?.llm?.model || 'Unknown')}"></label>
    <label class="field">Retrieval (RAG)<select id="target-rag"><option value="unknown" ${t?.integration?.rag_enabled==null?'selected':''}>Unknown</option><option value="yes" ${t?.integration?.rag_enabled===true?'selected':''}>Enabled</option><option value="no" ${t?.integration?.rag_enabled===false?'selected':''}>Disabled</option></select></label>
    <label class="field">Tool calling<select id="target-tools"><option value="unknown" ${t?.integration?.tools_enabled==null?'selected':''}>Unknown</option><option value="yes" ${t?.integration?.tools_enabled===true?'selected':''}>Enabled</option><option value="no" ${t?.integration?.tools_enabled===false?'selected':''}>Disabled</option></select></label>
    <label class="field">Conversation memory<select id="target-memory"><option value="unknown" ${t?.integration?.conversation_memory==null?'selected':''}>Unknown</option><option value="yes" ${t?.integration?.conversation_memory===true?'selected':''}>Enabled</option><option value="no" ${t?.integration?.conversation_memory===false?'selected':''}>Disabled</option></select></label>
    <label class="field">Target authentication variable<input id="target-auth-env" value="${esc(t?.adapter?.auth_env || '')}" placeholder="STAGING_TARGET_API_KEY"><span class="hint">Environment variable name only; leave blank for the demo.</span></label>
    <label class="field full">Architecture and adapter details (JSON)<textarea id="target-json" rows="15" spellcheck="false">${json(t || {application:{},llm:{provider:'Unknown',model:'Unknown'},integration:{},data_access:{},security_controls:{},known_components:{},previous_failures:[],testing_scope:{},adapter:{request_template:{message:'{input}',session_id:'{session}',max_tokens:'{max_tokens}'},response_path:'response',auth_env:''}})}</textarea><span class="hint">Preserved on import. Configure RAG, tools, memory, scope, request_template, response_path and an auth_env variable name. Never paste credentials.</span></label>
    <label class="field full">Import a target JSON file<input id="import-file" type="file" accept=".json,application/json"></label>
    <label class="check full"><input id="authorized" type="checkbox" ${t?.testing_scope?.authorized?'checked':''}> I am authorized to test this exact endpoint with synthetic, non-destructive inputs.</label>
    </div><div class="actions">${button('save-target','Continue to clarification','primary')}</div></section>`;
}
function clarificationForm(questions) {
  return heading('Clarify the testing context','Only authorization and exact target scope block execution.')+
    `<div class="wizard-step"><span class="step">02 / CLARIFICATION</span></div><section class="panel">${questions.length ? questions.map(q=>`<fieldset data-question="${q.id}" data-type="${q.type}"><legend>${esc(q.label)} ${q.essential?'· required':''}</legend>${q.type==='single' || q.type==='multiple' ? `<div class="choices">${q.options.map(o=>`<label class="check"><input type="${q.type==='single'?'radio':'checkbox'}" name="q-${q.id}" value="${esc(o)}">${esc(o)}</label>`).join('')}</div>` : q.type==='long'?`<textarea aria-label="${esc(q.label)}" rows="3"></textarea>`:`<input aria-label="${esc(q.label)}">`}</fieldset>`).join('') : `<div class="info-box">The supplied configuration already contains the essential context.</div>`}<div class="actions">${button('save-answers','Continue to strategy','primary')}${button('back-target','Edit target')}</div></section>`;
}
function strategyForm() {
  const rec = state.recommendation;
  return heading('Testing strategy & budget','Review the allocation and limits before any target requests are sent.')+
    `<div class="wizard-step"><span class="step">03 / REVIEW</span></div><div class="grid two"><section class="panel"><h2>Exploration / focused validation</h2>
    <div class="slider-labels"><div><strong id="explore-label">${state.exploration}%</strong><span>Exploration</span></div><div><strong id="exploit-label">${100-state.exploration}%</strong><span>Exploitation / retesting</span></div></div>
    <label for="exploration" class="hint">Proportion of testing scope allocated to unfamiliar risk areas</label><input id="exploration" type="range" min="0" max="100" value="${state.exploration}">
    <div id="exploration-warning" class="warning-box" ${state.exploration>65?'':'hidden'}>High exploration can substantially increase unique scenarios, prompts, tokens, model calls and execution time. Consider a lower level for your first run.</div>
    <div class="info-box"><strong>Recommended: ${rec.exploration}% Exploration / ${rec.exploitation}% Exploitation</strong><p>${esc(rec.explanation)}</p>${button('apply-recommendation','Apply recommendation')}</div>
    <table><thead><tr><th>Observable heuristic</th><th>Contribution</th></tr></thead><tbody>${rec.contributions.map(c=>`<tr><td>${esc(c.reason)}</td><td>${c.points>0?'+':''}${c.points}</td></tr>`).join('')}</tbody></table></section>
    <section class="panel"><h2>Execution limits</h2><label class="field">Agent mode<select id="agent-mode"><option value="offline" ${state.mode==='offline'?'selected':''}>Offline deterministic rules + bundled references</option><option value="live" ${state.mode==='live'?'selected':''}>Live shared model gateway + Tavily</option></select></label>
    <p class="hint">The target is separate from the platform's reasoning providers.</p><label class="field">Hard budget limits (JSON)<textarea id="limits" rows="16">${json(state.limits)}</textarea></label>
    <div class="actions">${button('estimate','Recalculate estimate')}</div><div id="estimate-output">${estimateView()}</div>
    <div class="actions">${button('start-run','Create & start authorized run','primary')}${button('back-target','Edit target')}</div></section></div>
    <details class="panel"><summary>Final target preview</summary><pre>${json(state.target)}</pre></details>`;
}
function estimateView() {
  const e = state.estimate;
  if (!e) return `<p class="hint">Recalculate the estimate after changing limits.</p>`;
  return `<div class="info-box"><strong>${e.tests} test cases · up to ${e.requests} requests</strong><p>~${e.tokens.toLocaleString()} reserved tokens · ~${e.seconds}s baseline runtime<br>Cost: ${e.cost_usd===null?'unavailable':'$'+e.cost_usd.toFixed(4)}<br>${esc(e.pricing)}</p></div>${e.violations.map(v=>`<div class="error-box">${esc(v)}</div>`).join('')}`;
}
function selector(options, id, selected, first='All') {return `<select id="${id}" aria-label="${id}"><option value="">${first}</option>${options.map(o=>`<option ${o===selected?'selected':''}>${esc(o)}</option>`).join('')}</select>`;}
function traceView() {
  const f = state.filters;
  return state.events.filter(e=>(!f.agent||e.agent===f.agent)&&(!f.severity||e.severity===f.severity)&&(!f.stage||e.stage===f.stage)).map(e=>`<article class="trace-entry"><header><strong>${esc(e.agent)}</strong>${tag(e.severity)}<time>${esc(date(e.timestamp))}</time></header><h3>${esc(e.decision)}</h3><p>${esc(e.explanation)}</p><small>${esc(e.stage)} · ${esc(e.provider)} / ${esc(e.model)} · fallback ${e.fallback?'yes':'no'}</small><details><summary>Evidence & context</summary><pre>${json({task:e.task,context:e.context_summary,evidence:e.evidence,confidence:e.confidence,result:e.result})}</pre></details></article>`).join('') || empty('No matching events','Recorded actions will appear as the workflow progresses.');
}
function live() {
  const r = state.run;
  if (!r) return heading('Live testing','Execution progress and auditable decision summaries.')+empty('Select or create a run','Use New test or open a run from history.');
  const done = r.evaluations.length;
  const controls=(r.status==='created'?button('start','Start run','primary'):'')+(r.status==='running'?button('pause','Pause'):'')+(['paused','failed','limited','interrupted'].includes(r.status)?button('resume','Resume'):'')+(!['completed','cancelled'].includes(r.status)?button('cancel','Cancel','danger'):'');
  return heading('Live testing',`${esc(r.target.application.name)} · ${r.id.slice(0,8)} · ${r.config.mode}`,controls)+
    `<div class="stats" id="live-stats">${liveStats(r)}</div>
    <section class="panel"><div class="split-label"><strong>${tag(r.status)}</strong><span>${done} completed · ${Math.max(0,r.cases.length-done)} remaining</span></div><progress value="${done}" max="${r.cases.length||1}" aria-label="Execution progress"></progress>${r.allocation?`<p class="hint">Planned request allocation: ${r.allocation.planned_exploration}% exploration / ${r.allocation.planned_exploitation}% retesting. Rounded to complete cases.</p>`:''}${r.error?`<div class="error-box">${esc(r.error)}</div>`:''}${r.report?`<p>${button('show-results','View results','primary')}</p>`:''}${['failed','limited','interrupted'].includes(r.status)?`<details><summary>Adjust hard limits before resuming</summary><label class="field">Explicit new limits (JSON)<textarea id="resume-limits" rows="12">${json(r.config.limits)}</textarea></label>${button('save-run-limits','Apply limits & resume')}</details>`:''}</section>
    <div class="grid two"><section class="panel"><h2>Test queue</h2>${r.cases.length?`<table><thead><tr><th>Test</th><th>Allocation</th><th>Status</th></tr></thead><tbody>${r.cases.map(c=>`<tr><td>${esc(c.title)}</td><td>${esc(c.strategy)}</td><td>${tag(r.evaluations.find(e=>e.test_id===c.id)?.classification||(r.active_tests?.includes(c.id)?'ACTIVE':'QUEUED'))}</td></tr>`).join('')}</tbody></table>`:empty('Preparing cases','Planning and generation run before target dispatch.')}</section>
    <section class="panel"><h2>Decision trace <span class="hint" id="trace-count">${state.events.length} recorded actions</span></h2><p class="hint">Concise audit summaries; no hidden chain of thought.</p><div class="trace-toolbar">${selector(['Clarification Agent','Planning Agent','Test Generation Agent','Execution Agent','Evaluation Agent','Reporting Agent','Recommendation Agent','LLM Gateway','Orchestrator'],'trace-agent',state.filters.agent,'All agents')}${selector(['info','warning','error','critical','high','medium','low'],'trace-severity',state.filters.severity,'All severities')}${selector(['clarification','planning','generation','execution','reporting'],'trace-stage',state.filters.stage,'All stages')}</div><div id="trace" class="trace">${traceView()}</div></section></div>`;
}
function liveStats(r) {
  return stat('Current stage',r.stage,r.status)+stat('Completed cases',r.evaluations.length+'/'+r.cases.length,'Recorded evaluations')+stat('Observed tokens',r.usage?.tokens_observed||0,'Target-reported usage')+stat('Reserved cost','$'+(r.usage?.cost_reserved_usd||0).toFixed(4),'Conservative dispatch ceiling');
}
function results() {
  const r = state.run, report = r?.report;
  if (!report) return heading('Results','Security findings grounded in observed behavior.')+empty('No report selected','Open a completed run from history.');
  return heading('Security assessment',`${esc(report.target)} · ${esc(report.status)} · ${esc(report.assessment)}`,`<a class="tag" href="/api/runs/${r.id}/report?format=json&download=true">Download JSON ↓</a><a class="tag" href="/api/runs/${r.id}/report?format=html&download=true">Download HTML ↓</a>`)+
    `<div class="stats">${stat('Passed',report.counts.PASS,'Secure behavior observed')}${stat('Failed',report.counts.FAIL,'Evidence-backed findings')}${stat('Inconclusive',report.counts.INCONCLUSIVE,'Additional assertions needed')}${stat('Errors / skipped',report.counts.ERROR+' / '+report.counts.SKIPPED,'No vulnerability claim')}</div>
    <div class="grid two"><section class="panel"><h2>Findings by severity</h2>${['critical','high','medium','low'].map(s=>`<div class="bar-row"><span>${tag(s)}</span><div class="bar-track"><div class="bar-fill fail" style="width:${(report.severity_counts[s]||0)/Math.max(1,report.counts.FAIL)*100}%"></div></div><strong>${report.severity_counts[s]||0}</strong></div>`).join('')}<p class="hint">${report.tests_executed} tests executed · ${report.usage.elapsed_seconds}s elapsed · ${report.usage.tokens_observed} observed tokens</p></section>
    <section class="panel"><h2>Next-run recommendation</h2><div class="slider-labels"><strong>${report.next_run.exploration}% explore</strong><strong>${report.next_run.exploitation}% retest</strong></div><p>${esc(report.next_run_advice)}</p><p class="hint">Repeated: ${report.repeated_failures.length} · new: ${report.new_failures.length} · resolved: ${report.resolved_failures.length}</p><details><summary>Strategy evidence</summary><pre>${json({contributions:report.next_run.contributions,outcomes:report.strategy_outcomes})}</pre></details></section></div>
    <section class="panel"><h2>Technical findings</h2>${report.findings.length?report.findings.map(f=>`<details><summary>${tag(f.severity)} ${esc(f.title)} ${f.repeated?tag('REPEATED'):''}</summary><p>${esc(f.plain_description)}</p><p><strong>Expected:</strong> ${esc(f.expected)}</p><p><strong>Observed:</strong> ${esc(f.observed)}</p><p><strong>Classification:</strong> ${esc(f.reason)} · confidence ${Math.round(f.confidence*100)}%</p><p><strong>Consequence:</strong> ${esc(f.consequence)}</p><p><strong>Remediation:</strong> ${esc(f.mitigation)}</p><p class="hint">${esc(f.owasp)} · ${esc(f.component)}</p><pre>${json(f.evidence)}</pre></details>`).join(''):empty('No failures observed','This conclusion applies only to the executed probes.')}</section>
    <section class="panel"><h2>Coverage & all outcomes</h2><p>${report.coverage.map(tag).join(' ')}</p><p class="hint">Uncovered: ${Object.keys(report.uncovered_categories).map(esc).join(', ')}</p><table><thead><tr><th>Test</th><th>Component</th><th>Outcome</th><th>Reason</th></tr></thead><tbody>${report.evaluations.map(e=>`<tr><td>${esc(e.title)}</td><td>${esc(e.component)}</td><td>${tag(e.classification)}</td><td>${esc(e.reason)}</td></tr>`).join('')}</tbody></table></section><div class="info-box">${report.limitations.map(esc).join('<br>')}</div>`;
}
function research() {
  const r = state.run;
  if (!r?.plan) return heading('Research & planning','Review sources, trust boundaries and testing priorities.')+empty('No plan selected','Open a run after its planning stage.');
  return heading('Research & planning',`${esc(r.target.application.name)} · ${r.config.mode} mode`)+
    `<div class="info-box">${esc(r.research?.mode || 'Live Tavily research')} · Research is untrusted evidence. Sources are never executed.</div>
    <div class="grid two"><section class="panel sources"><h2>Evidence sources</h2>${(r.research?.research||[]).map(s=>`<div><strong>${esc(s.title)}</strong>${/^https?:\/\//.test(s.url)?`<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.url)} ↗</a>`:''}<p class="hint">${esc(s.content)}</p></div>`).join('')}</section><section class="panel"><h2>Trust boundaries</h2>${(r.plan.trust_boundaries||[]).map(b=>`<p class="tag">${esc(typeof b==='string'?b:JSON.stringify(b))}</p>`).join('')}<h2>Declared architecture</h2><pre>${json(r.target.integration)}</pre></section></div>
    <section class="panel"><h2>Prioritized testing objectives</h2><div class="table-scroll"><table><thead><tr><th>Priority</th><th>Objective</th><th>Component</th><th>OWASP</th><th>Rationale</th></tr></thead><tbody>${r.plan.objectives.map(o=>`<tr><td>${o.priority} ${tag(o.severity)}</td><td>${esc(o.testing_objective)}</td><td>${esc(o.component)}</td><td>${esc(o.owasp)}</td><td>${esc(o.explanation)}<br><span class="hint">${esc(o.evidence)}</span></td></tr>`).join('')}</tbody></table></div></section>`;
}
function history() {
  const choices = state.runs.filter(r=>r.report).map(r=>`<option value="${r.id}">${esc(r.target_name)} · ${r.id.slice(0,8)} · ${esc(date(r.created_at))}</option>`).join('');
  return heading('Run history','Persistent evidence, testing allocations and regression comparisons.')+
    `<section class="panel flush">${tableRows(state.runs)}</section><section class="panel"><h2>Compare two runs of the same target</h2><div class="form-grid"><label class="field">Earlier run<select id="compare-first">${choices}</select></label><label class="field">Later run<select id="compare-second">${choices}</select></label></div><p></p>${button('compare','Compare runs')}<div id="comparison"></div></section>`;
}
function settingsView(settings, providers) {
  return heading('Workspace settings','Provider preferences, request limits and local retention.')+
    `<div class="grid two"><section class="panel"><h2>Provider status</h2>${Object.entries(providers).map(([p,s])=>`<div class="split-label"><strong>${esc(p)}</strong>${tag(s.available?'AVAILABLE':s.configured?'CONFIGURED':'NOT CONFIGURED')}</div><p class="hint">${esc(s.availability || s.model || 'Credentials remain server-side.')}</p>`).join('')}<div class="info-box">Availability indicators show configuration, not verified quota. Free models have request limits.</div><h2>Allowed remote scope</h2><pre>${json(settings.allowed_endpoints)}</pre><p class="hint">Configured server-side with LAB_ALLOWED_ENDPOINTS. Every target also requires exact endpoint authorization.</p></section>
    <section class="panel"><h2>Defaults</h2><label class="field">Preferred Gemini model<input id="preferred-model" value="${esc(settings.preferred_model)}"></label><label class="check"><input id="only-free" type="checkbox" ${settings.only_free?'checked':''}> Prefer only free OpenRouter models</label><label class="field">Default mode<select id="default-mode"><option value="offline" ${settings.mode==='offline'?'selected':''}>offline</option><option value="live" ${settings.mode==='live'?'selected':''}>live</option></select></label><label class="field">Default limits (JSON)<textarea id="settings-limits" rows="15">${json(settings.default_limits)}</textarea></label><label class="field">Retention (days)<input id="retention" type="number" min="1" max="3650" value="${settings.retention_days}"></label><p></p><div class="actions">${button('save-settings','Save settings','primary')}${button('prune','Prune expired run records')}</div><p class="hint">Pruning removes completed database records older than the retention window; downloaded report files remain on disk.</p></section></div>`;
}
async function render() {
  const route = routeName();
  document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('active',a.hash==='#'+route));
  $('#breadcrumb').textContent = ({dashboard:'Overview',new:'New test',live:'Live testing',results:'Results',research:'Research & planning',history:'Run history',settings:'Settings'})[route] || 'Overview';
  if (route==='new') {
    if (state.step===1) $('#page').innerHTML = targetForm();
    if (state.step===2) {const q = await api(`/targets/${state.target.id}/clarifications`); $('#page').innerHTML=clarificationForm(q.questions);}
    if (state.step===3) $('#page').innerHTML = strategyForm();
  } else if (route==='settings') {
    const [settings,providers] = await Promise.all([api('/settings'),api('/providers')]); $('#page').innerHTML=settingsView(settings,providers);
  } else {$('#page').innerHTML = ({dashboard,live,results,research,history}[route]||dashboard)();}
}
async function openRun(id, page) {
  if(state.stream) state.stream.close();
  state.run=await api('/runs/'+id); state.events=[];
  const stream=new EventSource(`/api/runs/${id}/events`); state.stream=stream;
  stream.onmessage = event=>{const item=JSON.parse(event.data); if(!state.events.some(e=>e.seq===item.seq)) state.events.push(item); if(routeName()==='live'&&$('#trace')) {$('#trace').innerHTML=traceView();if($('#trace-count'))$('#trace-count').textContent=state.events.length+' recorded actions';}};
  stream.addEventListener('done',async()=>{stream.close(); state.run=await api('/runs/'+id); await refreshRuns(); await render();});
  location.hash=page || (state.run.report?'results':'live'); await render();
}
async function calculateEstimate() {
  if($('#limits')) state.limits=JSON.parse($('#limits').value);
  if($('#agent-mode')) state.mode=$('#agent-mode').value;
  state.estimate=await api('/estimate','POST',{target_id:state.target.id,exploration:state.exploration,limits:state.limits,mode:state.mode});
  if($('#estimate-output')) $('#estimate-output').innerHTML=estimateView();
}
async function action(name, el) {
  clearNotice();
  if(name==='try-demo') {state.target=await api('/demo-target'); state.step=1; location.hash='new'; await render();}
  if(name==='new-test') {state.target=null;state.step=1;location.hash='new';await render();}
  if(name==='import-example') {state.target=await api('/example');state.step=1;await render();}
  if(name==='back-target') {state.step=1;await render();}
  if(name==='save-target') {
    const t=JSON.parse($('#target-json').value); delete t.id;
    t.application={...t.application,name:$('#target-name').value.trim(),purpose:$('#target-purpose').value};
    t.llm={...t.llm,provider:$('#target-provider').value,model:$('#target-model').value,model_version:$('#target-model').value};
    const choice=id=>$('#'+id).value==='unknown'?null:$('#'+id).value==='yes';
    t.integration={...t.integration,rag_enabled:choice('target-rag'),tools_enabled:choice('target-tools'),conversation_memory:choice('target-memory')};
    if(!t.application.name) throw Error('Enter an application name.');
    t.adapter={...t.adapter,endpoint:$('#target-url').value.trim(),kind:$('#target-kind').value,mode:$('#target-mode').value,auth_env:$('#target-auth-env').value.trim()};
    t.testing_scope={...t.testing_scope,authorized:$('#authorized').checked,allowed_endpoints:$('#authorized').checked?[t.adapter.endpoint]:[]};
    state.target=await api('/targets/import','POST',t);state.step=2;await render();
  }
  if(name==='save-answers') {
    const answers={}; document.querySelectorAll('[data-question]').forEach(field=>{
      const type=field.dataset.type; const id=field.dataset.question;
      if(type==='multiple') answers[id]=[...field.querySelectorAll('input:checked')].map(i=>i.value);
      else if(type==='single') {const input=field.querySelector('input:checked');if(input) answers[id]=input.value;}
      else {const value=field.querySelector('input,textarea').value;if(value) answers[id]=value;}
    });
    const response=await api(`/targets/${state.target.id}/clarifications`,'POST',answers);state.target=response.target;
    if(response.questions.some(q=>q.essential)) throw Error('Resolve authorization and the exact endpoint before continuing.');
    state.recommendation=await api(`/targets/${state.target.id}/recommendation`);state.exploration=state.recommendation.exploration;
    state.step=3;await calculateEstimate();await render();
  }
  if(name==='apply-recommendation') {state.exploration=state.recommendation.exploration;await calculateEstimate();await render();}
  if(name==='estimate') await calculateEstimate();
  if(name==='start-run') {
    await calculateEstimate();if(!state.estimate.can_start) throw Error('Adjust scope or limits to resolve the displayed budget violations.');
    const run=await api('/runs','POST',{target_id:state.target.id,exploration:state.exploration,limits:state.limits,mode:state.mode});
    await api('/runs/'+run.id+'/start','POST'); await refreshRuns();await openRun(run.id,'live');
  }
  if(name==='open-run') await openRun(el.dataset.id);
  if(['start','pause','resume','cancel'].includes(name)) {if(!state.run) throw Error('Select a run first.');state.run=await api('/runs/'+state.run.id+'/'+name,'POST');if(['start','resume'].includes(name))await openRun(state.run.id,'live');else await render();}
  if(name==='save-run-limits'){state.run=await api('/runs/'+state.run.id+'/limits','PATCH',JSON.parse($('#resume-limits').value));state.run=await api('/runs/'+state.run.id+'/resume','POST');await openRun(state.run.id,'live');}
  if(name==='show-results') {location.hash='results';await render();}
  if(name==='compare') {const result=await api(`/compare?first=${$('#compare-first').value}&second=${$('#compare-second').value}`);$('#comparison').innerHTML=`<div class="info-box">Resolved ${result.resolved.length} · repeated ${result.repeated.length} · new ${result.new.length} · not retested ${result.not_retested.length}</div><pre>${json(result)}</pre>`;}
  if(name==='save-settings') {const settings=await api('/settings','PUT',{mode:$('#default-mode').value,preferred_model:$('#preferred-model').value,only_free:$('#only-free').checked,retention_days:Number($('#retention').value),default_limits:JSON.parse($('#settings-limits').value)});state.limits=settings.default_limits;state.mode=settings.mode;await render();}
  if(name==='prune') {const result=await api('/maintenance/prune','POST');await refreshRuns();notice(result.deleted_runs+' expired run records removed.');}
}
document.addEventListener('click',async event=>{const el=event.target.closest('[data-action]');if(!el)return;el.disabled=true;try{await action(el.dataset.action,el);}catch(error){notice(error);}finally{el.disabled=false;}});
document.addEventListener('input',event=>{if(event.target.id==='exploration'){state.exploration=Number(event.target.value);$('#explore-label').textContent=state.exploration+'%';$('#exploit-label').textContent=(100-state.exploration)+'%';$('#exploration-warning').hidden=state.exploration<=65;state.estimate=null;$('#estimate-output').innerHTML=estimateView();}});
document.addEventListener('change',async event=>{
  try {
    if(event.target.id==='import-file'&&event.target.files[0]){state.target=JSON.parse(await event.target.files[0].text());await render();}
    if(event.target.id.startsWith('trace-')){state.filters[event.target.id.slice(6)]=event.target.value;$('#trace').innerHTML=traceView();}
  }catch(error){notice(error);}
});
window.addEventListener('hashchange',()=>render().catch(notice));
async function boot(){try{const [health,settings]=await Promise.all([api('/health'),api('/settings')]);$('#product-name').textContent=health.product;document.title=health.product;$('#connection').textContent='LOCAL · CONNECTED';state.limits=settings.default_limits;state.mode=settings.mode;await refreshRuns();await render();}catch(error){notice(error);$('#connection').textContent='CONNECTION ERROR';}}
setInterval(async()=>{if(state.run&&['running','paused','created'].includes(state.run.status)){try{state.run=await api('/runs/'+state.run.id);if(routeName()==='live'){if(!$('#page').contains(document.activeElement))await render();else{if($('#live-stats'))$('#live-stats').innerHTML=liveStats(state.run);const progress=$('progress');if(progress){progress.max=state.run.cases.length||1;progress.value=state.run.evaluations.length;}}}}catch(error){notice(error);}}},1500);
boot();
