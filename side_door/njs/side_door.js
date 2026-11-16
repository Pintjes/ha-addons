// SPDX-License-Identifier: GPL-3.0-or-later
// Side Door: what nginx changes in the answers of the apps.
//
// run.py copies this file and puts the apps of the configuration in APPS:
//   { "<number>": { path, base, own, rewrite, inject, prefixes } }
//   path      path of the app under the ingress path ("/" or "/app/<id>/")
//   base      path of the app on its own server ("/" most of the time)
//   own       full address of the app ("http://192.168.1.10:8000/")
//   rewrite   move the paths of the app under the ingress path
//   inject    load the script that moves the addresses built in JavaScript
//   prefixes  texts found right before a path of the app
var APPS = {};
// run.py also sets MARK: it changes with the version of the add-on and with
// its configuration. It is put in the ETag of the answers, so that a browser
// never reuses a page or a script rewritten another way.
var MARK = '';

// Answers that are texts and may hold addresses
var TEXTS = {
    'text/html': 'html',
    'text/css': 'css',
    'application/javascript': 'js',
    'text/javascript': 'js',
    'application/x-javascript': 'js',
    'application/json': 'json',
    'application/graphql-response+json': 'json',
    'application/manifest+json': 'json'
};
// A bigger answer is relayed as it is
var LARGEST = 32 * 1024 * 1024;

// Kept for the whole answer (one copy of this script runs per request)
var nonce = '';
var kind = null;
var chunks = [];
var size = 0;

function app(r) {
    return APPS[r.variables.sd_app];
}

function textKind(r) {
    var type = r.headersOut['Content-Type'] || '';
    return TEXTS[type.split(';')[0].trim().toLowerCase()] || null;
}

// The kind of text of an answer the add-on may rewrite, or null. Left alone:
// an answer the app compressed anyway (its bytes are not text), and a piece
// of an answer (206), whose addresses may be cut in two.
function rewritable(r, a) {
    if (!a || !(a.rewrite || a.inject) || r.status === 206) {
        return null;
    }
    var encoding = String(r.headersOut['Content-Encoding'] || '').trim().toLowerCase();
    if (encoding && encoding !== 'identity') {
        return null;
    }
    return textKind(r);
}

function escapeRegExp(text) {
    return text.replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&');
}

function replaceAll(text, from, to) {
    return text.indexOf(from) === -1 ? text : text.split(from).join(to);
}

