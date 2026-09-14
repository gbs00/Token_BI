async function act(action) {
  try { await window.__TAURI__.core.invoke('onboarding_action', { action }); }
  catch (error) { const output = document.getElementById('error'); output.hidden = false; output.textContent = String(error); }
}
document.addEventListener('click', event => { const button = event.target.closest('[data-action]'); if (button) void act(button.dataset.action); });
document.addEventListener('keydown', event => { if (event.key === 'Escape') void act('dismiss'); });
await act('ready');
