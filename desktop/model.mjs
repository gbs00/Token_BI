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
