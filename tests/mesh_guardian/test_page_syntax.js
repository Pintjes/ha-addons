// 2.40.15: every inline <script> of the page must be valid JavaScript. A stray comma in the texts
// (2.40.14) made the whole script fail and the page showed nothing, while the backend answered fine.
// The scripts are only compiled here (new vm.Script), never run. Same check as `node --check`.
const fs = require("fs"), vm = require("vm");
const file = process.argv[2];
const html = fs.readFileSync(file, "utf8");
const fail = m => { console.error("FAIL", m); process.exit(1); };
const found = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];
const inline = found.filter(m => !/\bsrc\s*=/.test(m[1]) && !/type\s*=\s*["'](?!module|text\/javascript|application\/javascript)/.test(m[1]));
if (!inline.length) fail("no inline script found in " + file);
let big = 0;
inline.forEach((m, i) => {
  const line = html.slice(0, m.index).split("\n").length;   // line of the <script> tag
  try {
    new vm.Script(m[2], {filename: `${file}#script${i + 1}`, lineOffset: line - 1});
  } catch (e) {
    const where = (e.stack || "").split("\n").slice(0, 4).join(" | ");
    fail(`inline script ${i + 1} (from line ${line}): ${e.name}: ${e.message} (${where})`);
  }
  big = Math.max(big, m[2].length);
});
// the files of the page it loads (QR code) must be valid too
for (const m of found.filter(m => /\bsrc\s*=/.test(m[1]))) {
  const src = (m[1].match(/src\s*=\s*["']([^"']+)["']/) || [])[1];
  const p = src && require("path").join(require("path").dirname(file), src);
  if (p && fs.existsSync(p) && p.endsWith(".js")) {
    try { new vm.Script(fs.readFileSync(p, "utf8"), {filename: p}); } catch (e) { fail(`${src}: ${e.message}`); }
  }
}
if (big < 10000) fail("the main script looks too small: " + big);
console.log("OK");
