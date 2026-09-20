import { copyFile, mkdir, rm } from 'node:fs/promises';

const root = new URL('../', import.meta.url);
const assets = new URL('desktop/assets/', root);
await mkdir(assets, { recursive: true });
const icons = ['qr-code', 'external-link', 'refresh-cw', 'settings', 'power', 'chevron-left', 'copy', 'user-round', 'triangle-alert', 'file-text', 'download', 'check', 'arrow-up-to-line', 'x', 'clock-3'];
for (const name of icons) {
  await copyFile(new URL(`node_modules/lucide-static/icons/${name}.svg`, root), new URL(`${name}.svg`, assets));
}
await copyFile(new URL('node_modules/lucide-static/LICENSE', root), new URL('lucide-LICENSE', assets));
await copyFile(new URL('src-tauri/icons/icon.png', root), new URL('icon.png', assets));
// Only production resources enter the app; preview fixtures stay in the workspace.
const output = new URL('dist/desktop/', root);
await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
for (const name of ['index.html', 'panel.css', 'panel.mjs', 'model.mjs', 'onboarding.html', 'onboarding.css', 'onboarding.mjs']) {
  await copyFile(new URL(`desktop/${name}`, root), new URL(name, output));
}
await mkdir(new URL('assets/', output));
for (const name of [...icons.map(name => `${name}.svg`), 'icon.png', 'lucide-LICENSE']) {
  await copyFile(new URL(name, assets), new URL(`assets/${name}`, output));
}
console.log('Desktop production assets ready');
