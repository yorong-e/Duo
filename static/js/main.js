/**
 * DuO — Digital Twin Interior Web Simulator
 * 리팩토링: 기능별 함수 분리
 * - 평면도(JSON) 업로드 버그 수정 (이미지 임베드 포맷 대응)
 * - 평면도 이미지 크기 확대
 * - 가구 드래그 시 "분해되는" 버그 수정 (모델 최상위 그룹 단위로 이동)
 * - 가구 회전 / 삭제 기능 추가
 *
 * 평면도 JSON 지원 포맷 (2가지)
 * ------------------------------------------------------------
 * (A) 이미지 임베드 포맷 (실사용 파일, 예: "84A평면도_투시도.json")
 *     SVG -> JSON 변환 결과물로, 평면도/투시도 이미지가 base64 PNG로
 *     통째로 들어있는 구조입니다.
 *     {
 *       "@attributes": { "width": "595", "height": "842" },
 *       "image": {
 *         "@attributes": {
 *           "width": "595", "height": "842",
 *           "xlink:href": "data:image/png;base64,...."
 *         }
 *       }
 *     }
 *     -> data:image 로 시작하는 base64 문자열을 재귀 탐색해서 찾고,
 *        해당 이미지를 바닥 텍스처(Plane)로 렌더링합니다.
 *
 * (B) 벡터 포맷 (레거시/향후 확장용 fallback)
 *     {
 *       "width": 6000, "depth": 4000,
 *       "walls": [{ "x1":0,"y1":0,"x2":6000,"y2":0,"height":2400,"thickness":100 }],
 *       "doors": [{ "x":3000, "y":0, "radius":900 }]
 *     }
 *     -> walls 배열이 있으면 벽/문 클리어런스를 3D 박스/링으로 렌더링합니다.
 * ------------------------------------------------------------
 *
 * 가구 드래그 관련 참고
 * ------------------------------------------------------------
 * THREE.DragControls 는 recursive 옵션으로 GLB 내부의 하위 메쉬까지
 * 레이캐스트하면, 클릭된 개별 파츠(하위 메쉬)만 움직이고 나머지는 그대로
 * 남는 문제가 있습니다 (모델이 "분해"되어 보이는 원인).
 * 이 파일에서는 DragControls 대신 커스텀 드래그 로직을 사용해서,
 * 클릭된 지점에서 부모를 타고 올라가 모델의 최상위 그룹(gltf.scene)을
 * 찾은 뒤 그 그룹 전체를 이동시킵니다.
 * ------------------------------------------------------------
 */

