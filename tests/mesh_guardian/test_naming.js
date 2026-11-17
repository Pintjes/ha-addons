// Essai de matterDevices / watchNewDevice / nameSave de la page, avec un faux Home Assistant.
const fs = require("fs"), vm = require("vm");
const html = fs.readFileSync(process.argv[2], "utf8");
const js = html.match(/<script[^>]*>([\s\S]*?)<\/script>/)[1];
const src = js.slice(js.indexOf("async function matterDevices("), js.indexOf("async function pairStart("));
const assert = (c, m) => { if (!c) { console.error("ECHEC", m); process.exit(1); } };
let devices = [{id: "a", identifiers: [["matter", "x"]]}, {id: "z", identifiers: [["zha", "y"]]}];
const calls = [], listeners = {};
const hass = {areas: {s: {area_id: "s", name: "Salon"}, b: {area_id: "b", name: "Bureau"}},
  callWS: async m => { calls.push(m); return m.type === "config/device_registry/list" ? devices : {}; }};
let sheet = "", toasts = [], closed = 0, loads = 0;
const ctx = {window: {parent: {addEventListener: (n, f) => { listeners[n] = f; }, removeEventListener: n => { delete listeners[n]; }}},
  setTimeout: (f, ms) => { if (ms <= 4000) setImmediate(f); return 0; }, Date, Promise, Object, String, console,
  L: k => k, esc: v => String(v ?? ""), head: (t, s) => `[${t}|${s}]`, openSheet: h => { sheet = h; }, closeSheet: () => { closed++; },
  toast: t => toasts.push(t), load: () => { loads++; }, openId: "x", pair: null, panelBusy: () => false};
vm.createContext(ctx);
vm.runInContext(src + "\nthis.matterDevices = matterDevices; this.watchNewDevice = watchNewDevice; this.nameSave = nameSave; Object.defineProperty(this, 'watching', {get: () => watching});", ctx);
(async () => {
  const before = await ctx.matterDevices(hass);
  assert(before.length === 1 && before[0].id === "a", "seuls les appareils Matter");
  const p = ctx.watchNewDevice(hass, new Set(before.map(d => d.id)));
  await new Promise(r => setImmediate(r));
  assert(listeners["matter-commission-finish"], "ecoute de la fin d'appairage");
  listeners["matter-commission-finish"]({detail: {name: "Prise du telephone", success: true}});
  devices = devices.concat([{id: "n", identifiers: [["matter", "w"]], name: "Smart Plug", manufacturer: "IKEA", model: "Smart Plug", area_id: "b"}]);
  await p;
  assert(sheet.includes("nm_title") && sheet.includes('value="Prise du telephone"'), "fiche avec le nom donne sur le telephone: " + sheet.slice(0, 200));
  assert(sheet.includes('<option value="b" selected>Bureau</option>') && sheet.indexOf("Bureau") < sheet.indexOf("Salon"), "pieces triees, la sienne choisie");
  assert(!listeners["matter-commission-finish"], "ecoute retiree");
  const btn = {disabled: false};
  await ctx.nameSave({n: {value: "  Prise TV Test "}, a: {value: "s"}, querySelector: () => btn});
  const up = calls.find(c => c.type === "config/device_registry/update");
  assert(up && up.device_id === "n" && up.name_by_user === "Prise TV Test" && up.area_id === "s", "mise a jour envoyee");
  assert(toasts.includes("nm_saved") && closed === 1, "message et fermeture");

  // Home Assistant annonce l'ajout dans son registre : lu à ce moment-là, sans sondage
  let onEvent = null, unsubs = 0, lists = 0;
  const hass2 = {areas: {}, connection: {subscribeEvents: async (cb, type) => { assert(type === "device_registry_updated", "type d'evenement"); onEvent = cb; return async () => { unsubs++; }; }},
    callWS: async m => { if (m.type === "config/device_registry/list") lists++; return m.type === "config/device_registry/list" ? devices : {}; }};
  const known = new Set(devices.map(d => d.id));
  const p2 = ctx.watchNewDevice(hass2, known);
  await new Promise(r => setImmediate(r));
  assert(onEvent && lists === 0, "abonne, registre pas encore lu");
  onEvent({data: {action: "update", device_id: "a"}});   // une mise à jour ne réveille pas
  await new Promise(r => setImmediate(r));
  assert(lists === 0, "update ignore");
  devices = devices.concat([{id: "m", identifiers: [["matter", "v"]], name: "Capteur"}]);
  onEvent({data: {action: "create", device_id: "m"}});
  await p2;
  assert(lists === 1 && sheet.includes('value="Capteur"') && unsubs === 1, "trouve des l'annonce, abonnement ferme");

  // un nouvel appairage remplace la veille du précédent (et la page quittée l'arrête)
  const p3 = ctx.watchNewDevice(hass2, new Set(devices.map(d => d.id)));
  await new Promise(r => setImmediate(r));
  const p4 = ctx.watchNewDevice(hass2, new Set(devices.map(d => d.id)));
  await p3;
  assert(unsubs === 2, "premiere veille arretee");
  await new Promise(r => setImmediate(r));
  ctx.watching.stop();
  await p4;
  assert(unsubs === 3 && ctx.watching === null, "seconde veille arretee");
  console.log("OK");
})();
