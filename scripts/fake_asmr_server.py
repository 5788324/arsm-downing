#!/usr/bin/env python3
"""Small local ASMR.one-compatible server for deterministic UI smoke tests."""

from __future__ import annotations

import argparse
import base64
from aiohttp import web

SMOKE_RJ_NUMERIC = "99999999"
TRACK_BYTES = (b"ARSM-SMOKE-TRACK\n" * 65536)[:1024 * 1024]
COVER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZrWQAAAAASUVORK5CYII="
)


def build_app() -> web.Application:
    app = web.Application()

    async def work_info(request: web.Request) -> web.Response:
        rj = request.match_info["rj"].lstrip("0") or "0"
        if rj != SMOKE_RJ_NUMERIC.lstrip("0"):
            raise web.HTTPNotFound()
        base = f"{request.scheme}://{request.host}"
        return web.json_response({
            "title": "ARSM UI Smoke Album",
            "circle": {"name": "Local Test Circle"},
            "vas": [{"name": "Test Voice"}],
            "tags": [{"name": "smoke-test"}],
            "price": 0,
            "dl_count": 1,
            "rate_average_2dp": 5.0,
            "release_date": "2026-07-20",
            "source_url": base,
            "mainCoverUrl": f"{base}/cover.png",
        })

    async def tracks(request: web.Request) -> web.Response:
        rj = request.match_info["rj"].lstrip("0") or "0"
        if rj != SMOKE_RJ_NUMERIC.lstrip("0"):
            raise web.HTTPNotFound()
        base = f"{request.scheme}://{request.host}"
        return web.json_response([{
            "id": 1,
            "title": "01 UI smoke track.bin",
            "type": "audio",
            "size": len(TRACK_BYTES),
            "mediaDownloadUrl": f"{base}/media/smoke-track.bin",
        }])

    async def cover(_request: web.Request) -> web.Response:
        return web.Response(body=COVER_PNG, content_type="image/png")

    async def media(request: web.Request) -> web.Response:
        range_header = request.headers.get("Range", "")
        if not range_header:
            return web.Response(
                body=TRACK_BYTES,
                status=200,
                headers={"Accept-Ranges": "bytes"},
                content_type="application/octet-stream",
            )
        if not range_header.startswith("bytes=") or not range_header.endswith("-"):
            raise web.HTTPBadRequest(text="unsupported range")
        try:
            start = int(range_header[6:-1])
        except ValueError:
            raise web.HTTPBadRequest(text="invalid range")
        if start >= len(TRACK_BYTES):
            return web.Response(
                status=416,
                headers={"Content-Range": f"bytes */{len(TRACK_BYTES)}"},
            )
        body = TRACK_BYTES[start:]
        return web.Response(
            body=body,
            status=206,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes {start}-{len(TRACK_BYTES)-1}/{len(TRACK_BYTES)}",
                "Content-Length": str(len(body)),
            },
            content_type="application/octet-stream",
        )

    app.router.add_get("/api/workInfo/{rj}", work_info)
    app.router.add_get("/api/tracks/{rj}", tracks)
    app.router.add_get("/cover.png", cover)
    app.router.add_get("/media/smoke-track.bin", media)
    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    web.run_app(build_app(), host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
