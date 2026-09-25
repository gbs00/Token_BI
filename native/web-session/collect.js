// 原生组件与验证工具共用；凭据留在隔离网页上下文，返回值采用字段白名单。
const expectedOrigin = options.origin;
if (location.origin !== expectedOrigin) return {category: 'origin_rejected'};
const started = performance.now();
const requests = [];
const timeoutMs = options.timeoutMs || 5000;
const maxBytes = 512 * 1024;

async function read(path, token) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let status = 0;
  try {
    const headers = {accept: 'application/json'};
    if (token) headers.authorization = 'Bearer ' + token;
    const response = await fetch(path, {
      headers, credentials: 'include', mode: 'same-origin', redirect: 'error',
      cache: 'no-store', signal: controller.signal
    });
    status = response.status;
    const entry = {endpoint: path, status};
    const retry = response.headers.get('retry-after');
    const retrySeconds = retry && /^\d+$/.test(retry) ? Number(retry)
      : retry ? (Date.parse(retry) - Date.now()) / 1000 : NaN;
    if (Number.isFinite(retrySeconds)) entry.retry_after_seconds = Math.max(20, Math.min(86400, retrySeconds));
    requests.push(entry);
    if (!response.ok) {
      controller.abort();
      return {status};
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let size = 0, body = '';
    for (;;) {
      const chunk = await reader.read();
      if (chunk.done) break;
      size += chunk.value.byteLength;
      if (size > maxBytes) {
        controller.abort();
        entry.error = 'response_too_large';
        return {status, error: entry.error};
      }
      body += decoder.decode(chunk.value, {stream: true});
    }
    body += decoder.decode();
    try { return {status, data: JSON.parse(body)}; }
    catch (_) { entry.error = 'non_json'; return {status, error: entry.error}; }
  } catch (error) {
    const kind = error.name === 'AbortError' ? 'timeout' : 'network_error';
    requests.push({endpoint: path, status, error: kind});
    return {status, error: kind};
  } finally { clearTimeout(timer); }
}

const finite = value => typeof value === 'number' && Number.isFinite(value);
function windowFields(value) {
  if (!value || !finite(value.used_percent) || value.used_percent < 0 || value.used_percent > 100) return null;
  const result = {used_percent: value.used_percent};
  for (const key of ['limit_window_seconds', 'reset_at', 'reset_after_seconds']) {
    if (finite(value[key]) && value[key] >= 0) result[key] = value[key];
  }
  return result;
}
function usageFields(value) {
  const rate = value && value.rate_limit;
  if (!rate || typeof rate !== 'object') return null;
  const result = {};
  for (const key of ['primary_window', 'secondary_window']) {
    const item = windowFields(rate[key]);
    if (item) result[key] = item;
  }
  return Object.keys(result).length ? {rate_limit: result} : null;
}
function resetFields(value) {
  if (!value || !Number.isInteger(value.available_count) || value.available_count < 0) return null;
  const result = {available_count: value.available_count};
  if (Array.isArray(value.credits)) {
    const ids = new Set();
    result.credits = [];
    for (const credit of value.credits.slice(0, 200)) {
      if (!credit || credit.status !== 'available' || credit.reset_type !== 'codex_rate_limits' ||
          typeof credit.id !== 'string' || !credit.id || ids.has(credit.id)) continue;
      ids.add(credit.id);
      const row = {id: String(ids.size), status: 'available', reset_type: 'codex_rate_limits'};
      if (finite(credit.expires_at) && credit.expires_at > 0) row.expires_at = credit.expires_at;
      else if (typeof credit.expires_at === 'string' &&
               /^\d{4}-\d\d-\d\dT[\d:.]+(?:Z|[+-]\d\d:\d\d)$/.test(credit.expires_at) &&
               Number.isFinite(Date.parse(credit.expires_at))) row.expires_at = credit.expires_at;
      result.credits.push(row);
    }
  }
  return result;
}
async function identityFields(session) {
  const email = session && session.user && session.user.email;
  if (typeof email !== 'string' || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email) || email.length > 254) return null;
  const value = email.trim().toLowerCase();
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  const key = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
  return {key, masked: value.slice(0, 2) + '***@' + value.split('@')[1]};
}
function domFields() {
  const text = (document.body && document.body.innerText || '').slice(0, 200000);
  const words = text.toLowerCase();
  const quotaRows = options.parseDOM && location.pathname !== options.domPath ? [] :
    text.match(/(?:weekly|session|周额度|5h\s*(?:额度)?)\s*\d{1,3}(?:\.\d+)?%\s*(?:left|remaining|剩余)(?:\s*(?:resets? in|重置剩余)\s*(?:\d+\s*[dhm]\s*){1,3})?/gi) || [];
  return {
    // 不回传整页文本，避免无关聊天内容、邮箱或登录挑战数据进入诊断文件。
    quota_text: quotaRows.slice(0, 8).join('\n'),
    challenge: /verify you are human|checking your browser|just a moment|验证您是真人/.test(words),
    login_visible: /log in|sign in|登录/.test(words)
  };
}

