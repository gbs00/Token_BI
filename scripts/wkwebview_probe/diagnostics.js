(() => {
  // 仅记录事件类型和状态；不读取表单值、请求头、请求体或响应体。
  const targets = {
    'chatgpt.com': 'chatgpt', 'auth.openai.com': 'auth', 'auth0.openai.com': 'auth',
    'auth.chatgpt.com': 'auth', 'challenges.cloudflare.com': 'challenge',
    'accounts.google.com': 'identity_provider', 'appleid.apple.com': 'identity_provider',
    'login.microsoftonline.com': 'identity_provider', 'login.live.com': 'identity_provider',
    '127.0.0.1': 'local',
  };
  if (!targets[location.hostname]) return;
  const endpoint = (raw) => {
    try {
      const url = new URL(raw, location.href);
      const path = url.pathname;
      return {
        target: targets[url.hostname] || 'other',
        route: /password/.test(path) ? 'password' : /\/api\/auth\/session/.test(path) ? 'session'
          : /challenge|sentinel/.test(path) ? 'challenge' : /wham/.test(path) ? 'usage'
          : /\/api\/accounts/.test(path) ? 'auth_api' : /log-in|login|authorize/.test(path) ? 'login'
          : /\.(js|css)$/.test(path) ? 'asset' : 'other',
      };
    } catch { return {target: 'none', route: 'other'}; }
  };
  const send = (event, details = {}) => {
    try { window.webkit.messageHandlers.probeDiagnostics.postMessage({event, ...endpoint(location.href), ...details}); }
    catch { /* 诊断失败不影响站点执行。 */ }
  };
  const errorKind = (error) => ['TypeError', 'ReferenceError', 'SyntaxError', 'RangeError', 'AbortError']
    .includes(error?.name) ? error.name : 'other';
  let sent = 0;
  const network = (event, details) => { if (sent++ < 120) send(event, details); };
  const fetch = window.fetch;
  window.fetch = function (...args) {
    const input = args[0];
    const detail = endpoint(typeof input === 'string' || input instanceof URL ? input : input?.url);
    network('fetch_start', detail);
    // 返回原 Promise/Response，不消费正文，不改变站点异常传播。
    const result = Reflect.apply(fetch, this, args);
    result.then(response => network('fetch_end', {...detail, status: response.status}),
      error => network('fetch_error', {...detail, error_kind: errorKind(error)}));
    return result;
  };
  const requests = new WeakMap();
  const open = XMLHttpRequest.prototype.open;
  const xhrSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (...args) {
    const result = Reflect.apply(open, this, args);
    requests.set(this, endpoint(args[1]));
    return result;
  };
  XMLHttpRequest.prototype.send = function (...args) {
    const detail = requests.get(this) || {target: 'none', route: 'other'};
    network('xhr_start', detail);
    this.addEventListener('loadend', () => network('xhr_end', {...detail, status: this.status}), {once: true});
    this.addEventListener('error', () => network('xhr_error', detail), {once: true});
    return Reflect.apply(xhrSend, this, args);
  };
  document.addEventListener('click', event => {
    const button = event.target.closest?.('button, input[type=submit]');
    if (button?.form && button.type === 'submit') send('submit_click', {disabled: button.disabled});
  }, true);
  document.addEventListener('submit', () => send('form_submit'), true);
  document.addEventListener('invalid', () => send('invalid_input'), true);
  window.addEventListener('error', event => {
    if (event.target !== window) send('resource_error', endpoint(event.target.src || event.target.href));
    else send('script_error', {error_kind: errorKind(event.error)});
  }, true);
  window.addEventListener('unhandledrejection', event => send('promise_error', {error_kind: errorKind(event.reason)}));
  document.addEventListener('DOMContentLoaded', () => send('page_ready'), {once: true});
})();
