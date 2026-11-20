/* Line icons (24x24, stroke = currentColor) */
(function () {
  var A = 'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"';
  function svg(body, extra) { return '<svg viewBox="0 0 24 24" ' + (extra || A) + '>' + body + '</svg>'; }

  window.SS_ICONS = {
    overview: svg('<rect x="3" y="3" width="7.5" height="9" rx="1.5"/><rect x="13.5" y="3" width="7.5" height="5" rx="1.5"/><rect x="13.5" y="11" width="7.5" height="10" rx="1.5"/><rect x="3" y="15" width="7.5" height="6" rx="1.5"/>'),
    devices: svg('<rect x="2.5" y="4" width="13" height="10" rx="1.5"/><path d="M6 18h6M9 14v4"/><rect x="17" y="8" width="4.5" height="11" rx="1.2"/>'),
    activity: svg('<path d="M3 12h4l3-7 4 14 3-7h4"/>'),
    settings: svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'),
    search: svg('<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>'),
    scan: svg('<path d="M12 12l6-6"/><circle cx="12" cy="12" r="9"/><path d="M12 7a5 5 0 1 0 5 5"/>'),
    stop: svg('<rect x="6" y="6" width="12" height="12" rx="1.5"/>'),
    edit: svg('<path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/>'),
    trash: svg('<path d="M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13"/>'),
    power: svg('<path d="M12 3v8"/><path d="M6.3 6.8a8 8 0 1 0 11.4 0"/>'),
    export: svg('<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5"/><path d="M5 19h14"/>'),
    check: svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>'),
    link: svg('<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>'),
    copy: svg('<rect x="8" y="8" width="12" height="12" rx="1.5"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>'),
    close: svg('<path d="M5 5l14 14M19 5L5 19"/>', 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"'),
    info: svg('<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>'),
    warn: svg('<path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4.5M12 17.3v.2"/>'),
    plus: svg('<path d="M12 5v14M5 12h14"/>'),
    minus: svg('<path d="M5 12h14"/>'),
    swap: svg('<path d="M4 8h13l-3.5-3.5M20 16H7l3.5 3.5"/>'),
    flag: svg('<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>'),
    refresh: svg('<path d="M20 11a8 8 0 0 0-14.5-4.5L4 8M4 4v4h4M4 13a8 8 0 0 0 14.5 4.5L20 16M20 20v-4h-4"/>'),

    t_router: svg('<rect x="3" y="13" width="18" height="7" rx="1.5"/><path d="M7 16.5h.01M10.5 16.5h.01"/><path d="M15 13V9M8.5 8.5a5 5 0 0 1 7 0M6 6a8.5 8.5 0 0 1 12 0"/>'),
    t_nas: svg('<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8.5 7h7M8.5 10.5h7"/><circle cx="9" cy="17" r=".6"/><path d="M12.5 17h3"/>'),
    t_computer: svg('<rect x="3" y="4" width="18" height="12" rx="1.5"/><path d="M8 20h8M12 16v4"/>'),
    t_server: svg('<rect x="3.5" y="4" width="17" height="7" rx="1.5"/><rect x="3.5" y="13" width="17" height="7" rx="1.5"/><path d="M7 7.5h.01M7 16.5h.01M11 7.5h6M11 16.5h6"/>'),
    t_phone: svg('<rect x="6.5" y="2.5" width="11" height="19" rx="2.5"/><path d="M11 18.5h2"/>'),
    t_tablet: svg('<rect x="4" y="3" width="16" height="18" rx="2.5"/><path d="M11 18h2"/>'),
    t_printer: svg('<path d="M7 9V3.5h10V9"/><rect x="3" y="9" width="18" height="8" rx="1.5"/><path d="M7 14h10v6.5H7z"/><path d="M17.5 12h.01"/>'),
    t_camera: svg('<rect x="2.5" y="6.5" width="14" height="11" rx="2"/><path d="M16.5 10.5l5-3v9l-5-3"/><circle cx="9.5" cy="12" r="2.5"/>'),
    t_media: svg('<rect x="2.5" y="4" width="19" height="13" rx="1.5"/><path d="M8 21h8"/><path d="M10 8.3v5.4l4.5-2.7z"/>'),
    t_speaker: svg('<rect x="6" y="2.5" width="12" height="19" rx="2"/><circle cx="12" cy="14.5" r="3.3"/><path d="M12 7h.01"/>'),
    t_console: svg('<path d="M7 7h10a4.5 4.5 0 0 1 4.3 5.8l-1.2 4a2.5 2.5 0 0 1-4.2 1l-1.6-1.8h-4.6l-1.6 1.8a2.5 2.5 0 0 1-4.2-1l-1.2-4A4.5 4.5 0 0 1 7 7z"/><path d="M8 10v3M6.5 11.5h3M15.5 11h.01M17.5 12.5h.01"/>'),
    t_iot: svg('<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.4.4.6.9.6 1.4V16h6v-.8c0-.5.2-1 .6-1.4A6 6 0 0 0 12 3z"/>'),
    t_network: svg('<rect x="2.5" y="9" width="19" height="6.5" rx="1.5"/><path d="M6 12.3h.01M9 12.3h.01M12 12.3h.01M15 12.3h.01M18 12.3h.01"/><path d="M6.5 9V6M17.5 9V6"/>'),
    t_virtual: svg('<rect x="3" y="3" width="13" height="13" rx="1.5" stroke-dasharray="2.5 2"/><rect x="8" y="8" width="13" height="13" rx="1.5"/>'),
    t_voip: svg('<path d="M3 9.5C3 7 7 5 12 5s9 2 9 4.5v.5a1 1 0 0 1-1 1h-2.5a1 1 0 0 1-1-1V8.6a11 11 0 0 0-9 0V10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/><rect x="5" y="13" width="14" height="8" rx="1.5"/><path d="M9 15.8h.01M12 15.8h.01M15 15.8h.01M9 18.3h.01M12 18.3h.01M15 18.3h.01"/>'),
    t_unknown: svg('<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.6v.6M12 17v.2"/>'),

    ev_new: svg('<path d="M12 5v14M5 12h14"/>', 'fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"'),
    ev_online: svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 'fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"'),
    ev_offline: svg('<path d="M6 12h12"/>', 'fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"'),
    ev_ip_changed: svg('<path d="M4 8h13l-3.5-3.5M20 16H7l3.5 3.5"/>', 'fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"'),
    ev_baseline: svg('<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>', 'fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"'),

    status_ok: '<svg viewBox="0 0 64 64"><circle cx="32" cy="32" r="30" fill="#e5f5e8"/><circle cx="32" cy="32" r="22" fill="#36a34a"/><path d="M22 32.5l7 7 13-14" fill="none" stroke="#fff" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    status_warn: '<svg viewBox="0 0 64 64"><circle cx="32" cy="32" r="30" fill="#fdf1e1"/><circle cx="32" cy="32" r="22" fill="#f08a0b"/><path d="M32 21v14" stroke="#fff" stroke-width="4.5" stroke-linecap="round"/><circle cx="32" cy="43" r="2.8" fill="#fff"/></svg>',
    status_idle: '<svg viewBox="0 0 64 64"><circle cx="32" cy="32" r="30" fill="#e3effc"/><circle cx="32" cy="32" r="22" fill="#057feb"/><circle cx="32" cy="32" r="12" fill="none" stroke="#fff" stroke-width="3.5"/><path d="M32 32l9-9" stroke="#fff" stroke-width="3.5" stroke-linecap="round"/></svg>',
    status_scan: '<svg viewBox="0 0 64 64"><circle cx="32" cy="32" r="30" fill="#e3effc"/><circle cx="32" cy="32" r="22" fill="#057feb"/><g style="transform-origin:32px 32px;animation:spin 1.6s linear infinite"><path d="M32 32V16a16 16 0 0 1 14 8z" fill="rgba(255,255,255,.55)"/></g><circle cx="32" cy="32" r="12" fill="none" stroke="#fff" stroke-width="3"/><circle cx="32" cy="32" r="3" fill="#fff"/></svg>',
  };

  window.SS_TYPE_COLORS = {
    router: ["#e3effc", "#057feb"], nas: ["#e7ebf8", "#3c5bd0"], computer: ["#e6f1fd", "#2b7bd6"],
    server: ["#eceff3", "#56677a"], phone: ["#e5f6ec", "#279a56"], tablet: ["#e3f5f2", "#16958a"],
    printer: ["#f2ebfa", "#8a52c9"], camera: ["#fcebea", "#d9483b"], media: ["#fff0e0", "#df7810"],
    speaker: ["#fcedf5", "#c4407f"], console: ["#ececfb", "#5b5bd6"], iot: ["#fdf5d8", "#bd8c00"],
    network: ["#e2f4fa", "#1290b3"], virtual: ["#eef1f4", "#66778a"], voip: ["#eaf5e4", "#4e8a1f"], unknown: ["#eef1f4", "#98a4b0"],
  };
})();
