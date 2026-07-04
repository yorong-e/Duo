(function () {
  "use strict";

  const STORAGE_KEY = "duo-layout-v2";
  const MM_TO_SCENE = 0.001;
  const FLOOR_PLAN_TARGET_SIZE = 20;
  const SNAP_DISTANCE = 0.35;
  const WALL_BUFFER = 0.04;
  const IMAGE_WALL_DARKNESS = 92;
  const IMAGE_WALL_ALPHA = 24;

  const COLOR_FILTERS = [
    { value: "all", label: "All", swatch: "linear-gradient(135deg, #f8fafc, #004b87)" },
    { value: "white", label: "White", swatch: "#ffffff" },
    { value: "gray", label: "Gray", swatch: "#9ca3af" },
    { value: "black", label: "Black", swatch: "#111827" },
    { value: "brown", label: "Brown", swatch: "#8b5e3c" },
    { value: "blue", label: "Blue", swatch: "#004b87" },
  ];

  const TREND_PATTERNS = [
    {
      code: "A",
      name: "미니멀",
      color: "white",
      placements: [
        { category: "소파", x: -1.8, z: -1.2, rot: 0 },
        { category: "침대", x: 1.8, z: 1.1, rot: Math.PI / 2 },
      ],
    },
    {
      code: "B",
      name: "웜우드",
      color: "brown",
      placements: [
        { category: "소파", x: -2.1, z: 0.8, rot: Math.PI / 2 },
        { category: "침대", x: 1.8, z: -1.2, rot: 0 },
      ],
    },
    {
      code: "C",
      name: "모던블랙",
      color: "black",
      placements: [
        { category: "소파", x: -1.6, z: -1.5, rot: 0 },
        { category: "소파", x: 1.6, z: 1.5, rot: Math.PI },
      ],
    },
    {
      code: "D",
      name: "트렌드블루",
      color: "blue",
      placements: [
        { category: "소파", x: -1.9, z: 0, rot: Math.PI / 2 },
        { category: "침대", x: 1.7, z: 1.3, rot: 0 },
      ],
    },
  ];

  const state = {
    scene: null,
    camera: null,
    renderer: null,
    controls: null,
    floorPlanGroup: null,
    visualizationGroup: null,
    floorBounds: null,
    imageWallMask: null,
    wallObjects: [],
    furnitureMeshes: [],
    selectedFurniture: null,
    selectionHelper: null,
    collisionHelpers: [],
    isDragging: false,
    dragOffset: null,
    catalogItems: [],
    activeColor: "all",
    activePattern: "A",
    lastWarnings: [],
    blockedDragWarning: "",
    suppressAutoSelect: false,
  };

  const gltfLoader = new THREE.GLTFLoader();
  const textureLoader = new THREE.TextureLoader();
  const raycaster = new THREE.Raycaster();
  const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  const pointerNDC = new THREE.Vector2();
  const planeIntersectPoint = new THREE.Vector3();

  window.onload = function () {
    initScene();
    initInteraction();
    initFloorPlanLoader();
    renderTrendPatterns();
    loadCatalog();
    window.addEventListener("resize", onWindowResize);
    animate();
  };

  function initScene() {
    const container = getCanvasContainer();
    state.scene = new THREE.Scene();
    state.scene.background = new THREE.Color(0xe5e7eb);
    state.camera = new THREE.PerspectiveCamera(60, container.clientWidth / container.clientHeight, 0.1, 1000);
    state.camera.position.set(5, 6, 7);
    state.renderer = new THREE.WebGLRenderer({ antialias: true });
    state.renderer.setSize(container.clientWidth, container.clientHeight);
    state.renderer.shadowMap.enabled = true;
    container.appendChild(state.renderer.domElement);

    state.controls = new THREE.OrbitControls(state.camera, state.renderer.domElement);
    state.controls.enableDamping = true;

    state.scene.add(new THREE.AmbientLight(0xffffff, 0.82));
    const dirLight = new THREE.DirectionalLight(0xffffff, 0.72);
    dirLight.position.set(6, 10, 8);
    dirLight.castShadow = true;
    state.scene.add(dirLight);

    const grid = new THREE.GridHelper(20, 20, 0x004b87, 0xaaaaaa);
    grid.position.y = 0.01;
    state.scene.add(grid);
    setFloorBounds({ minX: -10, maxX: 10, minZ: -10, maxZ: 10 });
  }

  function getCanvasContainer() {
    return document.getElementById("canvas-container");
  }

  function initInteraction() {
    const container = getCanvasContainer();
    const toolbar = document.getElementById("furniture-toolbar");
    const labelInput = document.getElementById("material-label-input");

    state.dragOffset = new THREE.Vector3();
    container.addEventListener("pointerdown", (e) => onPointerDown(e, container, toolbar));
    container.addEventListener("pointermove", (e) => onPointerMove(e, container));
    container.addEventListener("dragover", (e) => e.preventDefault());
    container.addEventListener("drop", (e) => onCatalogDrop(e, container));
    window.addEventListener("pointerup", onPointerUp);

    if (toolbar) toolbar.addEventListener("pointerdown", (e) => e.stopPropagation());
    bindClick("btn-rotate", rotateSelectedFurniture);
    bindClick("btn-delete", () => deleteSelectedFurniture(toolbar));
    bindClick("btn-accept", acceptLayout);
    bindClick("btn-save", saveLayout);
    bindClick("btn-load", loadSavedLayout);
    bindClick("btn-pdf", downloadEstimatePdf);

    if (labelInput) {
      labelInput.addEventListener("input", () => {
        if (!state.selectedFurniture) return;
        state.selectedFurniture.userData.label = labelInput.value.trim() || state.selectedFurniture.userData.productName;
        updateEstimate();
      });
    }
  }

  function bindClick(id, handler) {
    const el = document.getElementById(id);
    if (el) el.addEventListener("click", handler);
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
    if (!raycaster.ray.intersectPlane(groundPlane, planeIntersectPoint)) return;

    const next = new THREE.Vector3(
      planeIntersectPoint.x - state.dragOffset.x,
      state.selectedFurniture.position.y,
      planeIntersectPoint.z - state.dragOffset.z
    );
    const snapped = applyWallMagnetAndBounds(state.selectedFurniture, next);
    const blocked = getBlockedPlacementAt(state.selectedFurniture, snapped.position);
    if (blocked) {
      const safe = state.selectedFurniture.userData.lastSafePosition;
      if (safe) state.selectedFurniture.position.copy(safe);
      state.blockedDragWarning = `${state.selectedFurniture.userData.label}은 벽 위에 배치할 수 없습니다.`;
      updateSafetyState(snapped.message);
      addCollisionFootprint(blocked.box);
    } else {
      state.selectedFurniture.position.copy(snapped.position);
      state.selectedFurniture.userData.lastSafePosition = snapped.position.clone();
      state.blockedDragWarning = "";
      updateSafetyState(snapped.message);
    }
    if (state.selectionHelper) state.selectionHelper.update();
    updateEstimate();
  }

  function onPointerUp() {
    if (!state.isDragging) return;
    state.isDragging = false;
    state.controls.enabled = true;
    updateSafetyState();
    updateEstimate();
  }

  function onCatalogDrop(e, container) {
    e.preventDefault();
    const skuId = e.dataTransfer.getData("text/plain");
    const item = state.catalogItems.find((entry) => entry.sku_id === skuId);
    if (!item) return;
    updatePointerNDC(e, container);
    raycaster.setFromCamera(pointerNDC, state.camera);
    if (!raycaster.ray.intersectPlane(groundPlane, planeIntersectPoint)) return;
    spawnFurniture(item, { x: planeIntersectPoint.x, z: planeIntersectPoint.z });
  }

  function findFurnitureRoot(object) {
    let current = object;
    while (current.parent && current.parent !== state.scene) current = current.parent;
    return current;
  }

  function selectFurniture(model, toolbar) {
    clearSelectionHighlight();
    state.selectedFurniture = model;
    const labelInput = document.getElementById("material-label-input");

    if (model) {
      state.selectionHelper = new THREE.BoxHelper(model, 0x004b87);
      state.scene.add(state.selectionHelper);
      if (toolbar) toolbar.style.display = "flex";
      if (labelInput) labelInput.value = model.userData.label || model.userData.productName || "자재";
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
    clearVisualization();
    state.selectedFurniture.rotation.y += Math.PI / 2;
    if (state.selectionHelper) state.selectionHelper.update();
    updateSafetyState();
    updateEstimate();
  }

  function deleteSelectedFurniture(toolbar) {
    const model = state.selectedFurniture;
    if (!model) return;
    state.scene.remove(model);
    disposeObject3D(model);
    state.furnitureMeshes = state.furnitureMeshes.filter((m) => m !== model);
    clearSelectionHighlight();
    clearVisualization();
    state.selectedFurniture = null;
    if (toolbar) toolbar.style.display = "none";
    updateSafetyState();
    updateEstimate();
  }

  function initFloorPlanLoader() {
    const input = document.getElementById("floorPlanInput");
    if (!input) return;
    input.addEventListener("change", handleFloorPlanFileSelected);
  }

  function handleFloorPlanFileSelected(e) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    e.target.value = "";
    if (!file.name.toLowerCase().endsWith(".json")) {
      alert("JSON 형식의 평면도 파일만 업로드할 수 있습니다.");
      return;
    }

    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        loadFloorPlan(JSON.parse(event.target.result));
      } catch (err) {
        console.error(err);
        alert("평면도 데이터를 불러오지 못했습니다: " + err.message);
      }
    };
    reader.onerror = () => alert("평면도 파일을 읽는 중 오류가 발생했습니다.");
    reader.readAsText(file);
  }

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
    throw new Error("지원하지 않는 평면도 형식입니다.");
  }

  function findImageDataUri(node, depth) {
    depth = depth || 0;
    if (depth > 20 || node == null) return null;
    if (typeof node === "string" && node.indexOf("data:image") === 0) return node;
    if (typeof node !== "object") return null;
    for (const key of Object.keys(node)) {
      const found = findImageDataUri(node[key], depth + 1);
      if (found) return found;
    }
    return null;
  }

  function loadImageFloorPlan(planData, imageDataUri) {
    const attrs = getFloorPlanPixelSize(planData);
    textureLoader.load(imageDataUri, (texture) => {
      clearFloorPlan();
      const scale = FLOOR_PLAN_TARGET_SIZE / Math.max(attrs.width, attrs.height);
      const planeW = attrs.width * scale;
      const planeH = attrs.height * scale;
      const mesh = new THREE.Mesh(
        new THREE.PlaneGeometry(planeW, planeH),
        new THREE.MeshBasicMaterial({ map: texture, side: THREE.DoubleSide, transparent: true })
      );
      mesh.rotation.x = -Math.PI / 2;
      mesh.position.set(0, 0.001, 0);

      const group = new THREE.Group();
      group.name = "floorPlan";
      group.add(mesh);
      state.scene.add(group);
      state.floorPlanGroup = group;
      setFloorBounds({ minX: -planeW / 2, maxX: planeW / 2, minZ: -planeH / 2, maxZ: planeH / 2 });
      buildImageWallMask(imageDataUri, attrs.width, attrs.height, planeW, planeH);
      focusCameraOnArea(planeW, planeH, new THREE.Vector3(0, 0, 0));
      updateSceneStatus("평면도 로드 완료", "검은 도면선을 벽으로 인식해 가구 배치를 제한합니다.");
      updateSafetyState();
    });
  }

  function buildImageWallMask(imageDataUri, width, height, planeW, planeH) {
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(img, 0, 0, width, height);
      const rgba = ctx.getImageData(0, 0, width, height).data;
      const mask = new Uint8Array(width * height);
      let wallPixels = 0;

      for (let i = 0, p = 0; i < rgba.length; i += 4, p += 1) {
        const r = rgba[i];
        const g = rgba[i + 1];
        const b = rgba[i + 2];
        const a = rgba[i + 3];
        const darkness = (r + g + b) / 3;
        if (a > IMAGE_WALL_ALPHA && darkness < IMAGE_WALL_DARKNESS) {
          mask[p] = 1;
          wallPixels += 1;
        }
      }

      state.imageWallMask = {
        width,
        height,
        planeW,
        planeH,
        mask,
      };
      updateSceneStatus("벽 마스크 분석 완료", `검은 벽 픽셀 ${wallPixels.toLocaleString("ko-KR")}개를 배치 금지 영역으로 설정했습니다.`);
      updateSafetyState();
    };
    img.onerror = () => {
      state.imageWallMask = null;
      updateSceneStatus("벽 마스크 분석 실패", "평면도 이미지는 표시되지만 검은 벽 충돌 분석은 적용되지 않았습니다.");
    };
    img.src = imageDataUri;
  }

  function getFloorPlanPixelSize(planData) {
    const rootAttrs = planData["@attributes"] || {};
    const imageAttrs = (planData.image && planData.image["@attributes"]) || {};
    return {
      width: parseFloat(rootAttrs.width || imageAttrs.width) || 1000,
      height: parseFloat(rootAttrs.height || imageAttrs.height) || 1000,
    };
  }

  function loadVectorFloorPlan(planData) {
    clearFloorPlan();
    const group = new THREE.Group();
    group.name = "floorPlan";
    state.wallObjects = [];
    planData.walls.forEach((wall) => addWallToGroup(group, wall));
    if (Array.isArray(planData.doors)) planData.doors.forEach((door) => addDoorMarkerToGroup(group, door));
    state.scene.add(group);
    state.floorPlanGroup = group;

    const width = (planData.width || 6000) * MM_TO_SCENE;
    const depth = (planData.depth || 4000) * MM_TO_SCENE;
    setFloorBounds({ minX: 0, maxX: width, minZ: 0, maxZ: depth });
    focusCameraOnArea(width, depth);
    updateSceneStatus("벡터 평면도 로드 완료", "벽체 충돌과 외곽 벽 자석을 적용합니다.");
    updateSafetyState();
  }

  function addWallToGroup(group, wall) {
    const { x1, y1, x2, y2 } = wall || {};
    if ([x1, y1, x2, y2].some((v) => typeof v !== "number")) return;
    const height = (wall.height || 2400) * MM_TO_SCENE;
    const thickness = (wall.thickness || 100) * MM_TO_SCENE;
    const dx = (x2 - x1) * MM_TO_SCENE;
    const dz = (y2 - y1) * MM_TO_SCENE;
    const length = Math.sqrt(dx * dx + dz * dz);
    if (length === 0) return;

    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(length, height, thickness),
      new THREE.MeshStandardMaterial({ color: 0xd1d5db })
    );
    mesh.position.set((x1 + x2) * 0.5 * MM_TO_SCENE, height / 2, (y1 + y2) * 0.5 * MM_TO_SCENE);
    mesh.rotation.y = -Math.atan2(dz, dx);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    group.add(mesh);
    state.wallObjects.push(mesh);
  }

  function addDoorMarkerToGroup(group, door) {
    if (typeof door.x !== "number" || typeof door.y !== "number") return;
    const radius = (door.radius || 900) * MM_TO_SCENE;
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(Math.max(radius - 0.02, 0.01), radius, 32),
      new THREE.MeshBasicMaterial({ color: 0x004b87, side: THREE.DoubleSide, transparent: true, opacity: 0.5 })
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(door.x * MM_TO_SCENE, 0.02, door.y * MM_TO_SCENE);
    group.add(ring);
  }

  function setFloorBounds(bounds) {
    state.floorBounds = {
      minX: bounds.minX,
      maxX: bounds.maxX,
      minZ: bounds.minZ,
      maxZ: bounds.maxZ,
      get width() { return this.maxX - this.minX; },
      get depth() { return this.maxZ - this.minZ; },
      get center() { return new THREE.Vector3((this.minX + this.maxX) / 2, 0, (this.minZ + this.maxZ) / 2); },
    };
  }

  function clearFloorPlan() {
    if (state.floorPlanGroup) {
      state.scene.remove(state.floorPlanGroup);
      disposeObject3D(state.floorPlanGroup);
    }
    state.floorPlanGroup = null;
    state.imageWallMask = null;
    state.wallObjects = [];
    clearVisualization();
  }

  async function loadCatalog() {
    const listEl = document.getElementById("furniture-list");
    if (!listEl) return;
    try {
      const res = await fetch("/api/furniture");
      if (!res.ok) throw new Error("API 요청 실패");
      state.catalogItems = await res.json();
      renderColorFilters();
      renderCatalog();
      updateEstimate();
    } catch (err) {
      console.error(err);
      listEl.innerHTML = "데이터를 불러올 수 없습니다.";
    }
  }

  function renderColorFilters() {
    const el = document.getElementById("color-filter");
    if (!el) return;
    el.innerHTML = "";
    COLOR_FILTERS.forEach((filter) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "color-filter-btn" + (state.activeColor === filter.value ? " active" : "");
      button.innerHTML = `<span class="swatch"></span><span>${filter.label}</span>`;
      button.querySelector(".swatch").style.background = filter.swatch;
      button.addEventListener("click", () => {
        state.activeColor = filter.value;
        renderColorFilters();
        renderCatalog();
      });
      el.appendChild(button);
    });
  }

  function renderTrendPatterns() {
    const el = document.getElementById("trend-patterns");
    if (!el) return;
    el.innerHTML = "";
    TREND_PATTERNS.forEach((pattern) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "pattern-btn" + (state.activePattern === pattern.code ? " active" : "");
      button.innerHTML = `<strong>${pattern.code}</strong><span>${pattern.name}</span>`;
      button.addEventListener("click", () => applyTrendPattern(pattern));
      el.appendChild(button);
    });
  }

  function renderCatalog() {
    const listEl = document.getElementById("furniture-list");
    const countEl = document.getElementById("catalog-count");
    if (!listEl) return;
    const items = getFilteredCatalogItems();
    if (countEl) countEl.textContent = `${items.length} items`;
    listEl.innerHTML = "";
    if (items.length === 0) {
      const empty = document.createElement("p");
      empty.textContent = "표시할 가구가 없습니다.";
      empty.style.cssText = "padding:10px; color:#888; font-size:13px;";
      listEl.appendChild(empty);
      return;
    }
    items.forEach((item) => listEl.appendChild(createFurnitureCard(item)));
  }

  function getFilteredCatalogItems() {
    if (state.activeColor === "all") return state.catalogItems;
    return state.catalogItems.filter((item) => normalizeColor(item.color) === state.activeColor);
  }

  function createFurnitureCard(item) {
    const card = document.createElement("div");
    card.className = "furniture-card";
    card.draggable = true;
    card.addEventListener("click", () => spawnFurniture(item));
    card.addEventListener("dragstart", (e) => e.dataTransfer.setData("text/plain", item.sku_id || ""));

    card.appendChild(createFurnitureThumbnail(item));
    card.appendChild(createFurnitureInfo(item));
    return card;
  }

  function createFurnitureThumbnail(item) {
    const thumb = document.createElement("img");
    thumb.src = item.image_url || "";
    thumb.alt = item.product_name || "furniture";
    thumb.className = "furniture-thumb";
    thumb.onerror = () => thumb.replaceWith(createThumbnailFallback());
    return thumb;
  }

  function createThumbnailFallback() {
    const fallback = document.createElement("div");
    fallback.textContent = "3D";
    fallback.className = "thumb-fallback";
    return fallback;
  }

  function createFurnitureInfo(item) {
    const info = document.createElement("div");
    info.className = "furniture-info";
    const row = document.createElement("div");
    row.className = "furniture-meta-row";
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = getColorSwatch(item.color);
    const categoryEl = document.createElement("span");
    categoryEl.textContent = item.category || "Furniture";
    categoryEl.className = "furniture-category";
    row.append(swatch, categoryEl);
    info.appendChild(row);

    const nameEl = document.createElement("div");
    nameEl.textContent = item.product_name || "이름 없음";
    nameEl.className = "furniture-name";
    info.appendChild(nameEl);

    const metaEl = document.createElement("div");
    metaEl.textContent = `${item.size ? item.size + " · " : ""}${formatDimensions(item)} · ${formatColorLabel(item.color)}`;
    metaEl.className = "furniture-meta";
    info.appendChild(metaEl);

    const priceEl = document.createElement("div");
    priceEl.textContent = formatPrice(item.price);
    priceEl.className = "furniture-price";
    info.appendChild(priceEl);
    return info;
  }

  function spawnFurniture(item, options) {
    options = options || {};
    clearVisualization();
    const path = item.model_path || resolveModelPath(item);
    loadFurnitureModel([path, "/static/models/sofa/gray_sofa.glb", "/static/models/sofa/grey_sofa.glb"], item, options);
  }

  function loadFurnitureModel(paths, item, options, index) {
    index = index || 0;
    const path = paths[index];
    if (!path) {
      console.error("가구 모델을 불러오지 못했습니다.", item);
      return;
    }
    gltfLoader.load(
      path,
      (gltf) => onFurnitureModelLoaded(gltf, item, options),
      undefined,
      () => loadFurnitureModel(paths, item, options, index + 1)
    );
  }

  function onFurnitureModelLoaded(gltf, item, options) {
    const model = gltf.scene;
    const box = new THREE.Box3().setFromObject(model);
    const size = box.getSize(new THREE.Vector3());
    const targetW = (Number(item.width) || 150) * 0.01;
    const targetH = (Number(item.height) || 80) * 0.01;
    const targetD = (Number(item.depth) || 80) * 0.01;
    model.scale.set(targetW / Math.max(size.x, 0.001), targetH / Math.max(size.y, 0.001), targetD / Math.max(size.z, 0.001));

    const pivot = createCenteredFurniturePivot(model, item);
    pivot.position.set(options.x || 0, pivot.userData.centerY || 0, options.z || 0);
    pivot.rotation.y = options.rot || 0;
    state.scene.add(pivot);
    state.furnitureMeshes.push(pivot);
    const constrained = applyWallMagnetAndBounds(pivot, pivot.position);
    const safePosition = findNearestSafePosition(pivot, constrained.position);
    if (!safePosition) {
      state.scene.remove(pivot);
      state.furnitureMeshes = state.furnitureMeshes.filter((model) => model !== pivot);
      disposeObject3D(pivot);
      updateSafetyState(`${pivot.userData.label}은 벽 위에 배치할 수 없습니다.`);
      updateEstimate();
      return;
    }
    pivot.position.copy(safePosition);
    pivot.userData.lastSafePosition = safePosition.clone();

    if (!state.suppressAutoSelect && options.select !== false) {
      selectFurniture(pivot, document.getElementById("furniture-toolbar"));
    }
    updateSafetyState();
    updateEstimate();
  }

  function createCenteredFurniturePivot(model, item) {
    const scaledBox = new THREE.Box3().setFromObject(model);
    const center = scaledBox.getCenter(new THREE.Vector3());
    const minY = scaledBox.min.y;
    const pivot = new THREE.Group();
    model.position.sub(center);
    pivot.add(model);
    pivot.name = item.product_name || "furniture";
    pivot.userData = {
      type: "furniture",
      skuId: item.sku_id,
      productName: item.product_name || "자재",
      label: item.label || item.product_name || "자재",
      category: item.category || "",
      color: normalizeColor(item.color),
      modelPath: item.model_path || resolveModelPath(item),
      imageUrl: item.image_url || "",
      productUrl: item.product_url || "",
      price: parsePrice(item.price),
      rawPrice: item.price,
      size: item.size || "",
      dimensions: {
        width: Number(item.width) || 0,
        depth: Number(item.depth) || 0,
        height: Number(item.height) || 0,
      },
      centerY: center.y - minY,
    };
    pivot.traverse((obj) => {
      obj.castShadow = true;
      obj.receiveShadow = true;
    });
    return pivot;
  }

  function applyWallMagnetAndBounds(model, desiredPosition) {
    const bounds = state.floorBounds;
    if (!bounds) return { position: desiredPosition.clone(), message: "" };
    const original = model.position.clone();
    model.position.copy(desiredPosition);
    const box = getPlanBox(model);
    const position = desiredPosition.clone();
    const messages = [];

    const leftGap = box.minX - bounds.minX;
    const rightGap = bounds.maxX - box.maxX;
    const topGap = box.minZ - bounds.minZ;
    const bottomGap = bounds.maxZ - box.maxZ;

    if (leftGap < SNAP_DISTANCE) {
      const delta = bounds.minX + WALL_BUFFER - box.minX;
      position.x += delta;
      messages.push("왼쪽 벽에 자석 스냅");
    }
    if (rightGap < SNAP_DISTANCE) {
      const delta = bounds.maxX - WALL_BUFFER - box.maxX;
      position.x += delta;
      messages.push("오른쪽 벽에 자석 스냅");
    }
    if (topGap < SNAP_DISTANCE) {
      const delta = bounds.minZ + WALL_BUFFER - box.minZ;
      position.z += delta;
      messages.push("상단 벽에 자석 스냅");
    }
    if (bottomGap < SNAP_DISTANCE) {
      const delta = bounds.maxZ - WALL_BUFFER - box.maxZ;
      position.z += delta;
      messages.push("하단 벽에 자석 스냅");
    }

    model.position.copy(original);
    return { position, message: messages.join(", ") };
  }

  function findNearestSafePosition(model, preferredPosition) {
    const offsets = [
      [0, 0],
      [0.6, 0],
      [-0.6, 0],
      [0, 0.6],
      [0, -0.6],
      [1.2, 0],
      [-1.2, 0],
      [0, 1.2],
      [0, -1.2],
      [1.2, 1.2],
      [-1.2, 1.2],
      [1.2, -1.2],
      [-1.2, -1.2],
    ];

    for (const [dx, dz] of offsets) {
      const position = preferredPosition.clone();
      position.x += dx;
      position.z += dz;
      const constrained = applyWallMagnetAndBounds(model, position).position;
      if (!getBlockedPlacementAt(model, constrained)) return constrained;
    }
    return null;
  }

  function getBlockedPlacementAt(model, position) {
    const original = model.position.clone();
    model.position.copy(position);
    const box = getPlanBox(model);
    const reason = getBlockedPlacementReason(model, box);
    model.position.copy(original);
    return reason ? { reason, box } : null;
  }

  function getBlockedPlacementReason(model, box) {
    if (isOutsideBounds(box)) return "평면도 경계 밖";
    if (boxIntersectsImageWall(box)) return "이미지 평면도 벽";
    for (const wall of state.wallObjects) {
      if (boxesIntersect(getPlanBox(wall), box)) return "벡터 벽체";
    }
    return "";
  }

  function boxIntersectsImageWall(box) {
    if (!state.imageWallMask || !state.floorBounds) return false;
    const mask = state.imageWallMask;
    const bounds = state.floorBounds;
    const minPx = clamp(Math.floor(((box.minX - bounds.minX) / bounds.width) * mask.width), 0, mask.width - 1);
    const maxPx = clamp(Math.ceil(((box.maxX - bounds.minX) / bounds.width) * mask.width), 0, mask.width - 1);
    const minPy = clamp(Math.floor(((bounds.maxZ - box.maxZ) / bounds.depth) * mask.height), 0, mask.height - 1);
    const maxPy = clamp(Math.ceil(((bounds.maxZ - box.minZ) / bounds.depth) * mask.height), 0, mask.height - 1);

    const stepX = Math.max(1, Math.floor((maxPx - minPx + 1) / 32));
    const stepY = Math.max(1, Math.floor((maxPy - minPy + 1) / 32));
    let hits = 0;
    let samples = 0;

    for (let y = minPy; y <= maxPy; y += stepY) {
      for (let x = minPx; x <= maxPx; x += stepX) {
        samples += 1;
        if (mask.mask[y * mask.width + x]) hits += 1;
        if (hits >= 2 && hits / samples > 0.002) return true;
      }
    }
    return hits >= 3;
  }

  function updateSafetyState(extraMessage) {
    clearCollisionHelpers();
    const warnings = [];
    const colliding = new Set();
    if (extraMessage) warnings.push(extraMessage);
    if (state.blockedDragWarning) warnings.push(state.blockedDragWarning);

    state.furnitureMeshes.forEach((model) => {
      const box = getPlanBox(model);
      const blockedReason = getBlockedPlacementReason(model, box);
      if (blockedReason) {
        warnings.push(`${model.userData.label}이 ${blockedReason}과 간섭됩니다.`);
        colliding.add(model);
      }
    });

    for (let i = 0; i < state.furnitureMeshes.length; i += 1) {
      for (let j = i + 1; j < state.furnitureMeshes.length; j += 1) {
        const a = state.furnitureMeshes[i];
        const b = state.furnitureMeshes[j];
        if (boxesIntersect(getPlanBox(a), getPlanBox(b))) {
          warnings.push(`${a.userData.label} / ${b.userData.label} 간 충돌`);
          colliding.add(a);
          colliding.add(b);
        }
      }
    }

    colliding.forEach((model) => addCollisionHelper(model));
    state.lastWarnings = unique(warnings).slice(0, 6);
    renderWarnings();
  }

  function getPlanBox(object) {
    const box = new THREE.Box3().setFromObject(object);
    return { minX: box.min.x, maxX: box.max.x, minZ: box.min.z, maxZ: box.max.z };
  }

  function boxesIntersect(a, b) {
    return a.minX <= b.maxX && a.maxX >= b.minX && a.minZ <= b.maxZ && a.maxZ >= b.minZ;
  }

  function isOutsideBounds(box) {
    const bounds = state.floorBounds;
    if (!bounds) return false;
    return box.minX < bounds.minX || box.maxX > bounds.maxX || box.minZ < bounds.minZ || box.maxZ > bounds.maxZ;
  }

  function addCollisionHelper(model) {
    const helper = new THREE.BoxHelper(model, 0xff2d2d);
    state.scene.add(helper);
    state.collisionHelpers.push(helper);
  }

  function addCollisionFootprint(box) {
    const width = Math.max(box.maxX - box.minX, 0.08);
    const depth = Math.max(box.maxZ - box.minZ, 0.08);
    const geometry = new THREE.PlaneGeometry(width, depth);
    const material = new THREE.MeshBasicMaterial({
      color: 0xff2d2d,
      transparent: true,
      opacity: 0.32,
      side: THREE.DoubleSide,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.set((box.minX + box.maxX) / 2, 0.045, (box.minZ + box.maxZ) / 2);
    state.scene.add(mesh);
    state.collisionHelpers.push(mesh);
  }

  function clearCollisionHelpers() {
    state.collisionHelpers.forEach((helper) => {
      state.scene.remove(helper);
      helper.geometry.dispose();
      helper.material.dispose();
    });
    state.collisionHelpers = [];
  }

  function renderWarnings() {
    const panel = document.getElementById("warning-panel");
    if (!panel) return;
    panel.classList.toggle("ok", state.lastWarnings.length === 0);
    panel.style.display = "grid";
    if (state.lastWarnings.length === 0) {
      panel.innerHTML = "<strong>배치 상태 양호</strong><span>충돌이나 벽 간섭이 없습니다.</span>";
      return;
    }
    panel.innerHTML = `<strong>배치 경고</strong><span>${state.lastWarnings.join("<br>")}</span>`;
  }

  function updateEstimate() {
    const placedCount = document.getElementById("placed-count");
    const totalEl = document.getElementById("estimate-total");
    const listEl = document.getElementById("estimate-list");
    const activeTheme = document.getElementById("active-theme");
    const total = state.furnitureMeshes.reduce((sum, model) => sum + (model.userData.price || 0), 0);

    if (placedCount) placedCount.textContent = `${state.furnitureMeshes.length}개`;
    if (totalEl) totalEl.textContent = formatPrice(total);
    if (activeTheme) activeTheme.textContent = state.activePattern;
    if (!listEl) return;
    listEl.innerHTML = "";
    if (state.furnitureMeshes.length === 0) {
      listEl.innerHTML = '<div class="estimate-row"><strong>배치된 자재 없음</strong><span>카탈로그에서 선택하세요</span></div>';
      return;
    }
    state.furnitureMeshes.forEach((model) => {
      const row = document.createElement("div");
      row.className = "estimate-row";
      row.innerHTML = `<strong>${escapeHtml(model.userData.label)}</strong><b>${formatPrice(model.userData.price)}</b><span>${formatDimensions(model.userData.dimensions)}</span><span>${formatColorLabel(model.userData.color)}</span>`;
      listEl.appendChild(row);
    });
  }

  function applyTrendPattern(pattern) {
    state.activePattern = pattern.code;
    renderTrendPatterns();
    clearFurniture();
    state.suppressAutoSelect = true;
    const picks = pattern.placements.map((placement) => {
      return findCatalogItem(placement.category, pattern.color) || findCatalogItem(placement.category) || state.catalogItems[0];
    }).filter(Boolean);
    picks.forEach((item, index) => spawnFurniture(item, { ...pattern.placements[index], select: false }));
    state.suppressAutoSelect = false;
    updateSceneStatus("추천 패턴 적용", `${pattern.code} ${pattern.name} 기본 배치를 불러왔습니다.`);
  }

  function findCatalogItem(category, color) {
    return state.catalogItems.find((item) => {
      const categoryOk = !category || String(item.category || "").includes(category) || String(item.product_name || "").includes(category);
      const colorOk = !color || normalizeColor(item.color) === color;
      return categoryOk && colorOk;
    });
  }

  function clearFurniture() {
    clearSelectionHighlight();
    clearCollisionHelpers();
    state.furnitureMeshes.forEach((model) => {
      state.scene.remove(model);
      disposeObject3D(model);
    });
    state.furnitureMeshes = [];
    state.selectedFurniture = null;
    clearVisualization();
    updateEstimate();
  }

  function acceptLayout() {
    clearSelectionHighlight();
    state.selectedFurniture = null;
    const toolbar = document.getElementById("furniture-toolbar");
    if (toolbar) toolbar.style.display = "none";
    clearVisualization();
    const bounds = calculateLayoutBounds();
    const visualization = new THREE.Group();
    visualization.name = "acceptedLayoutVisualization";
    addPerimeterWalls(visualization, bounds);
    addFloorFinish(visualization, bounds);
    state.scene.add(visualization);
    state.visualizationGroup = visualization;
    focusCameraOnArea(bounds.width, bounds.depth, bounds.center);
    updateSafetyState();
    updateSceneStatus("3D 렌더링 완료", "벽체, 바닥, 배치 자재, 견적 상태가 갱신되었습니다.");
  }

  function calculateLayoutBounds() {
    const bounds = state.floorBounds || { minX: -4, maxX: 4, minZ: -3, maxZ: 3 };
    return {
      minX: bounds.minX,
      maxX: bounds.maxX,
      minZ: bounds.minZ,
      maxZ: bounds.maxZ,
      width: bounds.maxX - bounds.minX,
      depth: bounds.maxZ - bounds.minZ,
      center: new THREE.Vector3((bounds.minX + bounds.maxX) / 2, 0, (bounds.minZ + bounds.maxZ) / 2),
    };
  }

  function addPerimeterWalls(group, bounds) {
    const wallHeight = 2.7;
    const wallThickness = 0.12;
    const material = new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.72, transparent: true, opacity: 0.9 });
    const north = createWall(bounds.width, wallHeight, wallThickness, material);
    north.position.set(bounds.center.x, wallHeight / 2, bounds.minZ);
    const south = createWall(bounds.width, wallHeight, wallThickness, material);
    south.position.set(bounds.center.x, wallHeight / 2, bounds.maxZ);
    const west = createWall(bounds.depth, wallHeight, wallThickness, material);
    west.rotation.y = Math.PI / 2;
    west.position.set(bounds.minX, wallHeight / 2, bounds.center.z);
    const east = createWall(bounds.depth, wallHeight, wallThickness, material);
    east.rotation.y = Math.PI / 2;
    east.position.set(bounds.maxX, wallHeight / 2, bounds.center.z);
    group.add(north, south, west, east);
  }

  function createWall(length, height, thickness, material) {
    const wall = new THREE.Mesh(new THREE.BoxGeometry(length, height, thickness), material.clone());
    wall.receiveShadow = true;
    wall.castShadow = true;
    return wall;
  }

  function addFloorFinish(group, bounds) {
    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(bounds.width, bounds.depth),
      new THREE.MeshStandardMaterial({ color: 0xe5e7eb, roughness: 0.86, transparent: true, opacity: state.floorPlanGroup ? 0.22 : 1 })
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(bounds.center.x, -0.004, bounds.center.z);
    floor.receiveShadow = true;
    group.add(floor);
  }

  function clearVisualization() {
    if (!state.visualizationGroup) return;
    state.scene.remove(state.visualizationGroup);
    disposeObject3D(state.visualizationGroup);
    state.visualizationGroup = null;
  }

  function saveLayout() {
    const payload = {
      savedAt: new Date().toISOString(),
      activePattern: state.activePattern,
      floorBounds: state.floorBounds,
      items: state.furnitureMeshes.map((model) => ({
        skuId: model.userData.skuId,
        label: model.userData.label,
        position: { x: model.position.x, y: model.position.y, z: model.position.z },
        rotationY: model.rotation.y,
        item: exportCatalogLikeItem(model),
      })),
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    downloadBlob(JSON.stringify(payload, null, 2), "duo-layout.json", "application/json");
    updateSceneStatus("저장 완료", "브라우저 저장소와 duo-layout.json 파일로 현재 배치를 저장했습니다.");
  }

  function loadSavedLayout() {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      alert("저장된 배치가 없습니다.");
      return;
    }
    try {
      const payload = JSON.parse(raw);
      clearFurniture();
      if (payload.floorBounds) setFloorBounds(payload.floorBounds);
      state.activePattern = payload.activePattern || "A";
      renderTrendPatterns();
      state.suppressAutoSelect = true;
      payload.items.forEach((entry) => {
        const item = state.catalogItems.find((catalogItem) => catalogItem.sku_id === entry.skuId) || entry.item;
        spawnFurniture({ ...item, label: entry.label }, { x: entry.position.x, z: entry.position.z, rot: entry.rotationY, select: false });
      });
      state.suppressAutoSelect = false;
      updateSceneStatus("불러오기 완료", "저장된 배치를 복원했습니다.");
    } catch (err) {
      console.error(err);
      alert("저장 데이터를 불러오지 못했습니다.");
    }
  }

  function exportCatalogLikeItem(model) {
    return {
      sku_id: model.userData.skuId,
      product_name: model.userData.productName,
      label: model.userData.label,
      category: model.userData.category,
      color: model.userData.color,
      price: model.userData.price,
      size: model.userData.size,
      model_path: model.userData.modelPath,
      image_url: model.userData.imageUrl,
      product_url: model.userData.productUrl,
      width: model.userData.dimensions.width,
      depth: model.userData.dimensions.depth,
      height: model.userData.dimensions.height,
    };
  }

  function downloadEstimatePdf() {
    const rows = state.furnitureMeshes.map((model, index) => ({
      index: String(index + 1),
      label: model.userData.label,
      category: model.userData.category || "-",
      dimensions: formatDimensions(model.userData.dimensions),
      color: formatColorLabel(model.userData.color),
      price: formatPrice(model.userData.price),
    }));
    const total = state.furnitureMeshes.reduce((sum, model) => sum + (model.userData.price || 0), 0);
    const html = createEstimatePrintHtml(rows, total);
    const printWindow = window.open("", "_blank", "width=900,height=700");

    if (!printWindow) {
      downloadBlob(html, "duo-estimate.html", "text/html;charset=utf-8");
      alert("팝업이 차단되어 HTML 견적서를 저장했습니다. 브라우저에서 열어 PDF로 저장해주세요.");
      return;
    }

    printWindow.document.open();
    printWindow.document.write(html);
    printWindow.document.close();
    printWindow.focus();
    printWindow.setTimeout(() => {
      printWindow.print();
    }, 250);
  }

  function createEstimatePrintHtml(rows, total) {
    const createdAt = new Date().toLocaleString("ko-KR");
    const rowHtml = rows.length
      ? rows.map((row) => `
          <tr>
            <td>${escapeHtml(row.index)}</td>
            <td>${escapeHtml(row.label)}</td>
            <td>${escapeHtml(row.category)}</td>
            <td>${escapeHtml(row.dimensions)}</td>
            <td>${escapeHtml(row.color)}</td>
            <td class="price">${escapeHtml(row.price)}</td>
          </tr>
        `).join("")
      : `<tr><td colspan="6" class="empty">배치된 자재가 없습니다.</td></tr>`;

    return `<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <title>DuO 견적서</title>
  <style>
    * { box-sizing: border-box; }
    body {
      color: #111827;
      font-family: "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans KR", Arial, sans-serif;
      margin: 0;
      padding: 32px;
    }
    h1 { color: #002f5f; font-size: 24px; margin: 0 0 8px; }
    .meta { color: #6b7280; display: flex; gap: 18px; font-size: 12px; margin-bottom: 24px; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border-bottom: 1px solid #e5e7eb; font-size: 12px; padding: 10px 8px; text-align: left; }
    th { background: #f8fafc; color: #374151; font-weight: 700; }
    .price { text-align: right; white-space: nowrap; }
    .empty { color: #6b7280; padding: 24px; text-align: center; }
    .total { align-items: center; display: flex; justify-content: flex-end; gap: 18px; margin-top: 20px; }
    .total span { color: #6b7280; font-size: 13px; }
    .total strong { color: #002f5f; font-size: 22px; }
    @page { margin: 16mm; }
  </style>
</head>
<body>
  <h1>DuO 인테리어 기본 견적서</h1>
  <div class="meta">
    <span>생성일: ${escapeHtml(createdAt)}</span>
    <span>추천 패턴: ${escapeHtml(state.activePattern)}</span>
    <span>자재 수: ${rows.length}개</span>
  </div>
  <table>
    <thead>
      <tr>
        <th>No.</th>
        <th>자재명</th>
        <th>분류</th>
        <th>크기</th>
        <th>색상</th>
        <th class="price">금액</th>
      </tr>
    </thead>
    <tbody>${rowHtml}</tbody>
  </table>
  <div class="total"><span>합계</span><strong>${escapeHtml(formatPrice(total))}</strong></div>
</body>
</html>`;
  }

  function downloadBlob(content, filename, type) {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function disposeObject3D(object) {
    object.traverse((obj) => {
      if (obj.geometry) obj.geometry.dispose();
      if (obj.material) {
        const materials = Array.isArray(obj.material) ? obj.material : [obj.material];
        materials.forEach((material) => {
          if (material.map) material.map.dispose();
          material.dispose();
        });
      }
    });
  }

  function focusCameraOnArea(width, depth, centerOverride) {
    const center = centerOverride || new THREE.Vector3(width / 2, 0, depth / 2);
    const distance = Math.max(width, depth) * 1.15 || 5;
    state.camera.position.set(center.x + distance, distance, center.z + distance);
    state.controls.target.copy(center);
    state.controls.update();
  }

  function updateSceneStatus(title, detail) {
    const status = document.getElementById("scene-status");
    if (!status) return;
    const titleEl = status.querySelector("strong");
    const detailEl = status.querySelector("span");
    if (titleEl) titleEl.textContent = title;
    if (detailEl) detailEl.textContent = detail;
  }

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

  function resolveModelPath(item) {
    const color = normalizeColor(item.color);
    const category = String(item.category || "").toLowerCase();
    if (category.includes("bed") || category.includes("침대")) {
      const size = color === "black" || color === "white" ? "single" : "queen";
      return `/static/models/bed/${size}_${color}_bed.glb`;
    }
    if (color === "blue") return "/static/models/curve_sofa/blue_curve_sofa.glb";
    return `/static/models/sofa/${color}_sofa.glb`;
  }

  function normalizeColor(color) {
    return String(color || "gray").toLowerCase().replace("grey", "gray").trim();
  }

  function formatColorLabel(color) {
    const normalized = normalizeColor(color);
    if (normalized === "all") return "All";
    return normalized.charAt(0).toUpperCase() + normalized.slice(1);
  }

  function getColorSwatch(color) {
    const filter = COLOR_FILTERS.find((entry) => entry.value === normalizeColor(color));
    return filter ? filter.swatch : "#9ca3af";
  }

  function formatDimensions(item) {
    const w = formatNumber(item.width);
    const d = formatNumber(item.depth);
    const h = formatNumber(item.height);
    return `${w}x${d}x${h}cm`;
  }

  function formatNumber(value) {
    const num = Number(value) || 0;
    return Number.isInteger(num) ? String(num) : num.toFixed(1);
  }

  function parsePrice(value) {
    if (typeof value === "number") return value;
    const digits = String(value || "0").replace(/[^\d.-]/g, "");
    return Number(digits) || 0;
  }

  function formatPrice(value) {
    return parsePrice(value).toLocaleString("ko-KR") + "원";
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function unique(values) {
    return Array.from(new Set(values.filter(Boolean)));
  }

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    }[char]));
  }
})();
