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
vm.runInContext(src + "\nthis.matterDevices = matterDevices; this.watchNewDevice = watchNewDevice; this.nameSave = nameSave;", ctx);
(async () => {
  const before = await ctx.matterDevices(hass);
  assert(before.length === 1 && before[0].id === "a", "seuls les appareils Matter");
  const p = ctx.watchNewDevice(hass, new Set(before.map(d => d.id)));
  await new Promise(r => setImmediate(r));
  assert(listeners["matter-commission-finish"], "ecoute de la fin d'appairage");
  listeners["matter-commission-finish"]({detail: {name: "Prise du telephone", success: true}});
  devices = devices.concat([{id: "n", identifiers: [["matter", "w"]], name: "GRILLPLATS Plug", manufacturer: "IKEA", model: "GRILLPLATS Plug", area_id: "b"}]);
  await p;
  assert(sheet.includes("nm_title") && sheet.includes('value="Prise du telephone"'), "fiche avec le nom donne sur le telephone: " + sheet.slice(0, 200));
  assert(sheet.includes('<option value="b" selected>Bureau</option>') && sheet.indexOf("Bureau") < sheet.indexOf("Salon"), "pieces triees, la sienne choisie");
  assert(!listeners["matter-commission-finish"], "ecoute retiree");
  const btn = {disabled: false};
  await ctx.nameSave({n: {value: "  Prise TV Louise "}, a: {value: "s"}, querySelector: () => btn});
  const up = calls.find(c => c.type === "config/device_registry/update");
  assert(up && up.device_id === "n" && up.name_by_user === "Prise TV Louise" && up.area_id === "s", "mise a jour envoyee");
  assert(toasts.includes("nm_saved") && closed === 1, "message et fermeture");
  console.log("OK");
})();
