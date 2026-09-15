"use strict";

importScripts("shared.js");

const ENDPOINT = "http://127.0.0.1:17641";
const TOKEN_KEY = "arsmConnectionToken";

async function readToken() {
  const stored = await chrome.storage.local.get(TOKEN_KEY);
  return String(stored[TOKEN_KEY] || "").trim();
}

async function request(path, options = {}) {
  const token = await readToken();
  if (token.length < 32) {
    return {
      ok: false,
      status: 0,
      error: { code: "token_missing", message: "请先在扩展设置中填写 ARSM 连接令牌" }
    };
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs || 15000);
  try {
    const response = await fetch(ENDPOINT + path, {
      method: options.method || "GET",
      headers: {
        "Content-Type": "application/json",
        "X-ARSM-Token": token,
        "X-ARSM-Extension-Id": chrome.runtime.id
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      cache: "no-store",
      signal: controller.signal
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch (_error) {
      payload = {
        ok: false,
        error: { code: "invalid_response", message: "ARSM 返回了无法识别的响应" }
      };
    }
    return { ...payload, status: response.status };
  } catch (error) {
    const timeoutMessage = error && error.name === "AbortError";
    return {
      ok: false,
      status: 0,
      error: {
        code: timeoutMessage ? "timeout" : "disconnected",
        message: timeoutMessage ? "ARSM 响应超时" : "无法连接 ARSM，请确认应用已启动并启用浏览器扩展"
      }
    };
  } finally {
    clearTimeout(timeout);
  }
}

chrome.runtime.onInstalled.addListener(async () => {
  const token = await readToken();
  if (!token) {
    await chrome.runtime.openOptionsPage();
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id || !message || typeof message.type !== "string") {
    sendResponse({
      ok: false,
      error: { code: "sender_denied", message: "请求来源无效" }
    });
    return false;
  }

  const run = async () => {
    switch (message.type) {
      case "health":
        return request("/v1/health");
      case "statusBatch":
        return request("/v1/library/status", {
          method: "POST",
          body: { rj_ids: Array.isArray(message.rjIds) ? message.rjIds.slice(0, 200) : [] }
        });
      case "downloadStatus":
        return request("/v1/downloads/" + encodeURIComponent(message.rjId));
      case "enqueue":
        return request("/v1/downloads", {
          method: "POST",
          body: { rj_id: message.rjId },
          timeoutMs: 90000
        });
      case "open":
        return request("/v1/open", {
          method: "POST",
          body: { rj_id: message.rjId, view: message.view }
        });
      case "openOptions":
        await chrome.runtime.openOptionsPage();
        return { ok: true };
      case "getConnection":
        return {
          ok: true,
          endpoint: ENDPOINT,
          extensionId: chrome.runtime.id,
          hasToken: (await readToken()).length >= 32
        };
      case "saveToken": {
        const token = String(message.token || "").trim();
        if (token.length < 32) {
          return {
            ok: false,
            error: { code: "invalid_token", message: "连接令牌长度不正确" }
          };
        }
        await chrome.storage.local.set({ [TOKEN_KEY]: token });
        return { ok: true };
      }
      default:
        return {
          ok: false,
          error: { code: "unknown_message", message: "不支持的扩展操作" }
        };
    }
  };

  run().then(sendResponse).catch(() => sendResponse({
    ok: false,
    error: { code: "extension_error", message: "扩展内部操作失败" }
  }));
  return true;
});
