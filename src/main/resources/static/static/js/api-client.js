(function (global) {
  "use strict";

  async function requestJson(url, options, timeoutMs) {
    const controller = new AbortController();
    const timeout = global.setTimeout(() => controller.abort(), timeoutMs || 30_000);
    try {
      const response = await global.fetch(url, { ...(options || {}), signal: controller.signal });
      if (!response.ok) {
        const error = new Error(await readErrorMessage(response) || `요청 실패 (${response.status})`);
        error.status = response.status;
        throw error;
      }
      return response.json();
    } catch (error) {
      if (error && error.name === "AbortError") {
        throw new Error("서버 응답 시간이 너무 오래 걸립니다. 잠시 후 다시 시도해주세요.");
      }
      throw error;
    } finally {
      global.clearTimeout(timeout);
    }
  }

  async function readErrorMessage(response) {
    const text = await response.text();
    if (!text) return "";
    try {
      const data = JSON.parse(text);
      return data.message || data.error || text;
    } catch (_error) {
      return text;
    }
  }

  function getJson(url) {
    return requestJson(url, { method: "GET" }, 30_000);
  }

  function vectorizeFloorPlan(file) {
    const form = new FormData();
    form.append("file", file);
    return requestJson("/api/floorplans/vectorize", { method: "POST", body: form }, 190_000);
  }

  global.DuoApi = Object.freeze({ getJson, vectorizeFloorPlan });
})(window);
