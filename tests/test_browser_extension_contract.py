from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from core.browser_bridge import BROWSER_EXTENSION_ID

pytestmark = pytest.mark.portable

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "browser_extension"


def _extension_id_from_key(public_key: str) -> str:
    digest = hashlib.sha256(base64.b64decode(public_key)).digest()[:16]
    return "".join(chr(ord("a") + nibble) for byte in digest for nibble in (byte >> 4, byte & 15))


def test_manifest_is_narrow_mv3_and_has_stable_extension_id() -> None:
    manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    assert manifest["permissions"] == ["storage"]
    assert manifest["host_permissions"] == ["http://127.0.0.1:17641/*"]
    assert manifest["content_scripts"][0]["matches"] == [
        "https://asmr.one/*",
        "https://www.asmr.one/*",
    ]
    assert _extension_id_from_key(manifest["key"]) == BROWSER_EXTENSION_ID
    assert "downloads" not in manifest["permissions"]
    assert "cookies" not in manifest["permissions"]


def test_extension_contract_injects_status_and_delegates_downloads() -> None:
    content = (EXTENSION / "content.js").read_text(encoding="utf-8")
    worker = (EXTENSION / "service-worker.js").read_text(encoding="utf-8")
    shared = (EXTENSION / "shared.js").read_text(encoding="utf-8")
    combined = "\n".join((content, worker, shared))

    assert "MutationObserver" in content
    assert "statusBatch" in content
    assert "有字幕" in content
    assert "snapshot?.has_subtitles === true" in content
    assert ".arsm-extension-subtitle[hidden]" in (EXTENSION / "content.css").read_text()
    assert 'state === "disconnected"' in content
    assert "hasActive ? 4000 : (hasDisconnected ? 10000 : 60000)" in content
    assert "downloadStatus" in worker
    assert 'request("/v1/downloads"' in worker
    assert "chrome.storage.local" in worker
    assert "X-ARSM-Token" in worker
    assert "已入库" in shared
    assert "云盘资源" in shared
    assert "cloud_archive" in shared
    assert "未入库" in shared
    assert "下载到 ARSM" in content
    assert "使用 ARSM 下载" in content
    assert "file://" not in combined
    assert "absolutePath" not in combined
    assert "E:\\arsm" not in combined


def test_status_refresh_ignores_own_dom_mutations_and_deduplicates_requests() -> None:
    content = (EXTENSION / "content.js").read_text(encoding="utf-8")

    assert "let refreshInFlight = null;" in content
    assert "if (refreshInFlight || document.hidden" in content
    assert 'closest(".arsm-extension-controls")' in content
    assert "new MutationObserver((mutations) =>" in content
    assert "new MutationObserver(scheduleScan)" not in content


def test_extension_files_are_packaged_and_javascript_parses() -> None:
    required = {
        "manifest.json", "shared.js", "service-worker.js", "content.js",
        "content.css", "options.html", "options.css", "options.js", "README.md",
    }
    assert required <= {path.name for path in EXTENSION.iterdir()}
    spec = (ROOT / "ARSMSuite.spec").read_text(encoding="utf-8")
    assert '(str(ROOT / "browser_extension"), "browser_extension")' in spec

    for filename in ("shared.js", "service-worker.js", "content.js", "options.js"):
        result = subprocess.run(
            ["node", "--check", str(EXTENSION / filename)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_incremental_browser_refresh_batches_large_lists_and_skips_irrelevant_mutations():
    script = r"""
    const assert = require("node:assert/strict");
    const fs = require("node:fs");
    const vm = require("node:vm");
    class Element {
      constructor(links = []) { this.links = links; }
      closest() { return null; }
      matches() { return false; }
      querySelectorAll() { return this.links; }
      querySelector() { return null; }
    }
    const calls = [];
    const timers = new Map();
    let serial = 0;
    let observer;
    let wholeDocumentSearches = 0;
    const document = {
      hidden: false, documentElement: {}, addEventListener() {},
      querySelectorAll() { wholeDocumentSearches++; return []; },
    };
    const ctx = {
      document, window: { addEventListener() {} }, location: { pathname: "/" },
      Element, MutationObserver: class { constructor(cb) { observer = cb; } observe() {} },
      setTimeout(cb, delay) { timers.set(++serial, [cb, delay]); return serial; },
      clearTimeout(id) { timers.delete(id); },
      ARSMExtension: { extractRjId() { return null; } },
      chrome: { runtime: { sendMessage(message, callback) {
        calls.push(message.rjIds.length);
        const states = Object.fromEntries(message.rjIds.map(id => [id, {
          state: "not_in_library", has_subtitles: true,
        }]));
        callback({ ok: true, states });
      } } },
    };
    const source = fs.readFileSync(process.argv[1], "utf8").replace(/\r\n/g, "\n");
    const launch = "  discoverLinks(document);\n  scan();";
    assert(source.includes(launch));
    vm.runInNewContext(source.replace(launch,
      "  globalThis.hooks = { controlsByRj, pendingIds, stateByRj, refreshStatuses, schedulePolling };"), ctx);
    (async () => {
      const h = ctx.hooks;
      observer([{type: "childList", target: new Element(), addedNodes: [new Element()], removedNodes: []}]);
      assert.equal(timers.size, 0);
      assert.equal(wholeDocumentSearches, 0);
      for (let i = 0; i < 405; i++) {
        h.controlsByRj.set("RJ" + i, []);
        h.pendingIds.add("RJ" + i);
      }
      await h.refreshStatuses();
      assert.deepEqual(calls, [200, 200, 5]);
      assert.equal(h.pendingIds.size, 0);
      assert.equal(h.stateByRj.size, 405);
      assert.equal(timers.size, 1);
      assert.equal([...timers.values()][0][1], 60000);
      document.hidden = true;
      h.schedulePolling();
      h.pendingIds.add("RJ0");
      await h.refreshStatuses();
      assert.equal(timers.size, 0);
      assert.equal(calls.length, 3);
      assert.equal(h.pendingIds.size, 1);
    })().catch(error => { console.error(error); process.exitCode = 1; });
    """
    result = subprocess.run(["node", "-e", script, str(EXTENSION / "content.js")],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