(function () {
  "use strict";

  // ===== 전역 상태 =====
  const state = {
    scene: null,
    camera: null,
    renderer: null,
    controls: null,
    furnitureMeshes: [], // 배치된 가구 모델(최상위 그룹) 목록
    floorPlanGroup: null, // 현재 로드된 평면도 그룹 (재업로드 시 정리용)

    selectedFurniture: null, // 현재 선택된 가구(최상위 그룹)
    selectionHelper: null, // 선택 표시용 BoxHelper
    isDragging: false,
    dragOffset: null, // THREE.Vector3, 드래그 시작 시 (교차점 - 모델위치) 오프셋
  };

  const gltfLoader = new THREE.GLTFLoader();
  const textureLoader = new THREE.TextureLoader();

  const MM_TO_SCENE = 0.001; // mm -> 씬 단위(m) 변환 계수 (벡터 포맷용)
  const FLOOR_PLAN_TARGET_SIZE = 20; // 평면도 이미지를 씬에 배치할 때 긴 변 기준 목표 크기(m). 더 크게/작게 하려면 이 값을 조정하세요.

  // 드래그용 재사용 객체 (매 프레임 새로 생성하지 않도록 모듈 스코프에 미리 생성)
  const raycaster = new THREE.Raycaster();
  const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  const pointerNDC = new THREE.Vector2();
  const planeIntersectPoint = new THREE.Vector3();

  // ===== 진입점 =====
  window.onload = function () {
    console.log("App Starting...");
    initScene();
    initInteraction();
    initFloorPlanLoader();
    loadCatalog();
    window.addEventListener("resize", onWindowResize);
    animate();
  };

  // =========================================================
  // 1. Scene / Camera / Renderer 초기화
  // =========================================================
  function initScene() {
    const container = getCanvasContainer();

    state.scene = createScene();
    state.camera = createCamera(container);
    state.renderer = createRenderer(container);
    state.controls = createOrbitControls(state.camera, state.renderer);

    addLights(state.scene);
    addGrid(state.scene);
  }

  function getCanvasContainer() {
    return document.getElementById("canvas-container");
  }

  function createScene() {
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xe5e7eb);
    return scene;
  }

  function createCamera(container) {
    const camera = new THREE.PerspectiveCamera(
      60,
      container.clientWidth / container.clientHeight,
      0.1,
      1000
    );
    camera.position.set(5, 5, 5);
    return camera;
  }

  function createRenderer(container) {
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.shadowMap.enabled = true;
    container.appendChild(renderer.domElement);
    return renderer;
  }

  function createOrbitControls(camera, renderer) {
    const controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    return controls;
  }

  function addLights(scene) {
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
    scene.add(ambientLight);

    const dirLight = new THREE.DirectionalLight(0xffffff, 0.6);
    dirLight.position.set(5, 10, 7);
    dirLight.castShadow = true;
    scene.add(dirLight);
  }

  function addGrid(scene) {
    const gridHelper = new THREE.GridHelper(20, 20, 0x004b87, 0xaaaaaa);
    gridHelper.position.y = 0.01;
    scene.add(gridHelper);
  }

  // =========================================================
  // 2. 상호작용 (가구 선택 / 드래그 이동 / 회전 / 삭제)
  // =========================================================
  function initInteraction() {
    const container = getCanvasContainer();
    const toolbar = document.getElementById("furniture-toolbar");
    const rotateBtn = document.getElementById("btn-rotate");
    const deleteBtn = document.getElementById("btn-delete");

    state.dragOffset = new THREE.Vector3();

    container.addEventListener("pointerdown", (e) => onPointerDown(e, container, toolbar));
    container.addEventListener("pointermove", (e) => onPointerMove(e, container));
    window.addEventListener("pointerup", onPointerUp);

    // 툴바가 canvas-container 내부에 위치해 있어서, 버튼을 누르는 순간의
    // pointerdown이 그대로 컨테이너까지 버블링되어 "빈 공간 클릭"으로 처리되고
    // 선택이 풀려버리는 문제가 있었다. 툴바 안에서 발생한 pointerdown은
    // 캔버스 쪽으로 전달되지 않도록 막아서 회전/삭제 버튼이 정상 동작하게 한다.
    if (toolbar) {
      toolbar.addEventListener("pointerdown", (e) => e.stopPropagation());
    }

    if (rotateBtn) rotateBtn.addEventListener("click", rotateSelectedFurniture);
    if (deleteBtn) deleteBtn.addEventListener("click", () => deleteSelectedFurniture(toolbar));
  }

  function updatePointerNDC(e, container) {
    const rect = container.getBoundingClientRect();
    pointerNDC.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    pointerNDC.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
  }

  function onPointerDown(e, container, toolbar) {
    updatePointerNDC(e, container);
    raycaster.setFromCamera(pointerNDC, state.camera);

    const intersects = raycaster.intersectObjects(state.furnitureMeshes, true);

    if (intersects.length === 0) {
      selectFurniture(null, toolbar);
      return;
    }

    const root = findFurnitureRoot(intersects[0].object);
    selectFurniture(root, toolbar);

    if (raycaster.ray.intersectPlane(groundPlane, planeIntersectPoint)) {
      state.dragOffset.copy(planeIntersectPoint).sub(root.position);
      state.isDragging = true;
      state.controls.enabled = false;
    }
  }

  function onPointerMove(e, container) {
    if (!state.isDragging || !state.selectedFurniture) return;

    updatePointerNDC(e, container);
    raycaster.setFromCamera(pointerNDC, state.camera);

    if (raycaster.ray.intersectPlane(groundPlane, planeIntersectPoint)) {
      state.selectedFurniture.position.x = planeIntersectPoint.x - state.dragOffset.x;
      state.selectedFurniture.position.z = planeIntersectPoint.z - state.dragOffset.z;
      if (state.selectionHelper) state.selectionHelper.update();
    }
  }

  function onPointerUp() {
    if (!state.isDragging) return;
    state.isDragging = false;
    state.controls.enabled = true;
  }

  // 클릭된 하위 메쉬에서 부모를 타고 올라가 씬에 직접 추가된 최상위 모델(gltf.scene)을 찾는다.
  // -> 이 최상위 그룹을 통째로 옮겨야 GLB가 "분해"되지 않는다.
  function findFurnitureRoot(object) {
    let current = object;
    while (current.parent && current.parent !== state.scene) {
      current = current.parent;
    }
    return current;
  }

  function selectFurniture(model, toolbar) {
    if (state.selectedFurniture === model) return;

    clearSelectionHighlight();
    state.selectedFurniture = model;

    if (model) {
      state.selectionHelper = new THREE.BoxHelper(model, 0x004b87);
      state.scene.add(state.selectionHelper);
      if (toolbar) toolbar.style.display = "flex";
    } else if (toolbar) {
      toolbar.style.display = "none";
    }
  }

  function clearSelectionHighlight() {
    if (!state.selectionHelper) return;
    state.scene.remove(state.selectionHelper);
    state.selectionHelper.geometry.dispose();
    state.selectionHelper.material.dispose();
    state.selectionHelper = null;
  }

  function rotateSelectedFurniture() {
    if (!state.selectedFurniture) return;
    state.selectedFurniture.rotation.y += Math.PI / 2; // 90도 회전
    if (state.selectionHelper) state.selectionHelper.update();
  }

  function deleteSelectedFurniture(toolbar) {
    const model = state.selectedFurniture;
    if (!model) return;

    state.scene.remove(model);
    disposeObject3D(model);

    state.furnitureMeshes = state.furnitureMeshes.filter((m) => m !== model);

    clearSelectionHighlight();
    state.selectedFurniture = null;
    if (toolbar) toolbar.style.display = "none";
  }

  // =========================================================
  // 3. 평면도(JSON) 업로드
  // =========================================================
  function initFloorPlanLoader() {
    const input = document.getElementById("floorPlanInput");
    if (!input) return;

    input.addEventListener("change", handleFloorPlanFileSelected);
  }

  function handleFloorPlanFileSelected(e) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;

    // 같은 파일을 다시 선택해도 change 이벤트가 발생하도록 초기화
    e.target.value = "";

    if (!file.name.toLowerCase().endsWith(".json")) {
      alert("JSON 형식의 평면도 파일만 업로드할 수 있습니다.");
      return;
    }

    const reader = new FileReader();

    reader.onload = (event) => {
      let planData;
      try {
        planData = JSON.parse(event.target.result);
      } catch (err) {
        console.error("평면도 JSON 파싱 실패:", err);
        alert("평면도 파일을 열 수 없습니다. JSON 형식이 올바른지 확인해주세요.");
        return;
      }

      try {
        loadFloorPlan(planData);
      } catch (err) {
        console.error("평면도 처리 실패:", err);
        alert("평면도 데이터를 불러오는 중 오류가 발생했습니다: " + err.message);
      }
    };

    reader.onerror = () => {
      console.error("파일 읽기 실패:", reader.error);
      alert("평면도 파일을 읽는 중 오류가 발생했습니다.");
    };

    reader.readAsText(file);
  }

  // 두 포맷(이미지 임베드 / 벡터)을 판별해서 분기
  function loadFloorPlan(planData) {
    const imageDataUri = findImageDataUri(planData);

    if (imageDataUri) {
      loadImageFloorPlan(planData, imageDataUri);
      return;
    }

    if (Array.isArray(planData && planData.walls)) {
      loadVectorFloorPlan(planData);
      return;
    }

    throw new Error(
      "지원하지 않는 평면도 형식입니다. (이미지 데이터 또는 walls 배열이 필요합니다)"
    );
  }

  // JSON 트리 어디에 있든 "data:image..." 로 시작하는 base64 문자열을 재귀 탐색
  function findImageDataUri(node, depth) {
    depth = depth || 0;
    if (depth > 20 || node == null) return null;

    if (typeof node === "string" && node.indexOf("data:image") === 0) {
      return node;
    }
    if (typeof node !== "object") return null;

    for (const key of Object.keys(node)) {
      const found = findImageDataUri(node[key], depth + 1);
      if (found) return found;
    }
    return null;
  }

  // ---- (A) 이미지 임베드 포맷 ----
  function loadImageFloorPlan(planData, imageDataUri) {
    const { width, height } = getFloorPlanPixelSize(planData);

    textureLoader.load(
      imageDataUri,
      (texture) => {
        clearFloorPlan();

        const scale = FLOOR_PLAN_TARGET_SIZE / Math.max(width, height);
        const planeW = width * scale;
        const planeH = height * scale;

        const geometry = new THREE.PlaneGeometry(planeW, planeH);
        const material = new THREE.MeshBasicMaterial({
          map: texture,
          side: THREE.DoubleSide,
          transparent: true,
        });
        const mesh = new THREE.Mesh(geometry, material);
        mesh.rotation.x = -Math.PI / 2; // 바닥에 눕히기
        // PlaneGeometry는 자기 중심(로컬 원점)을 기준으로 만들어지므로, 위치를
        // (0,0,0)으로 두면 평면도가 씬/그리드의 정중앙에 오게 된다.
        // (기존에는 planeW/2, planeH/2 로 이동시켜서 원점 기준 모서리에 붙어있었음)
        mesh.position.set(0, 0.001, 0); // 그리드와 겹치지 않게 y만 살짝 띄움

        const group = new THREE.Group();
        group.name = "floorPlan";
        group.add(mesh);

        state.scene.add(group);
        state.floorPlanGroup = group;

        focusCameraOnArea(planeW, planeH, new THREE.Vector3(0, 0, 0));
        console.log("평면도 이미지 로딩 완료");
      },
      undefined,
      (err) => {
        console.error("평면도 이미지 로드 실패:", err);
        alert("평면도 이미지를 불러오지 못했습니다.");
      }
    );
  }

  function getFloorPlanPixelSize(planData) {
    const rootAttrs = planData["@attributes"] || {};
    const imageAttrs = (planData.image && planData.image["@attributes"]) || {};

    const width = parseFloat(rootAttrs.width || imageAttrs.width) || 1000;
    const height = parseFloat(rootAttrs.height || imageAttrs.height) || 1000;
    return { width, height };
  }

  // ---- (B) 벡터 포맷 (레거시 fallback) ----
  function loadVectorFloorPlan(planData) {
    clearFloorPlan();

    const group = new THREE.Group();
    group.name = "floorPlan";

    planData.walls.forEach((wall) => addWallToGroup(group, wall));
    if (Array.isArray(planData.doors)) {
      planData.doors.forEach((door) => addDoorMarkerToGroup(group, door));
    }

    state.scene.add(group);
    state.floorPlanGroup = group;

    const width = (planData.width || 6000) * MM_TO_SCENE;
    const depth = (planData.depth || 4000) * MM_TO_SCENE;
    focusCameraOnArea(width, depth);
    console.log("평면도(벡터) 로딩 완료");
  }

  function addWallToGroup(group, wall) {
    const { x1, y1, x2, y2 } = wall || {};
    if ([x1, y1, x2, y2].some((v) => typeof v !== "number")) {
      console.warn("잘못된 벽 데이터, 건너뜁니다:", wall);
      return;
    }

    const height = (wall.height || 2400) * MM_TO_SCENE;
    const thickness = (wall.thickness || 100) * MM_TO_SCENE;

    const dx = (x2 - x1) * MM_TO_SCENE;
    const dy = (y2 - y1) * MM_TO_SCENE;
    const length = Math.sqrt(dx * dx + dy * dy);
    if (length === 0) return;

    const geometry = new THREE.BoxGeometry(length, height, thickness);
    const material = new THREE.MeshStandardMaterial({ color: 0xcccccc });
    const mesh = new THREE.Mesh(geometry, material);

    const midX = (x1 + x2) * 0.5 * MM_TO_SCENE;
    const midZ = (y1 + y2) * 0.5 * MM_TO_SCENE;
    mesh.position.set(midX, height / 2, midZ);
    mesh.rotation.y = -Math.atan2(dy, dx);
    mesh.castShadow = true;
    mesh.receiveShadow = true;

    group.add(mesh);
  }

  function addDoorMarkerToGroup(group, door) {
    const { x, y } = door || {};
    if (typeof x !== "number" || typeof y !== "number") {
      console.warn("잘못된 문 데이터, 건너뜁니다:", door);
      return;
    }
    const radius = (door.radius || 900) * MM_TO_SCENE;

    const geometry = new THREE.RingGeometry(Math.max(radius - 0.02, 0.01), radius, 32);
    const material = new THREE.MeshBasicMaterial({
      color: 0x004b87,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.5,
    });
    const ring = new THREE.Mesh(geometry, material);
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(x * MM_TO_SCENE, 0.02, y * MM_TO_SCENE);

    group.add(ring);
  }

  // ---- 공통 ----
  function clearFloorPlan() {
    if (!state.floorPlanGroup) return;
    state.scene.remove(state.floorPlanGroup);
    disposeObject3D(state.floorPlanGroup);
    state.floorPlanGroup = null;
  }

  // 그룹/모델을 씬에서 제거하기 전에 geometry/material(및 텍스처)을 재귀적으로 정리
  function disposeObject3D(object) {
    object.traverse((obj) => {
      if (obj.geometry) obj.geometry.dispose();
      if (obj.material) {
        const materials = Array.isArray(obj.material) ? obj.material : [obj.material];
        materials.forEach((m) => {
          if (m.map) m.map.dispose();
          m.dispose();
        });
      }
    });
  }

  // width/depth(씬 단위, m)에 맞춰 카메라를 평면도가 잘 보이는 위치로 이동
  // centerOverride를 주면 그 지점을 기준으로, 없으면 (width/2, 0, depth/2)를 기준으로 삼는다.
  function focusCameraOnArea(width, depth, centerOverride) {
    const center = centerOverride || new THREE.Vector3(width / 2, 0, depth / 2);
    const distance = Math.max(width, depth) * 1.2 || 5;

    state.camera.position.set(center.x + distance, distance, center.z + distance);
    state.controls.target.copy(center);
    state.controls.update();
  }

  // =========================================================
  // 4. 카탈로그 (서버 API 연동)
  // =========================================================
  async function loadCatalog() {
    console.log("카탈로그 로딩 중...");
    const listEl = document.getElementById("furniture-list");
    if (!listEl) return;

    try {
      const items = await fetchFurnitureCatalog();
      renderCatalog(listEl, items);
      console.log("카탈로그 로딩 완료");
    } catch (e) {
      console.error("로딩 에러:", e);
      listEl.innerHTML = "데이터를 불러올 수 없습니다.";
    }
  }

  async function fetchFurnitureCatalog() {
    const res = await fetch("/api/furniture");
    if (!res.ok) throw new Error("API 요청 실패");
    return res.json();
  }

  function renderCatalog(listEl, items) {
    listEl.innerHTML = "";

    if (!items || items.length === 0) {
      const empty = document.createElement("p");
      empty.textContent = "표시할 가구가 없습니다.";
      empty.style.cssText = "padding:10px; color:#888; font-size:13px;";
      listEl.appendChild(empty);
      return;
    }

    items.forEach((item) => {
      listEl.appendChild(createFurnitureCard(item));
    });
  }

  // 카탈로그 한 항목을 이미지 + 이름 + 사이즈/치수 + 가격이 보이는 카드로 렌더링
  function createFurnitureCard(item) {
    const card = document.createElement("div");
    card.style.cssText = [
      "display:flex",
      "align-items:center",
      "gap:10px",
      "padding:8px",
      "margin-bottom:8px",
      "border:1px solid #e5e7eb",
      "border-radius:8px",
      "background:#fff",
      "cursor:pointer",
      "transition:box-shadow .15s ease, border-color .15s ease",
    ].join(";");
    card.addEventListener("mouseenter", () => {
      card.style.boxShadow = "0 2px 8px rgba(0,0,0,0.08)";
      card.style.borderColor = "#004b87";
    });
    card.addEventListener("mouseleave", () => {
      card.style.boxShadow = "none";
      card.style.borderColor = "#e5e7eb";
    });
    card.addEventListener("click", () => spawnFurniture(item));

    card.appendChild(createFurnitureThumbnail(item));
    card.appendChild(createFurnitureInfo(item));

    return card;
  }

  function createFurnitureThumbnail(item) {
    const thumb = document.createElement("img");
    thumb.src = item.image_url || "";
    thumb.alt = item.product_name || "furniture";
    thumb.style.cssText =
      "width:56px; height:56px; object-fit:contain; border-radius:6px; background:#f3f4f6; flex-shrink:0;";
    thumb.onerror = () => {
      // 이미지 URL이 없거나 로드에 실패하면 아이콘 플레이스홀더로 대체
      thumb.replaceWith(createThumbnailFallback());
    };
    return thumb;
  }

  function createThumbnailFallback() {
    const fallback = document.createElement("div");
    fallback.textContent = "🛋️";
    fallback.style.cssText =
      "width:56px; height:56px; display:flex; align-items:center; justify-content:center; " +
      "font-size:24px; background:#f3f4f6; border-radius:6px; flex-shrink:0;";
    return fallback;
  }

  function createFurnitureInfo(item) {
    const info = document.createElement("div");
    info.style.cssText = "flex:1; min-width:0;";

    if (item.category) {
      const categoryEl = document.createElement("div");
      categoryEl.textContent = item.category;
      categoryEl.style.cssText =
        "font-size:10px; color:#9ca3af; text-transform:uppercase; letter-spacing:.02em;";
      info.appendChild(categoryEl);
    }

    const nameEl = document.createElement("div");
    nameEl.textContent = item.product_name || "이름 없음";
    nameEl.style.cssText =
      "font-weight:600; font-size:13px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;";
    info.appendChild(nameEl);

    const metaEl = document.createElement("div");
    const sizeLabel = item.size ? `${item.size} · ` : "";
    metaEl.textContent = `${sizeLabel}${formatDimensions(item)}`;
    metaEl.style.cssText = "font-size:11px; color:#6b7280; margin-top:2px;";
    info.appendChild(metaEl);

    const priceEl = document.createElement("div");
    priceEl.textContent = formatPrice(item.price);
    priceEl.style.cssText = "font-size:12px; color:#004b87; font-weight:600; margin-top:4px;";
    info.appendChild(priceEl);

    return info;
  }

  function formatDimensions(item) {
    const w = formatNumber(item.width);
    const d = formatNumber(item.depth);
    const h = formatNumber(item.height);
    return `${w}×${d}×${h}cm`;
  }

  function formatNumber(value) {
    const num = Number(value) || 0;
    return Number.isInteger(num) ? String(num) : num.toFixed(1);
  }

  function formatPrice(value) {
    const num = Number(value) || 0;
    return num.toLocaleString("ko-KR") + "원";
  }

  // =========================================================
  // 5. 가구 배치 및 스케일링
  // =========================================================
  window.spawnFurniture = function (item) {
    const path = `/static/models/sofa/black_sofa.glb`; // 테스트용 경로

    gltfLoader.load(
      path,
      (gltf) => onFurnitureModelLoaded(gltf, item),
      undefined,
      (err) => console.error("로드 실패", err)
    );
  };

  function onFurnitureModelLoaded(gltf, item) {
    const model = gltf.scene;

    const box = new THREE.Box3().setFromObject(model);
    const size = box.getSize(new THREE.Vector3());

    const targetW = (item.width || 150) * 0.01;
    const targetH = (item.height || 80) * 0.01;
    const targetD = (item.depth || 80) * 0.01;

    model.scale.set(targetW / size.x, targetH / size.y, targetD / size.z);

    // 모델 최상위 그룹(gltf.scene)을 씬에 직접 추가한다.
    // 드래그 시에는 findFurnitureRoot()가 이 모델을 찾아서 통째로 이동시킨다.
    state.scene.add(model);
    state.furnitureMeshes.push(model);
  }

  // =========================================================
  // 6. 리사이즈 / 렌더 루프
  // =========================================================
  function onWindowResize() {
    const container = getCanvasContainer();
    state.camera.aspect = container.clientWidth / container.clientHeight;
    state.camera.updateProjectionMatrix();
    state.renderer.setSize(container.clientWidth, container.clientHeight);
  }

  function animate() {
    requestAnimationFrame(animate);
    state.controls.update();
    state.renderer.render(state.scene, state.camera);
  }
})();