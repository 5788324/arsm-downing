"use strict";

const tokenInput = document.getElementById("token");
const status = document.getElementById("status");
const endpoint = document.getElementById("endpoint");
const extensionId = document.getElementById("extension-id");

function message(payload) {
  return new Promise((resolve) => chrome.runtime.sendMessage(payload, resolve));
}

function showStatus(text, tone) {
  status.textContent = text;
  status.dataset.tone = tone;
}

async function checkConnection() {
  showStatus("正在检查 ARSM 连接…", "");
  const response = await message({ type: "health" });
  if (response && response.ok) {
    showStatus("连接成功，可以返回 asmr.one 使用。", "success");
  } else {
    showStatus(
      (response && response.error && response.error.message) ||
        "无法连接 ARSM，请确认应用已启动并启用浏览器扩展。",
      "error"
    );
  }
}

document.getElementById("toggle-token").addEventListener("click", (event) => {
  const reveal = tokenInput.type === "password";
  tokenInput.type = reveal ? "text" : "password";
  event.currentTarget.textContent = reveal ? "隐藏" : "显示";
});

document.getElementById("save").addEventListener("click", async () => {
  const token = tokenInput.value.trim();
  const saved = await message({ type: "saveToken", token });
  if (!saved || !saved.ok) {
    showStatus(
      (saved && saved.error && saved.error.message) || "令牌未保存",
      "error"
    );
    return;
  }
  await checkConnection();
});

document.getElementById("check").addEventListener("click", checkConnection);

(async () => {
  const connection = await message({ type: "getConnection" });
  endpoint.textContent = connection.endpoint;
  extensionId.textContent = connection.extensionId;
  const stored = await chrome.storage.local.get("arsmConnectionToken");
  tokenInput.value = stored.arsmConnectionToken || "";
  if (!connection.hasToken) {
    showStatus("请先填写 ARSM 设置页中的连接令牌。", "error");
  }
})();