// The texts of an answer, with the addresses of the app moved
function rewrite(r, a, type, text) {
    var ingress = (r.variables.http_x_ingress_path || '') + a.path;
    if (a.rewrite) {
        // A path of the app right after a known text. Upper and lower case
        // are told apart: 'src="/' must not catch 'imgSrc="/' in a script.
        // "//host/..." is another site, not a path: left as it is.
        a.prefixes.forEach(function (prefix) {
            if (text.indexOf(prefix + a.base) === -1) {
                return;
            }
            var found = new RegExp(escapeRegExp(prefix + a.base) + (a.base === '/' ? '(?!\\/)' : ''), 'g');
            text = text.replace(found, function () { return prefix + ingress; });
        });
        // Full addresses of the app itself, as some apps write them in their
        // answers. They stay full addresses: an app may refuse a bare path.
        var full = (r.variables.sd_public || '') + ingress;
        text = replaceAll(text, a.own, full);
        text = replaceAll(text, a.own.replace(/\//g, '\\/'), full);
    }
    if (type === 'html' || type === 'js') {
        // An app may check the fingerprint of its scripts before running them
        // (Subresource Integrity). A rewritten script no longer has the
        // fingerprint the app knows, and would be refused: the check is dropped.
        if (type === 'html') {
            text = text.replace(/\sintegrity=("[^"]*"|'[^']*')/g, '');
        }
        text = text.replace(/\.integrity\s*=(?!=)/g, '.sdIntegrity=');
    }
    if (a.inject && (type === 'html' || type === 'js')) {
        // The app sees an address bar without the ingress path, and itself
        // as the top page (see web/shim.js)
        text = text.replace(/\bwindow\.location(?![\w$])/g, 'window.__sd_loc')
            .replace(/\bdocument\.location(?![\w$])/g, 'document.__sd_loc')
            .replace(/\bwindow\.(top|parent)(?![\w$])/g, 'window.self');
        if (type === 'html') {
            var tag = '<script src="' + (r.variables.http_x_ingress_path || '') + '/side_door_shim.js" data-base="'
                + ingress + '"' + (nonce ? ' nonce="' + nonce + '"' : '') + '></script>';
            text = text.replace(/<head(\s[^>]*)?>/i, function (head) { return head + tag; });
        }
    }
    return text;
}

// The cookies of an app, made acceptable for the browser:
// - "Domain=": the domain the app names (its own) is not the one of Home
//   Assistant, and the browser would refuse the cookie. Without it, the cookie
//   belongs to the address of Home Assistant, which is the one in use.
// - Home Assistant opened in plain HTTP: a browser refuses, on a plain HTTP
//   page, a cookie marked "Secure", and one marked "Partitioned" or
//   "SameSite=None" without "Secure". Over HTTPS these marks are left alone.
function cookies(r, plain) {
    var list = r.headersOut['Set-Cookie'];
    if (!list) {
        return;
    }
    if (!Array.isArray(list)) {
        list = [list];
    }
    r.headersOut['Set-Cookie'] = list.map(function (cookie) {
        cookie = cookie.replace(/;\s*domain=[^;]*/ig, '');
        if (plain) {
            cookie = cookie
                .replace(/;\s*(secure|partitioned)(?=\s*(;|$))/ig, '')
                .replace(/;\s*samesite=none/ig, '; SameSite=Lax');
        }
        return cookie;
    });
}

// The security policy of a page (Content-Security-Policy). The page is shown
// inside the Home Assistant panel: the rule that says who may show it
// ("frame-ancestors") is taken out, like X-Frame-Options. The rest is kept;
// when the policy only runs the scripts that carry its pass ("nonce"), the
// pass is noted for the script the add-on injects.
function framePolicy(r) {
    ['Content-Security-Policy', 'Content-Security-Policy-Report-Only'].forEach(function (name) {
        var policy = r.headersOut[name];
        if (!policy) {
            return;
        }
        var text = Array.isArray(policy) ? policy.join(', ') : String(policy);
        var pass = /'nonce-([A-Za-z0-9+\/_=-]+)'/.exec(text);
        if (pass && !nonce) {
            nonce = pass[1];
        }
        var kept = text.split(';').filter(function (rule) {
            return !/^\s*frame-ancestors(\s|$)/i.test(rule);
        }).join(';');
        if (kept.trim()) {
            r.headersOut[name] = kept;
        } else {
            delete r.headersOut[name];
        }
    });
}

function headers(r) {
    try {
        var a = app(r);
        framePolicy(r);
        cookies(r, r.variables.sd_plain === '1');
        // A permanent redirection is never kept by the browser: it would
        // still be followed after the address of the app has been corrected
        if (r.status === 301 || r.status === 308) {
            r.headersOut['Cache-Control'] = 'no-store';
        }
        // What the browser keeps is tied to this version and configuration:
        // nginx only lets through the ETags that carry the same mark
        var etag = r.headersOut['ETag'];
        if (etag) {
            r.headersOut['ETag'] = 'W/"' + MARK + '-' + etag.replace(/^W\//, '').replace(/^"|"$/g, '') + '"';
        }
        var type = rewritable(r, a);
        if (!type) {
            return;
        }
        // The text will change: so will its length, and its date says nothing
        delete r.headersOut['Content-Length'];
        delete r.headersOut['Last-Modified'];
        if (a.inject && (type === 'html' || type === 'js')) {
            // Checked again at each visit: turning the option on or off takes
            // effect without emptying the cache of the browser
            r.headersOut['Cache-Control'] = 'no-cache';
            delete r.headersOut['Expires'];
        }
    } catch (error) {
        r.error('side_door headers: ' + error);
    }
}

function body(r, data, flags) {
    var a = app(r);
    if (kind === null) {
        kind = rewritable(r, a) || 'as it is';
    }
    if (kind === 'as it is') {
        r.sendBuffer(data, flags);
        return;
    }
    chunks.push(data);
    size += data.length;
    if (size > LARGEST) {
        // Too big to be a page or a script: relayed as it is from here on
        r.sendBuffer(Buffer.concat(chunks), flags);
        chunks = [];
        kind = 'as it is';
        return;
    }
    if (!flags.last) {
        return;
    }
    var whole = Buffer.concat(chunks);
    chunks = [];
    try {
        // Only a text in UTF-8 is rewritten. A page in another encoding
        // (ISO-8859-1, Windows-1252...) read as UTF-8 would lose its accented
        // letters: it is relayed as it is. Read then written back, a UTF-8
        // text gives the same bytes; any other does not.
        var text = whole.toString('utf8');
        if (Buffer.compare(Buffer.from(text, 'utf8'), whole) !== 0) {
            r.sendBuffer(whole, flags);
            return;
        }
        r.sendBuffer(rewrite(r, a, kind, text), flags);
    } catch (error) {
        r.error('side_door body: ' + error);
        r.sendBuffer(whole, flags);
    }
}

export default { headers, body };
