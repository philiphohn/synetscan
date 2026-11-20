// Screenshots and short GIFs for the wiki (docs/wiki/images/), made from the dev server with
// made-up data.
//
//   VAR=$(mktemp -d) && python3 tools/demo/seed.py "$VAR"
//   # switch every scan off before the daemon starts (see docs/wiki/Local-Development.md):
//   #   scan_on_start, schedule_enabled, use_mdns, use_ssdp, use_ipv6, auto_subnets = false
//   python3 tools/devserver.py --var "$VAR" --port 8641 &
//   node tools/demo/wiki_shots.mjs [http://localhost:8641/] [docs/wiki/images] [only-these,scenes]
//
// Use "localhost", not 127.0.0.1: the UI treats a numeric non-private host as a remote session
// and would grey out "Open Web Interface".
//
// Like tools/demo/record.mjs, it injects tools/demo/shim.js (demo NAS interfaces, a played scan
// instead of a real one). On top of that, a second shim makes every action that would change
// data or send packets answer locally: scan, cancel, wake, config_set, device_known,
// device_update, device_delete, clear_events, clear_offline and reset never reach the service.
// It also shows the default settings, whatever the preview's config.json says.
import { spawn, execFileSync } from "node:child_process";
import { writeFileSync, mkdtempSync, readFileSync, rmSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const [base = "http://localhost:8641/", outDir = join(HERE, "../../docs/wiki/images"), onlyArg = ""] = process.argv.slice(2);
const ONLY = onlyArg ? onlyArg.split(",") : null;
const W = 1200, H = 760, GIF_WIDTH = 880;
mkdirSync(outDir, { recursive: true });

// ------------------------------------------------------------------ the wiki shim
const WIKI_SHIM = `(function () {
  if (!/\\/SynetScan\\/index\\.html/.test(location.pathname)) return;
  var opt = (new URLSearchParams(location.search).get("wiki") || "").split(",");
  function has(k) { return opt.indexOf(k) >= 0; }
  var inner = window.fetch;  // tools/demo/shim.js
  var edits = {}, fresh = has("fresh"), scanAt = null, DURATION = 9000;
  function json(obj) { return Promise.resolve(new Response(JSON.stringify(obj), { headers: { "Content-Type": "application/json" } })); }
  function ok(data) { return json({ success: true, data: data }); }
  function freshBefore() { return fresh && (scanAt === null || Date.now() - scanAt < DURATION); }
  function freshAfter() { return fresh && scanAt !== null && Date.now() - scanAt >= DURATION; }
  var LOCAL = { cancel: {}, wake: { sent: 4 }, device_delete: { deleted: 1 }, clear_events: {}, clear_offline: { deleted: 1 }, reset: {} };
  function applyEdits(d) {
    var e = edits[d.id];
    if (freshAfter()) d.known = true;
    if (!e) return d;
    if (e.known !== undefined) d.known = e.known;
    if (e.name !== undefined) { d.name = e.name; d.display_name = e.name || d.detected_name; }
    if (e.type_user !== undefined) { d.type_user = e.type_user; d.type = e.type_user || d.type_auto || "unknown"; }
    if (e.notes !== undefined) d.notes = e.notes;
    return d;
  }
  function status(st) {
    if (has("noping")) st.ping = false;
    if (freshBefore()) { st.last_scan = scanAt === null ? null : st.last_scan; st.next_scan = null; }
    else if (!st.next_scan) st.next_scan = Math.floor(Date.now() / 1000) + 51 * 60;
    if (st.last_scan && has("v6")) st.last_scan.ipv6 = { enabled: true, ifaces: ["eth0"], routable: true, with_ipv6: 4, only: 1 };
    if (st.last_scan && has("v6off")) st.last_scan.ipv6 = { enabled: true, ifaces: [], routable: false, with_ipv6: 2, only: 0 };
    return st;
  }
  window.fetch = function (url, opts) {
    var m = /action=(\\w+)/.exec(String(url)), action = m && m[1];
    var body = null;
    try { body = opts && opts.body ? JSON.parse(opts.body) : null; } catch (e) { body = null; }
    if (LOCAL[action]) return ok(LOCAL[action]);
    if (action === "device_known") { (body.ids || []).forEach(function (id) { edits[id] = Object.assign(edits[id] || {}, { known: !!body.known }); }); return ok({}); }
    if (action === "device_update") { edits[body.id] = Object.assign(edits[body.id] || {}, { name: body.name, type_user: body.type_user, notes: body.notes, known: body.known }); return ok({ id: body.id }); }
    if (action === "config_set") {
      var t = (body.config && body.config.custom_targets || "").split(/[\\n,]/).map(function (x) { return x.trim(); }).filter(Boolean);
      var bad = t.filter(function (x) { return /\\/3[3-9]$/.test(x); })[0];
      if (bad) return json({ success: false, error: { code: "invalid_config", message: "custom_targets: invalid target: " + bad, field: "custom_targets", value: bad } });
      return ok({ config: body.config });
    }
    if (action === "client" && has("remote")) return ok({ ip: "203.0.113.50", local: false, via: "relay" });
    if (action === "scan" && fresh) scanAt = Date.now();
    return inner(url, opts).then(function (r) {
      return r.clone().json().then(function (j) {
        if (!j.success) return r;
        var d = j.data;
        if (action === "status") j.data = status(d);
        if (action === "overview") {
          d.status = status(d.status);
          var known = Object.keys(edits).filter(function (k) { return edits[k].known; }).length;
          d.counts.unknown = Math.max(0, d.counts.unknown - known);
          d.counts.new24h = Math.max(0, d.counts.new24h - known);
          if (freshBefore()) { d.counts = { total: 0, online: 0, offline: 0, new24h: 0, unknown: 0 }; d.types = {}; d.events = []; d.scans = []; }
          if (freshAfter()) {
            d.counts = { total: d.counts.online, online: d.counts.online, offline: 0, new24h: 0, unknown: 0 };
            d.events = [{ ts: Math.floor(Date.now() / 1000), kind: "baseline", id: null, name: "", ip: "", mac: "", detail: String(d.counts.online) }];
          }
        }
        if (action === "devices") {
          if (freshBefore()) d.devices = [];
          else d.devices = d.devices.filter(function (x) { return !freshAfter() || x.online; }).map(applyEdits);
        }
        if (action === "events" && freshBefore()) d.events = [];
        if (action === "config_get") {
          d.config = Object.assign({}, d.defaults, { excluded_interfaces: [], custom_targets: has("custom") ? ["192.168.20.0/24", "10.0.0.1-50"] : [] });
        }
        return new Response(JSON.stringify(j), { headers: { "Content-Type": "application/json" } });
      }, function () { return r; });
    });
  };
})();`;

// ------------------------------------------------------------------ browser
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const port = 9300 + Math.floor(Math.random() * 500);
const chrome = spawn("google-chrome", ["--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
  `--remote-debugging-port=${port}`, `--window-size=${W},${H}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), "ss-wiki-"))}`, "about:blank"],
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
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });
await send("Page.addScriptToEvaluateOnNewDocument", { source: readFileSync(join(HERE, "shim.js"), "utf8") });
await send("Page.addScriptToEvaluateOnNewDocument", { source: WIKI_SHIM });

