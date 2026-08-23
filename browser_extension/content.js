(function () {
  "use strict";

  if (globalThis.__arsmExtensionLoaded) {
    return;
  }
  globalThis.__arsmExtensionLoaded = true;

  const api = globalThis.ARSMExtension;
  const controlsByRj = new Map();
  const stateByRj = new Map();
  let scanTimer = 0;
  let pollTimer = 0;

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

    wrapper.append(badge, button);
    const existing = controlsByRj.get(rjId) || [];
    existing.push(wrapper);
    controlsByRj.set(rjId, existing);
    updateControls(rjId, stateByRj.get(rjId) || "loading");
    return wrapper;
  }

  function updateControls(rjId, state) {
    stateByRj.set(rjId, state);
    const presentation = api.presentationFor(state);
    for (const wrapper of controlsByRj.get(rjId) || []) {
      if (!wrapper.isConnected) {
        continue;
      }
      const badge = wrapper.querySelector(".arsm-extension-badge");
      const button = wrapper.querySelector(".arsm-extension-button");
      badge.textContent = presentation.label;
      badge.dataset.tone = presentation.tone;
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
    schedulePolling();
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
    if (action !== "download") {
      return;
    }

    updateControls(rjId, "loading");
    const response = await send({ type: "enqueue", rjId });
    if (response.ok && response.download) {
      updateControls(rjId, response.download.state || "queued");
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
  }

  function injectListCards() {
    const anchors = Array.from(document.querySelectorAll(
      "a[href*='/work/'], a[href*='/works/']"
    ));
    for (const anchor of anchors) {
      const rjId = api.extractRjId(anchor.getAttribute("href") || "");
      if (!rjId) {
        continue;
      }
      const card = findWorkCard(anchor);
      if (!card || card.querySelector(
        ".arsm-extension-controls[data-arsm-rj-id='" + rjId + "']"
      )) {
        continue;
      }
      findSalesPlacement(card).append(createControls(rjId, false));
    }
  }

  function injectDetail() {
    const rjId = api.extractRjId(location.pathname);
    if (!rjId || document.querySelector(
      ".arsm-extension-controls--detail[data-arsm-rj-id='" + rjId + "']"
    )) {
      return;
    }
    const title = document.querySelector(
      "main h1, main h2, h1, [class*='work-title'], [class*='WorkTitle']"
    );
    if (!title) {
      return;
    }
    const controls = createControls(rjId, true);
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

  function collectRjIds() {
    return Array.from(document.querySelectorAll(
      ".arsm-extension-controls[data-arsm-rj-id]"
    )).map((element) => element.dataset.arsmRjId).filter(Boolean)
      .filter((value, index, values) => values.indexOf(value) === index)
      .slice(0, 200);
  }

  async function refreshStatuses() {
    const rjIds = collectRjIds();
    if (!rjIds.length) {
      return;
    }
    const response = await send({ type: "statusBatch", rjIds });
    if (!response.ok || !response.states) {
      for (const rjId of rjIds) {
        updateControls(rjId, "disconnected");
      }
      return;
    }
    for (const rjId of rjIds) {
      const snapshot = response.states[rjId];
      updateControls(rjId, snapshot ? snapshot.state : "not_in_library");
    }
  }

  function cleanDisconnectedControls() {
    for (const [rjId, controls] of controlsByRj.entries()) {
      const connected = controls.filter((control) => control.isConnected);
      if (connected.length) {
        controlsByRj.set(rjId, connected);
      } else {
        controlsByRj.delete(rjId);
        stateByRj.delete(rjId);
      }
    }
  }

  async function scan() {
    cleanDisconnectedControls();
    injectListCards();
    injectDetail();
    await refreshStatuses();
  }

  function scheduleScan() {
    clearTimeout(scanTimer);
    scanTimer = setTimeout(scan, 250);
  }

  function schedulePolling() {
    const states = Array.from(stateByRj.values());
    const active = states.some(
      (state) => state === "queued" || state === "downloading" || state === "loading"
    );
    const disconnected = states.some((state) => state === "disconnected");
    clearTimeout(pollTimer);
    if (active || disconnected) {
      pollTimer = setTimeout(async () => {
        await refreshStatuses();
        schedulePolling();
      }, active ? 4000 : 10000);
    }
  }

  const observer = new MutationObserver(scheduleScan);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  scan();
})();
