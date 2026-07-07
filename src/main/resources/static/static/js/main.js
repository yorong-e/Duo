(function () {
  "use strict";

  const STORAGE_KEY = "duo-layout-v2";
  const MM_TO_SCENE = 0.001;
  const GRID_CELL_MM = 500;
  const GRID_MIN_EXTENT_M = 80;
  const GRID_PADDING_M = 12;
  const FLOOR_PLAN_PIXELS_PER_GRID_CELL = 50;
  const FLOOR_PLAN_PIXEL_MM = GRID_CELL_MM / FLOOR_PLAN_PIXELS_PER_GRID_CELL;
  const FLOOR_PLAN_PIXEL_TO_SCENE = FLOOR_PLAN_PIXEL_MM * MM_TO_SCENE;
  const FALLBACK_FLOOR_PLAN_SIZE_M = 12;
  const SNAP_DISTANCE = 0.35;
  const WALL_MAGNET_DISTANCE = 1.2;
  const WALL_MAGNET_OVERLAP_MARGIN = 0.35;
  const WALL_BUFFER = 0.04;
  const DEFAULT_WALL_COLOR = 0x111827;
  const PARTITION_WALL_MAX_THICKNESS_M = 0.2;
  const IMAGE_WALL_DARKNESS = 92;
  const IMAGE_WALL_ALPHA = 24;
  const FLOOR_COLOR_TOLERANCE = 64;
  const MIN_FLOOR_COMPONENT_PIXELS = 180;
  const IMAGE_FLOOR_SAMPLE_GRID = 5;
  const IMAGE_FLOOR_REQUIRED_RATIO = 0.48;
  const MIN_WALL_COMPONENT_PIXELS = 80;
  const MIN_WALL_COMPONENT_LONG_SIDE = 32;
  const IMAGE_WALL_HIT_RATIO = 0.0015;
  const COLLISION_EPSILON = 0.012;
  const ROOM_GAP_TOLERANCE_STEPS = [0.5, 1.0, 1.6, 2.4];
  const FLOOR_SEAM_MARGIN = 0;
  const FLOOR_SIMPLIFY_TOLERANCE = 0.025;
  const FLOOR_MASK_TARGET_WIDTH = 1024;
  const RENDERED_WALL_HEIGHT_RATIO = 0.6;

  const COLOR_FILTERS = [
    { value: "all", label: "All", swatch: "linear-gradient(135deg, #f8fafc, #004b87)" },
    { value: "white", label: "White", swatch: "#ffffff" },
    { value: "gray", label: "Gray", swatch: "#9ca3af" },
    { value: "black", label: "Black", swatch: "#111827" },
    { value: "brown", label: "Brown", swatch: "#8b5e3c" },
    { value: "blue", label: "Blue", swatch: "#004b87" },
  ];

  const CATALOG_SECTIONS = [
    { value: "furniture", label: "가구" },
    { value: "floor", label: "바닥" },
    { value: "wallpaper", label: "벽지" },
  ];

  const FURNITURE_CATEGORY_FILTERS = [
    { value: "all", label: "전체", keywords: [] },
    { value: "sofa", label: "소파", keywords: ["소파", "sofa", "seat"] },
    { value: "desk", label: "책상", keywords: ["책상", "desk", "table", "테이블"] },
    { value: "chair", label: "의자", keywords: ["의자", "chair"] },
    { value: "bed", label: "침대", keywords: ["침대", "bed"] },
  ];

  const FLOOR_MATERIALS = [
    { value: "oak", label: "세로형 마루 07", color: 0x8a5a3f, swatch: "linear-gradient(90deg, #6f432f 0 20%, #9c6b4d 20% 40%, #5f3828 40% 60%, #b6815c 60% 80%, #754934 80%)" },
    { value: "herringbone", label: "헤링본 마루 01", color: 0xb98f66, swatch: "repeating-linear-gradient(45deg, #caa074 0 8px, #a77b55 8px 16px)" },
    { value: "lightwood", label: "세로형 마루 16", color: 0xd8c7aa, swatch: "linear-gradient(90deg, #eadcc4 0 25%, #cdb895 25% 50%, #f1e4cc 50% 75%, #c7b08d 75%)" },
    { value: "graytile", label: "세로형 마루 08", color: 0xb9bbb8, swatch: "linear-gradient(90deg, #d4d6d2 0 25%, #aeb1ae 25% 50%, #c5c7c3 50% 75%, #969a98 75%)" },
    { value: "grass", label: "잔디", color: 0x7f986a, swatch: "radial-gradient(circle, #9db482 0 18%, #718c5d 20% 45%, #8fa873 48%)" },
    { value: "cream", label: "가로형 마루 33", color: 0xd6c09a, swatch: "linear-gradient(0deg, #e4d2ae 0 25%, #c8ac7c 25% 50%, #eadbbd 50% 75%, #baa071 75%)" },
  ];

  const WALL_MATERIALS = [
    { value: "white", label: "화이트 실크", color: 0xf8fafc, swatch: "linear-gradient(135deg, #ffffff, #e5e7eb)" },
    { value: "warm", label: "웜 그레이지", color: 0xd6cbbd, swatch: "linear-gradient(135deg, #e7dccf, #bfae9d)" },
    { value: "gray", label: "라이트 그레이", color: 0xc7ccd1, swatch: "linear-gradient(135deg, #e5e7eb, #9ca3af)" },
    { value: "green", label: "세이지", color: 0xa9b7a2, swatch: "linear-gradient(135deg, #c2d0bb, #7e9277)" },
    { value: "blue", label: "포그 블루", color: 0xa9bfd0, swatch: "linear-gradient(135deg, #caddea, #7f9bb2)" },
    { value: "charcoal", label: "차콜 포인트", color: 0x4b5563, swatch: "linear-gradient(135deg, #6b7280, #1f2937)" },
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
    gridHelper: null,
    renderMode: "2d",
    floorBounds: null,
    floorObjects: [],
    baseFloorObjects: [],
    roomObjects: [],
    wallOverlay: null,
    selectedRoomId: null,
    imageFloorMask: null,
    imageWallMask: null,
    wallRenderRects: null,
    floorLockedToPlan: false,
    wallObjects: [],
    furnitureMeshes: [],
    selectedFurniture: null,
    selectedWall: null,
    selectionHelper: null,
    collisionHelpers: [],
    isDragging: false,
    isWallDragging: false,
    isWallDrawing: false,
    dragOffset: null,
    wallDragOffset: null,
    pendingWallStart: null,
    wallPreview: null,
    catalogItems: [],
    activeColor: "all",
    activeCatalogSection: "furniture",
    activeFurnitureCategory: "all",
    activeFloorMaterial: "oak",
    activeWallMaterial: "white",
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
    renderCatalogTabs();
    renderFurnitureCategoryFilters();
    renderFloorMaterials();
    renderWallMaterials();
    loadCatalog();
    window.addEventListener("resize", onWindowResize);
    window.addEventListener("keydown", onKeyDown);
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

    state.floorPlanGroup = new THREE.Group();
    state.floorPlanGroup.name = "floorPlan";
    state.scene.add(state.floorPlanGroup);

    setFloorBounds({ minX: -GRID_MIN_EXTENT_M / 2, maxX: GRID_MIN_EXTENT_M / 2, minZ: -GRID_MIN_EXTENT_M / 2, maxZ: GRID_MIN_EXTENT_M / 2 });
  }

  function getCanvasContainer() {
    return document.getElementById("canvas-container");
  }

  function initInteraction() {
    const container = getCanvasContainer();
    const toolbar = document.getElementById("furniture-toolbar");
    const labelInput = document.getElementById("material-label-input");

    state.dragOffset = new THREE.Vector3();
    state.wallDragOffset = new THREE.Vector3();
    container.addEventListener("pointerdown", (e) => onPointerDown(e, container, toolbar));
    container.addEventListener("pointermove", (e) => onPointerMove(e, container));
    container.addEventListener("dragover", (e) => e.preventDefault());
    container.addEventListener("drop", (e) => onCatalogDrop(e, container));
    window.addEventListener("pointerup", onPointerUp);

    if (toolbar) toolbar.addEventListener("pointerdown", (e) => e.stopPropagation());
    bindClick("btn-rotate", rotateSelectedFurniture);
    bindClick("btn-delete", () => deleteSelectedFurniture(toolbar));
    bindClick("btn-wall-add", toggleWallDrawingMode);
    bindClick("btn-accept", acceptLayout);
    bindClick("btn-render-2d", show2DLayout);
    bindClick("btn-save", saveLayout);
    bindClick("btn-load", loadSavedLayout);
    bindClick("btn-pdf", downloadEstimatePdf);
    updateRenderModeButtons();

    if (labelInput) {
      labelInput.addEventListener("input", () => {
        if (!state.selectedFurniture) return;
        state.selectedFurniture.userData.label = labelInput.value.trim() || state.selectedFurniture.userData.productName;
        updateEstimate();
      });
    }
  }

  function onKeyDown(e) {
    if (e.key === "Escape" && state.isWallDrawing) {
      cancelWallDrawing();
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
    if (state.isWallDrawing) {
      handleWallDrawingClick();
      return;
    }
    const intersects = raycaster.intersectObjects(state.furnitureMeshes, true);

    if (intersects.length > 0) {
      const root = findFurnitureRoot(intersects[0].object);
      selectFurniture(root, toolbar);
      if (raycaster.ray.intersectPlane(groundPlane, planeIntersectPoint)) {
        state.dragOffset.copy(planeIntersectPoint).sub(root.position);
        state.isDragging = true;
        state.controls.enabled = false;
      }
      return;
    }

    const wallHits = raycaster.intersectObjects(state.wallObjects, false);
    if (wallHits.length > 0) {
      const wall = wallHits[0].object;
      selectWall(wall, toolbar);
      if (isMovableWall(wall) && raycaster.ray.intersectPlane(groundPlane, planeIntersectPoint)) {
        state.wallDragOffset.copy(planeIntersectPoint).sub(wall.position);
        state.isWallDragging = true;
        state.controls.enabled = false;
      }
      return;
    }

    if (raycaster.ray.intersectPlane(groundPlane, planeIntersectPoint)) {
      const room = getRoomAtScenePoint(planeIntersectPoint.x, planeIntersectPoint.z);
      if (room) {
        selectRoom(room);
        selectFurniture(null, toolbar);
        selectWall(null, toolbar);
        return;
      }
    }

    selectFurniture(null, toolbar);
    selectWall(null, toolbar);
    selectRoom(null);
  }

  function onPointerMove(e, container) {
    if (state.isWallDrawing && state.pendingWallStart) {
      updatePointerNDC(e, container);
      raycaster.setFromCamera(pointerNDC, state.camera);
      if (raycaster.ray.intersectPlane(groundPlane, planeIntersectPoint)) {
        updateWallPreview(state.pendingWallStart, planeIntersectPoint);
      }
      return;
    }

    if (state.isWallDragging && state.selectedWall) {
      updatePointerNDC(e, container);
      raycaster.setFromCamera(pointerNDC, state.camera);
      if (!raycaster.ray.intersectPlane(groundPlane, planeIntersectPoint)) return;

      state.selectedWall.position.set(
        planeIntersectPoint.x - state.wallDragOffset.x,
        state.selectedWall.position.y,
        planeIntersectPoint.z - state.wallDragOffset.z
      );
      clearVisualization();
      if (state.selectionHelper) state.selectionHelper.update();
      refreshRoomsAfterWallEdit();
      updateSafetyState("벽 위치를 조정했습니다.");
      return;
    }

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
    state.selectedFurniture.position.copy(snapped.position);
    if (blocked) {
      state.blockedDragWarning = `${state.selectedFurniture.userData.label}은 ${blocked.reason}에 배치할 수 없습니다.`;
      updateSafetyState(snapped.message);
      addCollisionFootprint(blocked.box);
    } else {
      state.selectedFurniture.userData.lastSafePosition = snapped.position.clone();
      state.blockedDragWarning = "";
      updateSafetyState(snapped.message);
    }
    if (state.selectionHelper) state.selectionHelper.update();
    updateEstimate();
  }

  function onPointerUp() {
    if (!state.isDragging && !state.isWallDragging) return;
    state.isDragging = false;
    state.isWallDragging = false;
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
    state.selectedWall = null;
    if (model) selectRoom(null);
    const labelInput = document.getElementById("material-label-input");

    if (model) {
      state.selectionHelper = new THREE.BoxHelper(model, 0x004b87);
      state.scene.add(state.selectionHelper);
      if (toolbar) toolbar.style.display = "flex";
      setWallToolbarLocked(toolbar, null);
      if (labelInput) labelInput.value = model.userData.label || model.userData.productName || "자재";
    } else if (toolbar) {
      toolbar.style.display = "none";
    }
  }

  function selectWall(wall, toolbar) {
    clearSelectionHighlight();
    state.selectedFurniture = null;
    state.selectedWall = wall;
    if (wall) selectRoom(null);
    const labelInput = document.getElementById("material-label-input");

    if (wall) {
      state.selectionHelper = new THREE.BoxHelper(wall, 0xf59e0b);
      state.scene.add(state.selectionHelper);
      if (toolbar) toolbar.style.display = "flex";
      setWallToolbarLocked(toolbar, wall);
      if (labelInput) labelInput.value = wall.userData.label || wall.userData.id || "벽";
      updateSceneStatus(
        isDeletableWall(wall) ? "가벽 삭제 가능" : "구조벽 잠금",
        isDeletableWall(wall) ? "200mm 이하 가벽만 삭제할 수 있습니다." : "200mm를 초과하는 구조벽은 삭제할 수 없습니다."
      );
    } else if (toolbar && !state.selectedFurniture) {
      toolbar.style.display = "none";
      setWallToolbarLocked(toolbar, null);
    }
  }

  function setWallToolbarLocked(toolbar, wall) {
    if (!toolbar) return;
    const rotate = document.getElementById("btn-rotate");
    const del = document.getElementById("btn-delete");
    if (rotate) rotate.disabled = wall ? !isMovableWall(wall) : false;
    if (del) del.disabled = wall ? !isDeletableWall(wall) : false;
  }

  function selectRoom(room) {
    state.selectedRoomId = room ? room.userData.id : null;
    state.roomObjects.forEach((entry) => {
      entry.position.y = entry.userData.id === state.selectedRoomId ? 0.002 : -0.004;
    });
    if (room) {
      updateSceneStatus("방 선택", "선택한 방에 바닥 마감재와 벽지를 따로 적용할 수 있습니다.");
      state.activeFloorMaterial = room.userData.floorMaterial || state.activeFloorMaterial;
      state.activeWallMaterial = room.userData.wallMaterial || state.activeWallMaterial;
      renderFloorMaterials();
      renderWallMaterials();
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
    if (state.selectedWall) {
      if (!isMovableWall(state.selectedWall)) {
        updateSafetyState("추출된 벽은 회전할 수 없습니다.");
        return;
      }
      clearVisualization();
      state.selectedWall.rotation.y += Math.PI / 2;
      if (state.selectionHelper) state.selectionHelper.update();
      refreshRoomsAfterWallEdit();
      updateSafetyState("벽을 90도 회전했습니다.");
      return;
    }
    if (!state.selectedFurniture) return;
    clearVisualization();
    state.selectedFurniture.rotation.y += Math.PI / 2;
    if (state.selectionHelper) state.selectionHelper.update();
    updateSafetyState();
    updateEstimate();
  }

  function deleteSelectedFurniture(toolbar) {
    if (state.selectedWall) {
      const wall = state.selectedWall;
      if (!isDeletableWall(wall)) {
        updateSafetyState("200mm를 초과하는 구조벽은 삭제할 수 없습니다.");
        return;
      }
      eraseWallRegionFromOverlay(wall);
      if (wall.parent) wall.parent.remove(wall);
      disposeObject3D(wall);
      state.wallObjects = state.wallObjects.filter((m) => m !== wall);
      clearSelectionHighlight();
      clearVisualization();
      state.selectedWall = null;
      if (toolbar) toolbar.style.display = "none";
      refreshRoomsAfterWallEdit();
      updateSafetyState("벽을 삭제했습니다.");
      return;
    }

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

  function toggleWallDrawingMode() {
    if (state.isWallDrawing) {
      cancelWallDrawing();
      return;
    }
    clearVisualization();
    clearSelectionHighlight();
    state.selectedFurniture = null;
    state.selectedWall = null;
    state.isWallDrawing = true;
    state.pendingWallStart = null;
    const button = document.getElementById("btn-wall-add");
    if (button) button.classList.add("active");
    updateSceneStatus("벽 추가 모드", "시작점과 끝점을 차례로 클릭해서 벽을 생성합니다. ESC로 취소합니다.");
  }

  function cancelWallDrawing() {
    state.isWallDrawing = false;
    state.pendingWallStart = null;
    removeWallPreview();
    const button = document.getElementById("btn-wall-add");
    if (button) button.classList.remove("active");
    updateSceneStatus("Planning Mode", "가구와 벽을 배치하고 충돌을 확인합니다.");
  }

  function handleWallDrawingClick() {
    if (!raycaster.ray.intersectPlane(groundPlane, planeIntersectPoint)) return;
    const point = planeIntersectPoint.clone();
    if (!state.pendingWallStart) {
      state.pendingWallStart = point;
      updateSceneStatus("벽 추가 모드", "끝점을 클릭해서 벽을 완성합니다. ESC로 취소합니다.");
      return;
    }

    const start = state.pendingWallStart.clone();
    const end = snapWallEnd(start, point);
    if (start.distanceTo(end) >= 0.12) {
      addSceneWall(start, end);
      refreshRoomsAfterWallEdit();
      updateSafetyState("벽을 추가했습니다.");
    }
    cancelWallDrawing();
  }

  function snapWallEnd(start, end) {
    const snapped = end.clone();
    const dx = Math.abs(end.x - start.x);
    const dz = Math.abs(end.z - start.z);
    if (dx > dz * 1.35) snapped.z = start.z;
    if (dz > dx * 1.35) snapped.x = start.x;
    return snapped;
  }

  function addSceneWall(start, end) {
    const group = state.floorPlanGroup || state.scene;
    const thickness = currentWallThickness();
    const height = 2.4;
    const wall = createPlanningWallMesh(start, end, thickness, height, {
      id: `wall_custom_${Date.now()}`,
      label: "사용자 벽",
      editable: true,
      source: null,
    });
    group.add(wall);
    state.wallObjects.push(wall);
  }

  function currentWallThickness() {
    const existing = state.wallObjects.find((wall) => wall.geometry && wall.geometry.parameters);
    return existing ? Math.max(existing.geometry.parameters.depth, 0.08) : 0.14;
  }

  function updateWallPreview(start, end) {
    const snapped = snapWallEnd(start, end);
    removeWallPreview();
    if (start.distanceTo(snapped) < 0.12) return;
    state.wallPreview = createPlanningWallMesh(start, snapped, currentWallThickness(), 2.4, {
      id: "wall_preview",
      label: "벽 미리보기",
      editable: false,
      source: null,
    });
    state.wallPreview.material.opacity = 0.42;
    state.scene.add(state.wallPreview);
  }

  function removeWallPreview() {
    if (!state.wallPreview) return;
    state.scene.remove(state.wallPreview);
    disposeObject3D(state.wallPreview);
    state.wallPreview = null;
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

    vectorizeFloorPlanFile(file)
      .then((planData) => loadFloorPlan(planData))
      .catch((err) => {
        console.error(err);
        alert("평면도 데이터를 불러오지 못했습니다: " + err.message);
      });
  }

  async function vectorizeFloorPlanFile(file) {
    updateSceneStatus("평면도 분석 중", "서버에서 벽과 바닥을 분리하고 재구성 JSON을 만들고 있습니다.");
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/floorplans/vectorize", {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const message = await readErrorMessage(res);
      if (res.status === 413) {
        throw new Error(`업로드 파일(${formatBytes(file.size)})이 서버 허용 크기보다 큽니다. 서버 재시작 후 다시 시도하세요.`);
      }
      throw new Error(message || `서버 벡터화 요청 실패 (${res.status})`);
    }
    return res.json();
  }

  async function readErrorMessage(res) {
    const text = await res.text();
    if (!text) return "";
    try {
      const data = JSON.parse(text);
      return data.message || data.error || text;
    } catch (_err) {
      return text;
    }
  }

  function formatBytes(bytes) {
    const value = Number(bytes) || 0;
    if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)}MB`;
    if (value >= 1024) return `${(value / 1024).toFixed(1)}KB`;
    return `${value}B`;
  }

  function loadFloorPlan(planData) {
    if (isEditableFloorPlan(planData)) {
      loadReconstructedFloorPlan(planData);
      return;
    }
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

  function isEditableFloorPlan(planData) {
    if (!planData || typeof planData !== "object") return false;
    if (planData.layers && planData.layers.mode === "editable_floorplan") return true;
    return Array.isArray(planData.walls) && Array.isArray(planData.floors);
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
      const scale = FLOOR_PLAN_PIXEL_TO_SCENE;
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
      state.floorLockedToPlan = false;
      group.add(mesh);
      const imageTransform = {
        scale,
        toScenePoint: (point) => ({ x: point.x * scale - planeW / 2, z: point.y * scale - planeH / 2 }),
      };
      addWallsToGroup(group, planData, imageTransform);
      state.scene.add(group);
      state.floorPlanGroup = group;
      setFloorBounds({ minX: -planeW / 2, maxX: planeW / 2, minZ: -planeH / 2, maxZ: planeH / 2 });
      buildImageFloorMask(imageDataUri, attrs.width, attrs.height, planeW, planeH);
      focusCameraOnPlanContent(planeW, planeH, new THREE.Vector3(0, 0, 0));
      updateSceneStatus("평면도 로드 완료", "타일 바닥색 영역만 가구 배치 가능 영역으로 인식합니다.");
      updateSafetyState();
    });
  }

  function buildImageFloorMask(imageDataUri, width, height, planeW, planeH) {
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(img, 0, 0, width, height);
      const rgba = ctx.getImageData(0, 0, width, height).data;
      const tileColor = inferTileColor(rgba);
      const inferredTileIsBeige = isBeigeTileColor(tileColor);
      const candidateMask = new Uint8Array(width * height);
      const wallCandidateMask = new Uint8Array(width * height);
      let candidatePixels = 0;

      for (let i = 0, p = 0; i < rgba.length; i += 4, p += 1) {
        const r = rgba[i];
        const g = rgba[i + 1];
        const b = rgba[i + 2];
        const a = rgba[i + 3];
        const darkness = (r + g + b) / 3;
        const color = { r, g, b };
        const nearTile = inferredTileIsBeige && colorDistance(color, tileColor) <= FLOOR_COLOR_TOLERANCE;
        if (a > IMAGE_WALL_ALPHA && darkness > IMAGE_WALL_DARKNESS && (isBeigeTileColor(color) || nearTile)) {
          candidateMask[p] = 1;
          candidatePixels += 1;
        }
        if (a > IMAGE_WALL_ALPHA && darkness < IMAGE_WALL_DARKNESS) {
          wallCandidateMask[p] = 1;
        }
      }

      let mask = cleanImageFloorMask(candidateMask, width, height);
      let floorPixels = countMaskPixels(mask);
      if (floorPixels === 0 && candidatePixels > 0) {
        mask = candidateMask;
        floorPixels = candidatePixels;
      }
      state.imageFloorMask = {
        width,
        height,
        planeW,
        planeH,
        mask,
        integral: buildMaskIntegral(mask, width, height),
      };
      const wallMask = cleanImageWallMask(wallCandidateMask, width, height);
      const wallPixels = countMaskPixels(wallMask);
      state.imageWallMask = {
        width,
        height,
        mask: wallMask,
        integral: buildMaskIntegral(wallMask, width, height),
      };
      updateSceneStatus(
        "바닥색 분석 완료",
        `베이지 바닥 ${floorPixels.toLocaleString("ko-KR")}개, 벽선 ${wallPixels.toLocaleString("ko-KR")}개를 인식했습니다.`
      );
      updateSafetyState();
    };
    img.onerror = () => {
      state.imageFloorMask = null;
      state.imageWallMask = null;
      updateSceneStatus("바닥색 분석 실패", "평면도 이미지는 표시되지만 타일색 배치 제한은 적용되지 않았습니다.");
    };
    img.src = imageDataUri;
  }

  function isBeigeTileColor(color) {
    const { r, g, b } = color;
    const brightness = (r + g + b) / 3;
    const warmEnough = r >= g - 18 && g >= b - 8 && r >= b + 10;
    const notTooRed = r - g <= 58;
    const muted = Math.max(r, g, b) - Math.min(r, g, b) <= 96;
    return brightness >= 132 && brightness <= 248 && warmEnough && notTooRed && muted;
  }

  function inferTileColor(rgba) {
    const buckets = new Map();
    let fallback = { r: 230, g: 230, b: 230 };
    let fallbackCount = 0;

    for (let i = 0; i < rgba.length; i += 4) {
      const r = rgba[i];
      const g = rgba[i + 1];
      const b = rgba[i + 2];
      const a = rgba[i + 3];
      const brightness = (r + g + b) / 3;
      const chroma = Math.max(r, g, b) - Math.min(r, g, b);
      if (a <= IMAGE_WALL_ALPHA || brightness <= IMAGE_WALL_DARKNESS || brightness >= 252 || chroma > 72) continue;
      const key = `${Math.round(r / 12) * 12},${Math.round(g / 12) * 12},${Math.round(b / 12) * 12}`;
      const bucket = buckets.get(key) || { r: 0, g: 0, b: 0, count: 0 };
      bucket.r += r;
      bucket.g += g;
      bucket.b += b;
      bucket.count += 1;
      buckets.set(key, bucket);
      if (bucket.count > fallbackCount) {
        fallbackCount = bucket.count;
        fallback = {
          r: bucket.r / bucket.count,
          g: bucket.g / bucket.count,
          b: bucket.b / bucket.count,
        };
      }
    }

    return fallback;
  }

  function colorDistance(a, b) {
    const dr = a.r - b.r;
    const dg = a.g - b.g;
    const db = a.b - b.b;
    return Math.sqrt(dr * dr + dg * dg + db * db);
  }

  function cleanImageFloorMask(rawMask, width, height) {
    const total = width * height;
    const visited = new Uint8Array(total);
    const cleaned = new Uint8Array(total);
    const queue = [];
    const minArea = Math.max(MIN_FLOOR_COMPONENT_PIXELS, Math.floor(total * 0.0003));

    for (let start = 0; start < total; start += 1) {
      if (!rawMask[start] || visited[start]) continue;

      let head = 0;
      let count = 0;
      let minX = width;
      let maxX = 0;
      let minY = height;
      let maxY = 0;

      queue.length = 0;
      queue.push(start);
      visited[start] = 1;

      while (head < queue.length) {
        const index = queue[head++];
        const x = index % width;
        const y = Math.floor(index / width);
        count += 1;
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;

        visitMaskNeighbor(index - 1, x > 0);
        visitMaskNeighbor(index + 1, x < width - 1);
        visitMaskNeighbor(index - width, y > 0);
        visitMaskNeighbor(index + width, y < height - 1);
      }

      const componentWidth = maxX - minX + 1;
      const componentHeight = maxY - minY + 1;
      const density = count / Math.max(componentWidth * componentHeight, 1);
      const touchesBorder = minX === 0 || minY === 0 || maxX === width - 1 || maxY === height - 1;
      const floorLike = count >= minArea && density >= 0.08 && !touchesBorder;

      if (floorLike) {
        for (const index of queue) cleaned[index] = 1;
      }

      function visitMaskNeighbor(index, inBounds) {
        if (!inBounds || visited[index] || !rawMask[index]) return;
        visited[index] = 1;
        queue.push(index);
      }
    }

    return cleaned;
  }

  function cleanImageWallMask(rawMask, width, height) {
    const total = width * height;
    const visited = new Uint8Array(total);
    const wallMask = new Uint8Array(total);
    const queue = [];
    const minArea = Math.max(MIN_WALL_COMPONENT_PIXELS, Math.floor(total * 0.00002));
    const minLongSide = Math.max(MIN_WALL_COMPONENT_LONG_SIDE, Math.floor(Math.min(width, height) * 0.01));

    for (let start = 0; start < total; start += 1) {
      if (!rawMask[start] || visited[start]) continue;

      let head = 0;
      let count = 0;
      let minX = width;
      let maxX = 0;
      let minY = height;
      let maxY = 0;

      queue.length = 0;
      queue.push(start);
      visited[start] = 1;

      while (head < queue.length) {
        const index = queue[head++];
        const x = index % width;
        const y = Math.floor(index / width);
        count += 1;
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;

        visitMaskNeighbor(index - 1, x > 0);
        visitMaskNeighbor(index + 1, x < width - 1);
        visitMaskNeighbor(index - width, y > 0);
        visitMaskNeighbor(index + width, y < height - 1);
      }

      const componentWidth = maxX - minX + 1;
      const componentHeight = maxY - minY + 1;
      const longSide = Math.max(componentWidth, componentHeight);
      const shortSide = Math.max(Math.min(componentWidth, componentHeight), 1);
      const aspect = longSide / shortSide;
      const density = count / Math.max(componentWidth * componentHeight, 1);
      const lineLike = longSide >= minLongSide && aspect >= 2.8;
      const outlineLike = count >= minArea * 4 && longSide >= minLongSide * 2;
      const tooSmallForWall = count < minArea || longSide < minLongSide;
      const wallLike = !tooSmallForWall && density >= 0.006 && (lineLike || outlineLike);

      if (wallLike) {
        for (const index of queue) wallMask[index] = 1;
      }

      function visitMaskNeighbor(index, inBounds) {
        if (!inBounds || visited[index] || !rawMask[index]) return;
        visited[index] = 1;
        queue.push(index);
      }
    }

    return wallMask;
  }

  function countMaskPixels(mask) {
    let count = 0;
    for (let i = 0; i < mask.length; i += 1) {
      if (mask[i]) count += 1;
    }
    return count;
  }

  function buildMaskIntegral(mask, width, height) {
    const integral = new Uint32Array((width + 1) * (height + 1));
    for (let y = 0; y < height; y += 1) {
      let rowSum = 0;
      for (let x = 0; x < width; x += 1) {
        rowSum += mask[y * width + x];
        const dest = (y + 1) * (width + 1) + x + 1;
        integral[dest] = integral[dest - width - 1] + rowSum;
      }
    }
    return integral;
  }

  function getFloorPlanPixelSize(planData) {
    const rootAttrs = planData["@attributes"] || {};
    const imageAttrs = (planData.image && planData.image["@attributes"]) || {};
    return {
      width: parseFloat(rootAttrs.width || imageAttrs.width) || 1000,
      height: parseFloat(rootAttrs.height || imageAttrs.height) || 1000,
    };
  }

  function loadReconstructedFloorPlan(planData) {
    clearFloorPlan();
    const attrs = getFloorPlanPixelSize(planData);
    const scale = FLOOR_PLAN_PIXEL_TO_SCENE;
    const planeW = attrs.width * scale;
    const planeH = attrs.height * scale;
    const group = new THREE.Group();
    group.name = "floorPlan";
    state.wallObjects = [];
    state.floorObjects = [];
    state.baseFloorObjects = [];
    state.roomObjects = [];
    state.selectedRoomId = null;
    state.floorLockedToPlan = false;

    const imageTransform = {
      scale,
      toScenePoint: (point) => ({ x: point.x * scale - planeW / 2, z: point.y * scale - planeH / 2 }),
    };

    addWallMaskOverlay(group, planData, planeW, planeH);
    addEditableWallRegionsToGroup(group, planData, imageTransform);
    state.scene.add(group);
    state.floorPlanGroup = group;
    setFloorBounds({ minX: -planeW / 2, maxX: planeW / 2, minZ: -planeH / 2, maxZ: planeH / 2 });
    state.wallRenderRects = normalizeWallRenderRects(planData.wall_render_rects);
    loadWallCollisionMaskFromPlan(planData);
    const usedExtractedFootprint = loadExtractedFloorFootprintFromPlan(planData, attrs);
    if (!usedExtractedFootprint) {
      const usedExtractedRooms = loadExtractedRoomsFromPlan(planData, attrs);
      if (!usedExtractedRooms) rebuildRoomsFromWalls();
    }
    focusCameraOnPlanContent(planeW, planeH, new THREE.Vector3(0, 0, 0));
    updateSceneStatus(
      "재구성 평면도 로드 완료",
      usedExtractedFootprint ? "평면도 이미지 영역 전체를 바닥으로 인식합니다." : "벽으로 닫힌 내부 공간을 방 단위 바닥으로 인식합니다."
    );
    updateSafetyState();
  }

  function addReconstructedFloorsToGroup(group, planData, transform) {
    const floors = Array.isArray(planData.floors) ? planData.floors : [];
    if (floors.length === 0) {
      addFallbackFloorPlane(group, transform);
      return;
    }

    floors.forEach((floor) => {
      const points = Array.isArray(floor.points) ? floor.points : [];
      if (points.length < 3) return;
      const scenePoints = points.map((point) => {
        const scenePoint = transform.toScenePoint(point);
        return { x: scenePoint.x, y: -scenePoint.z };
      });
      const smoothedPoints = simplifyPolygon(scenePoints, FLOOR_SIMPLIFY_TOLERANCE);
      const sealedPoints = inflatePolygon(smoothedPoints, FLOOR_SEAM_MARGIN);
      const shape = new THREE.Shape();
      sealedPoints.forEach((point, index) => {
        if (index === 0) shape.moveTo(point.x, point.y);
        else shape.lineTo(point.x, point.y);
      });
      shape.closePath();
      const mesh = new THREE.Mesh(
        new THREE.ShapeGeometry(shape),
        createFloorMaterial()
      );
      mesh.rotation.x = -Math.PI / 2;
      mesh.position.y = -0.002;
      mesh.receiveShadow = true;
      group.add(mesh);
      state.baseFloorObjects.push(mesh);
    });
  }

  function simplifyPolygon(points, tolerance) {
    if (tolerance <= 0 || points.length < 4) return points;
    const keep = new Uint8Array(points.length);
    keep[0] = 1;
    keep[points.length - 1] = 1;
    rdpMarkKeep(points, 0, points.length - 1, tolerance, keep);
    return points.filter((_, index) => keep[index]);
  }

  function rdpMarkKeep(points, startIndex, endIndex, tolerance, keep) {
    if (endIndex <= startIndex + 1) return;
    const start = points[startIndex];
    const end = points[endIndex];
    let maxDist = 0;
    let maxIndex = -1;
    for (let i = startIndex + 1; i < endIndex; i += 1) {
      const dist = pointToSegmentDistance(points[i], start, end);
      if (dist > maxDist) {
        maxDist = dist;
        maxIndex = i;
      }
    }
    if (maxDist > tolerance && maxIndex !== -1) {
      keep[maxIndex] = 1;
      rdpMarkKeep(points, startIndex, maxIndex, tolerance, keep);
      rdpMarkKeep(points, maxIndex, endIndex, tolerance, keep);
    }
  }

  function pointToSegmentDistance(point, start, end) {
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const lengthSq = dx * dx + dy * dy;
    if (lengthSq === 0) return Math.hypot(point.x - start.x, point.y - start.y);
    const t = Math.max(0, Math.min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / lengthSq));
    const projX = start.x + t * dx;
    const projY = start.y + t * dy;
    return Math.hypot(point.x - projX, point.y - projY);
  }

  function inflatePolygon(points, margin) {
    if (margin <= 0 || points.length < 3) return points;
    const centroid = points.reduce(
      (acc, p) => ({ x: acc.x + p.x / points.length, y: acc.y + p.y / points.length }),
      { x: 0, y: 0 }
    );
    return points.map((p) => {
      const dx = p.x - centroid.x;
      const dy = p.y - centroid.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      return { x: p.x + (dx / dist) * margin, y: p.y + (dy / dist) * margin };
    });
  }

  function addFallbackFloorPlane(group, transform) {
    const width = FALLBACK_FLOOR_PLAN_SIZE_M;
    const height = FALLBACK_FLOOR_PLAN_SIZE_M;
    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(width, height),
      createFloorMaterial()
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.002;
    floor.receiveShadow = true;
    group.add(floor);
    state.baseFloorObjects.push(floor);
  }

  function buildFloorMaskFromPolygons(planData, width, height, planeW, planeH) {
    const floors = Array.isArray(planData.floors) ? planData.floors : [];
    if (floors.length === 0) return null;

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.fillStyle = "#000";
    floors.forEach((floor) => {
      const points = Array.isArray(floor.points) ? floor.points : [];
      if (points.length < 3) return;
      ctx.beginPath();
      points.forEach((point, index) => {
        if (index === 0) ctx.moveTo(point.x, point.y);
        else ctx.lineTo(point.x, point.y);
      });
      ctx.closePath();
      ctx.fill();
    });

    const data = ctx.getImageData(0, 0, width, height).data;
    const mask = new Uint8Array(width * height);
    for (let i = 3, p = 0; i < data.length; i += 4, p += 1) {
      if (data[i] > 0) mask[p] = 1;
    }
    return {
      width,
      height,
      planeW,
      planeH,
      mask,
      integral: buildMaskIntegral(mask, width, height),
    };
  }

  function buildFullFloorMask(width, height, planeW, planeH) {
    const mask = new Uint8Array(width * height);
    mask.fill(1);
    return {
      width,
      height,
      planeW,
      planeH,
      mask,
      integral: buildMaskIntegral(mask, width, height),
    };
  }

  function loadExtractedFloorFootprintFromPlan(planData, attrs) {
    const floors = Array.isArray(planData.floors) ? planData.floors : [];
    if (floors.length === 0 || !state.floorBounds) return false;

    clearRoomFloors();
    const width = FLOOR_MASK_TARGET_WIDTH;
    const height = Math.max(96, Math.round(width * attrs.height / Math.max(attrs.width, 1)));
    const combined = new Uint8Array(width * height);

    floors.forEach((floor) => {
      const mask = rasterizePlanPolygonToMask(floor.points, attrs, width, height);
      mask.forEach((value, index) => {
        if (value) combined[index] = 1;
      });
    });

    const metrics = measureMask(combined, width, height);
    if (metrics.count <= Math.max(40, width * height * 0.0008)) return false;

    const roomData = {
      width,
      height,
      bounds: state.floorBounds,
      rooms: [{
        id: "floor_footprint",
        mask: combined,
        count: metrics.count,
        bbox: metrics.bbox,
        floorMaterial: state.activeFloorMaterial,
        wallMaterial: state.activeWallMaterial,
      }],
    };

    state.roomObjects = roomData.rooms.map((room) => createRoomFloor(room, roomData));
    state.roomObjects.forEach((room) => {
      state.floorPlanGroup.add(room);
      state.floorObjects.push(room);
    });
    state.imageFloorMask = buildMaskFromRooms(roomData);
    state.selectedRoomId = null;
    state.floorLockedToPlan = true;
    return true;
  }

  function loadExtractedRoomsFromPlan(planData, attrs) {
    const rooms = Array.isArray(planData.rooms) ? planData.rooms : [];
    if (rooms.length === 0 || !state.floorBounds) return false;

    clearRoomFloors();
    const width = FLOOR_MASK_TARGET_WIDTH;
    const height = Math.max(96, Math.round(width * attrs.height / Math.max(attrs.width, 1)));
    const roomData = { width, height, bounds: state.floorBounds, rooms: [] };

    rooms.forEach((room, index) => {
      const mask = rasterizePlanPolygonToMask(room.points, attrs, width, height);
      const metrics = measureMask(mask, width, height);
      if (metrics.count <= Math.max(40, width * height * 0.0008)) return;
      roomData.rooms.push({
        id: room.id || `room_${index + 1}`,
        mask,
        count: metrics.count,
        bbox: metrics.bbox,
        floorMaterial: state.activeFloorMaterial,
        wallMaterial: state.activeWallMaterial,
      });
    });

    if (roomData.rooms.length === 0) return false;

    state.roomObjects = roomData.rooms.map((room) => createRoomFloor(room, roomData));
    state.roomObjects.forEach((room) => {
      state.floorPlanGroup.add(room);
      state.floorObjects.push(room);
    });
    state.imageFloorMask = buildMaskFromRooms(roomData);
    state.selectedRoomId = null;
    state.floorLockedToPlan = true;
    return true;
  }

  function rasterizePlanPolygonToMask(points, attrs, width, height) {
    const mask = new Uint8Array(width * height);
    if (!Array.isArray(points) || points.length < 3) return mask;

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.fillStyle = "#000";
    ctx.beginPath();
    points.forEach((point, index) => {
      const x = ((Number(point.x) + 0.5) / Math.max(attrs.width, 1)) * width - 0.5;
      const y = ((Number(point.y) + 0.5) / Math.max(attrs.height, 1)) * height - 0.5;
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.fill();

    const data = ctx.getImageData(0, 0, width, height).data;
    for (let i = 3, p = 0; i < data.length; i += 4, p += 1) {
      if (data[i] > 0) mask[p] = 1;
    }
    return mask;
  }

  function measureMask(mask, width, height) {
    let count = 0;
    let minX = width;
    let minY = height;
    let maxX = 0;
    let maxY = 0;
    for (let index = 0; index < mask.length; index += 1) {
      if (!mask[index]) continue;
      const x = index % width;
      const y = Math.floor(index / width);
      count += 1;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
    if (count === 0) {
      return { count: 0, bbox: { minX: 0, minY: 0, maxX: 0, maxY: 0 } };
    }
    return { count, bbox: { minX, minY, maxX, maxY } };
  }

  function rebuildRoomsFromWalls() {
    if (!state.floorPlanGroup || !state.floorBounds) return;
    const previousRooms = state.roomObjects.map((room) => ({
      center: room.userData.center,
      floorMaterial: room.userData.floorMaterial,
      wallMaterial: room.userData.wallMaterial,
    }));
    clearRoomFloors();
    const roomData = detectRoomsFromWalls(260);
    if (roomData.rooms.length === 0 && state.wallObjects.length > 0) {
      roomData.rooms.push(createFallbackRoom(roomData));
    }
    roomData.rooms.forEach((room) => {
      const previous = previousRooms.find((entry) => entry.center && pointInRoomMask(entry.center.x, entry.center.z, room, roomData));
      if (previous) {
        room.floorMaterial = previous.floorMaterial;
        room.wallMaterial = previous.wallMaterial;
      }
    });
    state.roomObjects = roomData.rooms.map((room) => createRoomFloor(room, roomData));
    state.roomObjects.forEach((room) => {
      state.floorPlanGroup.add(room);
      state.floorObjects.push(room);
    });
    state.imageFloorMask = buildMaskFromRooms(roomData);
    if (state.selectedRoomId && !state.roomObjects.some((room) => room.userData.id === state.selectedRoomId)) {
      state.selectedRoomId = null;
    }
  }

  function refreshRoomsAfterWallEdit() {
    if (state.floorLockedToPlan) return;
    rebuildRoomsFromWalls();
  }

  function clearRoomFloors() {
    state.floorObjects.forEach((floor) => {
      if (floor.parent) floor.parent.remove(floor);
      disposeObject3D(floor);
    });
    state.floorObjects = [];
    state.roomObjects = [];
  }

  function detectRoomsFromWalls(size) {
    const bounds = state.floorBounds;
    const width = size;
    const height = Math.max(80, Math.round(size * bounds.depth / Math.max(bounds.width, 0.001)));
    const blocked = new Uint8Array(width * height);

    state.wallObjects.forEach((wall) => rasterizeFootprint(blocked, width, height, getPlanFootprint(wall), bounds));

    const pixelsPerUnit = width / Math.max(bounds.width, 0.001);
    let bestRooms = [];
    let bestArea = 0;
    for (const tolerance of ROOM_GAP_TOLERANCE_STEPS) {
      const gapRadius = Math.max(1, Math.round((tolerance / 2) * pixelsPerUnit));
      const sealedBlocked = closeMaskGaps(blocked, width, height, gapRadius);
      const rooms = findEnclosedRooms(sealedBlocked, width, height);
      const area = rooms.reduce((sum, room) => sum + room.count, 0);
      if (area > bestArea) {
        bestRooms = rooms;
        bestArea = area;
      }
    }

    return { width, height, bounds, rooms: bestRooms };
  }

  function findEnclosedRooms(sealedBlocked, width, height) {
    const rooms = [];
    const visited = new Uint8Array(width * height);
    const queue = [];
    for (let start = 0; start < sealedBlocked.length; start += 1) {
      if (sealedBlocked[start] || visited[start]) continue;
      let head = 0;
      let touchesBorder = false;
      let minX = width;
      let minY = height;
      let maxX = 0;
      let maxY = 0;
      queue.length = 0;
      queue.push(start);
      visited[start] = 1;

      while (head < queue.length) {
        const index = queue[head++];
        const x = index % width;
        const y = Math.floor(index / width);
        if (x === 0 || y === 0 || x === width - 1 || y === height - 1) touchesBorder = true;
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
        visitRoomNeighbor(index - 1, x > 0);
        visitRoomNeighbor(index + 1, x < width - 1);
        visitRoomNeighbor(index - width, y > 0);
        visitRoomNeighbor(index + width, y < height - 1);
      }

      if (!touchesBorder && queue.length > Math.max(80, width * height * 0.002)) {
        const roomMask = new Uint8Array(width * height);
        queue.forEach((index) => { roomMask[index] = 1; });
        rooms.push({
          id: `room_${rooms.length + 1}`,
          mask: roomMask,
          count: queue.length,
          bbox: { minX, minY, maxX, maxY },
          floorMaterial: state.activeFloorMaterial,
          wallMaterial: state.activeWallMaterial,
        });
      }

      function visitRoomNeighbor(index, inBounds) {
        if (!inBounds || visited[index] || sealedBlocked[index]) return;
        visited[index] = 1;
        queue.push(index);
      }
    }
    return rooms;
  }

  function createFallbackRoom(roomData) {
    const mask = new Uint8Array(roomData.width * roomData.height).fill(1);
    return {
      id: "room_fallback",
      mask,
      count: mask.length,
      bbox: { minX: 0, minY: 0, maxX: roomData.width - 1, maxY: roomData.height - 1 },
      floorMaterial: state.activeFloorMaterial,
      wallMaterial: state.activeWallMaterial,
    };
  }

  function dilateMask(mask, width, height, radius) {
    if (radius <= 0) return mask;
    const rowPass = new Uint8Array(width * height);
    for (let y = 0; y < height; y += 1) {
      const rowStart = y * width;
      for (let x = 0; x < width; x += 1) {
        const xStart = Math.max(0, x - radius);
        const xEnd = Math.min(width - 1, x + radius);
        let hit = 0;
        for (let xx = xStart; xx <= xEnd; xx += 1) {
          if (mask[rowStart + xx]) { hit = 1; break; }
        }
        rowPass[rowStart + x] = hit;
      }
    }
    const result = new Uint8Array(width * height);
    for (let x = 0; x < width; x += 1) {
      for (let y = 0; y < height; y += 1) {
        const yStart = Math.max(0, y - radius);
        const yEnd = Math.min(height - 1, y + radius);
        let hit = 0;
        for (let yy = yStart; yy <= yEnd; yy += 1) {
          if (rowPass[yy * width + x]) { hit = 1; break; }
        }
        result[y * width + x] = hit;
      }
    }
    return result;
  }

  function closeMaskGaps(mask, width, height, radius) {
    if (radius <= 0) return mask;
    const dilated = dilateMask(mask, width, height, radius);
    const invertedDilated = new Uint8Array(width * height);
    for (let i = 0; i < dilated.length; i += 1) invertedDilated[i] = dilated[i] ? 0 : 1;
    const erodedInverted = dilateMask(invertedDilated, width, height, radius);
    const result = new Uint8Array(width * height);
    for (let i = 0; i < erodedInverted.length; i += 1) result[i] = erodedInverted[i] ? 0 : 1;
    return result;
  }

  function rasterizeFootprint(mask, width, height, points, bounds) {
    if (!points || points.length < 3) return;
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#000";
    ctx.beginPath();
    points.forEach((point, index) => {
      const pixel = scenePointToRoomPixel(point.x, point.z, width, height, bounds);
      if (index === 0) ctx.moveTo(pixel.x, pixel.y);
      else ctx.lineTo(pixel.x, pixel.y);
    });
    ctx.closePath();
    ctx.fill();
    const data = ctx.getImageData(0, 0, width, height).data;
    for (let i = 3, p = 0; i < data.length; i += 4, p += 1) {
      if (data[i] > 0) mask[p] = 1;
    }
  }

  function createRoomFloor(room, roomData) {
    const material = createMaskedRoomMaterial(room, roomData);
    const mesh = new THREE.Mesh(
      new THREE.PlaneGeometry(roomData.bounds.width, roomData.bounds.depth),
      material
    );
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.set(roomData.bounds.center.x, -0.004, roomData.bounds.center.z);
    mesh.receiveShadow = true;
    mesh.userData = {
      type: "room",
      id: room.id,
      mask: room.mask,
      maskWidth: roomData.width,
      maskHeight: roomData.height,
      bbox: room.bbox,
      center: roomCenterToScene(room, roomData),
      floorMaterial: room.floorMaterial,
      wallMaterial: room.wallMaterial,
    };
    return mesh;
  }

  function roomCenterToScene(room, roomData) {
    const px = (room.bbox.minX + room.bbox.maxX) / 2;
    const py = (room.bbox.minY + room.bbox.maxY) / 2;
    return {
      x: roomData.bounds.minX + (px / Math.max(roomData.width - 1, 1)) * roomData.bounds.width,
      z: roomData.bounds.minZ + (py / Math.max(roomData.height - 1, 1)) * roomData.bounds.depth,
    };
  }

  function pointInRoomMask(x, z, room, roomData) {
    const pixel = scenePointToRoomPixel(x, z, roomData.width, roomData.height, roomData.bounds);
    return Boolean(room.mask[pixel.y * roomData.width + pixel.x]);
  }

  function createMaskedRoomMaterial(room, roomData) {
    const canvas = document.createElement("canvas");
    canvas.width = roomData.width;
    canvas.height = roomData.height;
    const ctx = canvas.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    const patternTexture = createFloorPatternCanvas(getFloorMaterialByValue(room.floorMaterial), canvas.width, canvas.height);
    ctx.drawImage(patternTexture, 0, 0);
    const image = ctx.getImageData(0, 0, canvas.width, canvas.height);
    for (let i = 3, p = 0; i < image.data.length; i += 4, p += 1) {
      image.data[i] = room.mask[p] ? 255 : 0;
    }
    ctx.putImageData(image, 0, 0);
    const texture = new THREE.CanvasTexture(canvas);
    texture.wrapS = THREE.ClampToEdgeWrapping;
    texture.wrapT = THREE.ClampToEdgeWrapping;
    texture.needsUpdate = true;
    return new THREE.MeshStandardMaterial({
      color: 0xffffff,
      map: texture,
      transparent: true,
      roughness: 0.82,
      side: THREE.DoubleSide,
    });
  }

  function buildMaskFromRooms(roomData) {
    const mask = new Uint8Array(roomData.width * roomData.height);
    roomData.rooms.forEach((room) => {
      room.mask.forEach((value, index) => {
        if (value) mask[index] = 1;
      });
    });
    return {
      width: roomData.width,
      height: roomData.height,
      planeW: roomData.bounds.width,
      planeH: roomData.bounds.depth,
      mask,
      integral: buildMaskIntegral(mask, roomData.width, roomData.height),
    };
  }

  function scenePointToRoomPixel(x, z, width, height, bounds) {
    return {
      x: clamp(Math.round(((x - bounds.minX) / bounds.width) * (width - 1)), 0, width - 1),
      y: clamp(Math.round(((z - bounds.minZ) / bounds.depth) * (height - 1)), 0, height - 1),
    };
  }

  function getRoomAtScenePoint(x, z) {
    if (!state.floorBounds || state.roomObjects.length === 0) return null;
    const width = state.roomObjects[0].userData.maskWidth;
    const height = state.roomObjects[0].userData.maskHeight;
    const pixel = scenePointToRoomPixel(x, z, width, height, state.floorBounds);
    return state.roomObjects.find((room) => room.userData.mask[pixel.y * width + pixel.x]);
  }

  function loadVectorFloorPlan(planData) {
    clearFloorPlan();
    const group = new THREE.Group();
    group.name = "floorPlan";
    state.wallObjects = [];
    state.floorLockedToPlan = false;
    const vectorTransform = {
      scale: MM_TO_SCENE,
      toScenePoint: (point) => ({ x: point.x * MM_TO_SCENE, z: point.y * MM_TO_SCENE }),
    };
    addWallsToGroup(group, planData, vectorTransform);
    state.scene.add(group);
    state.floorPlanGroup = group;

    const width = (planData.width || 6000) * MM_TO_SCENE;
    const depth = (planData.depth || 4000) * MM_TO_SCENE;
    setFloorBounds({ minX: 0, maxX: width, minZ: 0, maxZ: depth });
    rebuildRoomsFromWalls();
    focusCameraOnPlanContent(width, depth);
    updateSceneStatus("벡터 평면도 로드 완료", "벽체 충돌과 경계 스냅을 적용합니다.");
    updateSafetyState();
  }

  function addWallsToGroup(group, planData, transform) {
    if (!Array.isArray(planData.walls)) return;
    planData.walls.forEach((wall) => addWallToGroup(group, wall, transform));
    classifyWallsByThickness();
  }

  function addEditableWallRegionsToGroup(group, planData, transform) {
    const regions = Array.isArray(planData.editable_wall_regions) ? planData.editable_wall_regions : [];
    regions.forEach((wall) => addWallToGroup(group, wall, transform, { hitOnly: true }));
    classifyWallsByThickness();
  }

  function addWallMaskOverlay(group, planData, planeW, planeH) {
    const dataUri = getLayerDataUri(planData, "wall_transparent") || getLayerDataUri(planData, "wall_mask");
    if (!dataUri) return;
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = img.naturalWidth || img.width;
      canvas.height = img.naturalHeight || img.height;
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(img, 0, 0);
      const texture = new THREE.CanvasTexture(canvas);
      texture.needsUpdate = true;
      const mesh = new THREE.Mesh(
        new THREE.PlaneGeometry(planeW, planeH),
        new THREE.MeshBasicMaterial({ map: texture, transparent: true, side: THREE.DoubleSide })
      );
      mesh.rotation.x = -Math.PI / 2;
      mesh.position.set(0, 0.018, 0);
      mesh.renderOrder = 2;
      mesh.userData.type = "wallOverlay";
      group.add(mesh);
      state.wallOverlay = { mesh, canvas, ctx, texture };
    };
    img.src = dataUri;
  }

  function getLayerDataUri(planData, key) {
    const value = planData && planData.layers && planData.layers[key];
    return typeof value === "string" && value.indexOf("data:image") === 0 ? value : null;
  }

  function loadWallCollisionMaskFromPlan(planData) {
    const dataUri = getLayerDataUri(planData, "wall_mask");
    state.imageWallMask = null;
    if (!dataUri) return;
    const img = new Image();
    img.onload = () => {
      const width = img.naturalWidth || img.width;
      const height = img.naturalHeight || img.height;
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(img, 0, 0);
      const data = ctx.getImageData(0, 0, width, height).data;
      const mask = new Uint8Array(width * height);
      for (let i = 0, p = 0; i < data.length; i += 4, p += 1) {
        if (data[i] > 0 || data[i + 1] > 0 || data[i + 2] > 0) mask[p] = 1;
      }
      state.imageWallMask = {
        width,
        height,
        mask,
        integral: buildMaskIntegral(mask, width, height),
      };
      updateSafetyState();
    };
    img.src = dataUri;
  }

  function normalizeWallRenderRects(rectData) {
    if (!rectData || !Array.isArray(rectData.rects)) return null;
    const width = Number(rectData.width);
    const height = Number(rectData.height);
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return null;
    const rects = rectData.rects
      .map((rect) => Array.isArray(rect)
        ? { x: Number(rect[0]), y: Number(rect[1]), width: Number(rect[2]), height: Number(rect[3]) }
        : { x: Number(rect.x), y: Number(rect.y), width: Number(rect.width), height: Number(rect.height) })
      .filter((rect) => Number.isFinite(rect.x)
        && Number.isFinite(rect.y)
        && Number.isFinite(rect.width)
        && Number.isFinite(rect.height)
        && rect.width > 0
        && rect.height > 0);
    return rects.length ? { width, height, rects } : null;
  }

  function addWallToGroup(group, wall, transform, options) {
    const { x1, y1, x2, y2 } = wall || {};
    if ([x1, y1, x2, y2].some((v) => typeof v !== "number")) return;
    const start = transform.toScenePoint({ x: x1, y: y1 });
    const end = transform.toScenePoint({ x: x2, y: y2 });
    const height = (wall.height || 2400) * MM_TO_SCENE;
    const thickness = firstNumber(wall.thickness, wall.thickness_px, 100) * transform.scale;
    const dx = end.x - start.x;
    const dz = end.z - start.z;
    if (Math.sqrt(dx * dx + dz * dz) === 0) return;

    const mesh = createPlanningWallMesh(start, end, thickness, height, {
      id: wall.id || `wall_${state.wallObjects.length}`,
      label: wall.id || "벽",
      editable: wall.editable !== false,
      deletable: wall.deletable !== false,
      movable: wall.movable !== false,
      source: wall,
      hitOnly: options && options.hitOnly,
    });
    group.add(mesh);
    state.wallObjects.push(mesh);
  }

  function createPlanningWallMesh(start, end, thickness, height, meta) {
    const dx = end.x - start.x;
    const dz = end.z - start.z;
    const length = Math.sqrt(dx * dx + dz * dz);
    const material = meta.hitOnly
      ? new THREE.MeshBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.02, depthWrite: false })
      : new THREE.MeshStandardMaterial({ color: DEFAULT_WALL_COLOR, roughness: 0.78 });
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(length, 0.055, thickness),
      material
    );
    mesh.position.set((start.x + end.x) * 0.5, 0.032, (start.z + end.z) * 0.5);
    mesh.rotation.y = -Math.atan2(dz, dx);
    mesh.userData = {
      type: "wall",
      renderMode: "2d",
      id: meta.id,
      label: meta.label,
      editable: meta.editable,
      locked: meta.locked || false,
      wallRole: meta.wallRole || "partition",
      deletable: meta.deletable !== false,
      movable: meta.movable !== false,
      thicknessM: thickness,
      source: meta.source,
      renderHeight: height,
      wallMaterial: state.activeWallMaterial,
      wallpaperApplied: false,
      hitOnly: Boolean(meta.hitOnly),
    };
    mesh.castShadow = false;
    mesh.receiveShadow = true;
    return mesh;
  }

  function classifyWallsByThickness() {
    state.wallObjects.forEach((wall) => {
      if (!wall.userData.source) return;
      const params = wall.geometry && wall.geometry.parameters;
      const thickness = params ? Number(params.depth) || 0 : 0;
      const structural = thickness > PARTITION_WALL_MAX_THICKNESS_M;
      wall.userData.wallRole = structural ? "structural" : "partition";
      wall.userData.locked = structural;
      wall.userData.deletable = !structural && wall.userData.editable !== false;
      wall.userData.movable = !wall.userData.source && !structural && wall.userData.editable !== false;
      wall.userData.editable = wall.userData.deletable;
      if (wall.material) wall.material.color.setHex(DEFAULT_WALL_COLOR);
    });
  }

  function isEditableWall(wall) {
    return isDeletableWall(wall);
  }

  function isDeletableWall(wall) {
    return Boolean(wall && wall.userData && wall.userData.deletable !== false && wall.userData.editable !== false && !wall.userData.locked);
  }

  function isMovableWall(wall) {
    return Boolean(wall && wall.userData && wall.userData.movable !== false && wall.userData.editable !== false && !wall.userData.locked);
  }

  function eraseWallRegionFromOverlay(wall) {
    const overlay = state.wallOverlay;
    const source = wall && wall.userData && wall.userData.source;
    const bbox = source && source.bbox;
    if (!overlay || !source || !bbox || typeof source.mask !== "string") return;

    const img = new Image();
    img.onload = () => {
      const x = Math.max(0, Number(bbox.x) || 0);
      const y = Math.max(0, Number(bbox.y) || 0);
      const width = Math.min(Number(bbox.width) || img.width, overlay.canvas.width - x);
      const height = Math.min(Number(bbox.height) || img.height, overlay.canvas.height - y);
      if (width <= 0 || height <= 0) return;

      const maskCanvas = document.createElement("canvas");
      maskCanvas.width = width;
      maskCanvas.height = height;
      const maskCtx = maskCanvas.getContext("2d", { willReadFrequently: true });
      maskCtx.drawImage(img, 0, 0, width, height);
      const maskData = maskCtx.getImageData(0, 0, width, height).data;
      const overlayData = overlay.ctx.getImageData(x, y, width, height);
      const pixels = overlayData.data;

      for (let i = 0; i < maskData.length; i += 4) {
        if (maskData[i] <= 0) continue;
        pixels[i] = 0;
        pixels[i + 1] = 0;
        pixels[i + 2] = 0;
        pixels[i + 3] = 0;
      }

      overlay.ctx.putImageData(overlayData, x, y);
      overlay.texture.needsUpdate = true;
      eraseWallRegionFromCollisionMask(x, y, width, height, maskData);
    };
    img.src = source.mask;
  }

  function eraseWallRegionFromCollisionMask(x, y, width, height, maskData) {
    const wallMask = state.imageWallMask;
    if (!wallMask) return;
    for (let py = 0; py < height; py += 1) {
      const destY = y + py;
      if (destY < 0 || destY >= wallMask.height) continue;
      for (let px = 0; px < width; px += 1) {
        const destX = x + px;
        if (destX < 0 || destX >= wallMask.width) continue;
        const maskIndex = (py * width + px) * 4;
        if (maskData[maskIndex] <= 0) continue;
        wallMask.mask[destY * wallMask.width + destX] = 0;
      }
    }
    wallMask.integral = buildMaskIntegral(wallMask.mask, wallMask.width, wallMask.height);
    state.wallRenderRects = null;
  }

  function firstNumber(...values) {
    for (const value of values) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
    return NaN;
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
    updateGridForBounds(state.floorBounds);
  }

  function updateGridForBounds(bounds) {
    if (!state.scene || !bounds) return;
    const cellSize = GRID_CELL_MM * MM_TO_SCENE;
    const boundsWidth = Math.max(bounds.maxX - bounds.minX, 0);
    const boundsDepth = Math.max(bounds.maxZ - bounds.minZ, 0);
    const extent = Math.ceil(Math.max(GRID_MIN_EXTENT_M, boundsWidth + GRID_PADDING_M, boundsDepth + GRID_PADDING_M) / cellSize) * cellSize;
    const divisions = Math.max(1, Math.round(extent / cellSize));

    if (state.gridHelper) {
      state.scene.remove(state.gridHelper);
      state.gridHelper.geometry.dispose();
      state.gridHelper.material.dispose();
    }

    state.gridHelper = new THREE.GridHelper(extent, divisions, 0x004b87, 0xaaaaaa);
    state.gridHelper.position.set((bounds.minX + bounds.maxX) / 2, 0.01, (bounds.minZ + bounds.maxZ) / 2);
    state.scene.add(state.gridHelper);
  }

  function clearFloorPlan() {
    if (state.floorPlanGroup) {
      state.scene.remove(state.floorPlanGroup);
      disposeObject3D(state.floorPlanGroup);
    }
    state.floorPlanGroup = null;
    state.imageFloorMask = null;
    state.imageWallMask = null;
    state.wallOverlay = null;
    state.wallRenderRects = null;
    state.floorLockedToPlan = false;
    state.wallObjects = [];
    state.floorObjects = [];
    state.baseFloorObjects = [];
    state.roomObjects = [];
    state.selectedRoomId = null;
    state.selectedWall = null;
    clearVisualization();
  }

  async function loadCatalog() {
    const listEl = document.getElementById("furniture-list");
    if (!listEl) return;
    try {
      const res = await fetch("/api/furniture");
      if (!res.ok) throw new Error("API 요청 실패");
      state.catalogItems = await res.json();
      renderCatalogTabs();
      renderFurnitureCategoryFilters();
      renderColorFilters();
      renderCatalog();
      updateEstimate();
    } catch (err) {
      console.error(err);
      listEl.innerHTML = "데이터를 불러올 수 없습니다.";
    }
  }

  function renderCatalogTabs() {
    const el = document.getElementById("catalog-tabs");
    if (!el) return;
    el.innerHTML = "";
    CATALOG_SECTIONS.forEach((section) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "catalog-tab-btn" + (state.activeCatalogSection === section.value ? " active" : "");
      button.textContent = section.label;
      button.addEventListener("click", () => {
        state.activeCatalogSection = section.value;
        renderCatalogTabs();
        updateCatalogSections();
        renderCatalog();
      });
      el.appendChild(button);
    });
    updateCatalogSections();
  }

  function updateCatalogSections() {
    const isFurniture = state.activeCatalogSection === "furniture";
    setElementVisible("furniture-category-filter", isFurniture);
    setElementVisible("color-filter", isFurniture);
    setElementVisible("furniture-list", isFurniture);
    setElementVisible("floor-material-section", state.activeCatalogSection === "floor");
    setElementVisible("wall-material-section", state.activeCatalogSection === "wallpaper");
  }

  function setElementVisible(id, visible) {
    const el = document.getElementById(id);
    if (el) el.hidden = !visible;
  }

  function renderFurnitureCategoryFilters() {
    const el = document.getElementById("furniture-category-filter");
    if (!el) return;
    el.innerHTML = "";
    FURNITURE_CATEGORY_FILTERS.forEach((filter) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "category-filter-btn" + (state.activeFurnitureCategory === filter.value ? " active" : "");
      button.textContent = filter.label;
      button.addEventListener("click", () => {
        state.activeFurnitureCategory = filter.value;
        renderFurnitureCategoryFilters();
        renderCatalog();
      });
      el.appendChild(button);
    });
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

  function renderFloorMaterials() {
    const el = document.getElementById("floor-materials");
    const label = document.getElementById("floor-material-name");
    if (!el) return;
    el.innerHTML = "";
    FLOOR_MATERIALS.forEach((material) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "material-btn" + (state.activeFloorMaterial === material.value ? " active" : "");
      button.innerHTML = `<div class="material-swatch"></div><span>${escapeHtml(material.label)}</span>`;
      button.querySelector(".material-swatch").style.background = material.swatch;
      button.addEventListener("click", () => {
        state.activeFloorMaterial = material.value;
        applyFloorMaterial();
        renderFloorMaterials();
      });
      el.appendChild(button);
    });
    const active = getActiveFloorMaterial();
    if (label) label.textContent = active.label;
  }

  function renderWallMaterials() {
    const el = document.getElementById("wall-materials");
    const label = document.getElementById("wall-material-name");
    if (!el) return;
    el.innerHTML = "";
    WALL_MATERIALS.forEach((material) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "material-btn" + (state.activeWallMaterial === material.value ? " active" : "");
      button.innerHTML = `<div class="material-swatch"></div><span>${escapeHtml(material.label)}</span>`;
      button.querySelector(".material-swatch").style.background = material.swatch;
      button.addEventListener("click", () => {
        state.activeWallMaterial = material.value;
        applyWallMaterial();
        renderWallMaterials();
      });
      el.appendChild(button);
    });
    const active = getActiveWallMaterial();
    if (label) label.textContent = active.label;
  }

  function getActiveFloorMaterial() {
    return FLOOR_MATERIALS.find((material) => material.value === state.activeFloorMaterial) || FLOOR_MATERIALS[0];
  }

  function getFloorMaterialByValue(value) {
    return FLOOR_MATERIALS.find((material) => material.value === value) || getActiveFloorMaterial();
  }

  function getActiveWallMaterial() {
    return WALL_MATERIALS.find((material) => material.value === state.activeWallMaterial) || WALL_MATERIALS[0];
  }

  function getWallMaterialByValue(value) {
    return WALL_MATERIALS.find((material) => material.value === value) || getActiveWallMaterial();
  }

  function createFloorMaterial() {
    const material = getActiveFloorMaterial();
    const texture = createFloorTexture(material);
    return new THREE.MeshStandardMaterial({
      color: 0xffffff,
      map: texture,
      roughness: 0.82,
      side: THREE.DoubleSide,
    });
  }

  function createFloorTexture(material) {
    const canvas = createFloorPatternCanvas(material, 256, 256);
    const texture = new THREE.CanvasTexture(canvas);
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    texture.repeat.set(8, 8);
    return texture;
  }

  function createFloorPatternCanvas(material, width, height) {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = `#${material.color.toString(16).padStart(6, "0")}`;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    if (material.value === "herringbone") {
      drawHerringbone(ctx);
    } else if (material.value === "grass") {
      drawSpeckles(ctx, "#6f8b5a", "#a8bc83");
    } else if (material.value === "graytile") {
      drawPlanks(ctx, ["#cfd2cf", "#aeb2af", "#d9dbd8", "#999f9c"]);
    } else {
      const palettes = {
        oak: ["#6f432f", "#9c6b4d", "#5f3828", "#b6815c"],
        lightwood: ["#eadcc4", "#cdb895", "#f1e4cc", "#c7b08d"],
        cream: ["#e4d2ae", "#c8ac7c", "#eadbbd", "#baa071"],
      };
      drawPlanks(ctx, palettes[material.value] || palettes.oak);
    }
    return canvas;
  }

  function drawPlanks(ctx, colors) {
    const plankWidth = 8;
    const width = ctx.canvas.width;
    const height = ctx.canvas.height;
    for (let x = 0; x < width; x += plankWidth) {
      ctx.fillStyle = colors[(x / plankWidth) % colors.length];
      ctx.fillRect(x, 0, plankWidth, height);
      ctx.strokeStyle = "rgba(31, 41, 55, 0.18)";
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
      for (let y = 0; y < height; y += 32) {
        ctx.strokeStyle = "rgba(255,255,255,0.12)";
        ctx.beginPath();
        ctx.moveTo(x + 2, y + 6);
        ctx.lineTo(x + plankWidth - 2, y + 12);
        ctx.stroke();
      }
    }
  }

  function drawHerringbone(ctx) {
    const width = ctx.canvas.width;
    const height = ctx.canvas.height;
    ctx.strokeStyle = "rgba(73, 49, 31, 0.34)";
    ctx.lineWidth = 3;
    for (let i = -width; i < width * 2; i += 8) {
      ctx.beginPath();
      ctx.moveTo(i, 0);
      ctx.lineTo(i + width / 2, height / 2);
      ctx.lineTo(i, height);
      ctx.stroke();
    }
    ctx.strokeStyle = "rgba(255,255,255,0.18)";
    ctx.lineWidth = 1;
    for (let i = -width; i < width * 2; i += 8) {
      ctx.beginPath();
      ctx.moveTo(i + 4, 0);
      ctx.lineTo(i + width / 2 + 4, height / 2);
      ctx.lineTo(i + 4, height);
      ctx.stroke();
    }
  }

  function drawSpeckles(ctx, dark, light) {
    for (let i = 0; i < 850; i += 1) {
      ctx.fillStyle = i % 2 ? dark : light;
      ctx.globalAlpha = 0.35;
      ctx.fillRect(Math.random() * ctx.canvas.width, Math.random() * ctx.canvas.height, 2, 5);
    }
    ctx.globalAlpha = 1;
  }

  function applyFloorMaterial() {
    const targets = state.selectedRoomId
      ? state.roomObjects.filter((room) => room.userData.id === state.selectedRoomId)
      : state.roomObjects;
    targets.forEach((room) => {
      room.userData.floorMaterial = state.activeFloorMaterial;
    });
    refreshRoomFloorMaterials(targets);
    clearVisualization();
    updateSceneStatus("바닥 마감재 적용", `${state.selectedRoomId ? "선택한 방을" : "전체 방을"} ${getActiveFloorMaterial().label} 마감으로 변경했습니다.`);
  }

  function refreshRoomFloorMaterials(rooms) {
    rooms.forEach((room) => {
      const material = createMaskedRoomMaterial({
        id: room.userData.id,
        mask: room.userData.mask,
        floorMaterial: room.userData.floorMaterial,
      }, {
        width: room.userData.maskWidth,
        height: room.userData.maskHeight,
      });
      if (room.material) {
        if (room.material.map) room.material.map.dispose();
        room.material.dispose();
      }
      room.material = material;
    });
  }

  function createWallMaterial() {
    const material = getActiveWallMaterial();
    return createWallMaterialFromValue(material.value);
  }

  function createWallMaterialFromValue(value) {
    const texture = createWallTexture(getWallMaterialByValue(value));
    texture.repeat.set(2, 1);
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    return new THREE.MeshStandardMaterial({
      color: 0xffffff,
      map: texture,
      roughness: 0.72,
    });
  }

  function createWallSideMaterial(value) {
    const material = getWallMaterialByValue(value);
    const texture = createWallTexture(material);
    texture.repeat.set(3, 1);
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    return new THREE.MeshStandardMaterial({
      color: 0xffffff,
      map: texture,
      roughness: 0.72,
    });
  }

  function createWallCoreMaterial() {
    return new THREE.MeshStandardMaterial({
      color: DEFAULT_WALL_COLOR,
      roughness: 0.82,
    });
  }

  function createWallTexture(material) {
    const canvas = createWallPatternCanvas(material, 192, 192);
    const texture = new THREE.CanvasTexture(canvas);
    texture.needsUpdate = true;
    return texture;
  }

  function createWallPatternCanvas(material, width, height) {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    const base = `#${material.color.toString(16).padStart(6, "0")}`;
    ctx.fillStyle = base;
    ctx.fillRect(0, 0, width, height);
    ctx.strokeStyle = "rgba(255,255,255,0.24)";
    ctx.lineWidth = 1;
    for (let y = 12; y < height; y += 24) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y + 6);
      ctx.stroke();
    }
    ctx.strokeStyle = "rgba(15,23,42,0.08)";
    for (let x = 0; x < width; x += 18) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x + 10, height);
      ctx.stroke();
    }
    return canvas;
  }

  function applyWallMaterial() {
    const active = getActiveWallMaterial();
    const walls = state.selectedRoomId ? getWallsForRoom(state.selectedRoomId) : state.wallObjects;
    walls.forEach((wall) => {
      if (wall.material) {
        disposeMaterial(wall.material);
        wall.material = createWallMaterialFromValue(state.activeWallMaterial);
      }
      wall.userData.wallMaterial = state.activeWallMaterial;
      wall.userData.wallpaperApplied = true;
    });
    state.roomObjects.forEach((room) => {
      if (!state.selectedRoomId || room.userData.id === state.selectedRoomId) {
        room.userData.wallMaterial = state.activeWallMaterial;
      }
    });
    clearVisualization();
    updateSceneStatus("벽지 적용", `${state.selectedRoomId ? "선택한 방을" : "전체 방을"} ${active.label} 벽지로 변경했습니다.`);
  }

  function getWallsForRoom(roomId) {
    const room = state.roomObjects.find((entry) => entry.userData.id === roomId);
    if (!room || !state.floorBounds) return [];
    return state.wallObjects.filter((wall) => wallTouchesRoom(wall, room));
  }

  function wallTouchesRoom(wall, room) {
    const width = room.userData.maskWidth;
    const height = room.userData.maskHeight;
    const footprint = getPlanFootprint(wall);
    return footprint.some((point) => {
      const pixel = scenePointToRoomPixel(point.x, point.z, width, height, state.floorBounds);
      for (let dy = -3; dy <= 3; dy += 1) {
        for (let dx = -3; dx <= 3; dx += 1) {
          const x = pixel.x + dx;
          const y = pixel.y + dy;
          if (x < 0 || y < 0 || x >= width || y >= height) continue;
          if (room.userData.mask[y * width + x]) return true;
        }
      }
      return false;
    });
  }

  function renderCatalog() {
    const listEl = document.getElementById("furniture-list");
    const countEl = document.getElementById("catalog-count");
    if (!listEl) return;
    if (state.activeCatalogSection !== "furniture") {
      if (countEl) countEl.textContent = state.activeCatalogSection === "floor" ? `${FLOOR_MATERIALS.length} finishes` : `${WALL_MATERIALS.length} finishes`;
      return;
    }
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
    return state.catalogItems.filter((item) => {
      const colorOk = state.activeColor === "all" || normalizeColor(item.color) === state.activeColor;
      const categoryOk = furnitureCategoryMatches(item, state.activeFurnitureCategory);
      return colorOk && categoryOk;
    });
  }

  function furnitureCategoryMatches(item, filterValue) {
    if (filterValue === "all") return true;
    const filter = FURNITURE_CATEGORY_FILTERS.find((entry) => entry.value === filterValue);
    if (!filter) return true;
    const text = `${item.category || ""} ${item.product_name || ""} ${item.name || ""} ${item.size || ""}`.toLowerCase();
    return filter.keywords.some((keyword) => text.includes(keyword.toLowerCase()));
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

  async function spawnFurniture(item, options) {
    options = options || {};
    clearVisualization();
    const pivot = await createGLBFurniturePivot(item) || create2DFurniturePivot(item);
    addPlacedFurniturePivot(pivot, options);
  }

  function addPlacedFurniturePivot(pivot, options) {
    pivot.position.set(options.x || 0, pivot.userData.centerY || 0, options.z || 0);
    pivot.rotation.y = options.rot || 0;
    state.scene.add(pivot);
    state.furnitureMeshes.push(pivot);

    const constrained = applyWallMagnetAndBounds(pivot, pivot.position);
    pivot.position.copy(constrained.position);
    if (!getBlockedPlacementAt(pivot, pivot.position)) {
      pivot.userData.lastSafePosition = pivot.position.clone();
    }

    if (!state.suppressAutoSelect && options.select !== false) {
      selectFurniture(pivot, document.getElementById("furniture-toolbar"));
    }
    updateSafetyState();
    updateEstimate();
  }

  async function createGLBFurniturePivot(item) {
    const paths = [item.model_path, item.modelPath, resolveModelPath(item), "/static/models/sofa/gray_sofa.glb", "/static/models/sofa/grey_sofa.glb"].filter(Boolean);
    const gltf = await loadGltfWithFallback(paths);
    if (!gltf) return null;

    const model = gltf.scene;
    const box = new THREE.Box3().setFromObject(model);
    const size = box.getSize(new THREE.Vector3());
    const targetW = Math.max((Number(item.width) || 150) * 0.01, 0.18);
    const targetH = Math.max((Number(item.height) || 80) * 0.01, 0.18);
    const targetD = Math.max((Number(item.depth) || 80) * 0.01, 0.18);
    model.scale.set(targetW / Math.max(size.x, 0.001), targetH / Math.max(size.y, 0.001), targetD / Math.max(size.z, 0.001));
    return createCenteredFurniturePivot(model, item, "2d-glb");
  }

  function create2DFurniturePivot(item) {
    const width = Math.max((Number(item.width) || 150) * 0.01, 0.18);
    const depth = Math.max((Number(item.depth) || 80) * 0.01, 0.18);
    const height = 0.045;
    const color = furniturePlanColor(item);
    const pivot = new THREE.Group();
    const body = new THREE.Mesh(
      new THREE.BoxGeometry(width, height, depth),
      new THREE.MeshStandardMaterial({ color, roughness: 0.78, transparent: true, opacity: 0.78 })
    );
    body.position.y = height / 2;
    body.castShadow = false;
    body.receiveShadow = true;

    const outline = new THREE.LineSegments(
      new THREE.EdgesGeometry(body.geometry),
      new THREE.LineBasicMaterial({ color: 0x172f5b })
    );
    outline.position.copy(body.position);
    pivot.add(body, outline);
    pivot.name = item.product_name || "furniture";
    pivot.userData = {
      type: "furniture",
      renderMode: "2d",
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
      centerY: 0,
    };
    return pivot;
  }

  function furniturePlanColor(item) {
    return furnitureColorHex(item.color);
  }

  function furnitureColorHex(color) {
    switch (normalizeColor(color)) {
      case "black": return 0x1f2937;
      case "brown": return 0x8b5e3c;
      case "blue": return 0x2159b7;
      case "white": return 0xf8fafc;
      default: return 0x9ca3af;
    }
  }

  function applyFurnitureColorToModel(root, color) {
    const hex = furnitureColorHex(color);
    root.traverse((obj) => {
      if (!obj.isMesh || !obj.material) return;
      obj.material = Array.isArray(obj.material)
        ? obj.material.map((material) => cloneFurnitureMaterial(material, hex))
        : cloneFurnitureMaterial(obj.material, hex);
    });
  }

  function cloneFurnitureMaterial(material, color) {
    const cloned = material.clone();
    if (cloned.color) cloned.color.setHex(color);
    cloned.needsUpdate = true;
    return cloned;
  }

  function createCenteredFurniturePivot(model, item, renderMode) {
    const scaledBox = new THREE.Box3().setFromObject(model);
    const center = scaledBox.getCenter(new THREE.Vector3());
    const minY = scaledBox.min.y;
    const pivot = new THREE.Group();
    model.position.sub(center);
    pivot.add(model);
    applyFurnitureColorToModel(pivot, item.color);
    pivot.name = item.product_name || "furniture";
    pivot.userData = {
      type: "furniture",
      renderMode: renderMode || "3d",
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
    let box = getPlanBox(model);
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

    model.position.copy(position);
    box = getPlanBox(model);
    const wallSnap = findNearestWallSnap(box);
    if (wallSnap) {
      position.x += wallSnap.dx;
      position.z += wallSnap.dz;
      messages.push("벽면 자석 스냅");
    }

    model.position.copy(original);
    return { position, message: messages.join(", ") };
  }

  function findNearestWallSnap(modelBox) {
    let best = null;
    state.wallObjects.forEach((wall) => {
      const wallBox = getPlanBox(wall);
      const zOverlap = rangesOverlap(modelBox.minZ, modelBox.maxZ, wallBox.minZ, wallBox.maxZ, WALL_MAGNET_OVERLAP_MARGIN);
      const xOverlap = rangesOverlap(modelBox.minX, modelBox.maxX, wallBox.minX, wallBox.maxX, WALL_MAGNET_OVERLAP_MARGIN);
      considerWallSnap(wallBox.minX - modelBox.maxX, wallBox.minX - WALL_BUFFER - modelBox.maxX, 0, zOverlap);
      considerWallSnap(modelBox.minX - wallBox.maxX, wallBox.maxX + WALL_BUFFER - modelBox.minX, 0, zOverlap);
      considerWallSnap(wallBox.minZ - modelBox.maxZ, 0, wallBox.minZ - WALL_BUFFER - modelBox.maxZ, xOverlap);
      considerWallSnap(modelBox.minZ - wallBox.maxZ, 0, wallBox.maxZ + WALL_BUFFER - modelBox.minZ, xOverlap);
    });
    return best;

    function considerWallSnap(gap, dx, dz, overlapsAlongWall) {
      if (!overlapsAlongWall || gap < 0 || gap > WALL_MAGNET_DISTANCE) return;
      if (!best || gap < best.gap) best = { gap, dx, dz };
    }
  }

  function rangesOverlap(aMin, aMax, bMin, bMax, margin) {
    const extra = margin || 0;
    return Math.min(aMax + extra, bMax + extra) - Math.max(aMin - extra, bMin - extra) > 0;
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
    if (boxOutsideImageFloor(box)) return "타일 바닥 영역 밖";
    const modelFootprint = getPlanFootprint(model);
    for (const wall of state.wallObjects) {
      if (footprintsIntersect(modelFootprint, getPlanFootprint(wall))) return "벡터 벽체";
    }
    return "";
  }

  function boxIntersectsImageWall(box) {
    if (!state.imageWallMask || !state.floorBounds) return false;
    const mask = state.imageWallMask;
    const bounds = state.floorBounds;
    const pixelBox = planBoxToPixelBox(box, mask, bounds);
    const area = Math.max((pixelBox.maxX - pixelBox.minX + 1) * (pixelBox.maxY - pixelBox.minY + 1), 1);
    const hits = sumMaskArea(mask.integral, mask.width, pixelBox.minX, pixelBox.minY, pixelBox.maxX, pixelBox.maxY);
    return hits >= 3 && hits / area >= IMAGE_WALL_HIT_RATIO;
  }

  function boxOutsideImageFloor(box) {
    if (!state.imageFloorMask || !state.floorBounds) return false;
    const mask = state.imageFloorMask;
    const bounds = state.floorBounds;
    const center = planPointToPixel((box.minX + box.maxX) / 2, (box.minZ + box.maxZ) / 2, mask, bounds);
    if (!isNearbyFloorPixel(mask, center.x, center.y, 2)) return true;

    const insetX = Math.max((box.maxX - box.minX) * 0.08, 0.02);
    const insetZ = Math.max((box.maxZ - box.minZ) * 0.08, 0.02);
    const minX = Math.min(box.minX + insetX, (box.minX + box.maxX) / 2);
    const maxX = Math.max(box.maxX - insetX, (box.minX + box.maxX) / 2);
    const minZ = Math.min(box.minZ + insetZ, (box.minZ + box.maxZ) / 2);
    const maxZ = Math.max(box.maxZ - insetZ, (box.minZ + box.maxZ) / 2);

    let floorSamples = 0;
    let totalSamples = 0;
    for (let ix = 0; ix < IMAGE_FLOOR_SAMPLE_GRID; ix += 1) {
      const x = minX + ((maxX - minX) * ix) / (IMAGE_FLOOR_SAMPLE_GRID - 1);
      for (let iz = 0; iz < IMAGE_FLOOR_SAMPLE_GRID; iz += 1) {
        const z = minZ + ((maxZ - minZ) * iz) / (IMAGE_FLOOR_SAMPLE_GRID - 1);
        const pixel = planPointToPixel(x, z, mask, bounds);
        totalSamples += 1;
        if (isFloorPixel(mask, pixel.x, pixel.y)) floorSamples += 1;
      }
    }

    return floorSamples / Math.max(totalSamples, 1) < IMAGE_FLOOR_REQUIRED_RATIO;
  }

  function planBoxToPixelBox(box, mask, bounds) {
    return {
      minX: clamp(Math.floor(((box.minX - bounds.minX) / bounds.width) * mask.width), 0, mask.width - 1),
      maxX: clamp(Math.ceil(((box.maxX - bounds.minX) / bounds.width) * mask.width), 0, mask.width - 1),
      minY: clamp(Math.floor(((box.minZ - bounds.minZ) / bounds.depth) * mask.height), 0, mask.height - 1),
      maxY: clamp(Math.ceil(((box.maxZ - bounds.minZ) / bounds.depth) * mask.height), 0, mask.height - 1),
    };
  }

  function planPointToPixel(x, z, mask, bounds) {
    return {
      x: clamp(Math.round(((x - bounds.minX) / bounds.width) * (mask.width - 1)), 0, mask.width - 1),
      y: clamp(Math.round(((z - bounds.minZ) / bounds.depth) * (mask.height - 1)), 0, mask.height - 1),
    };
  }

  function isFloorPixel(mask, x, y) {
    return Boolean(mask.mask[y * mask.width + x]);
  }

  function isNearbyFloorPixel(mask, x, y, radius) {
    for (let dy = -radius; dy <= radius; dy += 1) {
      for (let dx = -radius; dx <= radius; dx += 1) {
        const nx = x + dx;
        const ny = y + dy;
        if (nx < 0 || ny < 0 || nx >= mask.width || ny >= mask.height) continue;
        if (isFloorPixel(mask, nx, ny)) return true;
      }
    }
    return false;
  }

  function sumMaskArea(integral, width, minX, minY, maxX, maxY) {
    const stride = width + 1;
    const x1 = minX;
    const y1 = minY;
    const x2 = maxX + 1;
    const y2 = maxY + 1;
    return integral[y2 * stride + x2]
      - integral[y1 * stride + x2]
      - integral[y2 * stride + x1]
      + integral[y1 * stride + x1];
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
        if (footprintsIntersect(getPlanFootprint(a), getPlanFootprint(b))) {
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
    return a.minX < b.maxX - COLLISION_EPSILON
      && a.maxX > b.minX + COLLISION_EPSILON
      && a.minZ < b.maxZ - COLLISION_EPSILON
      && a.maxZ > b.minZ + COLLISION_EPSILON;
  }

  function getPlanFootprint(object) {
    const dims = getFootprintDimensions(object);
    if (!dims) {
      const box = getPlanBox(object);
      return [
        { x: box.minX, z: box.minZ },
        { x: box.maxX, z: box.minZ },
        { x: box.maxX, z: box.maxZ },
        { x: box.minX, z: box.maxZ },
      ];
    }

    const halfW = dims.width / 2;
    const halfD = dims.depth / 2;
    const cos = Math.cos(object.rotation.y || 0);
    const sin = Math.sin(object.rotation.y || 0);
    return [
      { x: -halfW, z: -halfD },
      { x: halfW, z: -halfD },
      { x: halfW, z: halfD },
      { x: -halfW, z: halfD },
    ].map((point) => ({
      x: object.position.x + point.x * cos + point.z * sin,
      z: object.position.z - point.x * sin + point.z * cos,
    }));
  }

  function getFootprintDimensions(object) {
    if (object.userData && object.userData.type === "furniture" && object.userData.dimensions) {
      return {
        width: Math.max(Number(object.userData.dimensions.width) * 0.01, 0.01),
        depth: Math.max(Number(object.userData.dimensions.depth) * 0.01, 0.01),
      };
    }
    if (object.userData && object.userData.type === "wall" && object.geometry && object.geometry.parameters) {
      return {
        width: Math.max(Number(object.geometry.parameters.width), 0.01),
        depth: Math.max(Number(object.geometry.parameters.depth), 0.01),
      };
    }
    return null;
  }

  function footprintsIntersect(a, b) {
    if (!a || !b) return false;
    return !hasSeparatingAxis(a, b) && !hasSeparatingAxis(b, a);
  }

  function hasSeparatingAxis(a, b) {
    for (let i = 0; i < a.length; i += 1) {
      const current = a[i];
      const next = a[(i + 1) % a.length];
      const edge = { x: next.x - current.x, z: next.z - current.z };
      const axis = { x: -edge.z, z: edge.x };
      const projA = projectFootprint(a, axis);
      const projB = projectFootprint(b, axis);
      if (projA.max <= projB.min + COLLISION_EPSILON || projB.max <= projA.min + COLLISION_EPSILON) {
        return true;
      }
    }
    return false;
  }

  function projectFootprint(points, axis) {
    let min = Infinity;
    let max = -Infinity;
    points.forEach((point) => {
      const value = point.x * axis.x + point.z * axis.z;
      min = Math.min(min, value);
      max = Math.max(max, value);
    });
    return { min, max };
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

  async function acceptLayout() {
    await show3DLayout();
  }

  async function show3DLayout() {
    clearSelectionHighlight();
    state.selectedFurniture = null;
    state.selectedWall = null;
    const toolbar = document.getElementById("furniture-toolbar");
    if (toolbar) toolbar.style.display = "none";
    clearVisualization();
    state.renderMode = "3d";
    updateRenderModeButtons();
    const bounds = calculateLayoutBounds();
    const visualization = new THREE.Group();
    visualization.name = "acceptedLayoutVisualization";
    addRenderedRoomFloors(visualization);
    addRenderedWalls(visualization);
    state.scene.add(visualization);
    state.visualizationGroup = visualization;
    setPlanningFurnitureVisible(false);
    setPlanningWallsVisible(false);
    updateSceneStatus("3D 렌더링 중", "배치한 가구를 3D 모델로 변환하고 있습니다.");
    await addRenderedFurnitureModels(visualization);
    focusCameraOnPlanContent(bounds.width, bounds.depth, bounds.center);
    updateSafetyState();
    updateSceneStatus("3D 렌더링 완료", "벽체, 바닥, 배치 자재, 견적 상태가 갱신되었습니다.");
  }

  function show2DLayout() {
    clearSelectionHighlight();
    state.selectedFurniture = null;
    state.selectedWall = null;
    const toolbar = document.getElementById("furniture-toolbar");
    if (toolbar) toolbar.style.display = "none";
    clearVisualization();
    state.renderMode = "2d";
    updateRenderModeButtons();
    const bounds = calculateLayoutBounds();
    focusCameraOnPlanContent(bounds.width, bounds.depth, bounds.center);
    updateSafetyState();
    updateSceneStatus("2D 렌더링 완료", "평면도 위에서 벽과 GLB 가구를 다시 편집할 수 있습니다.");
  }

  function updateRenderModeButtons() {
    const btn2d = document.getElementById("btn-render-2d");
    const btn3d = document.getElementById("btn-accept");
    if (btn2d) btn2d.classList.toggle("active", state.renderMode === "2d");
    if (btn3d) btn3d.classList.toggle("active", state.renderMode === "3d");
  }

  async function addRenderedFurnitureModels(group) {
    const jobs = state.furnitureMeshes.map((model) => addRenderedFurnitureModel(group, model));
    await Promise.allSettled(jobs);
  }

  async function addRenderedFurnitureModel(group, planModel) {
    const item = exportCatalogLikeItem(planModel);
    const paths = [item.model_path, "/static/models/sofa/gray_sofa.glb", "/static/models/sofa/grey_sofa.glb"].filter(Boolean);
    const gltf = await loadGltfWithFallback(paths);
    if (!gltf) return;

    const model = gltf.scene;
    const box = new THREE.Box3().setFromObject(model);
    const size = box.getSize(new THREE.Vector3());
    const targetW = Math.max((Number(item.width) || 150) * 0.01, 0.18);
    const targetH = Math.max((Number(item.height) || 80) * 0.01, 0.18);
    const targetD = Math.max((Number(item.depth) || 80) * 0.01, 0.18);
    model.scale.set(targetW / Math.max(size.x, 0.001), targetH / Math.max(size.y, 0.001), targetD / Math.max(size.z, 0.001));

    const pivot = createCenteredFurniturePivot(model, item);
    pivot.position.set(planModel.position.x, pivot.userData.centerY || 0, planModel.position.z);
    pivot.rotation.y = planModel.rotation.y;
    group.add(pivot);
  }

  function loadGltfWithFallback(paths, index) {
    index = index || 0;
    const path = paths[index];
    if (!path) return Promise.resolve(null);
    return new Promise((resolve) => {
      gltfLoader.load(
        path,
        (gltf) => resolve(gltf),
        undefined,
        () => resolve(loadGltfWithFallback(paths, index + 1))
      );
    });
  }

  function setPlanningFurnitureVisible(visible) {
    state.furnitureMeshes.forEach((model) => {
      model.visible = visible;
    });
  }

  function setPlanningWallsVisible(visible) {
    state.wallObjects.forEach((wall) => {
      wall.visible = visible;
    });
  }

  function addRenderedWalls(group) {
    if (state.imageWallMask && state.floorBounds) {
      const renderedMask = createRenderedWallMaskMesh(state.imageWallMask, state.floorBounds, state.wallRenderRects);
      if (renderedMask) {
        group.add(renderedMask);
        return;
      }
    }

    state.wallObjects.forEach((wall) => {
      const params = wall.geometry && wall.geometry.parameters;
      if (!params) return;
      const height = (wall.userData.renderHeight || 2.4) * RENDERED_WALL_HEIGHT_RATIO;
      const rendered = createWall(params.width, height, params.depth, wall.userData.wallMaterial || state.activeWallMaterial, wall.userData.wallpaperApplied);
      rendered.position.set(wall.position.x, height / 2, wall.position.z);
      rendered.quaternion.copy(wall.quaternion);
      group.add(rendered);
    });
  }

  function createRenderedWallMaskMesh(maskData, bounds, rectData) {
    const mask = maskData.mask;
    const width = maskData.width;
    const height = maskData.height;
    if (!mask || !width || !height) return null;

    const wallHeight = 2.4 * RENDERED_WALL_HEIGHT_RATIO;
    const positions = [];
    const normals = [];
    const indices = [];
    const groups = [];
    const cellW = bounds.width / width;
    const cellD = bounds.depth / height;

    if (rectData && rectData.width === width && rectData.height === height) {
      rectData.rects.forEach((rect) => {
        addBoxToGeometryBuffers(
          positions,
          normals,
          indices,
          groups,
          bounds.minX + rect.x * cellW,
          bounds.minX + (rect.x + rect.width) * cellW,
          0,
          wallHeight,
          bounds.minZ + rect.y * cellD,
          bounds.minZ + (rect.y + rect.height) * cellD
        );
      });
    } else {
      for (let y = 0; y < height; y += 1) {
        let x = 0;
        while (x < width) {
          while (x < width && !mask[y * width + x]) x += 1;
          if (x >= width) break;
          const startX = x;
          while (x < width && mask[y * width + x]) x += 1;
          const endX = x;
          addBoxToGeometryBuffers(
            positions,
            normals,
            indices,
            groups,
            bounds.minX + startX * cellW,
            bounds.minX + endX * cellW,
            0,
            wallHeight,
            bounds.minZ + y * cellD,
            bounds.minZ + (y + 1) * cellD
          );
        }
      }
    }

    if (positions.length === 0) return null;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute("normal", new THREE.Float32BufferAttribute(normals, 3));
    geometry.setIndex(indices);
    groups.forEach((group) => geometry.addGroup(group.start, group.count, group.materialIndex));
    geometry.computeBoundingSphere();
    const mesh = new THREE.Mesh(geometry, [
      createWallCoreMaterial(),
      createWallSideMaterial(state.activeWallMaterial),
    ]);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData.type = "renderedWallMask";
    return mesh;
  }

  function addBoxToGeometryBuffers(positions, normals, indices, groups, minX, maxX, minY, maxY, minZ, maxZ) {
    addFace(positions, normals, indices, [
      [maxX, minY, minZ], [maxX, maxY, minZ], [maxX, maxY, maxZ], [maxX, minY, maxZ],
    ], [1, 0, 0], groups, 1);
    addFace(positions, normals, indices, [
      [minX, minY, maxZ], [minX, maxY, maxZ], [minX, maxY, minZ], [minX, minY, minZ],
    ], [-1, 0, 0], groups, 1);
    addFace(positions, normals, indices, [
      [minX, maxY, maxZ], [maxX, maxY, maxZ], [maxX, maxY, minZ], [minX, maxY, minZ],
    ], [0, 1, 0], groups, 0);
    addFace(positions, normals, indices, [
      [minX, minY, minZ], [maxX, minY, minZ], [maxX, minY, maxZ], [minX, minY, maxZ],
    ], [0, -1, 0], groups, 0);
    addFace(positions, normals, indices, [
      [minX, minY, maxZ], [maxX, minY, maxZ], [maxX, maxY, maxZ], [minX, maxY, maxZ],
    ], [0, 0, 1], groups, 1);
    addFace(positions, normals, indices, [
      [maxX, minY, minZ], [minX, minY, minZ], [minX, maxY, minZ], [maxX, maxY, minZ],
    ], [0, 0, -1], groups, 1);
  }

  function addFace(positions, normals, indices, corners, normal, groups, materialIndex) {
    const base = positions.length / 3;
    const indexStart = indices.length;
    corners.forEach((corner) => {
      positions.push(corner[0], corner[1], corner[2]);
      normals.push(normal[0], normal[1], normal[2]);
    });
    indices.push(base, base + 1, base + 2, base, base + 2, base + 3);
    groups.push({ start: indexStart, count: 6, materialIndex });
  }

  function calculateLayoutBounds() {
    const bounds = getVisiblePlanBounds() || state.floorBounds || { minX: -4, maxX: 4, minZ: -3, maxZ: 3 };
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

  function createWall(length, height, thickness, wallpaperValue, wallpaperApplied) {
    const core = createWallCoreMaterial();
    const side = wallpaperApplied ? createWallSideMaterial(wallpaperValue) : createWallCoreMaterial();
    const wall = new THREE.Mesh(new THREE.BoxGeometry(length, height, thickness), [
      core,
      core.clone(),
      core.clone(),
      core.clone(),
      side,
      side.clone(),
    ]);
    wall.receiveShadow = true;
    wall.castShadow = true;
    return wall;
  }

  function addRenderedRoomFloors(group) {
    state.roomObjects.forEach((room) => {
      const clone = room.clone();
      clone.material = room.material.clone();
      if (room.material.map) clone.material.map = room.material.map.clone();
      clone.position.y = -0.006;
      group.add(clone);
    });
  }

  function clearVisualization() {
    if (!state.visualizationGroup) return;
    state.scene.remove(state.visualizationGroup);
    disposeObject3D(state.visualizationGroup);
    state.visualizationGroup = null;
    setPlanningFurnitureVisible(true);
    setPlanningWallsVisible(true);
    state.renderMode = "2d";
    updateRenderModeButtons();
  }

  function saveLayout() {
    const payload = {
      savedAt: new Date().toISOString(),
      activePattern: state.activePattern,
      activeFloorMaterial: state.activeFloorMaterial,
      activeWallMaterial: state.activeWallMaterial,
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
      state.activeFloorMaterial = payload.activeFloorMaterial || state.activeFloorMaterial;
      state.activeWallMaterial = payload.activeWallMaterial || state.activeWallMaterial;
      applyFloorMaterial();
      applyWallMaterial();
      renderFloorMaterials();
      renderWallMaterials();
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
      if (obj.material) disposeMaterial(obj.material);
    });
  }

  function disposeMaterial(materialOrMaterials) {
    const materials = Array.isArray(materialOrMaterials) ? materialOrMaterials : [materialOrMaterials];
    materials.forEach((material) => {
      if (!material) return;
      if (material.map) material.map.dispose();
      material.dispose();
    });
  }

  function focusCameraOnArea(width, depth, centerOverride) {
    const center = centerOverride || new THREE.Vector3(width / 2, 0, depth / 2);
    const distance = Math.max(width, depth) * 1.15 || 5;
    state.camera.position.set(center.x + distance, distance, center.z + distance);
    state.controls.target.copy(center);
    state.controls.update();
  }

  function focusCameraOnPlanContent(fallbackWidth, fallbackDepth, fallbackCenter) {
    const bounds = getVisiblePlanBounds();
    if (!bounds) {
      focusCameraOnArea(fallbackWidth, fallbackDepth, fallbackCenter);
      return;
    }
    const paddedWidth = Math.max(bounds.width * 1.18, 1);
    const paddedDepth = Math.max(bounds.depth * 1.18, 1);
    focusCameraOnArea(paddedWidth, paddedDepth, bounds.center);
  }

  function getVisiblePlanBounds() {
    const targets = [...state.roomObjects, ...state.wallObjects, ...state.baseFloorObjects].filter((object) => object && object.parent);
    if (targets.length === 0) return null;

    const box = new THREE.Box3();
    targets.forEach((object) => box.expandByObject(object));
    if (!Number.isFinite(box.min.x) || !Number.isFinite(box.max.x) || box.isEmpty()) return null;

    const width = Math.max(box.max.x - box.min.x, 0.001);
    const depth = Math.max(box.max.z - box.min.z, 0.001);
    return {
      minX: box.min.x,
      maxX: box.max.x,
      minZ: box.min.z,
      maxZ: box.max.z,
      width,
      depth,
      center: new THREE.Vector3((box.min.x + box.max.x) / 2, 0, (box.min.z + box.max.z) / 2),
    };
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
