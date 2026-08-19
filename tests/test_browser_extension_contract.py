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
    assert manifest["content_scripts"][0]["matches"] == ["https://asmr.one/*"]
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
    assert "downloadStatus" in worker
    assert 'request("/v1/downloads"' in worker
    assert "chrome.storage.local" in worker
    assert "X-ARSM-Token" in worker
    assert "已入库" in shared
    assert "未入库" in shared
    assert "下载到 ARSM" in content
    assert "使用 ARSM 下载" in content
    assert "file://" not in combined
    assert "absolutePath" not in combined
    assert "E:\\arsm" not in combined


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
