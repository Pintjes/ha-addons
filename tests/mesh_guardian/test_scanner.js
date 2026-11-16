// Essai de scanQr / canScan de la page, avec une fausse application Home Assistant.
const fs = require("fs"), vm = require("vm");
const html = fs.readFileSync(process.argv[2], "utf8");
const js = html.match(/<script[^>]*>([\s\S]*?)<\/script>/)[1];
const cut = (from, to) => js.slice(js.indexOf(from), js.indexOf(to));
const src = cut("const appBus = ", "async function pairStart(");
const sent = [];
const ext = {config: {hasBarCodeScanner: 1}, fireMessage: m => sent.push(m), _commandHandler: m => { ext.seen = m.command; return true; }};
const winEv = {};
const ctx = {window: {parent: {document: {querySelector: () => ({hass: {auth: {external: ext}}})}}, addEventListener: (n, f) => { winEv[n] = f; }},
  L: k => k, setTimeout: () => 0, console, panelBusy: () => false};
vm.createContext(ctx);
vm.runInContext(src + "\nthis.canScan = canScan; this.scanQr = scanQr;", ctx);
const assert = (c, m) => { if (!c) { console.error("ECHEC", m); process.exit(1); } };
(async () => {
  const orig = ext._commandHandler;
  assert(ctx.canScan(), "canScan");
  let p = ctx.scanQr("alt");
  assert(sent[0].type === "bar_code/scan" && sent[0].payload.alternative_option_label === "alt", "demande de scan");
  assert(ext._commandHandler !== orig, "gestionnaire enveloppe");
  assert(ext._commandHandler({id: 1, command: "navigate"}) === true && ext.seen === "navigate", "autres messages laisses a Home Assistant");
  ext._commandHandler({id: 2, command: "bar_code/scan_result", payload: {rawValue: "https://exemple", format: "qr_code"}});
  assert(sent.some(m => m.type === "bar_code/notify"), "mauvais code signale");
  ext._commandHandler({id: 3, command: "bar_code/scan_result", payload: {rawValue: "MT:Y.K9042C00KA0648G00", format: "qr_code"}});
  let r = await p;
  assert(r.text === "MT:Y.K9042C00KA0648G00", "texte lu");
  assert(ext._commandHandler === orig, "gestionnaire remis en place");
  assert(sent.some(m => m.type === "result" && m.id === 3 && m.success) && sent.some(m => m.type === "bar_code/close"), "accuse et fermeture");
  p = ctx.scanQr("alt");
  ext._commandHandler({id: 4, command: "bar_code/aborted", payload: {reason: "canceled"}});
  r = await p;
  assert(r.aborted === "canceled" && ext._commandHandler === orig, "abandon");
  // un seul scan a la fois : le second repond « occupe » sans toucher au gestionnaire
  p = ctx.scanQr("alt");
  const mine = ext._commandHandler;
  r = await ctx.scanQr("alt");
  assert(r.aborted === "busy" && ext._commandHandler === mine, "second scan refuse");
  // page quittee pendant le scan : le gestionnaire de Home Assistant est rendu
  assert(typeof winEv.pagehide === "function", "ecoute de pagehide");
  winEv.pagehide();
  r = await p;
  assert(r.aborted === "left" && ext._commandHandler === orig, "rendu en quittant la page");
  // Home Assistant a remplace le gestionnaire entre-temps : on ne l'ecrase pas
  p = ctx.scanQr("alt");
  const theirs = () => true;
  ext._commandHandler = theirs;
  winEv.pagehide();
  await p;
  assert(ext._commandHandler === theirs, "gestionnaire de Home Assistant non ecrase");
  ext._commandHandler = orig;
  delete ext._commandHandler;
  assert(!ctx.canScan(), "pas de lecteur si Home Assistant change");
  ext.config = {};
  assert(!ctx.canScan(), "pas de lecteur si l'application n'en a pas");
  console.log("OK");
})();
