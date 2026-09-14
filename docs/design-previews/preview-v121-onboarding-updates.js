(() => {
  'use strict';
  // Isolated prototype: no Tauri bridge, account access, service calls, or downloads.
  const $ = id => document.getElementById(id);
  const base = '../../desktop/assets/';
  const asset = name => `./v121-assets/${name}.svg`;
  const seenKey = 'token-bi.prototype.v121.onboarding-seen';
  const state = { view: 'home', update: 'idle', version: '1.2.1', online: true, progress: 0, notes: false, noUpdate: false };
  let timer = null;
  const icons = { check: asset('check'), download: asset('download'), update: asset('arrow-up-to-line'), refresh: base + 'refresh-cw.svg', warning: base + 'triangle-alert.svg' };
  const descriptions = {
    first: '首次提示贴近顶部图标。确认或打开面板后，本原型再次加载不重复提示。',
    daily: '点击顶部图标展开；点击面板外或切换窗口即收起。设置中可体验模拟更新。',
    available: '模拟后台发现更新：设置出现红点，不弹窗打断。进入设置即可更新。',
    latest: '本场景的版本源没有更高版本，检查后显示“已是最新版本”。',
    offline: '模拟断网。打开左侧“模拟网络连接”后，可在设置中重新检查。',
    'download-error': '模拟下载中断。网络恢复后可重新下载，旧版本继续可用。',
    'verify-error': '模拟签名不可信：更新被阻止，不允许安装。可重试下载新的包。',
  };
  function cancelTimer() { clearTimeout(timer); timer = null; }
  function later(fn, delay) { cancelTimer(); timer = setTimeout(fn, delay); }
  function feedback(message) { $('simulation-feedback').textContent = message; }
  function positionTip() {
    if ($('onboarding').hidden) return;
    const tip = $('onboarding').getBoundingClientRect(), tray = $('tray').getBoundingClientRect();
    const right = Math.min(tip.width - 24, Math.max(18, tip.right - tray.left - tray.width / 2 - 5));
    $('onboarding').style.setProperty('--tip-right', `${right}px`);
  }
  function acknowledgeTip() {
    $('onboarding').hidden = true;
    $('tray').classList.remove('spotlight');
    try { localStorage.setItem(seenKey, 'true'); } catch (_) { /* File previews can disallow storage. */ }
  }
  function openPanel(view = 'home') {
    acknowledgeTip();
    state.view = view;
    $('app-panel').hidden = false;
    $('closed-hint').hidden = true;
    $('tray').setAttribute('aria-expanded', 'true');
    renderView();
  }
  function closePanel() {
    $('app-panel').hidden = true;
    $('closed-hint').hidden = $('onboarding').hidden === false;
    $('tray').setAttribute('aria-expanded', 'false');
  }
  function closeOnOutsideInteraction(event) {
    if (!$('app-panel').hidden && event.target instanceof Element && !event.target.closest('#app-panel, #tray, #onboarding')) closePanel();
  }
  function renderView() {
    for (const view of ['home', 'settings', 'qr', 'diagnostics']) $(view).hidden = view !== state.view;
    $('brand').hidden = state.view !== 'home';
    $('subhead').hidden = state.view === 'home';
    $('view-title').textContent = { settings: '设置', qr: '连接副屏', diagnostics: '诊断信息' }[state.view] || '';
    $('settings-button').toggleAttribute('aria-current', state.view === 'settings');
    if (state.view === 'settings') $('settings-button').setAttribute('aria-current', 'page');
    renderUpdate();
  }
  function renderUpdate() {
    const s = state.update;
    const pending = ['available', 'downloading', 'ready', 'restarting', 'download-error', 'verify-error'].includes(s);
    $('update-dot').hidden = !pending;
    $('settings-button').setAttribute('aria-label', pending ? '设置，有新版本待更新' : '设置');
    $('current-version').textContent = state.version;
    const views = {
      idle: ['保持 Token BI 为最新版本', '上次检查：尚未检查', '检查更新', 'refresh', 'neutral'],
      checking: ['正在检查更新', '正在连接更新服务…', '正在检查…', 'refresh', 'neutral'],
      available: ['发现新版本 1.2.2', '可下载并在准备好后重启安装。', '立即更新', 'download', 'available'],
      latest: ['已是最新版本', '上次检查：刚刚', '检查更新', 'check', 'success'],
      downloading: ['正在下载 1.2.2', '下载期间可继续查看额度。', '下载中…', 'download', 'available'],
      ready: ['更新已准备好', '安装包已通过签名校验。', '重启完成更新', 'update', 'success'],
      restarting: ['正在完成更新', '正在重启 Token BI…', '正在重启…', 'refresh', 'neutral'],
      success: ['已更新至 1.2.2', '本地服务已恢复运行。', '检查更新', 'check', 'success'],
      'check-error': ['暂时无法检查更新', '网络不可用，请联网后重试。', '重新检查', 'warning', 'error'],
      'download-error': ['下载已中断', '网络连接中断，当前版本未受影响。', '重新下载', 'warning', 'error'],
      'verify-error': ['无法验证此更新', '签名校验失败，已阻止安装。当前版本可继续使用。', '重新下载', 'warning', 'error'],
    };
    const [title, description, label, icon, tone] = views[s];
    $('update-title').textContent = title;
    $('update-description').textContent = description;
    $('diag-update').textContent = title;
    $('update-icon').src = icons[icon];
    $('update-symbol').dataset.tone = tone;
    $('update-icon').classList.toggle('is-spinning', s === 'checking' || s === 'restarting');
    const button = $('update-action');
    button.querySelector('span').textContent = label;
    button.querySelector('img').src = icons[s === 'ready' ? 'update' : s.endsWith('error') ? 'refresh' : icon];
    button.disabled = ['checking', 'downloading', 'restarting'].includes(s);
    $('release-notes').hidden = !['available', 'downloading', 'ready', 'download-error', 'verify-error'].includes(s);
    $('notes-list').hidden = !state.notes;
    $('toggle-notes').textContent = state.notes ? '收起' : '展开';
    $('toggle-notes').setAttribute('aria-expanded', String(state.notes));
    $('download-progress').hidden = s !== 'downloading';
    $('progress').value = state.progress;
    $('progress-label').textContent = `已下载 ${state.progress}%`;
    $('restart-note').hidden = s !== 'ready';
    $('update-later').hidden = !['available', 'downloading', 'ready', 'download-error', 'verify-error'].includes(s);
    $('update-later').textContent = s === 'downloading' ? '返回额度，后台下载' : '稍后再说';
  }
  function checkUpdate() {
    state.update = 'checking';
    renderUpdate();
    later(() => {
      state.update = !state.online ? 'check-error' : state.noUpdate || state.version === '1.2.2' ? 'latest' : 'available';
      renderUpdate();
    }, 1100);
  }
  function download() {
    cancelTimer();
    state.progress = 0;
    state.update = state.online ? 'downloading' : 'download-error';
    renderUpdate();
    if (!state.online) return;
    function tick() {
      if (!state.online) { state.update = 'download-error'; renderUpdate(); return; }
      state.progress = Math.min(100, state.progress + 5);
      if (state.progress === 100) {
        state.update = 'ready';
        renderUpdate();
        return;
      }
      renderUpdate();
      later(tick, 180);
    }
    later(tick, 180);
  }
  function restart() {
    state.update = 'restarting';
    renderUpdate();
    later(() => {
      state.version = '1.2.2';
      state.update = 'success';
      state.noUpdate = true;
      renderUpdate();
      feedback('模拟更新完成：红点清除，版本变为 1.2.2。实际应用、服务和文件均未改变。');
    }, 1500);
  }
  function selectScenario(name) {
    cancelTimer();
    Object.assign(state, { view: 'home', update: 'idle', version: '1.2.1', online: true, progress: 0, notes: false, noUpdate: false });
    $('scenario').value = name;
    $('onboarding').hidden = true;
    $('tray').classList.remove('spotlight');
    if (name === 'first') {
      closePanel();
      $('closed-hint').hidden = true;
      $('onboarding').hidden = false;
      $('tray').classList.add('spotlight');
      positionTip();
    } else {
      if (name === 'available') state.update = 'available';
      if (name === 'latest') { state.update = 'latest'; state.noUpdate = true; }
      if (name === 'offline') { state.online = false; state.update = 'check-error'; }
      if (name === 'download-error') { state.online = false; state.update = 'download-error'; }
      if (name === 'verify-error') state.update = 'verify-error';
      openPanel(['first', 'daily', 'available'].includes(name) ? 'home' : 'settings');
    }
    $('network').checked = state.online;
    renderUpdate();
    feedback(descriptions[name]);
  }
  $('scenario').addEventListener('change', event => selectScenario(event.target.value));
  $('replay').addEventListener('click', () => selectScenario($('scenario').value));
  $('network').addEventListener('change', event => {
    state.online = event.target.checked;
    if (!state.online && state.update === 'downloading') { cancelTimer(); state.update = 'download-error'; renderUpdate(); }
    feedback(state.online ? '模拟网络已恢复，可点击重新检查或重新下载。' : '模拟网络已断开，原有额度与当前应用版本不变。');
  });
  $('tray').addEventListener('click', () => {
    if ($('app-panel').hidden) openPanel(state.view); else closePanel();
  });
  $('open-from-tip').addEventListener('click', () => { openPanel(); $('settings-button').focus(); feedback('引导已确认。这里保留原有额度、扫码和看板入口；再次启动不重复提示。'); });
  for (const id of ['dismiss-tip', 'ack-tip']) $(id).addEventListener('click', () => { acknowledgeTip(); closePanel(); $('tray').focus(); feedback('引导已关闭。Token BI 继续常驻菜单栏，点击顶部图标即可打开。'); });
  $('toggle-notes').addEventListener('click', () => { state.notes = !state.notes; renderUpdate(); });
  $('update-later').addEventListener('click', () => openPanel('home'));
  $('update-action').addEventListener('click', () => {
    if (['idle', 'latest', 'success', 'check-error'].includes(state.update)) checkUpdate();
    else if (['available', 'download-error', 'verify-error'].includes(state.update)) download();
    else if (state.update === 'ready') restart();
  });
  $('app-panel').addEventListener('click', async event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.kind) {
      document.querySelectorAll('[data-kind]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
      feedback('二维码是 example.com 的示例链接，不包含真实局域网地址或连接凭证。');
      return;
    }
    const action = button.dataset.action;
    if (['settings', 'qr', 'diagnostics'].includes(action)) openPanel(action);
    else if (action === 'back') openPanel(state.view === 'diagnostics' ? 'settings' : 'home');
    else if (action === 'quit') { cancelTimer(); if (state.update === 'downloading') state.update = 'available'; closePanel(); feedback('仅模拟关闭面板，未退出真实 Token BI。顶部图标可重新打开原型。'); }
    else if (action === 'refresh') feedback('额度刷新已模拟完成；没有调用真实账号或后端。');
    else if (action === 'logout') feedback('原有退出账号入口保留。本轮原型不执行账号操作。');
    else if (action === 'dashboard') feedback('原有打开看板入口保留。本轮原型未启动本地看板服务。');
    else if (action === 'copy') {
      try { await navigator.clipboard.writeText('https://example.com/token-bi-demo'); feedback('已复制示例链接，不是真实副屏地址。'); }
      catch (_) { feedback('浏览器未允许复制。示例链接：https://example.com/token-bi-demo'); }
    }
  });
  document.addEventListener('pointerdown', closeOnOutsideInteraction);
  document.addEventListener('focusin', closeOnOutsideInteraction);
  // Hiding the panel does not cancel background checks or downloads.
  window.addEventListener('blur', closePanel);
  document.addEventListener('visibilitychange', () => { if (document.hidden) closePanel(); });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    if (!$('onboarding').hidden) acknowledgeTip();
    closePanel();
    $('tray').focus();
  });
  window.addEventListener('resize', positionTip);
  window.addEventListener('pagehide', cancelTimer);
  let seen = false;
  try { seen = localStorage.getItem(seenKey) === 'true'; } catch (_) { /* Keep first-run preview usable without storage. */ }
  selectScenario(seen ? 'daily' : 'first');
})();