const sessionBefore = await read('/api/auth/session');
const identity = await identityFields(sessionBefore.data);
let token = sessionBefore.data && typeof sessionBefore.data.accessToken === 'string'
  ? sessionBefore.data.accessToken : null;
const authorization = {
  access_token_present: Boolean(token),
  usage_request: token ? 'bearer_with_session' : 'session_cookie'
};
// 不输出 session 或 token；只向当前已验证同源的官方接口发出只读请求。
function sessionFailure(response) {
  if (response.status === 429) return 'rate_limited';
  if (response.error === 'timeout') return 'timeout';
  if (response.error === 'network_error' || response.status >= 500) return 'network_error';
  if (response.status === 401 || response.status === 200 && response.data && !response.data.user) return 'auth_required';
  if (response.status === 403) return 'access_denied';
  return 'identity_unknown';
}
function result(category, usage = null, extra = {}) {
  return {schema: 1, category, identity, authorization, usage, requests,
    checked_at: new Date().toISOString(), elapsed_ms: Math.round(performance.now() - started), ...extra};
}
if (!identity) return result(sessionFailure(sessionBefore));
if (options.expectedIdentity && identity.key !== options.expectedIdentity) return result('account_mismatch');
let response = await read('/backend-api/wham/usage', token);
if (response.status === 401) {
  const renewed = await read('/api/auth/session');
  const renewedIdentity = await identityFields(renewed.data);
  if (!renewedIdentity) return result(sessionFailure(renewed));
  if (renewedIdentity.key !== identity.key) return result('identity_changed');
  token = typeof renewed.data.accessToken === 'string' ? renewed.data.accessToken : null;
  authorization.access_token_present = Boolean(token);
  authorization.usage_request = token ? 'bearer_with_session' : 'session_cookie';
  response = await read('/backend-api/wham/usage', token);
}
let usage = usageFields(response.data);
let resets = resetFields(response.data && response.data.rate_limit_reset_credits);
if (usage && resets && resets.available_count > 0 && !Array.isArray(resets.credits)) {
  const details = await read('/backend-api/wham/rate-limit-reset-credits', token);
  resets = resetFields(details.data) || resets;
}
if (usage && resets) usage.rate_limit_reset_credits = resets;
const dom = domFields();
let category = usage ? 'success' : 'schema_changed';
if (!usage) {
  if (response.status === 429) category = 'rate_limited';
  else if (response.error === 'timeout') category = 'timeout';
  else if (response.error === 'network_error' || response.status >= 500) category = 'network_error';
  else if (dom.challenge) category = 'challenge';
  else if (response.status === 401) category = 'auth_required';
  else if (response.status === 403) category = 'access_denied';
  else if (dom.quota_text) category = 'dom_candidate';
}
// 仅在指定额度页解析明确的“剩余”及重置语义，不从聊天首页猜测数字。
if (options.parseDOM && category === 'dom_candidate' && location.pathname === options.domPath) {
  const rate = {};
  const rows = dom.quota_text.matchAll(/(weekly|session|周额度|5h\s*(?:额度)?)\s*(\d{1,3}(?:\.\d+)?)%\s*(?:left|remaining|剩余)\s*(?:resets? in|重置剩余)\s*((?:\d+\s*[dhm]\s*){1,3})/gi);
  for (const row of rows) {
    const remaining = Number(row[2]);
    const weekly = /weekly|周额度/i.test(row[1]);
    let seconds = 0;
    for (const part of row[3].matchAll(/(\d+)\s*([dhm])/gi)) {
      seconds += Number(part[1]) * ({d: 86400, h: 3600, m: 60}[part[2].toLowerCase()]);
    }
    const duration = weekly ? 604800 : 18000;
    if (remaining <= 100 && seconds > 0 && seconds <= duration) {
      rate[weekly ? 'secondary_window' : 'primary_window'] = {
        used_percent: 100 - remaining, limit_window_seconds: duration,
        reset_at: Math.floor(Date.now() / 1000) + seconds
      };
    }
  }
  if (Object.keys(rate).length) { usage = {rate_limit: rate, is_estimated: true}; category = 'success'; }
}
if (usage) {
  const after = await read('/api/auth/session');
  const latestIdentity = await identityFields(after.data);
  if (!latestIdentity) { category = sessionFailure(after); usage = null; }
  else if (identity.key !== latestIdentity.key) { category = 'identity_changed'; usage = null; }
}
return result(category, usage, {dom, source_detail: usage && usage.is_estimated ? 'dom_fallback' : 'wkwebview_json'});
