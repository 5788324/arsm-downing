(function () {
  "use strict";

  if (globalThis.__arsmExtensionLoaded) {
    return;
  }
  globalThis.__arsmExtensionLoaded = true;

  const api = globalThis.ARSMExtension;
  const controlsByRj = new Map();
  const stateByRj = new Map();
  const cardControls = new WeakMap();
  const pendingAnchors = new Set();
  const pendingIds = new Set();
  const enqueuing = new Set();
  const WORK_LINK = "a[href*='/work/'], a[href*='/works/']";
  const BATCH_SIZE = 200;
  let detailControls = null;
  let pathname = location.pathname;
  let needsCleanup = false;
  let scanTimer = 0;
  let pollTimer = 0;
  let pollDue = 0;
  let refreshInFlight = null;

  function send(message) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage(message, (response) => {
        if (chrome.runtime.lastError) {
          resolve({
            ok: false,
            error: { code: "disconnected", message: "ARSM 扩展连接不可用" }
          });
          return;
        }
        resolve(response || {
          ok: false,
          error: { code: "empty_response", message: "扩展没有返回结果" }
        });
      });
    });
  }

  function findWorkCard(anchor) {
    return anchor.closest(
      "article, li, .q-card, [data-work-id], [class*='work-card'], [class*='WorkCard']"
    );
  }

  function findSalesPlacement(card) {
    const candidates = Array.from(card.querySelectorAll("span, div, p, small"));
    const sales = candidates.find((element) => {
      if (element.children.length > 2) {
        return false;
      }
      const text = (element.textContent || "").trim();
      return /(?:销量|販売数|DL数|Sales)\s*[:：]?\s*[\d,]+/i.test(text);
    });
    if (sales) {
      return sales.parentElement || sales;
    }
    return card.querySelector(
      "[class*='sales'], [class*='meta'], [class*='info'], .q-card__actions"
    ) || card;
  }

  function createControls(rjId, detail) {
    const wrapper = document.createElement("span");
    wrapper.className = "arsm-extension-controls" +
      (detail ? " arsm-extension-controls--detail" : "");
    wrapper.dataset.arsmRjId = rjId;

    const badge = document.createElement("span");
    badge.className = "arsm-extension-badge";
    badge.setAttribute("role", "status");
    badge.setAttribute("aria-live", "polite");

    const button = document.createElement("button");
    button.className = "arsm-extension-button";
    button.type = "button";

    for (const eventName of ["click", "mousedown", "mouseup"]) {
      wrapper.addEventListener(eventName, (event) => {
        event.stopPropagation();
      });
    }
    button.addEventListener("click", () => handleAction(rjId, button));

    const subtitleBadge = document.createElement("span");
    subtitleBadge.className = "arsm-extension-badge arsm-extension-subtitle";
    subtitleBadge.textContent = "有字幕";
    subtitleBadge.title = "本机字幕库中有该作品的字幕包";
    subtitleBadge.hidden = true;

    wrapper.append(badge, subtitleBadge, button);
    const existing = controlsByRj.get(rjId) || [];
    existing.push(wrapper);
    controlsByRj.set(rjId, existing);
    const snapshot = stateByRj.get(rjId);
    renderControls(wrapper, snapshot?.state || "loading", snapshot?.hasSubtitles === true);
    if (!snapshot) {
      pendingIds.add(rjId);
    }
    return wrapper;
  }

  function renderControls(wrapper, state, hasSubtitles) {
    const presentation = api.presentationFor(state);
    const badge = wrapper.querySelector(".arsm-extension-badge");
    const button = wrapper.querySelector(".arsm-extension-button");
    badge.textContent = presentation.label;
    badge.dataset.tone = presentation.tone;
    wrapper.querySelector(".arsm-extension-subtitle").hidden = !hasSubtitles;
    button.hidden = presentation.action === "none";
    button.disabled = state === "loading";
    button.dataset.action = presentation.action;
    if (presentation.action === "download") {
      button.textContent = wrapper.classList.contains("arsm-extension-controls--detail")
        ? "使用 ARSM 下载"
        : "下载到 ARSM";
    } else if (presentation.action === "open-library") {
      button.textContent = "在 ARSM 中打开";
    } else if (presentation.action === "open-download") {
      button.textContent = "查看下载";
    } else if (presentation.action === "settings") {
      button.textContent = "设置连接";
    }
  }

  function updateControls(rjId, state, hasSubtitles = stateByRj.get(rjId)?.hasSubtitles === true) {
    if (!controlsByRj.has(rjId)) {
      return;
    }
    hasSubtitles = hasSubtitles && state !== "disconnected";
    const previous = stateByRj.get(rjId);
    if (previous?.state === state && previous.hasSubtitles === hasSubtitles) {
      previous.refreshedAt = Date.now();
      return;
    }
    stateByRj.set(rjId, { state, hasSubtitles, refreshedAt: Date.now() });
    for (const wrapper of controlsByRj.get(rjId)) {
      if (wrapper.isConnected) {
        renderControls(wrapper, state, hasSubtitles);
      }
    }
  }

  async function handleAction(rjId, button) {
    const action = button.dataset.action;
    if (action === "settings") {
      await send({ type: "openOptions" });
      return;
    }
    if (action === "open-library" || action === "open-download") {
      await send({
        type: "open",
        rjId,
        view: action === "open-library" ? "library" : "download"
      });
      return;
    }
    if (action !== "download" || enqueuing.has(rjId)) {
      return;
    }

    enqueuing.add(rjId);
    updateControls(rjId, "loading");
    const response = await send({ type: "enqueue", rjId });
    enqueuing.delete(rjId);
    if (response.ok && response.download) {
      updateControls(rjId, response.download.state || "queued");
      schedulePolling();
      return;
    }
    const code = response.error && response.error.code;
    if (code === "already_in_library") {
      updateControls(rjId, "in_library");
    } else if (code === "already_queued" || code === "already_running") {
      updateControls(rjId, "queued");
    } else if (code === "token_missing" || code === "invalid_token" ||
               code === "disconnected" || code === "timeout") {
      updateControls(rjId, "disconnected");
    } else {
      updateControls(rjId, "failed");
    }
    schedulePolling();
  }

  function discoverLinks(node) {
    if (node.matches?.(WORK_LINK)) {
      pendingAnchors.add(node);
    }
    for (const anchor of node.querySelectorAll?.(WORK_LINK) || []) {
      pendingAnchors.add(anchor);
    }
  }

  function injectListCards() {
    for (const anchor of pendingAnchors) {
      if (!anchor.isConnected) {
        continue;
      }
      const rjId = api.extractRjId(anchor.getAttribute("href") || "");
      const card = findWorkCard(anchor);
      if (!card) {
        continue;
      }
      const previous = cardControls.get(card);
      if (!rjId) {
        if (previous?.isConnected && !card.querySelector(WORK_LINK)) {
          previous.remove();
          needsCleanup = true;
        }
        continue;
      }
      if (previous?.isConnected && previous.dataset.arsmRjId === rjId) {
        continue;
      }
      if (previous?.isConnected) {
        previous.remove();
        needsCleanup = true;
      }
      const controls = createControls(rjId, false);
      findSalesPlacement(card).append(controls);
      cardControls.set(card, controls);
    }
    pendingAnchors.clear();
  }

  function injectDetail() {
    const rjId = api.extractRjId(pathname);
    if (detailControls?.isConnected && detailControls.dataset.arsmRjId === rjId) {
      return;
    }
    if (detailControls?.isConnected) {
      detailControls.remove();
      needsCleanup = true;
    }
    detailControls = null;
    if (!rjId) {
      return;
    }
    const title = document.querySelector(
      "main h1, main h2, h1, [class*='work-title'], [class*='WorkTitle']"
    );
    if (!title) {
      return;
    }
    const controls = createControls(rjId, true);
    detailControls = controls;
    const detailRoot = title.closest("main, .col-12, .q-page") || document;
    const sales = Array.from(detailRoot.querySelectorAll("span, div, p, small"))
      .find((element) => {
        if (element.children.length > 2) {
          return false;
        }
        return /(?:销量|販売数|DL数|Sales)\s*[:：]?\s*[\d,]+/i.test(
          (element.textContent || "").trim()
        );
      });
    if (sales) {
      (sales.parentElement || sales).append(controls);
      return;
    }
    const parent = title.parentElement || title;
    parent.insertAdjacentElement("afterend", controls);
  }

  async function refreshStatuses() {
    if (refreshInFlight || document.hidden || !pendingIds.size) {
      return;
    }
    refreshInFlight = (async () => {
      while (pendingIds.size && !document.hidden) {
        const ids = [];
        for (const rjId of pendingIds) {
          pendingIds.delete(rjId);
          if (controlsByRj.has(rjId) && !enqueuing.has(rjId)) {
            ids.push(rjId);
          }
          if (ids.length === BATCH_SIZE) {
            break;
          }
        }
        if (!ids.length) {
          continue;
        }
        const before = ids.map(rjId => stateByRj.get(rjId));
        const response = await send({ type: "statusBatch", rjIds: ids });
        const disconnected = !response.ok || !response.states;
        ids.forEach((rjId, index) => {
          if (enqueuing.has(rjId) || stateByRj.get(rjId) !== before[index]) {
            return;
          }
          if (disconnected) {
            updateControls(rjId, "disconnected");
            return;
          }
          const snapshot = response.states[rjId];
          updateControls(
            rjId, snapshot ? snapshot.state : "not_in_library", snapshot?.has_subtitles === true
          );
        });
        if (disconnected) {
          for (const rjId of pendingIds) {
            if (!enqueuing.has(rjId)) {
              updateControls(rjId, "disconnected");
            }
          }
          pendingIds.clear();
          break;
        }
      }
    })();
    try {
      await refreshInFlight;
    } finally {
      refreshInFlight = null;
      schedulePolling();
    }
  }

  function cleanDisconnectedControls() {
    for (const [rjId, controls] of controlsByRj) {
      const connected = controls.filter(control => control.isConnected);
      if (connected.length) {
        controlsByRj.set(rjId, connected);
      } else {
        controlsByRj.delete(rjId);
        stateByRj.delete(rjId);
        pendingIds.delete(rjId);
      }
    }
    needsCleanup = false;
  }

  function scan() {
    scanTimer = 0;
    if (pathname !== location.pathname) {
      pathname = location.pathname;
    }
    injectListCards();
    injectDetail();
    if (needsCleanup) {
      cleanDisconnectedControls();
    }
    if (pendingIds.size) {
      void refreshStatuses();
    } else if (!pollTimer) {
      schedulePolling();
    }
  }

  function scheduleScan() {
    if (!scanTimer) {
      scanTimer = setTimeout(scan, 100);
    }
  }

  function schedulePolling() {
    if (document.hidden || !controlsByRj.size) {
      clearTimeout(pollTimer);
      pollTimer = 0;
      return;
    }
    let hasActive = false;
    let hasDisconnected = false;
    for (const { state } of stateByRj.values()) {
      hasActive ||= state === "queued" || state === "downloading";
      hasDisconnected ||= state === "disconnected";
    }
    const delay = hasActive ? 4000 : (hasDisconnected ? 10000 : 60000);
    const due = Date.now() + delay;
    if (pollTimer && pollDue <= due) {
      return;
    }
    clearTimeout(pollTimer);
    pollDue = due;
    pollTimer = setTimeout(() => {
      pollTimer = 0;
      const now = Date.now();
      for (const rjId of controlsByRj.keys()) {
        const snapshot = stateByRj.get(rjId);
        if (!snapshot || ["queued", "downloading", "disconnected"].includes(snapshot.state)
            || now - snapshot.refreshedAt >= 60000) {
          pendingIds.add(rjId);
        }
      }
      if (pendingIds.size) {
        void refreshStatuses();
      } else {
        schedulePolling();
      }
    }, delay);
  }

  const observer = new MutationObserver((mutations) => {
    let relevant = pathname !== location.pathname || (!detailControls?.isConnected &&
      Boolean(api.extractRjId(location.pathname)));
    for (const mutation of mutations) {
      const target = mutation.target instanceof Element
        ? mutation.target
        : mutation.target.parentElement;
      if (!target || target.closest(".arsm-extension-controls")) {
        continue;
      }
      if (mutation.type === "attributes") {
        if (target.matches("a")) {
          pendingAnchors.add(target);
        }
        continue;
      }
      for (const node of mutation.addedNodes) {
        if (node instanceof Element && !node.closest(".arsm-extension-controls")) {
          discoverLinks(node);
        }
      }
      for (const node of mutation.removedNodes) {
        if (!(node instanceof Element)) {
          continue;
        }
        if (node.matches(".arsm-extension-controls") ||
            node.querySelector(".arsm-extension-controls")) {
          needsCleanup = true;
        }
        if (node.matches(WORK_LINK) || node.querySelector(WORK_LINK)) {
          const card = findWorkCard(target);
          if (card) {
            const link = card.querySelector(WORK_LINK);
            if (link) {
              pendingAnchors.add(link);
            } else if (cardControls.get(card)?.isConnected) {
              cardControls.get(card).remove();
              needsCleanup = true;
            }
          }
        }
      }
    }
    if (relevant || pendingAnchors.size || needsCleanup) {
      scheduleScan();
    }
  });
  observer.observe(document.documentElement, {
    childList: true, subtree: true, attributes: true, attributeFilter: ["href"]
  });
  window.addEventListener("popstate", scheduleScan);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      schedulePolling();
      return;
    }
    for (const rjId of controlsByRj.keys()) {
      pendingIds.add(rjId);
    }
    scan();
  });
  discoverLinks(document);
  scan();
})();
