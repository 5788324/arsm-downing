(function (root) {
  "use strict";

  const RJ_PATTERN = /(?:^|[^A-Z0-9])RJ?(\d{6,8})(?=$|[^0-9])/i;
  const STATE_PRESENTATION = Object.freeze({
    in_library: { label: "已入库", tone: "success", action: "open-library" },
    not_in_library: { label: "未入库", tone: "neutral", action: "download" },
    queued: { label: "已排队", tone: "pending", action: "open-download" },
    downloading: { label: "下载中", tone: "pending", action: "open-download" },
    paused: { label: "已暂停", tone: "warning", action: "open-download" },
    failed: { label: "下载失败", tone: "danger", action: "open-download" },
    cancelled: { label: "已取消", tone: "warning", action: "open-download" },
    completed: { label: "已下载", tone: "success", action: "open-library" },
    disconnected: { label: "ARSM 未连接", tone: "muted", action: "settings" },
    loading: { label: "查询中", tone: "muted", action: "none" }
  });

  function normalizeRjId(value) {
    const match = String(value || "").trim().match(RJ_PATTERN);
    if (!match) {
      return "";
    }
    return "RJ" + String(Number(match[1])).padStart(8, "0");
  }

  function extractRjId(value) {
    const decoded = (() => {
      try {
        return decodeURIComponent(String(value || ""));
      } catch (_error) {
        return String(value || "");
      }
    })();
    return normalizeRjId(decoded);
  }

  function presentationFor(state) {
    return STATE_PRESENTATION[state] || STATE_PRESENTATION.disconnected;
  }

  const api = Object.freeze({
    extractRjId,
    normalizeRjId,
    presentationFor,
    states: STATE_PRESENTATION
  });

  root.ARSMExtension = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
