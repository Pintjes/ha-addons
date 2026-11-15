// SPDX-License-Identifier: GPL-3.0-or-later
// Side Door, option "inject_script".
//
// An app that builds its addresses in JavaScript believes it lives at "/".
// Behind the ingress it lives under a longer path (data-base on this script).
// This script, loaded before the app, moves the addresses the app builds
// under that path, and shows the app an address bar without it.
(function () {
  "use strict";
  var me = document.currentScript;
  var base = me && me.getAttribute("data-base");
  if (!base || window.__sd_loc) return;
  var real = window.location;
  var origin = real.origin;

  // The panel around the app is on the same site. An app that looks at its
  // parent must not take it for its own shell: it sees itself as the top page.
  try {
    Object.defineProperty(window, "parent", { value: window, configurable: true, writable: true });
  } catch (error) { /* kept as it is */ }
  try {
    Object.defineProperty(window, "frameElement", { value: null, configurable: true });
  } catch (error) { /* kept as it is */ }

  function under(path) {
    return path === base.slice(0, -1) || path.indexOf(base) === 0;
  }
  // The path as the app sees it
  function shown(path) {
    return under(path) ? "/" + path.slice(base.length) : path;
  }
  function shownHref() {
    return origin + shown(real.pathname) + real.search + real.hash;
  }
  // The address as the browser must request it
  function fix(value) {
    if (value === undefined || value === null || value === "") return value;
    var url;
    try {
      url = new URL(String(value), shownHref());
    } catch (error) {
      return value;
    }
    if (url.host !== real.host) return value; // another site, mailto:, data:, blob:
    if (!under(url.pathname)) url.pathname = base + url.pathname.slice(1);
    return url.href;
  }

  // The address bar. The add-on replaces "window.location" and
  // "document.location" in the scripts of the app by this object.
  var fake = {
    get href() { return shownHref(); },
    set href(value) { real.href = fix(value); },
    get pathname() { return shown(real.pathname); },
    set pathname(value) { real.pathname = base + String(value).replace(/^\//, ""); },
    get search() { return real.search; },
    set search(value) { real.search = value; },
    get hash() { return real.hash; },
    set hash(value) { real.hash = value; },
    get protocol() { return real.protocol; },
    get host() { return real.host; },
    get hostname() { return real.hostname; },
    get port() { return real.port; },
    get origin() { return origin; },
    get ancestorOrigins() { return real.ancestorOrigins; },
    assign: function (value) { real.assign(fix(value)); },
    replace: function (value) { real.replace(fix(value)); },
    reload: function () { real.reload(); },
    toString: function () { return shownHref(); }
  };
  [window, document].forEach(function (target) {
    Object.defineProperty(target, "__sd_loc", {
      get: function () { return fake; },
      set: function (value) { real.href = fix(value); },
      configurable: true
    });
  });

  // Navigation inside the app
  ["pushState", "replaceState"].forEach(function (name) {
    var original = history[name];
    history[name] = function (state, title, url) {
      return original.call(this, state, title, url === undefined || url === null ? url : fix(url));
    };
  });

  // Requests
  if (window.fetch) {
    var originalFetch = window.fetch;
    window.fetch = function (input, init) {
      if (typeof input === "string" || input instanceof URL) {
        input = fix(input);
      } else if (input && input.url) {
        var fixed = fix(input.url);
        if (fixed !== input.url) input = new Request(fixed, input);
      }
      return originalFetch.call(this, input, init);
    };
  }
  var originalOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    var args = Array.prototype.slice.call(arguments);
    args[1] = fix(url);
    return originalOpen.apply(this, args);
  };
  ["WebSocket", "EventSource"].forEach(function (name) {
    var Original = window[name];
    if (!Original) return;
    var Wrapped = function (url, more) {
      return arguments.length > 1 ? new Original(fix(url), more) : new Original(fix(url));
    };
    Wrapped.prototype = Original.prototype;
    ["CONNECTING", "OPEN", "CLOSING", "CLOSED"].forEach(function (key) {
      if (key in Original) Wrapped[key] = Original[key];
    });
    window[name] = Wrapped;
  });

  // Addresses the app puts on elements it creates
  [
    [window.HTMLScriptElement, "src"], [window.HTMLImageElement, "src"],
    [window.HTMLLinkElement, "href"], [window.HTMLAnchorElement, "href"],
    [window.HTMLIFrameElement, "src"], [window.HTMLSourceElement, "src"],
    [window.HTMLMediaElement, "src"]
  ].forEach(function (pair) {
    var proto = pair[0] && pair[0].prototype;
    var found = proto && Object.getOwnPropertyDescriptor(proto, pair[1]);
    if (!found || !found.set) return;
    Object.defineProperty(proto, pair[1], {
      get: found.get,
      set: function (value) { found.set.call(this, fix(value)); },
      configurable: true,
      enumerable: found.enumerable
    });
  });
  var originalSetAttribute = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function (name, value) {
    var lower = String(name).toLowerCase();
    if ((lower === "src" || lower === "href") && /^(SCRIPT|IMG|LINK|A|IFRAME|SOURCE|VIDEO|AUDIO)$/.test(this.tagName)) {
      value = fix(value);
    }
    return originalSetAttribute.call(this, name, value);
  };
})();
