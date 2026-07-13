(function (global) {
  "use strict";

  function createFrameThrottle(callback) {
    let frameId = 0;
    let latestArgs = [];
    return function throttled() {
      latestArgs = Array.from(arguments);
      if (frameId) return;
      frameId = global.requestAnimationFrame(() => {
        frameId = 0;
        callback.apply(null, latestArgs);
      });
    };
  }

  function cloneMaterial(material) {
    if (!material) return material;
    const clone = material.clone();
    Object.keys(clone).forEach((key) => {
      const value = clone[key];
      if (value && value.isTexture) clone[key] = value.clone();
    });
    return clone;
  }

  function cloneGltf(source) {
    const scene = source.scene.clone(true);
    scene.traverse((object) => {
      if (object.geometry) object.geometry = object.geometry.clone();
      if (Array.isArray(object.material)) {
        object.material = object.material.map(cloneMaterial);
      } else if (object.material) {
        object.material = cloneMaterial(object.material);
      }
    });
    return {
      ...source,
      scene,
      animations: Array.isArray(source.animations) ? source.animations.slice() : [],
    };
  }

  function disposeScene(scene) {
    if (!scene || !scene.traverse) return;
    scene.traverse((object) => {
      if (object.geometry && object.geometry.dispose) object.geometry.dispose();
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      materials.forEach((material) => {
        if (!material) return;
        Object.keys(material).forEach((key) => {
          const value = material[key];
          if (value && value.isTexture && value.dispose) value.dispose();
        });
        if (material.dispose) material.dispose();
      });
    });
  }

  function createGltfCache(loader, maxLoadedModels) {
    const entries = new Map();
    const loadedLimit = Math.max(1, Number(maxLoadedModels) || 12);

    function pruneLoaded(exceptPath) {
      const loaded = Array.from(entries.entries())
        .filter((entry) => entry[1].source && entry[0] !== exceptPath)
        .sort((a, b) => a[1].lastUsed - b[1].lastUsed);
      while (loaded.length >= loadedLimit) {
        const [path, entry] = loaded.shift();
        entries.delete(path);
        disposeScene(entry.source.scene);
      }
    }

    function loadSource(path) {
      const cached = entries.get(path);
      if (cached) {
        cached.lastUsed = Date.now();
        return cached.promise;
      }
      const entry = { source: null, lastUsed: Date.now(), promise: null };
      entry.promise = new Promise((resolve) => {
        loader.load(path, resolve, undefined, () => resolve(null));
      }).then((source) => {
        entry.source = source && source.scene ? source : null;
        entry.lastUsed = Date.now();
        if (entry.source) pruneLoaded(path);
        return entry.source;
      });
      entries.set(path, entry);
      return entry.promise;
    }

    async function loadFirst(paths) {
      for (const path of paths || []) {
        const source = await loadSource(path);
        if (source && source.scene) return cloneGltf(source);
      }
      return null;
    }

    return {
      loadFirst,
      get size() { return entries.size; },
      get loadedModelCount() {
        return Array.from(entries.values()).filter((entry) => entry.source).length;
      },
    };
  }

  global.DuoPerformance = Object.freeze({
    createFrameThrottle,
    createGltfCache,
  });
})(window);
