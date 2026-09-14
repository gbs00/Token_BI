export function visibleMetrics(metrics = []) {
  return metrics.filter(m => {
    const minutes = m.window_minutes ?? (m.window_seconds == null ? null : Math.floor(m.window_seconds / 60));
    return (['session', 'weekly'].includes(m.metric_type) || [300, 10080].includes(minutes)) &&
      typeof m.remaining_pct === 'number' && Number.isFinite(m.remaining_pct);
  }).map(m => ({ ...m, remaining_pct: Math.max(0, Math.min(100, m.remaining_pct)) }));
}
export function tier(value) {
  return value > 75 ? 'high' : value > 50 ? 'medium' : value > 25 ? 'low' : 'critical';
}
export function resetRemaining(resetAt, now = Date.now()) {
  const target = Date.parse(resetAt);
  if (!Number.isFinite(target)) return null;
  if (target - now <= 60000) return '即将重置';
  const minutes = Math.floor((target - now) / 60000);
  const days = Math.floor(minutes / 1440), hours = Math.floor(minutes % 1440 / 60), remainder = minutes % 60;
  return [days && `${days}d`, hours && `${hours}h`, !days && remainder && `${remainder}m`].filter(Boolean).slice(0, 2).join(' ');
}
export function lastSuccess(summary = {}, now = Date.now()) {
  const target = Date.parse(summary.last_success_at || summary.updated_at);
  if (!Number.isFinite(target)) return '等待首次同步';
  const minutes = Math.max(0, Math.floor((now - target) / 60000));
  return minutes < 1 ? '刚刚更新' : minutes < 60 ? `${minutes} 分钟前更新` : `${new Date(target).toLocaleString('zh-CN', {month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})} 更新`;
}
export const sources = { oauth: 'OAuth', cli_rpc: 'CLI RPC', web_session: 'Web Session', dom_fallback: 'Web 页面兼容', local_snapshot: '本地测试数据' };
export function updateModel(update = {}) {
  const phase = update.phase || 'idle', version = update.version || '';
  const entries = {
    idle: ['检查应用更新', '上次检查：尚未检查', '检查更新', 'check', 'refresh-cw'],
    checking: ['正在检查更新', '正在连接更新服务…', '正在检查…', 'check', 'refresh-cw'],
    latest: ['已是最新版本', '检查完成', '检查更新', 'check', 'check'],
    available: [`发现新版本 ${version}`, '可下载并在准备好后重启安装。', '立即更新', 'download', 'download'],
    downloading: [`正在下载 ${version}`, '下载期间可继续查看额度。', '下载中…', 'download', 'download'],
    ready: ['更新已准备好', '安装包已通过签名校验。', '重启完成更新', 'install', 'arrow-up-to-line'],
    installing: ['正在完成更新', '正在安装并重启 Token BI…', '正在更新…', 'install', 'refresh-cw'],
    check_error: ['暂时无法检查更新', '', update.available ? '立即更新' : '重新检查', update.available ? 'download' : 'check', 'triangle-alert'],
    download_error: ['下载未完成', '', '重新下载', 'download', 'triangle-alert'],
    install_error: ['安装未完成', '', '重新下载', 'download', 'triangle-alert'],
  };
  const [title, description, label, action, icon] = entries[phase] || entries.idle;
  const error = phase.endsWith('_error');
  return { phase, title, description: update.error || description, label, action, icon,
    disabled: ['checking', 'downloading', 'installing'].includes(phase),
    pending: Boolean(update.available), tone: error ? 'error' : phase === 'ready' || phase === 'latest' ? 'success' : update.available ? 'available' : 'neutral',
    percent: update.total > 0 ? Math.min(100, Math.floor((update.received || 0) / update.total * 100)) : null,
  };
}
export function viewModel(status) {
  const payload = status?.dashboard;
  const allowed = status?.access_enabled !== false;
  const account = allowed ? (payload ? payload.account : status?.account) : null;
  return {
    account,
    metrics: allowed ? visibleMetrics(payload?.metrics) : [],
    summary: payload?.summary || {},
    state: payload?.state || 'empty',
    message: payload?.message || '',
    authenticated: Boolean(allowed && account?.status === 'active'),
  };
}
