// Screenshot helper using the Chrome DevTools Protocol (no dependencies).
// node tools/shot.mjs <url> <out.png> [js-to-run-inside-the-app-iframe] [width] [height]
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, out, js = "", w = "1400", h = "900"] = process.argv.slice(2);
const port = 9300 + Math.floor(Math.random() * 500);
const chrome = spawn("google-chrome", ["--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
  `--remote-debugging-port=${port}`, `--window-size=${w},${h}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), "ss-chrome-"))}`, "about:blank"],
  { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let target;
for (let i = 0; i < 50 && !target; i++) {
  await sleep(200);
  try { target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((t) => t.type === "page"); } catch {}
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0;
const pending = new Map();
ws.addEventListener("message", (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: +w, height: +h, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url });
await sleep(2500);
if (js) {
  const res = await send("Runtime.evaluate", {
    expression: `(async () => { const win = document.querySelector("iframe").contentWindow; const doc = win.document; ${js} })()`,
    awaitPromise: true,
  });
  if (res.result?.exceptionDetails) console.error(JSON.stringify(res.result.exceptionDetails));
  await sleep(1200);
}
const shot = await send("Page.captureScreenshot", { format: "png" });
writeFileSync(out, Buffer.from(shot.result.data, "base64"));
ws.close();
chrome.kill();
console.log("saved", out);
process.exit(0);
