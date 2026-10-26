// Music Producer's icon: "Keys, note, wave". A piano keyboard along the bottom,
// a violet note sitting on it, and a blue/violet waveform off the note's stem,
// on near-black navy.
//   NODE_PATH=<a node_modules with playwright> node assets/icon/make-icons.cjs
// Redraws every icon at its existing pixel size, full-bleed and opaque:
//   - iOS 1024 (iOS masks the corners itself)
//   - web/public: icon-192, icon-512 (also the manifest's maskable icon, so the
//     motif is shrunk to 84% to sit inside the maskable safe zone), apple-touch-icon
//   - Android launcher: legacy ic_launcher / ic_launcher_round (full design), and
//     the adaptive-icon background (108dp canvas; motif at 60% so the launcher's
//     circle/squircle crop never clips it).
// Supersedes scripts/make_app_icon.py (the old eighth-note icon).
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..', '..');
const BG = '#0f1020';

const MOTIF = `
<rect x="14" y="70" width="72" height="16" rx="3" fill="#ececf6"/>
<path d="M23 70 V86 M32 70 V86 M41 70 V86 M50 70 V86 M59 70 V86 M68 70 V86 M77 70 V86" stroke="#0f1020" stroke-opacity="0.25" stroke-width="0.8"/>
<rect x="20.5" y="70" width="5" height="9" rx="1" fill="#0f1020"/><rect x="29.5" y="70" width="5" height="9" rx="1" fill="#0f1020"/><rect x="47.5" y="70" width="5" height="9" rx="1" fill="#0f1020"/><rect x="56.5" y="70" width="5" height="9" rx="1" fill="#0f1020"/><rect x="65.5" y="70" width="5" height="9" rx="1" fill="#0f1020"/>
<rect x="40" y="14" width="6" height="44" rx="3" fill="#ececf6"/>
<rect x="48" y="19" width="3" height="6" rx="1.5" fill="#2563eb"/><rect x="52.5" y="16" width="3" height="12" rx="1.5" fill="#8b5cf6"/><rect x="57" y="13" width="3" height="18" rx="1.5" fill="#2563eb"/><rect x="61.5" y="17" width="3" height="10" rx="1.5" fill="#8b5cf6"/><rect x="66" y="15" width="3" height="14" rx="1.5" fill="#2563eb"/><rect x="70.5" y="18.5" width="3" height="7" rx="1.5" fill="#8b5cf6"/><rect x="75" y="20" width="3" height="4" rx="1.5" fill="#2563eb"/>
<rect x="24" y="46" width="22" height="15" rx="6" fill="#7c3aed"/>`;

// Full-bleed square; `scale` shrinks the motif about the centre.
function svg(px, scale = 1) {
  const t = scale === 1 ? '' : ` transform="translate(50 50) scale(${scale}) translate(-50 -50)"`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${px}" height="${px}" viewBox="0 0 100 100">` +
    `<rect width="100" height="100" fill="${BG}"/><g${t}>${MOTIF}</g></svg>`;
}

const size = (file) => {
  const buf = fs.readFileSync(file);   // PNG IHDR
  return buf.readUInt32BE(16);
};

const jobs = [];
const add = (rel, scale = 1) => {
  const file = path.join(ROOT, rel);
  jobs.push([file, fs.existsSync(file) ? size(file) : 1024, scale]);
};
add('ios/AiMusic/Assets.xcassets/AppIcon.appiconset/AppIcon.png');
add('web/public/icon-192.png', 0.84);
add('web/public/icon-512.png', 0.84);
add('web/public/apple-touch-icon.png');
const res = path.join(ROOT, 'android/app/src/main/res');
for (const d of fs.readdirSync(res).filter((d) => d.startsWith('mipmap-') && !d.includes('anydpi'))) {
  for (const name of ['ic_launcher.png', 'ic_launcher_round.png', 'ic_launcher_background.png']) {
    if (fs.existsSync(path.join(res, d, name))) add(`android/app/src/main/res/${d}/${name}`, name.includes('background') ? 0.6 : 1);
  }
}

(async () => {
  const browser = await chromium.launch().catch(() => chromium.launch({ channel: 'chrome' }));
  const page = await browser.newPage();
  for (const [file, px, scale] of jobs) {
    await page.setViewportSize({ width: px, height: px });
    await page.setContent(`<html><body style="margin:0;background:${BG}">${svg(px, scale)}</body></html>`);
    // No omitBackground: Chromium writes an opaque RGB PNG (no alpha), as the App Store wants.
    await page.locator('svg').screenshot({ path: file });
    console.log(path.relative(ROOT, file), `${px}x${px}`, `motif ${scale * 100}%`);
  }
  await browser.close();
})();
