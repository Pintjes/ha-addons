// Aller-retour : QR code dessine par qrcode.js, relu par jsQR (les deux fichiers livres avec la page).
const fs = require("fs"), vm = require("vm"), path = require("path");
const web = process.argv[2];
const ctx = {self: {}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(web, "qrcode.js"), "utf8"), ctx);
vm.runInContext(fs.readFileSync(path.join(web, "jsqr.js"), "utf8"), ctx);
const qrcode = vm.runInContext("qrcode", ctx), jsQR = ctx.self.jsQR;
const text = "MT:Y.K9042C00KA0648G00";
const q = qrcode(0, "M"); q.addData(text, "Alphanumeric"); q.make();
const n = q.getModuleCount(), scale = 6, quiet = 4, w = (n + 2 * quiet) * scale;
const data = new Uint8ClampedArray(w * w * 4).fill(255);
for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) if (q.isDark(y, x))
  for (let dy = 0; dy < scale; dy++) for (let dx = 0; dx < scale; dx++) {
    const i = (((y + quiet) * scale + dy) * w + (x + quiet) * scale + dx) * 4;
    data[i] = data[i + 1] = data[i + 2] = 0;
  }
const r = jsQR(data, w, w);
console.log("modules", n, "relu:", r && r.data);
if (!r || r.data !== text) process.exit(1);
console.log("OK");
