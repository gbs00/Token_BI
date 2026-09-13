import { copyFile, cp, mkdir, rm } from 'node:fs/promises';

const root = new URL('../', import.meta.url);
const assets = new URL('desktop/assets/', root);
await mkdir(assets, { recursive: true });
for (const name of ['qr-code', 'external-link', 'refresh-cw', 'settings', 'power', 'chevron-left', 'pin', 'copy', 'user-round', 'triangle-alert', 'file-text']) {
  await copyFile(new URL(`node_modules/lucide-static/icons/${name}.svg`, root), new URL(`${name}.svg`, assets));
}
await copyFile(new URL('node_modules/lucide-static/LICENSE', root), new URL('lucide-LICENSE', assets));
await copyFile(new URL('src-tauri/icons/icon.png', root), new URL('icon.png', assets));
// Only production resources enter the app; preview fixtures stay in the workspace.
const output = new URL('dist/desktop/', root);
await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
for (const name of ['index.html', 'panel.css', 'panel.mjs', 'model.mjs']) {
  await copyFile(new URL(`desktop/${name}`, root), new URL(name, output));
}
await cp(assets, new URL('assets/', output), { recursive: true });
console.log('Desktop production assets ready');
