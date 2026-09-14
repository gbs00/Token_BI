// Explicit preview only. No accounts, sidecars, or production endpoints are accessed.
export function createPreview(scenario) {
  let signedIn = scenario !== 'logged-out', failed = scenario === 'error';
  const now = Date.now();
  const urls = {local:'http://127.0.0.1:8787/dashboard', lan:'http://192.168.1.20:8787/dashboard', fixed:'http://token-bi-demo.local:8787/dashboard'};
  function status() {
    const account = signedIn ? {masked_email:'demo****@example.com', status:'active', account_id:'preview'} : null;
    return {running:true, healthy:true, account, access_enabled:signedIn, urls, log_tail:'Local preview. No services started.', dashboard:{
      account, state:signedIn ? failed ? 'stale' : 'ready' : 'empty', message:failed ? '同步失败：网络连接超时。' : '',
      summary:{source_type:'oauth', last_success_at:new Date(now - (failed ? 720000 : 0)).toISOString()},
      metrics:signedIn ? [{metric_type:'session',label:'5h 额度', remaining_pct:82,reset_at:new Date(now+13080000+59000).toISOString()},
        {metric_type:'weekly',label:'周额度',remaining_pct:44,reset_at:new Date(now+291600000+59000).toISOString()}] : [],
    }};
  }
  return {async invoke(command, args) {
    if (command === 'panel_state') return {phase:'ready',visible:true,update:{phase:'idle',current_version:'1.2.1'}};
    if (command === 'update_action') throw new Error('预览模式不会连接真实更新服务。请使用 1.2.1 交互原型查看更新演示。');
    if (command === 'panel_hide' || command === 'panel_quit') return;
    if (command !== 'panel_action') throw new Error('Unknown preview command');
    const action = args.action;
    if (action === 'status') return status();
    if (action === 'logout') signedIn = false;
    if (action === 'login') signedIn = true;
    if (action === 'refresh') failed = false;
    if (action.startsWith('qr_')) {
      const kind = action.slice(3);
      const response = await fetch(`/preview-qr?kind=${kind}`);
      if (!response.ok) throw new Error('请使用 npm run desktop:preview 查看二维码');
      return response.json();
    }
    return {ok:true, message:action === 'login' ? '预览账号已登录' : ''};
  }};
}
