const Module = require("node:module");

const load = Module._load;
Module._load = function loadRollup(request, parent, isMain) {
  if (request.startsWith("@rollup/rollup-") && request !== "@rollup/wasm-node") {
    return require("@rollup/wasm-node/dist/native.js");
  }
  return load.call(this, request, parent, isMain);
};