// Elements inside the app frame: q(selector) or q(selector, text).
const FIND = `function q(sel, text) {
  const doc = document.getElementById("app").contentDocument;
  const all = Array.from(doc.querySelectorAll(sel));
  const el = text ? all.find((e) => e.textContent.trim().indexOf(text) === 0) : all[0];
  if (!el) throw new Error("not found: " + sel + " " + (text || ""));
  return el;
}`;
const CURSOR = `(() => {
  if (document.getElementById("demo-cursor")) return;
  const s = document.createElement("style");
  s.textContent = "#demo-cursor{position:fixed;z-index:99999;pointer-events:none;width:22px;height:22px;margin:-2px 0 0 -3px}" +
    "#demo-cursor:after{content:'';position:absolute;left:-9px;top:-9px;width:22px;height:22px;border-radius:50%;background:rgba(5,127,235,.35);transform:scale(0)}" +
    "#demo-cursor.down:after{transform:scale(1)}#demo-cursor.off{display:none}";
  document.head.appendChild(s);
  const c = document.createElement("div"); c.id = "demo-cursor"; c.className = "off";
  c.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M4 2.5l6.6 18.2 2.6-7.4 7.6-2.4z" fill="#fff" stroke="#1d2733" stroke-width="1.5" stroke-linejoin="round"/></svg>';
  document.body.appendChild(c);
})()`;

