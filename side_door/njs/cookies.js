// SPDX-License-Identifier: GPL-3.0-or-later
// Side Door: cookies of an app when Home Assistant is opened in plain HTTP.
//
// A browser refuses, on a plain HTTP page, a cookie marked "Secure", and one
// marked "Partitioned" or "SameSite=None" without "Secure". An app that marks
// its session cookie that way could never log anyone in: the marks are removed.
// Over HTTPS this code is not called and the cookies are left as they are.
function plain(r) {
    var cookies = r.headersOut['Set-Cookie'];
    if (!cookies) {
        return;
    }
    if (!Array.isArray(cookies)) {
        cookies = [cookies];
    }
    r.headersOut['Set-Cookie'] = cookies.map(function (cookie) {
        return cookie
            .replace(/;\s*(secure|partitioned)(?=\s*(;|$))/ig, '')
            .replace(/;\s*samesite=none/ig, '; SameSite=Lax');
    });
}

export default { plain };
