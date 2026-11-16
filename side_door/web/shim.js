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
  var realTop = window.top;
  // When the app is a tab of the Side Door panel: the address of that panel,
  // ready to receive the page the app must open (see the tabs page of run.py)
  var panel = null;
  var tab = /\/app\/([^\/]+)\/$/.exec(base);
  if (tab && realTop !== window) {
    try {
      panel = realTop.location.origin + realTop.location.pathname + "?app=" + tab[1] + "&sd_path=";
    } catch (error) { /* the panel is on another site */ }
  }

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

  function elsewhere(value) {
    try {
      return new URL(String(value), shownHref()).host !== real.host;
    } catch (error) {
      return false;
    }
  }
  // An app that sends the browser to another site (a login service) tells it
  // where to come back. That address is the one the app sees; it becomes,
  // plain or encoded, the address of the panel followed by the page to open.
  // Coming back straight to the app would be refused: Home Assistant only
  // lets its own pages reach an app, not a page arriving from another site.
  function withReturnAddress(text) {
    var back = panel || origin + base;
    [[origin + "/", back], [encodeURIComponent(origin + "/"), encodeURIComponent(back)]]
      .forEach(function (pair) {
        text = text.split(pair[1]).join(pair[0]).split(pair[0]).join(pair[1]);
      });
    return text;
  }
  // Going to a page. Another site is opened in the whole window, not in the
  // panel: login pages refuse to be shown inside another page.
  function go(how, value) {
    if (!elsewhere(value)) {
      real[how](fix(value));
      return;
    }
    var address = withReturnAddress(String(value));
    if (realTop !== window) {
      try {
        realTop.location[how](address);
        return;
      } catch (error) { /* the panel is on another site: stay in the frame */ }
    }
    real[how](address);
  }

  // The address bar. The add-on replaces "window.location" and
  // "document.location" in the scripts of the app by this object.
  var fake = {
    get href() { return shownHref(); },
    set href(value) { go("assign", value); },
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
    assign: function (value) { go("assign", value); },
    replace: function (value) { go("replace", value); },
    reload: function () { real.reload(); },
    toString: function () { return shownHref(); }
  };
  [window, document].forEach(function (target) {
    Object.defineProperty(target, "__sd_loc", {
      get: function () { return fake; },
      set: function (value) { go("assign", value); },
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
  // The storage of the browser (localStorage, sessionStorage) is the one of
  // Home Assistant: an app that empties it at log out would log you out of
  // Home Assistant too. Each app gets its own part of it instead: it only
  // sees, changes and empties what it wrote itself.
  var part = "side_door/" + (tab ? tab[1] : "app") + "/";
  function ownPart(real) {
    function keys() {
      var found = [];
      for (var i = 0; i < real.length; i++) {
        var key = real.key(i);
        if (key !== null && key.indexOf(part) === 0) found.push(key.slice(part.length));
      }
      return found;
    }
    var methods = {
      getItem: function (key) { return real.getItem(part + String(key)); },
      setItem: function (key, value) { real.setItem(part + String(key), String(value)); },
      removeItem: function (key) { real.removeItem(part + String(key)); },
      clear: function () { keys().forEach(function (key) { real.removeItem(part + key); }); },
      key: function (index) { var all = keys(); return index >= 0 && index < all.length ? all[index] : null; }
    };
    return new Proxy({}, {
      get: function (target, name) {
        if (name === "length") return keys().length;
        if (Object.prototype.hasOwnProperty.call(methods, name)) return methods[name];
        if (typeof name === "symbol") return undefined;
        return methods.getItem(name) === null ? undefined : methods.getItem(name);
      },
      set: function (target, name, value) {
        if (typeof name !== "symbol") methods.setItem(name, value);
        return true;
      },
      has: function (target, name) {
        return name === "length" || Object.prototype.hasOwnProperty.call(methods, name) ||
          (typeof name !== "symbol" && methods.getItem(name) !== null);
      },
      deleteProperty: function (target, name) {
        if (typeof name !== "symbol") methods.removeItem(name);
        return true;
      },
      ownKeys: function () { return keys(); },
      getOwnPropertyDescriptor: function (target, name) {
        var value = typeof name === "symbol" ? null : methods.getItem(name);
        return value === null ? undefined : { value: value, writable: true, enumerable: true, configurable: true };
      }
    });
  }
  ["localStorage", "sessionStorage"].forEach(function (name) {
    try {
      var real = window[name];
      if (real) Object.defineProperty(window, name, { value: ownPart(real), configurable: true });
    } catch (error) { /* storage not available: left as it is */ }
  });

  // Cookies the app writes in JavaScript. A path the app gives ("path=/")
  // is moved under the path of the app, as for the cookies of its answers;
  // a domain it gives is dropped (it is not the one of Home Assistant).
  var cookieProperty = Object.getOwnPropertyDescriptor(Document.prototype, "cookie");
  if (cookieProperty && cookieProperty.set) {
    Object.defineProperty(document, "cookie", {
      get: function () { return cookieProperty.get.call(document); },
      set: function (value) {
        value = String(value)
          .replace(/;\s*domain=[^;]*/ig, "")
          .replace(/(;\s*path=)([^;]*)/i, function (all, start, path) {
            path = path.trim();
            return start + (path.charAt(0) === "/" && !under(path) ? base + path.slice(1) : path);
          });
        cookieProperty.set.call(document, value);
      },
      configurable: true
    });
  }

  var originalSetAttribute = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function (name, value) {
    var lower = String(name).toLowerCase();
    if ((lower === "src" || lower === "href") && /^(SCRIPT|IMG|LINK|A|IFRAME|SOURCE|VIDEO|AUDIO)$/.test(this.tagName)) {
      value = fix(value);
    }
    return originalSetAttribute.call(this, name, value);
  };
})();
