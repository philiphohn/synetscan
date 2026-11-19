/* Injected into the app frame while recording the README demo (tools/demo/record.mjs).
 * It replaces the dev machine's own network details with those of the demo NAS and plays a
 * scan instead of running one, so the recording never depends on (or reveals) a real network. */
(function () {
  if (!/\/SynetScan\/index\.html/.test(location.pathname)) return;
  var realFetch = window.fetch.bind(window);
  var scanStart = null, DURATION = 9000;
  var IFACES = [
    { name: "eth0", ip: "192.168.1.10", prefix: 24, network: "192.168.1.0/24", mac: "00:11:32:10:20:10", up: true, speed: 1000, virtual: false, gateway: "192.168.1.1" },
    { name: "eth1", ip: "169.254.12.4", prefix: 16, network: "169.254.0.0/16", mac: "00:11:32:10:20:11", up: false, speed: null, virtual: false, gateway: "" },
  ];

  function status(st) {
    st = Object.assign({}, st, { ping: true, tz_offset: 0 });
    if (scanStart === null) return st;
    var t = Date.now() - scanStart;
    if (t < DURATION) {
      var p = t / DURATION, phase, done, total;
      if (p < 0.6) { phase = "discover"; total = 254; done = Math.round(254 * p / 0.6); }
      else if (p < 0.95) { phase = "identify"; total = 24; done = Math.round(24 * (p - 0.6) / 0.35); }
      else { phase = "verify"; total = 1; done = 0; }
      return Object.assign(st, { status: "scanning", phase: phase, done: done, total: total, found: Math.min(24, Math.round(24 * Math.min(1, p / 0.55))) });
    }
    var fin = Math.floor((scanStart + DURATION) / 1000);
    return Object.assign(st, { status: "idle", phase: "", next_scan: fin + 3600,
      last_scan: Object.assign({}, st.last_scan, { started: fin - 9, finished: fin, duration: 9.4, found: 24, new: 0, trigger: "manual" }) });
  }

  function reply(data) {
    return Promise.resolve(new Response(JSON.stringify({ success: true, data: data }), { headers: { "Content-Type": "application/json" } }));
  }

  window.fetch = function (url, opts) {
    var m = /action=(\w+)/.exec(String(url)), action = m && m[1];
    if (action === "scan") { scanStart = Date.now(); return reply({ started: true }); }
    if (action === "client") return reply({ ip: "192.168.1.40", local: true, via: "eth0" });
    return realFetch(url, opts).then(function (r) {
      return r.clone().json().then(function (j) {
        if (!j.success) return r;
        var d = j.data;
        if (action === "status") j.data = status(d);
        if (action === "overview") { d.status = status(d.status); d.interfaces = IFACES; d.hostname = "DiskStation"; d.dns = ["192.168.1.1"]; }
        if (action === "config_get") d.interfaces = IFACES.map(function (i) { return { name: i.name, ip: i.ip, prefix: i.prefix, network: i.network, virtual: false, up: i.up }; });
        return new Response(JSON.stringify(j), { headers: { "Content-Type": "application/json" } });
      }, function () { return r; });
    });
  };
})();
