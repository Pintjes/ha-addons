// 2.40.4: "Automatic recovery" in the facts shows its state like the line of the imposed prefix:
// dot + word, bold, green when on, orange when off; same words, no "i". Fictitious values only.
const fs = require("fs");
const page = fs.readFileSync(process.argv[2], "utf8");   // the page, given by run_all.py
const assert = (c, m) => { if (!c) { console.error("FAIL", m); process.exit(1); } };
const line = page.split("\n").find(l => l.includes('[L("f_recov"),'));
assert(line, "f_recov fact");
assert(line.includes('class="ancv ${n.auto_recovery ? "ok" : "warn"}"') && line.includes("<i></i>"), "dot and colour");
assert(line.includes('L(n.auto_recovery ? "on" : "off")'), "same words");
assert(!line.includes("tipI("), "no i");
// the style of the facts reuses the dot and colours of the prefix line
assert(/\.facts \.ancv \{[^}]*font-size: 12\.5px[^}]*font-weight: 600/.test(page), "size and weight of the prefix line");
assert(page.includes(".br .ancv.ok, .facts .ancv.ok { color: var(--ok); }"), "green");
assert(page.includes(".br .ancv.warn, .facts .ancv.warn { color: var(--warn); }"), "orange");
// the words exist in English and French
assert(page.includes('on:"on", off:"off"') && page.includes('on:"activée", off:"désactivée"'), "words");
console.log("OK");
