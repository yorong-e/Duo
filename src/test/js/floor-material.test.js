"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

let imageCount = 0;
class FakeImage {
  constructor() {
    imageCount += 1;
  }

  set src(value) {
    this._src = value;
    queueMicrotask(() => this.onload());
  }
}

const context = {
  console,
  Image: FakeImage,
  queueMicrotask,
  URL,
  window: {
    location: { href: "http://localhost/", origin: "http://localhost" },
    DuoPerformance: {
      createGltfCache() { return {}; },
      createFrameThrottle(callback) { return callback; },
    },
  },
  document: {
    getElementById() { return null; },
  },
  THREE: {
    GLTFLoader: class {},
    TextureLoader: class {},
    Raycaster: class {},
    Plane: class {},
    Vector2: class {},
    Vector3: class {},
  },
};

const mainPath = "src/main/resources/static/static/js/main.js";
let source = fs.readFileSync(mainPath, "utf8");
const closingIndex = source.lastIndexOf("})();");
assert.notEqual(closingIndex, -1, "main.js IIFE 종료 지점을 찾을 수 없습니다.");
source = `${source.slice(0, closingIndex)}
  window.__floorMaterialTest = {
    state,
    applyFloorMaterial,
    resizeBinaryMask,
    getCachedFloorImage
  };
${source.slice(closingIndex)}`;

vm.createContext(context);
vm.runInContext(source, context);

async function run() {
  const api = context.window.__floorMaterialTest;

  const resized = api.resizeBinaryMask(
    new Uint8Array([
      1, 1, 0, 0,
      1, 1, 0, 0,
      0, 0, 1, 1,
      0, 0, 1, 1,
    ]),
    4,
    4,
    2,
    2
  );
  assert.deepEqual(Array.from(resized), [1, 0, 0, 1], "축소 후에도 바닥 마스크 위치를 보존해야 합니다.");

  api.state.roomObjects = [];
  api.state.selectedRoomId = null;
  api.state.pendingFloorApplication = null;
  api.state.floorMaterialSelectionVersion = 0;
  assert.equal(api.applyFloorMaterial("oak"), false);
  assert.equal(api.state.pendingFloorApplication.materialValue, "oak", "방 분석 전 선택은 예약되어야 합니다.");
  assert.equal(api.state.floorMaterialSelectionVersion, 1, "사용자 선택 순서를 추적해야 합니다.");

  const first = api.getCachedFloorImage("/floorimage/oak.jpg");
  const second = api.getCachedFloorImage("/floorimage/oak.jpg");
  assert.equal(first, second, "같은 바닥 이미지는 하나의 로딩 작업을 공유해야 합니다.");
  await Promise.all([first, second]);
  assert.equal(imageCount, 1, "같은 바닥 이미지를 중복 생성하지 않아야 합니다.");

  console.log("floor material flow test: OK");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
