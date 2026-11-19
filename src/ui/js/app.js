/* SynetScan front end – vanilla JS, DSM 7 style. */
(function () {
  "use strict";
  var I = window.SS_ICONS, TC = window.SS_TYPE_COLORS;

  // ------------------------------------------------------------------ DSM integration
  var SYNO = null;
  try { if (window.parent !== window && window.parent.SYNO) SYNO = window.parent.SYNO; } catch (e) { /* cross origin */ }
  var params = new URLSearchParams(location.search);
  var TOPLEVEL = window.parent === window;
  var APP_ID = "SYNO.SDS.SynetScan.Instance";

  // The DSM window passes the session token in the fragment (never sent to a server). Keep it in
  // memory and take it out of the address bar.
  var handedToken = new URLSearchParams(location.hash.slice(1)).get("SynoToken") || "";
  if (location.hash) {
    try { history.replaceState(null, "", location.pathname + location.search); } catch (e) { /* ignore */ }
  }

  function synoToken() {
    // DSM renews the token; the desktop's current value wins over the one handed over at launch.
    try {
      if (SYNO && SYNO.SDS && SYNO.SDS.Session && SYNO.SDS.Session.SynoToken) return SYNO.SDS.Session.SynoToken;
      if (!TOPLEVEL && window.parent._S) { var t = window.parent._S("SynoToken"); if (t) return t; }
    } catch (e) { /* ignore */ }
    return handedToken;
  }

  // Clicks inside the iframe are invisible to DSM: tell the window to come to the front.
  if (!TOPLEVEL) {
    document.addEventListener("mousedown", function () {
      try { window.parent.postMessage("synetscan:activate", location.origin); } catch (e) { /* ignore */ }
    }, true);
  }

  function detectLang() {
    var l = params.get("lang");
    if (!l || l === "def") {
      try { l = SYNO.SDS.Session.lang; if (!l || l === "def") l = SYNO.SDS.Session.sys_lang; } catch (e) { l = ""; }
    }
    if (!l) l = (navigator.language || "en").slice(0, 2);
    l = String(l).toLowerCase();
    return (l === "ger" || l === "de" || l.indexOf("de") === 0) ? "de" : "en";
  }
  var LANG = detectLang();
  var STR = window.SS_I18N;

  function T(key) {
    var s = (STR[LANG] && STR[LANG][key]) || STR.en[key] || key;
    for (var i = 1; i < arguments.length; i++) s = s.split("{" + (i - 1) + "}").join(arguments[i]);
    return s;
  }

  // Inherit DSM's own font so the app is indistinguishable from native windows.
  try {
    var pf = window.parent.getComputedStyle(window.parent.document.body).fontFamily;
    if (pf && window.parent !== window) document.documentElement.style.setProperty("--font", pf);
  } catch (e) { /* ignore */ }

  // ------------------------------------------------------------------ helpers
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function ipNum(ip) {
    var p = String(ip || "").split(".");
    return p.length === 4 ? ((+p[0] * 256 + +p[1]) * 256 + +p[2]) * 256 + +p[3] : 0;
  }
  function nowSec() { return Math.floor(Date.now() / 1000); }
  var LOCALE = LANG === "de" ? "de-DE" : undefined;
  function fmtTime(ts) {
    if (!ts) return "–";
    // Show times like DSM does: in the NAS's time zone, not the browser's.
    var off = S.status && typeof S.status.tz_offset === "number" ? S.status.tz_offset : null;
    var d = new Date((ts + (off === null ? 0 : off)) * 1000);
    var o = off === null ? {} : { timeZone: "UTC" };
    return d.toLocaleDateString(LOCALE, Object.assign({ year: "numeric", month: "2-digit", day: "2-digit" }, o)) + " " +
      d.toLocaleTimeString(LOCALE, Object.assign({ hour: "2-digit", minute: "2-digit" }, o));
  }
  function fmtNum(n, digits) {
    return Number(n).toLocaleString(LOCALE, { maximumFractionDigits: digits === undefined ? 1 : digits });
  }
  function rel(ts) {
    if (!ts) return T("never");
    var d = nowSec() - ts;
    if (d < 0) {
      d = -d;
      return d < 3600 ? T("in_min", Math.max(1, Math.round(d / 60))) : T("in_h", Math.round(d / 3600));
    }
    if (d < 60) return T("just_now");
    if (d < 3600) return T("min_ago", Math.floor(d / 60));
    if (d < 86400) return T("h_ago", Math.floor(d / 3600));
    if (d < 86400 * 14) return T("d_ago", Math.floor(d / 86400));
    return fmtTime(ts);
  }
  function typeName(t) { return T("type_" + (t || "unknown")); }
  function devIcon(type, cls) {
    var c = TC[type] || TC.unknown;
    return '<span class="devicon ' + (cls || "") + '" style="background:' + c[0] + ";color:" + c[1] + '">' + (I["t_" + type] || I.t_unknown) + "</span>";
  }
  function debounce(fn, ms) {
    var t; return function () { var a = arguments, self = this; clearTimeout(t); t = setTimeout(function () { fn.apply(self, a); }, ms); };
  }

  // ------------------------------------------------------------------ API
  function ApiError(code, message, extra) { this.code = code; this.message = message; this.extra = extra || {}; }

  function api(action, body) {
    var opts = { method: body === undefined ? "GET" : "POST", credentials: "same-origin",
      headers: { "X-SYNO-TOKEN": synoToken() } };
    if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    return fetch("api.cgi?action=" + encodeURIComponent(action), opts).then(function (r) {
      return r.text().then(function (txt) {
        var j;
        try { j = JSON.parse(txt); } catch (e) { throw new ApiError("http", "HTTP " + r.status); }
        if (!j.success) throw new ApiError(j.error && j.error.code, j.error && j.error.message, j.error);
        return j.data;
      });
    }, function () { throw new ApiError("network", "Network error"); });
  }

  // Translated text for an API error; the English message from the service is only a fallback.
  function errorText(err) {
    var code = err && err.code, x = (err && err.extra) || {};
    if (code === "invalid_config") {
      var key = "err_cfg_" + x.field;
      return STR.en[key] ? T(key, x.value) : T("err_cfg", x.field, x.value);
    }
    if (code && STR.en["err_" + code]) return T("err_" + code);
    return T("err_generic", (err && err.message) || err);
  }

  function handleError(err) {
    var code = err && err.code;
    if (code === "auth") return fatal(T(TOPLEVEL ? "err_auth_tab" : "err_auth"), TOPLEVEL);
    if (code === "permission") return fatal(T("err_permission"));
    if (code === "daemon" || code === "daemon_perm") return fatal(T("err_" + code) + (code === "daemon_perm" ? " (" + err.message + ")" : ""));
    toast(errorText(err), "err");
  }

  // ------------------------------------------------------------------ UI widgets
  function toast(text, kind) {
    kind = kind || "ok";
    var wrap = $(".toast-wrap");
    var el = document.createElement("div");
    el.className = "toast " + kind;
    el.innerHTML = (kind === "err" ? I.warn : kind === "info" ? I.info : I.check) + "<span>" + esc(text) + "</span>";
    wrap.appendChild(el);
    setTimeout(function () { el.style.transition = "opacity .3s"; el.style.opacity = "0"; }, 3200);
    setTimeout(function () { el.remove(); }, 3600);
  }

  function dialog(opts) {
    var mask = document.createElement("div");
    mask.className = "mask";
    var tabs = opts.tabs || null;
    var html = '<div class="dialog" style="width:' + (opts.width || 480) + 'px">' +
      '<div class="dialog-head"><span>' + esc(opts.title) + '</span><span class="x" data-x>' + I.close + "</span></div>";
    if (tabs) {
      html += '<div class="tabs">' + tabs.map(function (t, i) {
        return '<div class="tab' + (i === 0 ? " active" : "") + '" data-tab="' + i + '">' + esc(t.title) + "</div>";
      }).join("") + "</div>";
      html += '<div class="dialog-body" style="height:' + (opts.height || 380) + 'px">' + tabs.map(function (t, i) {
        return '<div class="dtab' + (i === 0 ? "" : " hidden") + '" data-body="' + i + '">' + t.html + "</div>";
      }).join("") + "</div>";
    } else {
      html += '<div class="dialog-body">' + opts.html + "</div>";
    }
    html += '<div class="dialog-foot"><div class="left"></div></div></div>';
    mask.innerHTML = html;
    var foot = $(".dialog-foot", mask);
    var api_ = { el: mask, close: close };
    (opts.buttons || []).forEach(function (b) {
      var btn = document.createElement("button");
      btn.className = "btn" + (b.primary ? " primary" : "") + (b.danger ? " danger" : "");
      btn.innerHTML = (b.icon ? I[b.icon] : "") + "<span>" + esc(b.text) + "</span>";
      if (b.disabled) btn.disabled = true;
      btn.onclick = function () { if (!b.onClick || b.onClick(api_) !== false) close(); };
      (b.left ? $(".left", foot) : foot).appendChild(btn);
    });
    function close() { mask.remove(); document.removeEventListener("keydown", onKey); if (opts.onClose) opts.onClose(); }
    function onKey(e) { if (e.key === "Escape") close(); }
    document.addEventListener("keydown", onKey);
    $("[data-x]", mask).onclick = close;
    $$(".tab", mask).forEach(function (t) {
      t.onclick = function () {
        $$(".tab", mask).forEach(function (x) { x.classList.toggle("active", x === t); });
        $$(".dtab", mask).forEach(function (b) { b.classList.toggle("hidden", b.getAttribute("data-body") !== t.getAttribute("data-tab")); });
      };
    });
    document.body.appendChild(mask);
    var first = $("input, textarea, select", mask);
    if (first && opts.focus !== false) first.focus();
    return api_;
  }

  function confirmBox(text, danger) {
    return new Promise(function (resolve) {
      var done = false;
      dialog({
        title: T("app"), width: 440, focus: false,
        html: '<div class="msg">' + (danger ? '<span style="color:var(--orange)">' + I.warn + "</span>" : '<span style="color:var(--blue)">' + I.info + "</span>") + "<div>" + esc(text) + "</div></div>",
        buttons: [
          { text: T("cancel"), onClick: function () { done = true; resolve(false); } },
          { text: T("yes"), primary: true, onClick: function () { done = true; resolve(true); } },
        ],
        onClose: function () { if (!done) resolve(false); },
      });
    });
  }

  var menuEl = null;
  function closeMenu() { if (menuEl) { menuEl.remove(); menuEl = null; } }
  function showMenu(x, y, items) {
    closeMenu();
    menuEl = document.createElement("div");
    menuEl.className = "menu";
    items.forEach(function (it) {
      if (it === "-") { var s = document.createElement("div"); s.className = "menu-sep"; menuEl.appendChild(s); return; }
      var d = document.createElement("div");
      d.className = "menu-item" + (it.disabled ? " disabled" : "") + (it.hint ? " has-hint" : "");
      d.innerHTML = (it.icon ? I[it.icon] : "") + "<span>" + esc(it.text) + (it.hint ? '<small class="menu-hint">' + esc(it.hint) + "</small>" : "") + "</span>";
      if (it.hint) d.title = it.hint;
      d.onclick = function () { closeMenu(); it.onClick(); };
      menuEl.appendChild(d);
    });
    document.body.appendChild(menuEl);
    var r = menuEl.getBoundingClientRect();
    menuEl.style.left = Math.min(x, innerWidth - r.width - 6) + "px";
    menuEl.style.top = Math.min(y, innerHeight - r.height - 6) + "px";
  }
  document.addEventListener("mousedown", function (e) { if (menuEl && !menuEl.contains(e.target)) closeMenu(); });
  window.addEventListener("blur", closeMenu);

  function copyText(text) {
    function fallback() {
      var ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); } catch (e) { /* ignore */ }
      ta.remove();
    }
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).catch(fallback); else fallback();
    toast(T("copied"), "info");
  }

  // ------------------------------------------------------------------ Grid
  function Grid(el, cfg) {
    this.el = el; this.cfg = cfg; this.rows = []; this.view = []; this.sel = {}; this.anchor = null;
    this.sort = cfg.sort || null;
    try {
      var saved = cfg.storeKey && JSON.parse(localStorage.getItem("synetscan.sort." + cfg.storeKey) || "null");
      if (saved && cfg.columns.some(function (c) { return c.key === saved.key; })) this.sort = saved;
    } catch (e) { /* ignore */ }
    var self = this;
    el.addEventListener("click", function (e) {
      var th = e.target.closest("th[data-k]");
      if (th) { self.toggleSort(th.getAttribute("data-k")); return; }
      var tr = e.target.closest("tr[data-i]");
      if (!tr) { if (e.target === el || e.target.closest(".empty")) self.select([]); return; }
      if (e.target.closest("[data-action]")) return;
      var i = +tr.getAttribute("data-i"), id = self.view[i][cfg.idKey];
      if (e.shiftKey && self.anchor !== null) {
        var a = Math.min(self.anchor, i), b = Math.max(self.anchor, i), ids = [];
        for (var k = a; k <= b; k++) ids.push(self.view[k][cfg.idKey]);
        self.select(ids, true);
      } else if (e.ctrlKey || e.metaKey) {
        if (self.sel[id]) delete self.sel[id]; else self.sel[id] = true;
        self.anchor = i; self.paint();
      } else { self.anchor = i; self.select([id]); }
    });
    el.addEventListener("dblclick", function (e) {
      var tr = e.target.closest("tr[data-i]");
      if (tr && cfg.onOpen) cfg.onOpen(self.view[+tr.getAttribute("data-i")]);
    });
    el.addEventListener("contextmenu", function (e) {
      var tr = e.target.closest("tr[data-i]");
      if (!tr || !cfg.onMenu) return;
      e.preventDefault();
      var row = self.view[+tr.getAttribute("data-i")];
      if (!self.sel[row[cfg.idKey]]) { self.anchor = +tr.getAttribute("data-i"); self.select([row[cfg.idKey]]); }
      cfg.onMenu(e, self.selected());
    });
  }
  Grid.prototype.toggleSort = function (k) {
    if (this.sort && this.sort.key === k) this.sort.dir = -this.sort.dir; else this.sort = { key: k, dir: 1 };
    try { if (this.cfg.storeKey) localStorage.setItem("synetscan.sort." + this.cfg.storeKey, JSON.stringify(this.sort)); } catch (e) { /* ignore */ }
    this.render();
  };
  Grid.prototype.setRows = function (rows) {
    this.rows = rows;
    var ids = {}, self = this;
    rows.forEach(function (r) { ids[r[self.cfg.idKey]] = true; });
    Object.keys(this.sel).forEach(function (k) { if (!ids[k]) delete self.sel[k]; });
    this.render();
  };
  Grid.prototype.select = function (ids, silent) {
    var self = this; this.sel = {};
    ids.forEach(function (id) { self.sel[id] = true; });
    this.paint();
  };
  Grid.prototype.selected = function () {
    var self = this; return this.view.filter(function (r) { return self.sel[r[self.cfg.idKey]]; });
  };
  Grid.prototype.paint = function () {
    var self = this;
    $$("tbody tr[data-i]", this.el).forEach(function (tr) {
      var r = self.view[+tr.getAttribute("data-i")];
      tr.classList.toggle("selected", !!self.sel[r[self.cfg.idKey]]);
    });
    if (this.cfg.onSelect) this.cfg.onSelect(this.selected());
  };
  Grid.prototype.render = function () {
    var cfg = this.cfg, self = this, avail = this.el.clientWidth || 9999;
    var cols = cfg.columns.filter(function (c) { return !c.hideBelow || avail >= c.hideBelow; });
    if (cfg.flexMin) {
      // drop optional columns (highest `hide` first) until the flexible column has room
      var fixed = function () { return cols.reduce(function (n, c) { return n + (parseInt(c.width, 10) || 0); }, 0); };
      while (avail - fixed() < cfg.flexMin) {
        var cand = cols.filter(function (c) { return c.hide; }).sort(function (a, b) { return b.hide - a.hide; })[0];
        if (!cand) break;
        cols = cols.filter(function (c) { return c !== cand; });
      }
    }
    var rows = this.rows.slice();
    if (this.sort) {
      var col = cfg.columns.filter(function (c) { return c.key === self.sort.key; })[0];
      if (col) {
        var val = col.sortVal || function (r) { return r[col.key]; };
        var dir = this.sort.dir;
        rows.sort(function (a, b) {
          var x = val(a), y = val(b);
          if (typeof x === "string" || typeof y === "string") return dir * String(x || "").localeCompare(String(y || ""), undefined, { numeric: true, sensitivity: "base" });
          return dir * ((x || 0) - (y || 0));
        });
      }
    }
    this.view = rows;
    var h = '<table class="grid"><colgroup>' + cols.map(function (c) { return '<col style="width:' + (c.width || "auto") + '">'; }).join("") + "</colgroup><thead><tr>";
    h += cols.map(function (c) {
      var s = self.sort && self.sort.key === c.key;
      return "<th" + (c.sortable === false ? "" : ' data-k="' + c.key + '"') + (s ? ' class="sorted"' : "") + ' title="' + esc(c.title) + '">' + esc(c.title) +
        (s ? '<span class="arrow">' + (self.sort.dir > 0 ? "▲" : "▼") + "</span>" : "") + "</th>";
    }).join("") + "</tr></thead><tbody>";
    h += rows.map(function (r, i) {
      return '<tr data-i="' + i + '"' + (self.sel[r[cfg.idKey]] ? ' class="selected"' : "") + ">" +
        cols.map(function (c) { return "<td" + (c.title_attr ? ' title="' + esc(c.title_attr(r)) + '"' : "") + ">" + (c.render ? c.render(r) : esc(r[c.key])) + "</td>"; }).join("") + "</tr>";
    }).join("");
    h += "</tbody></table>";
    if (!rows.length) h += '<div class="empty">' + (cfg.emptyIcon ? I[cfg.emptyIcon] : "") + esc(cfg.empty()) + "</div>";
    var top = this.el.scrollTop;
    this.el.innerHTML = h;
    this.el.scrollTop = top;
    if (cfg.onRender) cfg.onRender(rows);
    if (cfg.onSelect) cfg.onSelect(this.selected());
  };

  // ------------------------------------------------------------------ state
  var S = {
    page: "overview", status: null, devices: [], portNames: {}, types: [], config: null,
    filter: "all", typeFilter: "", search: "", wasScanning: false, loaded: {},
  };

  // ------------------------------------------------------------------ shell
  function buildShell() {
    var nav = [["overview", "nav_overview"], ["devices", "nav_devices"], ["activity", "nav_activity"], ["settings", "nav_settings"]];
    document.title = T("app");
    $("#app").innerHTML =
      '<div class="app">' +
      '<div class="nav">' + nav.map(function (n) {
        return '<div class="nav-item" data-page="' + n[0] + '">' + I[n[0]] + "<span>" + esc(T(n[1])) + "</span>" +
          (n[0] === "devices" ? '<span class="badge new hidden" id="nav-badge"></span>' : "") + "</div>";
      }).join("") +
      '<div class="nav-spacer"></div><div class="nav-status" id="nav-status"></div></div>' +
      '<div class="main">' +
      '<div class="page" id="page-overview"><div class="page-scroll" id="ov"></div></div>' +
      '<div class="page" id="page-devices">' + devicesSkeleton() + "</div>" +
      '<div class="page" id="page-activity">' + activitySkeleton() + "</div>" +
      '<div class="page" id="page-settings"><div id="settings-root" style="display:flex;flex-direction:column;flex:1;min-height:0"></div></div>' +
      "</div></div><div class=\"toast-wrap\"></div>";
    $$(".nav-item").forEach(function (n) { n.onclick = function () { go(n.getAttribute("data-page")); }; });
    initDevices();
    initActivity();
  }

  function go(page) {
    S.page = page;
    $$(".nav-item").forEach(function (n) { n.classList.toggle("active", n.getAttribute("data-page") === page); });
    $$(".page").forEach(function (p) { p.classList.toggle("active", p.id === "page-" + page); });
    try { localStorage.setItem("synetscan.page", page); } catch (e) { /* ignore */ }
    refreshPage();
  }

  function refreshPage() {
    if (S.page === "overview") return loadOverview();
    if (S.page === "devices") return loadDevices();
    if (S.page === "activity") return loadActivity();
    if (S.page === "settings") return loadSettings();
  }

  function fatal(text, offerDsm) {
    stopPolling();
    $("#app").innerHTML = '<div class="fatal"><div class="box">' + I.warn + "<h2>" + esc(T("err_title")) + "</h2><p>" + esc(text) +
      '</p><div style="display:flex;gap:8px;justify-content:center">' +
      (offerDsm ? '<button class="btn primary" id="open-dsm">' + esc(T("open_in_dsm")) + "</button>" : "") +
      '<button class="btn' + (offerDsm ? "" : " primary") + '" id="retry">' + esc(T("retry")) + "</button></div></div></div>";
    $("#retry").onclick = start;
    if (offerDsm) $("#open-dsm").onclick = function () { location.href = "/?launchApp=" + encodeURIComponent(APP_ID); };
  }

  // ------------------------------------------------------------------ status polling
  var pollTimer = null;
  function stopPolling() { clearTimeout(pollTimer); pollTimer = null; }
  function poll() {
    stopPolling();
    api("status").then(function (st) {
      setStatus(st);
      pollTimer = setTimeout(poll, st.status === "scanning" ? 1500 : 10000);
    }, function (err) {
      if (err.code === "auth" || err.code === "permission" || err.code === "daemon") return handleError(err);
      pollTimer = setTimeout(poll, 10000);
    });
  }

  function progressPct(st) {
    if (!st || st.status !== "scanning") return 0;
    var base = { prepare: 0, discover: 0, identify: 55, verify: 95 }[st.phase] || 0;
    var span = { prepare: 0, discover: 55, identify: 40, verify: 5 }[st.phase] || 0;
    return Math.min(100, Math.round(base + (st.total ? span * st.done / st.total : 0)));
  }

  function setStatus(st) {
    var prev = S.status;
    S.status = st;
    var scanning = st.status === "scanning";
    var el = $("#nav-status");
    if (el) {
      if (scanning) {
        el.innerHTML = '<div class="row"><span class="spinner"></span><span class="txt">' + esc(T("phase_" + st.phase) || T("scanning")) +
          '</span></div><div class="progress"><div style="width:' + progressPct(st) + '%"></div></div>' +
          '<div class="row txt" style="margin-top:6px">' + esc(T("found_n", st.found || 0)) + "</div>";
      } else {
        el.innerHTML = '<div class="row txt"><span class="dot on"></span>' + esc(T("idle")) + '</div><div class="txt" style="margin-top:6px">' +
          esc(T("last_scan")) + ": " + esc(st.last_scan ? rel(st.last_scan.finished) : T("never")) + "</div>";
      }
    }
    $$("[data-scan-btn]").forEach(function (b) {
      b.innerHTML = (scanning ? I.stop : I.scan) + "<span>" + esc(scanning ? T("cancel_scan") : T("scan_now")) + "</span>";
      b.classList.toggle("primary", !scanning);
    });
    if (S.page === "overview") renderBanner();
    if (S.wasScanning && !scanning) {
      S.wasScanning = false;
      if (st.last_scan && !st.last_error) toast(T("scan_done", st.last_scan.found, st.last_scan.new), "info");
      refreshPage();
      if (S.page !== "devices") loadDevices(true);
    } else if (scanning) {
      S.wasScanning = true;
      if (S.page === "devices" && prev && prev.found !== st.found && prev.phase !== st.phase) loadDevices(true);
    }
  }

  function scanButtonClick() {
    if (S.status && S.status.status === "scanning") {
      api("cancel", {}).then(poll, handleError);
    } else {
      api("scan", {}).then(function (r) {
        if (!r.started) toast(T("scan_running"), "info");
        S.wasScanning = true;
        poll();
      }, handleError);
    }
  }
  document.addEventListener("click", function (e) { if (e.target.closest("[data-scan-btn]")) scanButtonClick(); });

  function scanBtn() { return '<button class="btn primary" data-scan-btn>' + I.scan + "<span>" + esc(T("scan_now")) + "</span></button>"; }

  function updateNavBadge() {
    var n = S.devices.filter(function (d) { return !d.known; }).length;
    var b = $("#nav-badge");
    if (b) { b.textContent = n; b.classList.toggle("hidden", !n); }
  }

  // ------------------------------------------------------------------ overview
  var OV = null;
  function loadOverview() {
    return api("overview").then(function (d) { OV = d; S.status = d.status; renderOverview(); }, handleError);
  }

  function renderBanner() {
    var host = $("#ov-banner");
    if (!host || !OV) return;
    var st = S.status || OV.status, c = OV.counts, icon, title, desc, actions;
    var scanning = st.status === "scanning";
    if (scanning) {
      var ranges = (st.last_scan && st.last_scan.targets || []).join(", ") || "LAN";
      icon = I.status_scan; title = T("ov_scanning"); desc = T("ov_scanning_desc", ranges);
      actions = scanBtn() + '<div class="progress"><div style="width:' + progressPct(st) + '%"></div></div><div class="muted">' +
        esc(T("phase_" + st.phase)) + " · " + esc(T("found_n", st.found || 0)) + "</div>";
    } else if (!st.last_scan) {
      icon = I.status_idle; title = T("ov_first"); desc = T("ov_first_desc"); actions = scanBtn();
    } else if (c.unknown) {
      icon = I.status_warn; title = T("ov_unknown", c.unknown); desc = T("ov_unknown_desc");
      actions = '<div style="display:flex;gap:8px"><button class="btn" id="ov-review">' + esc(T("review")) + "</button>" + scanBtn() + "</div>";
    } else {
      icon = I.status_ok; title = T("ov_healthy"); desc = T("ov_healthy_desc", c.online); actions = scanBtn();
    }
    var meta = "";
    if (!scanning && st.last_scan) {
      meta = '<p style="margin-top:6px" class="faint">' + esc(T("last_scan")) + ": " + esc(rel(st.last_scan.finished)) + " · " +
        esc(T("next_scan")) + ": " + esc(st.next_scan ? rel(st.next_scan) : T("manual_only")) + "</p>";
    }
    host.innerHTML = '<div class="status-icon">' + icon + '</div><div><h2>' + esc(title) + "</h2><p>" + esc(desc) + "</p>" + meta +
      '</div><div class="actions">' + actions + "</div>";
    var rv = $("#ov-review");
    if (rv) rv.onclick = function () { S.filter = "unknown"; go("devices"); };
    $$("[data-scan-btn]").forEach(function (b) {
      b.innerHTML = (scanning ? I.stop : I.scan) + "<span>" + esc(scanning ? T("cancel_scan") : T("scan_now")) + "</span>";
      b.classList.toggle("primary", !scanning);
    });
  }

  function renderOverview() {
    var d = OV, c = d.counts;
    var tiles = [
      ["online", T("tile_online"), c.online, "/ " + c.total, '<span class="dot on"></span>'],
      ["all", T("tile_total"), c.total, "", ""],
      ["new", T("tile_new"), c.new24h, "", ""],
      ["unknown", T("tile_unknown"), c.unknown, "", c.unknown ? '<span class="dot warn"></span>' : ""],
    ];
    var ifaces = d.interfaces.filter(function (i) { return !i.virtual; });
    var ifHtml = ifaces.map(function (i) {
      return '<div class="iface"><div class="head"><span class="dot' + (i.up ? " on" : "") + '"></span>' + esc(i.name) +
        '<span class="faint" style="font-weight:400">' + esc(i.network) + '</span></div><dl class="kv">' +
        "<dt>" + esc(T("iface_ip")) + '</dt><dd class="mono">' + esc(i.ip + "/" + i.prefix) + "</dd>" +
        (i.gateway ? "<dt>" + esc(T("iface_gateway")) + '</dt><dd class="mono">' + esc(i.gateway) + "</dd>" : "") +
        (i.mac ? "<dt>" + esc(T("iface_mac")) + '</dt><dd class="mono">' + esc(i.mac.toUpperCase()) + "</dd>" : "") +
        (i.speed ? "<dt>" + esc(T("iface_speed")) + "</dt><dd>" + esc(i.speed >= 1000 ? i.speed / 1000 + " Gbps" : i.speed + " Mbps") + "</dd>" : "") +
        "</dl></div>";
    }).join("");
    ifHtml += '<div class="iface"><dl class="kv"><dt>' + esc(T("hostname")) + "</dt><dd>" + esc(d.hostname) + "</dd>" +
      (d.dns.length ? "<dt>" + esc(T("dns")) + '</dt><dd class="mono">' + esc(d.dns.join(", ")) + "</dd>" : "") +
      (d.status.last_scan ? "<dt>" + esc(T("scanned_ranges")) + '</dt><dd class="mono">' + esc((d.status.last_scan.targets || []).join(", ")) + "</dd>" : "") +
      "</dl></div>";

    var types = Object.keys(d.types).sort(function (a, b) { return d.types[b] - d.types[a]; });
    var max = types.length ? d.types[types[0]] : 1;
    var bars = types.length ? '<div class="bars">' + types.map(function (t) {
      var col = (TC[t] || TC.unknown)[1];
      return '<div class="bar-row" data-type="' + esc(t) + '">' + devIcon(t) + '<span class="bar-name">' + esc(typeName(t)) +
        '</span><div class="bar"><div style="width:' + Math.max(4, Math.round(100 * d.types[t] / max)) + "%;background:" + col +
        '"></div></div><span class="num">' + d.types[t] + "</span></div>";
    }).join("") + "</div>" : '<div class="faint">' + esc(T("no_devices_online")) + "</div>";

    var evs = d.events.length ? '<div class="events-list">' + d.events.slice(0, 7).map(eventRow).join("") + "</div>" :
      '<div class="faint">' + esc(T("no_activity")) + "</div>";

    $("#ov").innerHTML = '<div class="banner" id="ov-banner"></div>' +
      '<div class="tiles">' + tiles.map(function (t) {
        return '<div class="tile" data-filter="' + t[0] + '"><div class="label">' + t[4] + esc(t[1]) + '</div><div class="value">' + t[2] +
          (t[3] ? "<small>" + esc(t[3]) + "</small>" : "") + "</div></div>";
      }).join("") + "</div>" +
      '<div class="cards"><div style="display:flex;flex-direction:column;gap:16px;min-width:0">' +
      '<div class="card"><div class="card-head">' + esc(T("card_activity")) + '<a class="more" href="#" data-go="activity">' + esc(T("view_all")) + '</a></div><div class="card-body">' + evs + "</div></div>" +
      '<div class="card"><div class="card-head">' + esc(T("card_types")) + '</div><div class="card-body">' + bars + "</div></div></div>" +
      '<div class="card"><div class="card-head">' + esc(T("card_network")) + '</div><div class="card-body" style="padding-top:4px">' + ifHtml + "</div></div></div>";
    renderBanner();
    $$(".tile", $("#ov")).forEach(function (t) {
      t.onclick = function () {
        var f = t.getAttribute("data-filter");
        S.filter = f === "new" ? "unknown" : f; S.typeFilter = ""; go("devices");
      };
    });
    $$(".bar-row", $("#ov")).forEach(function (r) {
      r.onclick = function () { S.filter = "online"; S.typeFilter = r.getAttribute("data-type"); go("devices"); };
    });
    $$("[data-go]", $("#ov")).forEach(function (a) { a.onclick = function (e) { e.preventDefault(); go(a.getAttribute("data-go")); }; });
  }

  function eventText(ev) {
    if (ev.kind === "baseline") return T("ev_baseline_detail", ev.detail);
    return ev.detail || "";
  }
  function eventRow(ev) {
    return '<div class="ev"><span class="ev-icon ' + esc(ev.kind) + '">' + (I["ev_" + ev.kind] || I.info) + "</span><div style=\"min-width:0\"><div><b style=\"font-weight:600\">" +
      esc(T("ev_" + ev.kind)) + "</b>" + (ev.name ? " · " + esc(ev.name) : "") + (ev.ip && ev.ip !== ev.name ? ' <span class="faint mono">' + esc(ev.ip) + "</span>" : "") +
      '</div><div class="t">' + esc(rel(ev.ts)) + (eventText(ev) ? " · " + esc(eventText(ev)) : "") + "</div></div></div>";
  }

  // ------------------------------------------------------------------ devices
  var grid = null;
  function devicesSkeleton() {
    return '<div class="toolbar">' + scanBtn() +
      '<button class="btn" id="d-edit" disabled>' + esc(T("edit")) + "</button>" +
      '<button class="btn" id="d-delete" disabled>' + esc(T("del")) + "</button>" +
      '<button class="btn" id="d-action">' + esc(T("action")) + '<span class="caret"></span></button>' +
      '<div class="tb-group"><select class="select" id="d-filter"><option value="all">' + esc(T("filter_all")) + '</option><option value="online">' + esc(T("filter_online")) +
      '</option><option value="offline">' + esc(T("filter_offline")) + '</option><option value="unknown">' + esc(T("filter_unknown")) + "</option></select>" +
      '<select class="select" id="d-type"></select>' +
      '<div class="search">' + I.search + '<input class="input" id="d-search" placeholder="' + esc(T("search")) + '"></div></div></div>' +
      '<div class="grid-wrap" id="d-grid"></div><div class="grid-footer" id="d-foot"></div>';
  }

  function portLabel(p) { return S.portNames[p] || String(p); }

  function initDevices() {
    grid = new Grid($("#d-grid"), {
      idKey: "id", sort: { key: "ip", dir: 1 }, storeKey: "devices", emptyIcon: "t_network", flexMin: 260,
      empty: function () { return S.devices.length ? T("no_match") : T("no_devices"); },
      columns: [
        { key: "online", title: T("col_status"), width: "96px", sortVal: function (r) { return r.online ? 0 : 1; },
          render: function (r) { return '<span class="status ' + (r.online ? "on" : "off") + '"><span class="dot' + (r.online ? " on" : "") + '"></span>' + esc(r.online ? T("online") : T("offline")) + "</span>"; } },
        { key: "display_name", title: T("col_name"), width: "auto", sortVal: function (r) { return r.display_name.toLowerCase(); },
          render: function (r) {
            var sub = r.name || r.friendly ? (r.hostname || r.mdns_name || r.netbios || r.model || "") : (r.model || "");
            var badges = (r.self ? ' <span class="badge gray">' + esc(T("this_nas")) + "</span>" : "") +
              (r.gateway ? ' <span class="badge gray">' + esc(T("gateway")) + "</span>" : "") +
              (!r.known ? ' <span class="badge new">' + esc(T("new_badge")) + "</span>" : "");
            return '<div class="cell-name">' + devIcon(r.type) + '<div style="min-width:0;overflow:hidden"><div class="nm">' + esc(r.display_name) + badges +
              "</div>" + (sub && sub !== r.display_name ? '<div class="sub nm">' + esc(sub) + "</div>" : "") + "</div></div>";
          }, title_attr: function (r) { return r.display_name; } },
        { key: "ip", title: T("col_ip"), width: "128px", sortVal: function (r) { return ipNum(r.ip); }, render: function (r) { return '<span class="mono">' + esc(r.ip) + "</span>"; } },
        { key: "mac", title: T("col_mac"), width: "140px", hide: 5, render: function (r) { return '<span class="mono">' + esc((r.mac || "–").toUpperCase()) + "</span>"; } },
        { key: "vendor", title: T("col_vendor"), width: "150px", hide: 3, render: function (r) { return r.vendor ? esc(r.vendor) : '<span class="faint">' + esc(r.random_mac ? T("private_mac") : "–") + "</span>"; }, title_attr: function (r) { return r.vendor || ""; } },
        { key: "type", title: T("col_type"), width: "132px", hide: 1, sortVal: function (r) { return typeName(r.type); }, render: function (r) { return esc(typeName(r.type)); },
          title_attr: function (r) { return typeName(r.type); } },
        { key: "ports", title: T("col_ports"), width: "170px", hide: 2, sortVal: function (r) { return (r.ports || []).length; },
          render: function (r) {
            var p = r.ports || [];
            return p.slice(0, 2).map(function (x) { return '<span class="tag">' + esc(portLabel(x)) + "</span>"; }).join("") +
              (p.length > 2 ? '<span class="tag">+' + (p.length - 2) + "</span>" : "");
          }, title_attr: function (r) { return (r.ports || []).map(function (x) { return x + " " + portLabel(x); }).join(", "); } },
        { key: "last_seen", title: T("col_last_seen"), width: "124px", hide: 4, render: function (r) { return esc(rel(r.last_seen)); },
          title_attr: function (r) { return fmtTime(r.last_seen); } },
      ],
      onOpen: openDevice,
      onSelect: updateDeviceButtons,
      onMenu: function (e, rows) { showMenu(e.clientX, e.clientY, deviceMenu(rows)); },
      onRender: function (rows) {
        $("#d-foot").textContent = T("items", rows.length) + (S.devices.length !== rows.length ? " / " + S.devices.length : "");
      },
    });
    $("#d-filter").onchange = function () { S.filter = this.value; applyFilter(); };
    $("#d-type").onchange = function () { S.typeFilter = this.value; applyFilter(); };
    $("#d-search").oninput = debounce(function () { S.search = this.value.trim().toLowerCase(); applyFilter(); }, 150);
    $("#d-edit").onclick = function () { var r = grid.selected(); if (r.length === 1) openDevice(r[0]); };
    $("#d-delete").onclick = function () { deleteDevices(grid.selected()); };
    $("#d-action").onclick = function () {
      var r = this.getBoundingClientRect(), sel = grid.selected();
      var items = deviceMenu(sel).filter(function (it) { return it === "-" || (it.icon !== "edit" && it.icon !== "trash"); });
      while (items[items.length - 1] === "-") items.pop();
      items.push("-", { text: T("export"), icon: "export", onClick: exportCsv });
      showMenu(r.left, r.bottom + 4, items);
    };
    window.addEventListener("resize", debounce(function () { grid.render(); evGrid.render(); scGrid.render(); }, 120));
    document.addEventListener("keydown", function (e) {
      if (S.page !== "devices" || $(".mask") || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
      if (e.key === "Delete") deleteDevices(grid.selected());
      if (e.key === "Enter") { var r = grid.selected(); if (r.length === 1) openDevice(r[0]); }
      if ((e.ctrlKey || e.metaKey) && e.key === "a") { e.preventDefault(); grid.select(grid.view.map(function (r) { return r.id; })); }
    });
  }

  function updateDeviceButtons(sel) {
    $("#d-edit").disabled = sel.length !== 1;
    $("#d-delete").disabled = !sel.length;
    var foot = $("#d-foot");
    if (foot && grid) foot.textContent = (sel.length ? T("selected_n", sel.length) + " · " : "") + T("items", grid.view.length);
  }

  function deviceMenu(rows) {
    var one = rows.length === 1 ? rows[0] : null;
    var web = one && webUrl(one);
    return [
      { text: T("edit"), icon: "edit", disabled: !one, onClick: function () { openDevice(one); } },
      { text: T("open_web"), icon: "link", disabled: !web || !webAllowed(), hint: web && !webAllowed() ? T("web_local_only") : "",
        onClick: function () { openWeb(web); } },
      { text: T("wake"), icon: "power", disabled: !(one && one.mac && !one.self), onClick: function () { wake(one); } },
      { text: T("mark_known"), icon: "check", disabled: !rows.some(function (r) { return !r.known; }), onClick: function () { markKnown(rows); } },
      "-",
      { text: T("copy_ip"), icon: "copy", disabled: !one, onClick: function () { copyText(one.ip); } },
      { text: T("copy_mac"), icon: "copy", disabled: !(one && one.mac), onClick: function () { copyText(one.mac.toUpperCase()); } },
      "-",
      { text: T("del"), icon: "trash", onClick: function () { deleteDevices(rows); } },
    ];
  }

  // A device's own address only works when the browser is in the NAS's network. The service
  // knows best (it sees the browser's address: a QuickConnect relay arrives via loopback); the
  // host name is the fallback. QuickConnect sends LAN users to "192-168-1-61.<id>.direct…".
  var PRIVATE = /^(10|192[.-]168|172[.-](1[6-9]|2\d|3[01]))[.-]/;
  function guessLocal() {
    var h = location.hostname.toLowerCase();
    if (/\.quickconnect\.(to|cn)$/.test(h)) return PRIVATE.test(h);
    if (/^[\d.]+$/.test(h)) return PRIVATE.test(h);
    if (h.indexOf(".") < 0 || /\.(local|lan|home|fritz\.box|localdomain|internal|home\.arpa)$/.test(h)) return true;
    return null;
  }
  // Local only if the service says so and the host name does not contradict it: a wrong
  // "local" would silently open an address in whatever network the viewer is in.
  function loadClient() {
    return api("client").then(function (c) {
      var g = guessLocal();
      S.local = c.local === null ? g : (c.local && g !== false);
    }, function () { S.local = guessLocal(); });
  }
  function webAllowed() { return S.local !== false; }
  function openWeb(url) { if (webAllowed()) window.open(url, "_blank", "noopener"); }

  function webUrl(d) {
    var p = d.ports || [];
    var order = [[443, "https"], [5001, "https"], [80, "http"], [8080, "http"], [5000, "http"], [8443, "https"], [8123, "http"], [32400, "http"]];
    for (var i = 0; i < order.length; i++) {
      if (p.indexOf(order[i][0]) >= 0) {
        var port = order[i][0];
        return order[i][1] + "://" + d.ip + ((port === 80 || port === 443) ? "" : ":" + port) + "/";
      }
    }
    return "";
  }

  var devSeq = 0;
  function loadDevices(silent) {
    var seq = ++devSeq;
    return api("devices").then(function (d) {
      if (seq !== devSeq) return; // a newer request is under way; never let an older answer win
      S.devices = d.devices; S.portNames = d.port_names; S.types = d.types; S.loaded.devices = true;
      updateNavBadge();
      if (S.page === "devices") renderDeviceFilters();
      applyFilter();
    }, silent ? function () {} : handleError);
  }

  function renderDeviceFilters() {
    $("#d-filter").value = S.filter;
    var present = {};
    S.devices.forEach(function (d) { present[d.type] = (present[d.type] || 0) + 1; });
    var opts = '<option value="">' + esc(T("all_types")) + "</option>" + S.types.filter(function (t) { return present[t] || t === S.typeFilter; })
      .map(function (t) { return '<option value="' + t + '">' + esc(typeName(t)) + " (" + (present[t] || 0) + ")</option>"; }).join("");
    $("#d-type").innerHTML = opts;
    $("#d-type").value = S.typeFilter;
  }

  function applyFilter() {
    if (!grid) return;
    var q = S.search;
    var rows = S.devices.filter(function (d) {
      if (S.filter === "online" && !d.online) return false;
      if (S.filter === "offline" && d.online) return false;
      if (S.filter === "unknown" && d.known) return false;
      if (S.typeFilter && d.type !== S.typeFilter) return false;
      if (q) {
        var hay = [d.display_name, d.ip, d.mac, d.vendor, d.hostname, d.mdns_name, d.netbios, d.model, d.notes, typeName(d.type)].join(" ").toLowerCase();
        if (hay.indexOf(q) < 0 && hay.replace(/:/g, "").indexOf(q.replace(/:/g, "")) < 0) return false;
      }
      return true;
    });
    grid.setRows(rows);
  }

  function wake(d) {
    api("wake", { id: d.id }).then(function () { toast(T("wol_sent", d.display_name)); }, handleError);
  }
  function markKnown(rows) {
    var ids = rows.filter(function (r) { return !r.known; }).map(function (r) { return r.id; });
    if (!ids.length) return;
    api("device_known", { ids: ids, known: true }).then(function () { loadDevices(); }, handleError);
  }
  function deleteDevices(rows) {
    if (!rows.length) return;
    confirmBox(T("confirm_delete", rows.length), true).then(function (ok) {
      if (!ok) return;
      api("device_delete", { ids: rows.map(function (r) { return r.id; }) }).then(function (r) {
        toast(T("deleted_n", r.deleted)); loadDevices();
      }, handleError);
    });
  }
  function exportCsv() {
    // fetch with the token in a header (not in a link) so it stays out of history and logs
    fetch("api.cgi?action=export&format=csv", { credentials: "same-origin", headers: { "X-SYNO-TOKEN": synoToken() } })
      .then(function (r) {
        var type = r.headers.get("Content-Type") || "";
        if (type.indexOf("text/csv") < 0) return r.json().then(function (j) { throw new ApiError(j.error && j.error.code, j.error && j.error.message, j.error); });
        return r.blob();
      })
      .then(function (blob) {
        var a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "synetscan-devices.csv";
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 5000);
      }, handleError);
  }

  function kvRow(label, value, mono) {
    if (value === undefined || value === null || value === "" || (Array.isArray(value) && !value.length)) return "";
    return "<dt>" + esc(label) + '</dt><dd class="' + (mono ? "mono" : "") + '">' + value + "</dd>";
  }

  function openDevice(d) {
    if (!d) return;
    var typeOpts = '<option value="">' + esc(T("f_type_auto", typeName(d.type_auto || "unknown"))) + "</option>" +
      S.types.map(function (t) { return '<option value="' + t + '"' + (d.type_user === t ? " selected" : "") + ">" + esc(typeName(t)) + "</option>"; }).join("");
    var detected = d;
    var general = '<div class="dev-head">' + devIcon(d.type, "lg") + '<div><h3>' + esc(d.display_name) + '</h3><div class="status ' + (d.online ? "on" : "off") + '"><span class="dot' + (d.online ? " on" : "") + '"></span>' +
      esc(d.online ? T("online") : T("offline") + " · " + rel(d.last_seen)) + '</div></div></div>' +
      '<div class="field"><label>' + esc(T("f_name")) + '</label><div class="ctl"><input class="input" id="dv-name" maxlength="64" value="' + esc(d.name || "") + '" placeholder="' + esc(dispNoName(detected)) + '"></div></div>' +
      '<div class="field"><label>' + esc(T("f_type")) + '</label><div class="ctl"><select class="select" id="dv-type">' + typeOpts + "</select></div></div>" +
      '<div class="field"><label>' + esc(T("f_notes")) + '</label><div class="ctl"><textarea class="textarea" id="dv-notes" rows="4" maxlength="1000">' + esc(d.notes || "") + "</textarea></div></div>" +
      '<div class="field"><label></label><div class="ctl"><label class="check"><input type="checkbox" id="dv-known"' + (d.known ? " checked" : "") + ">" + esc(T("f_known")) + "</label></div></div>";

    var http = d.http ? esc(d.http.title || "") + (d.http.server ? ' <span class="faint">(' + esc(d.http.server) + ")</span>" : "") : "";
    var upnp = d.upnp ? esc([d.upnp.manufacturer, d.upnp.modelName, d.upnp.modelNumber].filter(Boolean).join(" ")) : "";
    var details = '<dl class="kv selectable">' +
      kvRow(T("d_detected_name"), esc(dispNoName(detected))) +
      kvRow(T("d_ip"), esc(d.ip), true) +
      kvRow(T("d_mac"), d.mac ? esc(d.mac.toUpperCase()) + (d.random_mac ? '<div class="faint" style="font-family:var(--font)">' + esc(T("d_random")) + "</div>" : "") : "", true) +
      kvRow(T("d_vendor"), esc(d.vendor)) +
      kvRow(T("d_model"), esc(d.model)) +
      kvRow(T("d_hostname"), esc(d.hostname)) +
      kvRow(T("d_mdns"), esc(d.mdns_name)) +
      kvRow(T("d_netbios"), esc(d.netbios)) +
      kvRow(T("d_workgroup"), esc(d.workgroup)) +
      kvRow(T("d_http"), http) +
      kvRow(T("d_upnp"), upnp) +
      kvRow(T("d_iface"), esc(d.iface)) +
      kvRow(T("d_via"), esc((d.via || []).join(", ").toUpperCase())) +
      kvRow(T("d_rtt"), d.rtt ? esc(fmtNum(d.rtt) + " ms") : "") +
      kvRow(T("d_first"), esc(fmtTime(d.first_seen))) +
      kvRow(T("d_last"), esc(fmtTime(d.last_seen))) +
      kvRow(T("d_ip_history"), esc((d.ip_history || []).join(", ")), true) +
      "</dl>";

    var ports = d.ports || [];
    var services = ports.length ? '<table class="ports-table"><thead><tr><th style="width:90px">' + esc(T("port")) + "</th><th>" + esc(T("service")) + "</th><th style=\"width:90px\"></th></tr></thead><tbody>" +
      ports.map(function (p) {
        var scheme = [443, 5001, 8443, 9443].indexOf(p) >= 0 ? "https" : [80, 81, 5000, 8000, 8008, 8080, 8081, 8123, 8888, 9000, 3000, 32400].indexOf(p) >= 0 ? "http" : "";
        var url = scheme ? scheme + "://" + d.ip + ((p === 80 || p === 443) ? "" : ":" + p) + "/" : "";
        var link = !url ? "" : webAllowed() ? '<a href="#" data-web="' + esc(url) + '">' + esc(T("open_link")) + "</a>" :
          '<span class="faint" title="' + esc(T("web_local_only")) + '">' + esc(T("open_link")) + "</span>";
        return '<tr><td class="mono">' + p + "/tcp</td><td>" + esc(portLabel(p)) + "</td><td>" + link + "</td></tr>";
      }).join("") + "</tbody></table>" : '<div class="faint">' + esc(T("no_ports")) + "</div>";
    if (ports.length && webUrl(d) && !webAllowed()) services = '<div class="note">' + I.info + "<span>" + esc(T("web_local_only")) + "</span></div>" + services;
    if ((d.services || []).length) {
      services += '<div style="margin-top:18px"><div class="muted" style="margin-bottom:8px">' + esc(T("d_mdns_services")) + "</div>" +
        d.services.map(function (s) { return '<span class="tag">' + esc(s) + "</span>"; }).join("") + "</div>";
    }

    var dlg = dialog({
      title: d.display_name, width: 600, height: 420,
      tabs: [{ title: T("tab_general"), html: general }, { title: T("tab_details"), html: details }, { title: T("tab_services"), html: services }],
      buttons: [
        { text: T("wake"), left: true, disabled: !(d.mac && !d.self), onClick: function () { wake(d); return false; } },
        { text: T("cancel") },
        { text: T("ok"), primary: true, onClick: function (dlg) {
          var body = { id: d.id, name: $("#dv-name", dlg.el).value, type_user: $("#dv-type", dlg.el).value,
            notes: $("#dv-notes", dlg.el).value, known: $("#dv-known", dlg.el).checked };
          api("device_update", body).then(function () { toast(T("saved_device")); loadDevices(); }, handleError);
        } },
      ],
    });
    $$("[data-web]", dlg.el).forEach(function (a) { a.onclick = function (e) { e.preventDefault(); openWeb(a.getAttribute("data-web")); }; });
  }

  function dispNoName(d) { return d.detected_name || d.ip; }

  // ------------------------------------------------------------------ activity
  var evGrid = null, scGrid = null, EVENTS = [];
  function activitySkeleton() {
    return '<div class="tabs"><div class="tab active" data-atab="events">' + esc(T("tab_events")) + '</div><div class="tab" data-atab="scans">' + esc(T("tab_scan_history")) + "</div></div>" +
      '<div class="tab-body active" data-abody="events"><div class="toolbar"><select class="select" id="ev-filter"><option value="">' + esc(T("all_events")) + "</option>" +
      ["new", "online", "offline", "ip_changed"].map(function (k) { return '<option value="' + k + '">' + esc(T("ev_" + k)) + "</option>"; }).join("") +
      '</select><button class="btn" id="ev-clear">' + esc(T("clear")) + '</button><span class="spacer"></span><div class="search">' + I.search +
      '<input class="input" id="ev-search" placeholder="' + esc(T("search")) + '"></div></div><div class="grid-wrap" id="ev-grid"></div><div class="grid-footer" id="ev-foot"></div></div>' +
      '<div class="tab-body" data-abody="scans"><div class="toolbar">' + scanBtn() + '</div><div class="grid-wrap" id="sc-grid"></div><div class="grid-footer" id="sc-foot"></div></div>';
  }

  function initActivity() {
    $$("[data-atab]").forEach(function (t) {
      t.onclick = function () {
        $$("[data-atab]").forEach(function (x) { x.classList.toggle("active", x === t); });
        $$("[data-abody]").forEach(function (b) { b.classList.toggle("active", b.getAttribute("data-abody") === t.getAttribute("data-atab")); });
      };
    });
    evGrid = new Grid($("#ev-grid"), {
      idKey: "_k", sort: { key: "ts", dir: -1 }, storeKey: "events", emptyIcon: "activity", empty: function () { return T("no_activity"); },
      columns: [
        { key: "ts", title: T("col_time"), width: "160px", render: function (r) { return esc(fmtTime(r.ts)); } },
        { key: "kind", title: T("col_event"), width: "200px", sortVal: function (r) { return T("ev_" + r.kind); },
          render: function (r) { return '<span class="cell-name"><span class="ev-icon ' + esc(r.kind) + '">' + (I["ev_" + r.kind] || "") + "</span>" + esc(T("ev_" + r.kind)) + "</span>"; } },
        { key: "name", title: T("col_device"), width: "26%", title_attr: function (r) { return r.name; } },
        { key: "ip", title: T("col_ip"), width: "130px", sortVal: function (r) { return ipNum(r.ip); }, render: function (r) { return '<span class="mono">' + esc(r.ip) + "</span>"; } },
        { key: "mac", title: T("col_mac"), width: "150px", hideBelow: 980, render: function (r) { return '<span class="mono">' + esc((r.mac || "").toUpperCase()) + "</span>"; } },
        { key: "detail", title: T("col_detail"), render: function (r) { return esc(eventText(r)); }, title_attr: function (r) { return eventText(r); } },
      ],
      onOpen: function (r) { var d = S.devices.filter(function (x) { return x.id === r.id; })[0]; if (d) openDevice(d); },
      onRender: function (rows) { $("#ev-foot").textContent = T("items", rows.length); },
    });
    scGrid = new Grid($("#sc-grid"), {
      idKey: "started", sort: { key: "finished", dir: -1 }, storeKey: "scans", emptyIcon: "scan", empty: function () { return T("never"); },
      columns: [
        { key: "finished", title: T("col_time"), width: "160px", render: function (r) { return esc(fmtTime(r.finished)); } },
        { key: "trigger", title: T("col_trigger"), width: "140px", render: function (r) { return esc(T("trig_" + (r.trigger || "manual"))); } },
        { key: "duration", title: T("col_duration"), width: "100px", render: function (r) { return esc(T("seconds", fmtNum(r.duration))); } },
        { key: "found", title: T("col_found"), width: "100px" },
        { key: "new", title: T("col_new"), width: "80px", render: function (r) { return r.new ? '<span class="badge new">' + r.new + "</span>" : "0"; } },
        { key: "offline", title: T("col_offline"), width: "90px" },
        { key: "targets", title: T("col_targets"), sortable: false, hideBelow: 820, render: function (r) { return '<span class="mono">' + esc((r.targets || []).join(", ")) + "</span>"; },
          title_attr: function (r) { return (r.targets || []).join(", "); } },
      ],
      onRender: function (rows) { $("#sc-foot").textContent = T("items", rows.length); },
    });
    $("#ev-filter").onchange = filterEvents;
    $("#ev-search").oninput = debounce(filterEvents, 150);
    $("#ev-clear").onclick = function () {
      confirmBox(T("confirm_clear_events"), true).then(function (ok) {
        if (ok) api("clear_events", {}).then(loadActivity, handleError);
      });
    };
  }

  function filterEvents() {
    var k = $("#ev-filter").value, q = $("#ev-search").value.trim().toLowerCase();
    evGrid.setRows(EVENTS.filter(function (e) {
      if (k && e.kind !== k) return false;
      if (q && [e.name, e.ip, e.mac, e.detail].join(" ").toLowerCase().indexOf(q) < 0) return false;
      return true;
    }));
  }

  function loadActivity() {
    if (!S.loaded.devices) loadDevices(true);
    return Promise.all([api("events"), api("scans")]).then(function (r) {
      EVENTS = r[0].events.map(function (e, i) { e._k = i; return e; });
      filterEvents();
      scGrid.setRows(r[1].scans);
    }, handleError);
  }

  // ------------------------------------------------------------------ settings
  var CFG = null;
  function loadSettings() {
    return api("config_get").then(function (d) { CFG = d; renderSettings(); }, handleError);
  }

  function intervalLabel(m) {
    if (m < 60) return T("every_min", m);
    if (m === 60) return T("every_hour");
    if (m === 1440) return T("every_day");
    return T("every_hours", m / 60);
  }
  function opt(v, label, cur) { return '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? " selected" : "") + ">" + esc(label) + "</option>"; }
  function chk(id, label, on, extra) {
    return '<label class="check"><input type="checkbox" id="' + id + '"' + (on ? " checked" : "") + (extra || "") + ">" + esc(label) + "</label>";
  }
  function field(label, ctl, hint) {
    return '<div class="field"><label>' + esc(label) + '</label><div class="ctl">' + ctl + (hint ? '<div class="hint">' + esc(hint) + "</div>" : "") + "</div></div>";
  }

  function renderSettings() {
    var c = CFG.config, root = $("#settings-root"), ifaces = CFG.interfaces.filter(function (i) { return !i.virtual; });
    var activeTab = (root.querySelector(".tab.active") || {}).getAttribute ? root.querySelector(".tab.active").getAttribute("data-stab") : "targets";
    var ifList = ifaces.map(function (i) {
      return '<div class="indent">' + chk("if-" + esc(i.name), i.name + "  –  " + i.network + (i.up ? "" : " (down)"), c.excluded_interfaces.indexOf(i.name) < 0, ' data-if="' + esc(i.name) + '"') + "</div>";
    }).join("");
    var targets = '<div class="form-section"><h3>' + esc(T("s_targets")) + '</h3><p class="desc">' + esc(T("s_targets_desc")) + "</p>" +
      '<div style="display:flex;flex-direction:column;gap:10px;margin-bottom:16px">' + chk("s-auto", T("s_auto"), c.auto_subnets) + ifList + "</div>" +
      field(T("s_max_hosts"), '<select class="select" id="s-maxhosts" style="width:160px">' + [[24, 256], [23, 512], [22, 1024], [21, 2048], [20, 4096], [19, 8192]].map(function (v) { return opt(v[1], "/" + v[0] + "  (" + (v[1] - 2) + ")", c.max_hosts_per_subnet); }).join("") + "</select>", T("s_max_hosts_hint")) +
      field(T("s_custom"), '<textarea class="textarea mono" id="s-custom" rows="5" spellcheck="false">' + esc(c.custom_targets.join("\n")) + "</textarea>", T("s_custom_hint")) + "</div>";

    var sched = '<div class="form-section"><h3>' + esc(T("s_schedule")) + '</h3><p class="desc">' + esc(T("s_schedule_desc")) + "</p>" +
      field("", chk("s-sched", T("s_schedule_enable"), c.schedule_enabled)) +
      field(T("s_interval"), '<select class="select" id="s-interval" style="width:220px">' + CFG.intervals.map(function (m) { return opt(m, intervalLabel(m), c.schedule_interval); }).join("") + "</select>") +
      field("", chk("s-onstart", T("s_scan_on_start"), c.scan_on_start)) +
      field(T("s_offline_after"), '<select class="select" id="s-offline" style="width:220px">' + [1, 2, 3, 5].map(function (n) { return opt(n, n === 1 ? T("s_offline_after_1") : T("s_offline_after_n", n), c.offline_after_scans); }).join("") + "</select>") + "</div>";

    var ports = '<div class="form-section"><h3>' + esc(T("s_ports")) + '</h3><p class="desc">' + esc(T("s_ports_desc")) + "</p>" +
      field(T("s_ports_field"), '<textarea class="textarea mono" id="s-ports" rows="5" spellcheck="false">' + esc(c.ports.join(", ")) + '</textarea><div><button class="btn" id="s-ports-reset">' + esc(T("s_ports_reset")) + "</button></div>", T("s_ports_hint")) +
      '<div id="s-ports-preview" style="margin-left:226px"></div></div>';

    var pingAvail = S.status ? S.status.ping : true;
    var adv = '<div class="form-section"><h3>' + esc(T("s_detection")) + "</h3>" +
      '<div style="display:flex;flex-direction:column;gap:10px">' +
      chk("s-ping", T("s_use_ping"), c.use_ping) + (pingAvail ? "" : '<div class="hint indent faint">' + esc(T("ping_unavailable")) + "</div>") +
      chk("s-dns", T("s_use_dns"), c.use_dns) + chk("s-netbios", T("s_use_netbios"), c.use_netbios) +
      chk("s-mdns", T("s_use_mdns"), c.use_mdns) + chk("s-ssdp", T("s_use_ssdp"), c.use_ssdp) + chk("s-http", T("s_use_http"), c.use_http) +
      "</div></div>" +
      '<div class="form-section"><h3>' + esc(T("s_perf")) + "</h3>" +
      field(T("s_timeout"), '<select class="select" id="s-timeout" style="width:160px">' + [0.3, 0.6, 1, 1.5, 2, 3].map(function (v) { return opt(v, String(v).replace(".", LANG === "de" ? "," : "."), c.timeout); }).join("") + "</select>") +
      field(T("s_threads"), '<select class="select" id="s-threads" style="width:160px">' + [16, 32, 64, 128, 256].map(function (v) { return opt(v, String(v), c.threads); }).join("") + "</select>") + "</div>" +
      '<div class="form-section"><h3>' + esc(T("s_data")) + "</h3>" +
      field(T("s_forget"), '<select class="select" id="s-forget" style="width:160px">' + [0, 7, 30, 90, 365].map(function (v) { return opt(v, v ? T("s_forget_days", v) : T("s_forget_never"), c.forget_after_days); }).join("") + "</select>") +
      field("", '<div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn" id="s-clear-offline">' + esc(T("s_clear_offline")) + '</button><button class="btn danger" id="s-reset">' + esc(T("s_reset")) + "</button></div>") + "</div>";

    var tabs = [["targets", "tab_targets", targets], ["schedule", "tab_schedule", sched], ["ports", "tab_ports", ports], ["advanced", "tab_advanced", adv]];
    root.innerHTML = '<div class="tabs">' + tabs.map(function (t) { return '<div class="tab' + (t[0] === activeTab ? " active" : "") + '" data-stab="' + t[0] + '">' + esc(T(t[1])) + "</div>"; }).join("") + "</div>" +
      tabs.map(function (t) { return '<div class="tab-body' + (t[0] === activeTab ? " active" : "") + '" data-sbody="' + t[0] + '"><div class="page-scroll"><div class="form">' + t[2] + "</div></div></div>"; }).join("") +
      '<div class="footer-bar"><button class="btn" id="s-revert">' + esc(T("reset")) + '</button><button class="btn primary" id="s-apply">' + esc(T("apply")) + "</button></div>";

    $$("[data-stab]", root).forEach(function (t) {
      t.onclick = function () {
        $$("[data-stab]", root).forEach(function (x) { x.classList.toggle("active", x === t); });
        $$("[data-sbody]", root).forEach(function (b) { b.classList.toggle("active", b.getAttribute("data-sbody") === t.getAttribute("data-stab")); });
      };
    });
    function syncDisabled() {
      var auto = $("#s-auto").checked;
      $$("[data-if]", root).forEach(function (x) { x.disabled = !auto; });
      $("#s-maxhosts").disabled = !auto;
      var sch = $("#s-sched").checked;
      $("#s-interval").disabled = !sch;
    }
    $("#s-auto").onchange = syncDisabled; $("#s-sched").onchange = syncDisabled; syncDisabled();
    function preview() {
      var list = $("#s-ports").value.split(/[\s,]+/).filter(Boolean).slice(0, 60);
      $("#s-ports-preview").innerHTML = list.map(function (p) {
        var m = /^(\d+)(?:-(\d+))?$/.exec(p), a = m && +m[1], b = m && (m[2] ? +m[2] : a);
        var ok = m && a >= 1 && b <= 65535 && b >= a && b - a <= 1024;
        return '<span class="tag' + (ok ? "" : " bad") + '"' + (ok ? "" : ' title="' + esc(T("err_cfg_ports", p)) + '"') + ">" + esc(p) +
          (ok && CFG.port_names[p] ? " · " + esc(CFG.port_names[p]) : "") + "</span>";
      }).join("");
    }
    $("#s-ports").oninput = preview; preview();
    $("#s-ports-reset").onclick = function () { $("#s-ports").value = CFG.defaults.ports.join(", "); preview(); };
    $("#s-revert").onclick = function () { renderSettings(); toast(T("reverted"), "info"); };
    $("#s-apply").onclick = saveSettings;
    $("#s-clear-offline").onclick = function () {
      confirmBox(T("confirm_clear_offline"), true).then(function (ok) {
        if (ok) api("clear_offline", {}).then(function (r) { toast(T("deleted_n", r.deleted)); loadDevices(true); }, handleError);
      });
    };
    $("#s-reset").onclick = function () {
      confirmBox(T("confirm_reset"), true).then(function (ok) {
        if (ok) api("reset", {}).then(function () { toast(T("deleted_n", S.devices.length)); loadDevices(true); poll(); }, handleError);
      });
    };
  }

  function saveSettings() {
    var root = $("#settings-root");
    var excluded = $$("[data-if]", root).filter(function (x) { return !x.checked; }).map(function (x) { return x.getAttribute("data-if"); });
    var cfg = {
      auto_subnets: $("#s-auto").checked, excluded_interfaces: excluded,
      max_hosts_per_subnet: +$("#s-maxhosts").value, custom_targets: $("#s-custom").value,
      schedule_enabled: $("#s-sched").checked, schedule_interval: +$("#s-interval").value,
      scan_on_start: $("#s-onstart").checked, offline_after_scans: +$("#s-offline").value,
      ports: $("#s-ports").value,
      use_ping: $("#s-ping").checked, use_dns: $("#s-dns").checked, use_netbios: $("#s-netbios").checked,
      use_mdns: $("#s-mdns").checked, use_ssdp: $("#s-ssdp").checked, use_http: $("#s-http").checked,
      timeout: +$("#s-timeout").value, threads: +$("#s-threads").value, forget_after_days: +$("#s-forget").value,
    };
    $$(".invalid", root).forEach(function (x) { x.classList.remove("invalid"); });
    api("config_set", { config: cfg }).then(function (r) {
      CFG.config = r.config; renderSettings(); toast(T("saved")); poll();
    }, function (err) {
      if (err.code === "invalid_config") {
        var map = { custom_targets: ["#s-custom", "targets"], ports: ["#s-ports", "ports"] };
        var hit = map[err.extra.field];
        if (hit) {
          $$("[data-stab]", root).forEach(function (x) { if (x.getAttribute("data-stab") === hit[1]) x.click(); });
          $(hit[0]).classList.add("invalid");
        }
        dialog({ title: T("app"), width: 420, focus: false, html: '<div class="msg"><span style="color:var(--red)">' + I.warn + "</span><div>" + esc(errorText(err)) + "</div></div>",
          buttons: [{ text: T("ok"), primary: true }], onClose: function () { if (hit) $(hit[0]).focus(); } });
      } else handleError(err);
    });
  }

  // ------------------------------------------------------------------ boot
  function start() {
    buildShell();
    var page = "overview";
    try { page = params.get("page") || localStorage.getItem("synetscan.page") || "overview"; } catch (e) { page = params.get("page") || page; }
    if (["overview", "devices", "activity", "settings"].indexOf(page) < 0) page = "overview";
    loadClient();
    api("status").then(function (st) {
      S.wasScanning = st.status === "scanning";
      setStatus(st);
      go(page);
      if (page !== "devices") loadDevices(true);
      pollTimer = setTimeout(poll, st.status === "scanning" ? 1500 : 10000);
    }, handleError);
  }

  // re-render relative times every minute
  setInterval(function () { if (S.status) setStatus(S.status); if (S.page === "devices" && grid) grid.render(); }, 60000);

  start();
})();