async function open(query) {
  await send("Page.navigate", { url: base + query });
  await sleep(2600);
  await js(CURSOR);
}
const at = (find) => js(`(() => { ${FIND} const el = ${find}; const f = document.getElementById("app").getBoundingClientRect();
  const r = el.getBoundingClientRect(); return [f.left + r.left + Math.min(r.width / 2, 60), f.top + r.top + r.height / 2]; })()`);
const rectOf = (find, pad = 0) => js(`(() => { ${FIND} const el = ${find}; const f = document.getElementById("app").getBoundingClientRect();
  const r = el.getBoundingClientRect(); return { x: Math.max(0, f.left + r.left - ${pad}), y: Math.max(0, f.top + r.top - ${pad}),
  width: r.width + 2 * ${pad}, height: r.height + 2 * ${pad}, scale: 1 }; })()`);

// --- pointer (only drawn while a GIF is recorded)
let pos = [W * 0.72, H * 0.62], recording = null;
async function pointer(x, y, down = false) {
  pos = [x, y];
  await js(`(() => { const c = document.getElementById("demo-cursor"); c.style.left = ${x} + "px"; c.style.top = ${y} + "px";
    c.classList.toggle("down", ${down}); c.classList.toggle("off", ${!recording}); })()`);
}
async function frame(ms) {
  if (!recording) return;
  const shot = await send("Page.captureScreenshot", { format: "png" });
  const file = join(recording.dir, `f${String(recording.frames.length).padStart(4, "0")}.png`);
  writeFileSync(file, Buffer.from(shot.result.data, "base64"));
  recording.frames.push({ file, ms });
}
async function move(find, steps = 8) {
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
// right-click at the pointer position inside the frame, so the menu opens where a user would see it
async function rightClick(find) {
  await move(find);
  await pointer(pos[0], pos[1], true);
  await frame(120);
  await js(`(() => { ${FIND} const el = ${find}; const win = document.getElementById("app").contentWindow;
    const f = document.getElementById("app").getBoundingClientRect();
    el.dispatchEvent(new win.MouseEvent("contextmenu", { bubbles: true, cancelable: true, view: win, button: 2,
      clientX: ${pos[0]} - f.left, clientY: ${pos[1]} - f.top })); })()`);
  await pointer(pos[0], pos[1], false);
}
async function type(find, text, clear = true) {
  await click(find);
  if (clear) await js(`(() => { ${FIND} ${find}.value = ""; })()`);
  for (const ch of text) {
    await js(`(() => { ${FIND} const el = ${find}; el.value += ${JSON.stringify(ch)};
      el.dispatchEvent(new (document.getElementById("app").contentWindow.Event)("input", { bubbles: true })); })()`);
    await frame(90);
  }
  await sleep(250);
}
async function setValue(find, value, ev = "change") {
  await js(`(() => { ${FIND} const el = ${find}; el.value = ${JSON.stringify(value)};
    el.dispatchEvent(new (document.getElementById("app").contentWindow.Event)(${JSON.stringify(ev)}, { bubbles: true })); })()`);
  await sleep(300);
}
const hold = (ms) => frame(ms);

async function png(name, clip) {
  await js(`document.getElementById("demo-cursor").classList.add("off")`);
  const shot = await send("Page.captureScreenshot", clip ? { format: "png", clip } : { format: "png" });
  writeFileSync(join(outDir, name), Buffer.from(shot.result.data, "base64"));
  console.log("saved", name);
}
function gifStart() { recording = { dir: mkdtempSync(join(tmpdir(), "ss-wiki-frames-")), frames: [] }; }
function gifEnd(name) {
  const { dir, frames } = recording;
  recording = null;
  const list = join(dir, "frames.txt");
  writeFileSync(list, frames.map((f) => `file '${f.file}'\nduration ${(f.ms / 1000).toFixed(3)}`).join("\n") + `\nfile '${frames.at(-1).file}'\n`);
  const scale = `scale=${GIF_WIDTH}:-1:flags=lanczos`;
  const palette = join(dir, "palette.png");
  const out = join(outDir, name);
  execFileSync("ffmpeg", ["-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", list, "-vf", `${scale},palettegen=max_colors=128:stats_mode=diff`, palette]);
  execFileSync("ffmpeg", ["-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", list, "-i", palette,
    "-lavfi", `${scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle`, "-fps_mode", "passthrough", "-loop", "0", out]);
  rmSync(dir, { recursive: true, force: true });
  console.log(`saved ${name} (${frames.length} frames)`);
}

// ------------------------------------------------------------------ scenes
const scenes = {
  async overview() { await open("?page=overview"); await png("overview.png"); },
  async "overview-de"() { await open("?page=overview&lang=de"); await png("overview-de.png"); },
  async "first-run"() { await open("?page=overview&wiki=fresh"); await png("overview-first-run.png"); },
  async scanning() {
    await open("?page=overview");
    await click(`q("#ov-banner [data-scan-btn]")`);
    await sleep(3200);
    await png("overview-scanning.png");
  },
  async devices() { await open("?page=devices"); await png("devices.png"); },
  async unconfirmed() {
    await open("?page=devices");
    await setValue(`q("#d-filter")`, "unknown");
    await png("devices-unconfirmed.png");
  },
  async dialog() {
    await open("?page=devices");
    await setValue(`q("#d-search")`, "macbook", "input");
    await sleep(400);
    await click(`q("#d-grid tr[data-i]")`, "dblclick");
    await sleep(500);
    await png("device-general.png", await rectOf(`q(".dialog")`, 8));
    await click(`q(".dialog .tab", "Details")`);
    await sleep(300);
    await png("device-details.png", await rectOf(`q(".dialog")`, 8));
  },
  async services() {
    await open("?page=devices");
    await setValue(`q("#d-search")`, "laserjet", "input");
    await sleep(400);
    await click(`q("#d-grid tr[data-i]")`, "dblclick");
    await sleep(500);
    await click(`q(".dialog .tab", "Services")`);
    await sleep(300);
    await png("device-services.png", await rectOf(`q(".dialog")`, 8));
  },
  async ipv6only() {
    await open("?page=devices");
    await setValue(`q("#d-search")`, "heat pump", "input");
    await sleep(400);
    await click(`q("#d-grid tr[data-i]")`, "dblclick");
    await sleep(500);
    await click(`q(".dialog .tab", "Details")`);
    await sleep(300);
    await png("device-details-ipv6-only.png", await rectOf(`q(".dialog")`, 8));
  },
  async menus() {
    await open("?page=devices");
    // the printer row: it has a web interface
    const rows = await js(`(() => { ${FIND} return Array.from(document.getElementById("app").contentDocument.querySelectorAll("#d-grid tr[data-i]")).map((r) => r.textContent); })()`);
    const idx = rows.findIndex((t) => t.indexOf("HP LaserJet") >= 0);
    await rightClick(`q("#d-grid tr[data-i='${idx}'] td:nth-child(2)")`);
    await sleep(300);
    await png("context-menu.png", await rectOf(`q(".menu")`, 10));
    await open("?page=devices");
    await click(`q("#d-action")`);
    await sleep(300);
    await png("action-menu.png", await rectOf(`q(".menu")`, 10));
  },
  async remote() {
    await open("?page=devices&wiki=remote");
    const rows = await js(`(() => Array.from(document.getElementById("app").contentDocument.querySelectorAll("#d-grid tr[data-i]")).map((r) => r.textContent))()`);
    const idx = rows.findIndex((t) => t.indexOf("HP LaserJet") >= 0);
    await rightClick(`q("#d-grid tr[data-i='${idx}'] td:nth-child(2)")`);
    await sleep(300);
    await png("context-menu-remote.png", await rectOf(`q(".menu")`, 10));
  },
  async activity() {
    await open("?page=activity");
    await png("activity-events.png");
    await click(`q("[data-atab=scans]")`);
    await sleep(400);
    await png("activity-scan-history.png");
  },
  async settings() {
    await open("?page=settings&wiki=custom");
    await png("settings-scan-targets.png");
    await click(`q("[data-stab=schedule]")`); await sleep(300);
    await png("settings-schedule.png");
    await click(`q("[data-stab=ports]")`); await sleep(300);
    await png("settings-ports.png");
    await open("?page=settings&wiki=v6");
    await click(`q("[data-stab=advanced]")`); await sleep(300);
    await png("settings-advanced.png");
  },
  async noping() {
    await open("?page=settings&wiki=noping,v6off");
    await click(`q("[data-stab=advanced]")`); await sleep(300);
    await png("settings-ping-unavailable.png", await rectOf(`q("[data-sbody=advanced] .form-section")`, 6));
  },
  async invalid() {
    await open("?page=settings&wiki=custom");
    await setValue(`q("#s-custom")`, "192.168.20.0/24\n10.0.0.1-50\n192.168.30.0/33", "input");
    await click(`q("#s-apply")`);
    await sleep(600);
    await png("settings-invalid-range.png");
  },

  // ---- GIFs
  async "gif-first-scan"() {
    await open("?page=overview&wiki=fresh");
    gifStart();
    await pointer(...pos);
    await hold(1600);
    await click(`q("#ov-banner [data-scan-btn]")`);
    for (let i = 0; i < 7; i++) { await sleep(1300); await frame(450); }
    await sleep(1800);
    await hold(1800);
    await click(`q(".nav-item[data-page=devices]")`);
    await sleep(700);
    await hold(2400);
    gifEnd("first-scan.gif");
  },
  async "gif-review"() {
    await open("?page=overview");
    gifStart();
    await pointer(...pos);
    await hold(1500);
    await click(`q("#ov-review")`);
    await sleep(700);
    await hold(1300);
    await rightClick(`q("#d-grid tr[data-i] td:nth-child(2)")`);
    await hold(1000);
    await click(`q(".menu-item", "Mark as Known")`);
    await sleep(800);
    await hold(1000);
    await click(`q(".nav-item[data-page=overview]")`);
    await sleep(800);
    await hold(2200);
    gifEnd("review-new-device.gif");
  },
  async "gif-edit"() {
    await open("?page=devices");
    gifStart();
    await pointer(...pos);
    await hold(1000);
    await type(`q("#d-search")`, "esp32");
    await hold(500);
    await click(`q("#d-grid tr[data-i]")`, "dblclick");
    await sleep(400);
    await hold(1000);
    await type(`q("#dv-name")`, "Garden sensor");
    await click(`q("#dv-type")`);
    await setValue(`q("#dv-type")`, "iot");
    await hold(500);
    await type(`q("#dv-notes")`, "ESP32 in the shed, flashed 2026-10");
    await click(`q("#dv-known")`);
    await hold(700);
    await click(`q(".dialog .btn.primary")`);
    await sleep(700);
    await hold(2200);
    gifEnd("edit-device.gif");
  },
};

for (const [name, fn] of Object.entries(scenes)) {
  if (ONLY && !ONLY.includes(name)) continue;
  try { await fn(); } catch (e) { console.error("scene", name, "failed:", e.message); recording = null; }
}
ws.close();
chrome.kill();
process.exit(0);
