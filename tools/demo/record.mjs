// Records the animated README demo (docs/images/demo.gif) from the dev server.
//
//   python3 tools/demo/seed.py .devvar && python3 tools/devserver.py &
//   node tools/demo/record.mjs [http://127.0.0.1:8640/] [docs/images/demo.gif]
//
// Drives the app in headless Chrome over the DevTools protocol (no dependencies), draws a mouse
// pointer, captures a PNG per frame and assembles the GIF with ffmpeg (two-pass palette).
import { spawn, execFileSync } from "node:child_process";
import { writeFileSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const [base = "http://127.0.0.1:8640/", out = join(HERE, "../../docs/images/demo.gif")] = process.argv.slice(2);
const W = 1200, H = 760, GIF_WIDTH = 960;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const port = 9300 + Math.floor(Math.random() * 500);
const chrome = spawn("google-chrome", ["--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
  `--remote-debugging-port=${port}`, `--window-size=${W},${H}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), "ss-demo-"))}`, "about:blank"],
  { stdio: "ignore" });
let target;
for (let i = 0; i < 50 && !target; i++) {
  await sleep(200);
  try { target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((t) => t.type === "page"); } catch {}
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let seq = 0;
const pending = new Map();
ws.addEventListener("message", (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
});
const send = (method, params = {}) => new Promise((r) => { const i = ++seq; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const js = async (expr) => {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error(expr + "\n" + JSON.stringify(r.result.exceptionDetails));
  return r.result?.result?.value;
};

// ------------------------------------------------------------------ frames
const dir = mkdtempSync(join(tmpdir(), "ss-frames-"));
const frames = [];
async function frame(ms) {
  const shot = await send("Page.captureScreenshot", { format: "png" });
  const file = join(dir, `f${String(frames.length).padStart(4, "0")}.png`);
  writeFileSync(file, Buffer.from(shot.result.data, "base64"));
  frames.push({ file, ms });
}
const hold = (ms) => frame(ms);

// ------------------------------------------------------------------ pointer and app helpers
// Elements inside the app frame: q(selector) or q(selector, text).
const FIND = `function q(sel, text) {
  const doc = document.getElementById("app").contentDocument;
  const all = Array.from(doc.querySelectorAll(sel));
  return text ? all.find((e) => e.textContent.trim().indexOf(text) === 0) : all[0];
}`;
const at = (find) => js(`(() => { ${FIND} const el = ${find}; const f = document.getElementById("app").getBoundingClientRect();
  const r = el.getBoundingClientRect(); return [f.left + r.left + Math.min(r.width / 2, 60), f.top + r.top + r.height / 2]; })()`);
let pos = [W * 0.72, H * 0.62];
async function pointer(x, y, down = false) {
  pos = [x, y];
  await js(`(() => { const c = document.getElementById("demo-cursor"); c.style.left = ${x} + "px"; c.style.top = ${y} + "px";
    c.classList.toggle("down", ${down}); })()`);
}
async function move(find, steps = 9) {
  const [tx, ty] = await at(find), [sx, sy] = pos;
  for (let i = 1; i <= steps; i++) {
    const t = i / steps, e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
    await pointer(sx + (tx - sx) * e, sy + (ty - sy) * e);
    await frame(40);
  }
}
async function click(find, how = "click") {
  await move(find);
  await pointer(pos[0], pos[1], true);
  await frame(120);
  await js(`(() => { ${FIND} const el = ${find}; const win = document.getElementById("app").contentWindow; const r = el.getBoundingClientRect();
    const o = { bubbles: true, cancelable: true, view: win, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, button: ${how === "contextmenu" ? 2 : 0} };
    if (${JSON.stringify(how)} === "click") el.click(); else el.dispatchEvent(new win.MouseEvent(${JSON.stringify(how)}, o)); })()`);
  await pointer(pos[0], pos[1], false);
}
async function type(find, text) {
  await click(find);
  for (const ch of text) {
    await js(`(() => { ${FIND} const el = ${find}; el.value += ${JSON.stringify(ch)};
      el.dispatchEvent(new (document.getElementById("app").contentWindow.Event)("input", { bubbles: true })); })()`);
    await frame(110);
  }
  await sleep(300);
}
async function select(find, value) {
  await click(find);
  await js(`(() => { ${FIND} const el = ${find}; el.value = ${JSON.stringify(value)};
    el.dispatchEvent(new (document.getElementById("app").contentWindow.Event)("change", { bubbles: true })); })()`);
  await sleep(250);
}

// ------------------------------------------------------------------ the tour
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });
await send("Page.addScriptToEvaluateOnNewDocument", { source: readFileSync(join(HERE, "shim.js"), "utf8") });
await send("Page.navigate", { url: base + "?page=overview" });
await sleep(3000);
await js(`(() => {
  const s = document.createElement("style");
  s.textContent = "#demo-cursor{position:fixed;z-index:99999;pointer-events:none;width:22px;height:22px;margin:-2px 0 0 -3px}" +
    "#demo-cursor:after{content:'';position:absolute;left:-9px;top:-9px;width:22px;height:22px;border-radius:50%;background:rgba(5,127,235,.35);transform:scale(0)}" +
    "#demo-cursor.down:after{transform:scale(1)}";
  document.head.appendChild(s);
  const c = document.createElement("div"); c.id = "demo-cursor";
  c.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M4 2.5l6.6 18.2 2.6-7.4 7.6-2.4z" fill="#fff" stroke="#1d2733" stroke-width="1.5" stroke-linejoin="round"/></svg>';
  document.body.appendChild(c);
})()`);
await pointer(...pos);

// 1. Overview, then a scan
await hold(1800);
await click(`q("#ov-banner [data-scan-btn]")`);
for (let i = 0; i < 8; i++) { await sleep(1300); await frame(450); }
await sleep(1500);
await hold(1600);

// 2. Review the unknown device and mark it as known
await click(`q("#ov-review")`);
await sleep(700);
await hold(1300);
await click(`q("#d-grid tr[data-i]")`);
await hold(300);
await click(`q("#d-grid tr[data-i]")`, "contextmenu");
await hold(900);
await click(`q(".menu-item", "Mark as Known")`);
await sleep(800);
await hold(800);
await select(`q("#d-filter")`, "all");
await hold(1800);

// 3. Search and open a device
await type(`q("#d-search")`, "living");
await hold(700);
await click(`q("#d-grid tr[data-i]")`, "dblclick");
await sleep(300);
await hold(1500);
await click(`q(".dialog .tab", "Details")`);
await hold(1700);
await click(`q(".dialog .tab", "Services")`);
await hold(1500);
await click(`q(".dialog [data-x]")`);
await js(`(() => { ${FIND} const el = q("#d-search"); el.value = "";
  el.dispatchEvent(new (document.getElementById("app").contentWindow.Event)("input", { bubbles: true })); })()`);
await sleep(300);

// 4. Activity and settings
await click(`q(".nav-item[data-page=activity]")`);
await sleep(600);
await hold(1800);
await click(`q("[data-atab=scans]")`);
await hold(1400);
await click(`q(".nav-item[data-page=settings]")`);
await sleep(600);
await hold(1300);
await click(`q("[data-stab=schedule]")`);
await hold(1400);
await click(`q(".nav-item[data-page=overview]")`);
await sleep(700);
await hold(1500);

ws.close();
chrome.kill();

// ------------------------------------------------------------------ GIF
const list = join(dir, "frames.txt");
writeFileSync(list, frames.map((f) => `file '${f.file}'\nduration ${(f.ms / 1000).toFixed(3)}`).join("\n") + `\nfile '${frames.at(-1).file}'\n`);
const scale = `scale=${GIF_WIDTH}:-1:flags=lanczos`;
const palette = join(dir, "palette.png");
execFileSync("ffmpeg", ["-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", list, "-vf", `${scale},palettegen=max_colors=192:stats_mode=diff`, palette]);
execFileSync("ffmpeg", ["-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", list, "-i", palette,
  "-lavfi", `${scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle`, "-fps_mode", "passthrough", "-loop", "0", out]);
rmSync(dir, { recursive: true, force: true });
console.log(`saved ${out} (${frames.length} frames)`);
process.exit(0);
