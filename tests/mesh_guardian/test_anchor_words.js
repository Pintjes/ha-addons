// Bloc « avant l'ancrage / depuis » de la fiche du border router (2.40.0) : mots simples, accords
// singulier / pluriel (fr : 0 et 1,5 au singulier), arrondis lisibles, un « i » qui explique. Valeurs fictives.
const fs = require("fs"), vm = require("vm");
const html = fs.readFileSync(process.argv[2], "utf8");
const js = html.match(/<script[^>]*>([\s\S]*?)<\/script>/)[1];
const src = js.slice(js.indexOf("const ancPlural"), js.indexOf("function renderAnchor("));
const assert = (c, m) => { if (!c) { console.error("ECHEC", m); process.exit(1); } };
// textes : première occurrence = anglais, dernière = français
const texts = (last) => { const t = {}; for (const m of js.matchAll(/(anc_\w+):"([^"]*)"/g)) if (last || !(m[1] in t)) t[m[1]] = m[2]; return t; };
function run(lang) {
  const T = texts(lang === "fr");
  const ctx = {LANG: lang, L: k => T[k], F: (k, v) => T[k].replace(/\{(\w+)\}/g, (_, x) => v[x]), esc: s => s,
    tipI: s => `[i:${s.slice(0, 12)}]`, dec: v => String(Number(Number(v).toFixed(1))).replace(".", lang === "fr" ? "," : "."), Math, Number, String};
  vm.createContext(ctx);
  vm.runInContext(src + "\nthis.ancCompare = ancCompare; this.ancSpan = ancSpan;", ctx);
  return ctx;
}
const fr = run("fr"), en = run("en");
const strip = h => h.replace(/<[^>]+>/g, "|");
// avant : taux par jour, arrondi à l'unité au-dessus de 10, une décimale sinon ; « i » sur « Avant »
let [lab, val] = fr.ancCompare("anc_b", {days: 3.4, seconds: 293760, omr: 5, lost: 56, omr_per_day: 1.5, lost_per_day: 16.4});
assert(lab.startsWith("Avant l'ancrage (3 jours)") && lab.includes("[i:"), lab);
assert(strip(val) === "|16 décrochages par jour||1,5 changement de préfixe par jour|", val);
// depuis, moins d'un jour : les nombres tels quels, singulier pour 0 et 1
[lab, val] = fr.ancCompare("anc_a", {seconds: 9 * 3600 + 13 * 60, omr: 0, lost: 1});
assert(lab === "Depuis (9 h)" && !lab.includes("[i:"), lab);
assert(strip(val) === "|1 décrochage en 9 h||0 changement de préfixe|", val);
[, val] = fr.ancCompare("anc_a", {seconds: 600, omr: 2, lost: 3});
assert(strip(val) === "|3 décrochages en 10 min||2 changements de préfixe|", val);
// durées lisibles
assert(fr.ancSpan(2 * 3600 + 600) === "2 h 10 min" && fr.ancSpan(3600) === "1 h" && fr.ancSpan(1.2 * 86400) === "1,2 jour" && fr.ancSpan(5 * 86400) === "5 jours", "durées");
// anglais : 1 au singulier, 0 et 1,5 au pluriel
[lab, val] = en.ancCompare("anc_a", {seconds: 9 * 3600, omr: 0, lost: 1});
assert(lab === "Since (9 h)" && strip(val) === "|1 detach in 9 h||0 prefix changes|", val);
[, val] = en.ancCompare("anc_b", {days: 2, seconds: 172800, omr: 3, lost: 2, omr_per_day: 1.5, lost_per_day: 1});
assert(strip(val) === "|1 detach a day||1.5 prefix changes a day|", val);
assert(!fr.ancCompare("anc_b", null), "pas de période : rien");
console.log("OK");
