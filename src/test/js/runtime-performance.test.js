"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const context = {
  window: {
    requestAnimationFrame(callback) {
      callback();
      return 1;
    },
  },
};
vm.createContext(context);
vm.runInContext(
  fs.readFileSync("src/main/resources/static/static/js/runtime-performance.js", "utf8"),
  context
);

function createScene(id) {
  return {
    id,
    clone() { return createScene(id); },
    traverse() {},
  };
}

async function testGltfPromiseCache() {
  let loadCount = 0;
  const loader = {
    load(path, success) {
      loadCount += 1;
      setTimeout(() => success({ scene: createScene(path), animations: [] }), 0);
    },
  };
  const cache = context.window.DuoPerformance.createGltfCache(loader);
  const [first, second] = await Promise.all([
    cache.loadFirst(["/chair.glb"]),
    cache.loadFirst(["/chair.glb"]),
  ]);

  assert.equal(loadCount, 1, "동일 GLB의 동시 요청은 한 번만 로드해야 합니다.");
  assert.notEqual(first.scene, second.scene, "각 배치에는 독립된 scene 복제본이 필요합니다.");
  assert.equal(cache.size, 1);
}

testGltfPromiseCache()
  .then(() => console.log("runtime-performance cache test: OK"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
