/* SynetScan DSM desktop integration.
 *
 * Since DSM 7.2 a "legacy" app entry opens in a browser tab instead of a DSM window, so the app
 * registers an ExtJS application (see ui/config) whose window holds the UI in an iframe. The
 * iframe is same-origin with the DSM desktop and reads the session token and language from it;
 * the token is also handed over in the URL fragment, which never reaches a server or a log.
 */
(function () {
  var BASE = "/webman/3rdparty/SynetScan/";
  var VERSION = "1.0.4";

  function session(key) {
    try { return _S(key) || ""; } catch (e) { return ""; }
  }

  Ext.define("SYNO.SDS.SynetScan.Instance", {
    extend: "SYNO.SDS.AppInstance",
    appWindowName: "SYNO.SDS.SynetScan.MainWindow",
    constructor: function () {
      this.callParent(arguments);
    }
  });

  Ext.define("SYNO.SDS.SynetScan.MainWindow", {
    extend: "SYNO.SDS.AppWindow",
    constructor: function (cfg) {
      var self = this;
      var frameId = Ext.id(null, "synetscan-frame-");
      var src = BASE + "index.html?v=" + VERSION + "&lang=" + encodeURIComponent(session("lang")) +
        "#SynoToken=" + encodeURIComponent(session("SynoToken"));
      var config = Ext.apply({
        title: "SynetScan",
        width: 1120,
        height: 740,
        minWidth: 820,
        minHeight: 520,
        showHelp: false,
        layout: "fit",
        items: [new Ext.BoxComponent({
          html: '<iframe id="' + frameId + '" title="SynetScan" src="' + src + '" ' +
            'style="border:0;width:100%;height:100%;display:block;background:#fff"></iframe>'
        })]
      }, cfg);
      this.callParent([config]);
      this.frameId = frameId;

      // A click inside the iframe never reaches DSM: bring this window to the front and close
      // DSM's open menus ourselves. bringToFront does not move the keyboard focus out of the frame.
      // DSM's top-bar dropdowns (user menu, notifications…) are not Ext menus; they close on a
      // mousedown/click anywhere else on the page, so replay the click on the frame element.
      function activate() {
        try { if (self.manager && self.manager.bringToFront) self.manager.bringToFront(self); } catch (e) { /* ignore */ }
        try { if (Ext.menu && Ext.menu.MenuMgr) Ext.menu.MenuMgr.hideAll(); } catch (e) { /* ignore */ }
        var frame = document.getElementById(frameId);
        if (frame) {
          ["mousedown", "mouseup", "click"].forEach(function (type) {
            try { frame.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window })); } catch (e) { /* ignore */ }
          });
        }
      }
      function onBlur() {
        setTimeout(function () {
          var frame = document.getElementById(frameId);
          if (frame && document.activeElement === frame) activate();
        }, 0);
      }
      function onActivate(e) {
        var frame = document.getElementById(frameId);
        if (frame && e.source === frame.contentWindow && e.data === "synetscan:activate") activate();
      }
      window.addEventListener("blur", onBlur);
      window.addEventListener("message", onActivate);
      this.on("destroy", function () {
        window.removeEventListener("blur", onBlur);
        window.removeEventListener("message", onActivate);
      });
    }
  });
})();
