import { viewModel, tier, resetRemaining, lastSuccess, sources, updateModel, storedResets } from './model.mjs';

const $ = id => document.getElementById(id);
const native = Boolean(window.__TAURI__?.core?.invoke);
const scenario = new URLSearchParams(location.search).get('preview');
let preview;
if (!native && scenario) preview = (await import('./preview.mjs')).createPreview(scenario);
const invoke = (command, args = {}) => native ? window.__TAURI__.core.invoke(command, args) : preview
  ? preview.invoke(command, args) : Promise.reject(new Error('请从 Token BI App 打开，或使用本地预览入口。'));
const request = action => invoke('panel_action', { action });
let status = null, boot = { phase: 'starting', visible: true }, view = 'home', kind = 'lan';
let busy = false, serial = 0, qrSerial = 0, qrURL = '', qrKey = '';
let pollRunning = false, nextRead = 0, toastTimer;

function feedback(message) {
  clearTimeout(toastTimer);
  $('feedback').textContent = message;
  $('feedback').hidden = !message;
  toastTimer = setTimeout(() => { $('feedback').hidden = true; }, 9000);
}
function render() {
  const model = viewModel(status), hasMetrics = model.metrics.length > 0;
  $('account').hidden = !model.account;
  $('email').textContent = model.account?.masked_email || 'Codex 账号';
  $('email').title = $('email').textContent;
  $('source').textContent = [sources[model.summary.source_type], lastSuccess(model.summary)].filter(Boolean).join(' · ');
  const failing = ['stale', 'error', 'rate_limited', 'source_changed', 'reauth_required'].includes(model.state);
  const loginNeeded = ['reauth_required', 'source_changed'].includes(model.state);
  const issue = boot.phase === 'error' ? boot.message : status?.healthy === false
    ? status.health_error || '本地服务未运行，请重试。'
    : (failing ? model.message || '本次同步未成功，将自动重试。' : '');
  $('notice').hidden = !issue;
  $('notice').querySelector('[data-action="retry"]').textContent = boot.phase === 'ready' && status?.healthy !== false && loginNeeded ? '查看登录页' : '重试';
  $('notice-text').textContent = issue ? `${issue}${hasMetrics ? ' 当前显示上次成功数据。' : ''}` : '';
  $('empty').hidden = hasMetrics;
  $('metrics').hidden = !hasMetrics;
  $('login').hidden = boot.phase !== 'ready' || (model.authenticated && !loginNeeded);
  $('empty-title').textContent = boot.phase === 'starting' ? '正在连接本地服务' : boot.phase === 'error' ? '本地服务暂不可用'
    : !model.authenticated ? '未检测到可用账号' : '等待额度数据';
  $('empty-copy').textContent = boot.phase !== 'ready' ? '' : !model.authenticated ? '登录后即可查看 Codex 使用额度' : '等待下一次同步';
  const cards = model.metrics.map(metric => {
    const article = document.createElement('article');
    article.className = `metric tier-${tier(metric.remaining_pct)}`;
    const heading = document.createElement('div'); heading.className = 'metric-heading';
    const label = document.createElement('h2');
    label.textContent = metric.label || (metric.metric_type === 'weekly' ? '周额度' : '5h 额度');
    const value = document.createElement('span'); value.className = 'metric-value';
    const number = document.createElement('span'); number.className = 'metric-number'; number.textContent = String(metric.remaining_pct);
    const unit = document.createElement('span'); unit.className = 'metric-unit'; unit.textContent = '%';
    const suffix = document.createElement('small'); suffix.textContent = '剩余';
    value.append(number, unit, suffix);
    heading.append(label, value);
    const bar = document.createElement('div'); bar.className = 'bar'; bar.setAttribute('aria-hidden', 'true');
    const fill = document.createElement('div'); fill.className = 'bar-fill'; fill.style.width = `${metric.remaining_pct}%`; bar.append(fill);
    article.append(heading, bar);
    const remaining = resetRemaining(metric.reset_at);
    if (remaining) {
      const reset = document.createElement('p'); reset.className = 'reset'; reset.dataset.reset = metric.reset_at;
      reset.textContent = `重置剩余 ${remaining}`; article.append(reset);
    }
    return article;
  });
  $('metrics').replaceChildren(...cards);
  renderResetCredits(model);
  $('diag-health').textContent = status?.healthy ? '运行中' : status?.health_error || boot.message || '等待就绪';
  $('diag-success').textContent = lastSuccess(model.summary);
  $('diag-state').textContent = model.message || ({ready:'同步成功', empty:'等待数据', stale:'上次数据', reauth_required:'需要重新登录'}[model.state] || model.state);
  $('log').textContent = status?.log_tail || '暂无日志';
  document.querySelector('[data-action="logout"]').textContent = model.authenticated ? '退出账号' : '登录账号';
  updateButtons();
  if (view === 'qr') void updateQR();
}
function renderResetCredits(model = viewModel(status)) {
  const resets = model.metrics.length ? storedResets(model.resetCredits) : null;
  $('reset-credits').hidden = !resets;
  $('metrics').classList.toggle('with-resets', Boolean(resets));
  $('reset-credits-times').replaceChildren();
  if (!resets) return;
  const entries = resets.expirations.map(expiry => {
    const item = document.createElement('span'); item.setAttribute('role', 'listitem');
    item.textContent = expiry.label;
    item.title = `${new Date(expiry.at).toLocaleString('zh-CN')} 到期`;
    item.setAttribute('aria-label', `${expiry.label} 后到期`);
    return item;
  });
  if (resets.unknown) {
    const unknown = document.createElement('span'); unknown.setAttribute('role', 'listitem');
    unknown.textContent = `${resets.unknown} 次到期未知`; entries.push(unknown);
  }
  $('reset-expirations').hidden = entries.length === 0;
  $('reset-credits-empty').hidden = entries.length > 0;
  $('reset-credits-times').replaceChildren(...entries);
}
function updateButtons() {
  document.querySelectorAll('[data-action]').forEach(button => {
    const a = button.dataset.action;
    const needsBackend = ['refresh','login','logout','open_local'].includes(a);
    button.disabled = (busy && ['refresh','retry','login','logout'].includes(a)) || (needsBackend && boot.phase !== 'ready');
    if (['copy','open_selected'].includes(a)) button.disabled = !qrURL;
  });
  $('refresh-label').textContent = busy ? '处理中' : '刷新';
}
function renderUpdate() {
  const update = boot.update || {}, model = updateModel(update);
  $('update-dot').hidden = !model.pending;
  $('settings-button').setAttribute('aria-label', model.pending ? '设置，有新版本待更新' : '设置');
  $('current-version').textContent = update.current_version || '';
  $('update-title').textContent = model.title;
  $('update-description').textContent = model.phase === 'latest' && update.checked_at
    ? `上次检查：${new Date(update.checked_at * 1000).toLocaleString('zh-CN')}` : model.description;
  $('update-icon').src = `./assets/${model.icon}.svg`;
  $('update-symbol').dataset.tone = model.tone;
  $('update-action').disabled = model.disabled;
  $('update-action').querySelector('span').textContent = model.label;
  $('update-action').querySelector('img').src = `./assets/${model.icon}.svg`;
  $('release-notes').hidden = !model.pending;
  $('release-version').textContent = `${update.version || ''} 更新内容`;
  $('notes-copy').textContent = update.notes || '此版本未提供更新说明。';
  $('download-progress').hidden = model.phase !== 'downloading';
  if (model.percent == null) $('progress').removeAttribute('value'); else $('progress').value = model.percent;
  $('progress-label').textContent = model.percent == null ? `已下载 ${((update.received || 0) / 1048576).toFixed(1)} MiB` : `已下载 ${model.percent}%`;
  $('restart-note').hidden = model.phase !== 'ready';
  $('update-later').hidden = !model.pending || model.phase === 'installing';
  $('update-later').textContent = model.phase === 'downloading' ? '返回额度，后台下载' : '稍后再说';
}
function navigate(next) {
  view = next;
  for (const id of ['home','qr','settings','diagnostics']) $(id).hidden = id !== view;
  $('brand').hidden = view !== 'home'; $('subhead').hidden = view === 'home';
  $('view-title').textContent = { qr:'连接副屏', settings:'设置', diagnostics:'诊断信息' }[view] || '';
  document.querySelector('.scroll-body').scrollTop = 0;
  if (view === 'qr') void updateQR();
}
async function updateQR(force = false) {
  const target = status?.urls?.[kind] || '';
  const key = `${kind}:${target}:${status?.healthy}:${boot.phase}`;
  if (key === qrKey && !force) return;
  qrKey = key; qrURL = ''; const sequence = ++qrSerial;
  $('qr-image').hidden = true; $('qr-url').textContent = target || '暂无可用地址';
  $('qr-status').textContent = !target || !status?.healthy ? '等待本地网络就绪' : '正在生成二维码';
  $('connection-note').textContent = kind === 'fixed' ? '固定入口依赖局域网名称解析，无法连接时请切换局域网。' : '副屏与 Mac 需连接同一局域网。';
  document.querySelectorAll('[data-kind]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.kind === kind)));
  updateButtons();
  if (!target || !status?.healthy || boot.phase !== 'ready') return;
  try {
    const result = await request(`qr_${kind}`);
    if (sequence !== qrSerial) return;
    if (!result.ok || !result.url || !result.svg) throw new Error(result.message || '无法生成二维码');
    // SVG and URL are returned atomically, so a Wi-Fi change cannot mismatch them.
    qrURL = result.url; $('qr-url').textContent = qrURL;
    $('qr-image').src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(result.svg)}`;
    $('qr-image').hidden = false; $('qr-status').textContent = '';
  } catch (error) {
    if (sequence !== qrSerial) return;
    qrKey = ''; $('qr-status').textContent = String(error.message || error);
  }
  updateButtons();
}
async function readStatus() {
  const sequence = ++serial;
  try {
    const next = await request('status');
    if (sequence !== serial) return;
    if (!next.healthy && next.access_enabled !== false && status?.dashboard &&
        next.account?.account_id && next.account.account_id === status.dashboard.account?.account_id) {
      next.dashboard = status.dashboard;
    }
    status = next; render();
  } catch (error) {
    if (sequence !== serial) return;
    status = { ...status, healthy: false, health_error: `无法连接本地服务：${String(error.message || error)}` };
    render();
  }
}
async function poll() {
  if (pollRunning) return;
  pollRunning = true;
  try {
    boot = await invoke('panel_state');
    renderUpdate();
    if (!boot.visible && $('confirm-dialog').open) $('confirm-dialog').close();
    if (boot.open_qr) navigate('qr');
    if (boot.visible && !document.hidden) {
      if (boot.phase === 'ready' && !busy && Date.now() >= nextRead) {
        nextRead = Date.now() + 15000; await readStatus();
      } else if (boot.phase !== 'ready') render();
      document.querySelectorAll('[data-reset]').forEach(el => { el.textContent = `重置剩余 ${resetRemaining(el.dataset.reset)}`; });
      renderResetCredits();
    }
  } catch (error) { boot = {phase:'error', message:String(error.message || error)}; render(); }
  finally { pollRunning = false; }
}
async function perform(action) {
  if (busy) return;
  busy = true; ++serial; updateButtons();
  try {
    const result = await request(action);
    if (result.ok === false) throw new Error(result.message || '操作未成功');
    if (action === 'logout') { status = { ...status, access_enabled: false, account: null, dashboard: null }; render(); }
    if (action === 'retry_start') { boot.phase = 'starting'; render(); }
    else await readStatus();
    if (action === 'login') feedback(result.message || '登录请求已提交');
    if (action === 'refresh') feedback('额度已同步');
  } catch (error) { feedback(String(error.message || error)); if (boot.phase === 'ready') await readStatus(); }
  finally { busy = false; nextRead = action === 'retry_start' ? 0 : Date.now() + 15000; updateButtons(); }
}
function confirmAction(action) {
  const quitting = action === 'quit';
  $('confirm-title').textContent = quitting ? '退出 Token BI？' : '退出当前账号？';
  $('confirm-copy').textContent = quitting ? '副屏将停止更新，重新打开 App 后恢复。' : '仅解除 Token BI 的账号接入，不会退出 Codex、CLI 或网页账号。';
  $('confirm-button').textContent = quitting ? '退出' : '退出账号';
  $('confirm-button').onclick = async () => {
    $('confirm-dialog').close();
    if (quitting) { try { await invoke('panel_quit'); } catch (error) { feedback(String(error)); } }
    else await perform('logout');
  };
  $('confirm-dialog').showModal();
}
async function handleAction(action) {
  if (action === 'qr' || action === 'settings' || action === 'diagnostics') return navigate(action);
  if (action === 'back') return navigate(view === 'diagnostics' ? 'settings' : 'home');
  if (action === 'cancel') return $('confirm-dialog').close();
  if (action === 'quit') return confirmAction('quit');
  if (action === 'logout') return viewModel(status).authenticated ? confirmAction('logout') : perform('login');
  if (action === 'copy') { await navigator.clipboard.writeText(qrURL); feedback('链接已复制'); return; }
  if (action === 'open_selected' || action === 'open_local') {
    const result = await request(action === 'open_selected' ? `open_${kind}` : action);
    if (result.ok === false) throw new Error(result.message || '无法打开看板');
    if (!native) feedback('预览模式，不打开真实看板');
    return;
  }
  if (action === 'retry') return perform(boot.phase === 'error' || status?.healthy === false || status?.running === false ? 'retry_start' : ['reauth_required', 'source_changed'].includes(viewModel(status).state) ? 'login' : 'refresh');
  if (action === 'refresh' || action === 'login') return perform(action);
}
document.addEventListener('click', event => {
  const segment = event.target.closest('[data-kind]');
  if (segment) { kind = segment.dataset.kind; void updateQR(); return; }
  const button = event.target.closest('[data-action]');
  if (button && !button.disabled) handleAction(button.dataset.action).catch(error => feedback(String(error.message || error)));
});
$('toggle-notes').addEventListener('click', () => {
  $('notes-copy').hidden = !$('notes-copy').hidden;
  $('toggle-notes').textContent = $('notes-copy').hidden ? '展开' : '收起';
  $('toggle-notes').setAttribute('aria-expanded', String(!$('notes-copy').hidden));
});
$('update-later').addEventListener('click', () => navigate('home'));
$('update-action').addEventListener('click', async () => {
  $('update-action').disabled = true;
  try { await invoke('update_action', {action: updateModel(boot.update).action}); await poll(); }
  catch (error) { feedback(String(error.message || error)); renderUpdate(); }
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !$('confirm-dialog').open) {
    event.preventDefault(); if (view !== 'home') navigate('home'); else invoke('panel_hide').catch(error => feedback(String(error)));
  }
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'r') { event.preventDefault(); void perform('refresh'); }
});
document.addEventListener('visibilitychange', () => { if (!document.hidden) { nextRead = 0; void poll(); } });
window.addEventListener('focus', () => { nextRead = 0; void poll(); });
await poll();
if (scenario === 'qr') navigate('qr');
setInterval(poll, 2000);
