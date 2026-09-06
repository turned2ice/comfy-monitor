"""Mock ComfyUI server for end-to-end testing of the widget.

Faithful to real ComfyUI (aiohttp): serves GET /prompt over HTTP and the
/ws WebSocket endpoint, emitting the same message types:
  status, executing, progress, execution_success

The fake running graph lets the widget resolve node ids to class types
(e.g. 13 -> KSampler).

Run:  python mock_server.py [port]
Default port is 8188. Pick another port if your real ComfyUI runs there.
"""

import asyncio
import base64
import json
import struct
import sys
import uuid

from aiohttp import web

PROMPT_ID = str(uuid.uuid4())
GRAPH = {
    "6": {"class_type": "CLIPTextEncode", "inputs": {}},
    "10": {"class_type": "VAEDecode", "inputs": {}},
    "13": {"class_type": "KSampler", "inputs": {}},
}

# Tiny 8x8 PNGs so the widget can decode a visible, changing preview.
_PREVIEWS = [
    base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEUlEQVR4nGM4oaGBFTEMLQkAgl1GAWqNFmsAAAAASUVORK5CYII="),
    base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEUlEQVR4nGPQOKGBFTEMLQkAWl1GASZicMUAAAAASUVORK5CYII="),
    base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEUlEQVR4nGPQCLiDFTEMLQkACbdVAfTkR+4AAAAASUVORK5CYII="),
]

# Animated WebP (2 frames) mimicking a KJ Preview Override message payload.
def _animated_webp():
    from PIL import Image
    import io
    frames = [Image.new("RGB", (8, 8), c) for c in ((255, 0, 0), (0, 0, 255))]
    buf = io.BytesIO()
    frames[0].save(buf, format="WEBP", save_all=True,
                   append_images=frames[1:], loop=0, duration=100)
    return buf.getvalue()

_ANIM_WEBP = _animated_webp()

STAGES = [
    ("13", 30, 0.08),   # sampler node id, total steps, delay between steps (s)
    ("10", 0, 0.0),     # VAEDecode, no progress (just executing)
]


def preview_frame_with_metadata(png):
    meta = json.dumps({"image_type": "image/png"}).encode("utf-8")
    payload = struct.pack(">I", len(meta)) + meta + png
    return struct.pack(">I", 4) + payload   # PREVIEW_IMAGE_WITH_METADATA


def preview_frame_plain(png):
    return struct.pack(">I", 1) + struct.pack(">I", 2) + png   # PREVIEW_IMAGE, PNG


async def prompt_handler(request):
    return web.json_response({
        "queue_running": [[PROMPT_ID, 1, {"prompt": GRAPH}]],
        "queue_pending": [],
    })


async def nodemap_handler(request):
    return web.json_response({
        "bridge": 2,
        "running": [{"prompt_id": PROMPT_ID, "nodes": {
            nid: node["class_type"] for nid, node in GRAPH.items()
        }}],
    })


CYCLES = 3


async def ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    print("[mock] client connected")
    # Like real ComfyUI: binary previews are only sent to clients that
    # announced supports_preview_metadata as their first WS message.
    supports_preview = False
    try:
        msg = await asyncio.wait_for(ws.receive(), timeout=5)
        if msg.type == web.WSMsgType.TEXT:
            data = json.loads(msg.data)
            if data.get("type") == "feature_flags":
                supports_preview = bool(data.get("data", {}).get("supports_preview_metadata"))
                await ws.send_json({"type": "feature_flags",
                                    "data": {"supports_preview_metadata": True}})
                print(f"[mock] feature flags: preview={supports_preview}")
    except (asyncio.TimeoutError, json.JSONDecodeError):
        pass
    try:
        for cycle in range(CYCLES):
            remaining = [2, 1, 0][cycle % 3]
            await ws.send_json({"type": "status", "data": {"exec_info": {"queue_remaining": remaining}}})

            for node_id, total, delay in STAGES:
                await ws.send_json({
                    "type": "executing", "data": {"node": node_id, "prompt_id": PROMPT_ID}
                })
                await asyncio.sleep(0.3)
                if total:
                    for step in range(1, total + 1):
                        # progress_state includes a finished CLIP node, like real
                        # ComfyUI, to prove the widget only tracks the running one.
                        nodes = {
                            "6": {"state": "finished", "value": 1, "max": 1},
                            node_id: {"state": "running", "value": step, "max": total},
                        }
                        await ws.send_json({
                            "type": "progress_state",
                            "data": {"prompt_id": PROMPT_ID, "nodes": nodes},
                        })
                        # Alternate binary preview formats; cycle the image.
                        # Skipped entirely unless the client announced
                        # supports_preview_metadata (real server behavior).
                        png = _PREVIEWS[step % len(_PREVIEWS)]
                        if supports_preview:
                            if step % 2:
                                await ws.send_bytes(preview_frame_with_metadata(png))
                            else:
                                await ws.send_bytes(preview_frame_plain(png))
                        # KJ Preview Override style message: sent unconditionally
                        # (the override node does not check feature flags).
                        # Animated WebP, like a real override with preview_frames>1.
                        await ws.send_json({
                            "type": "kj_preview_override",
                            "data": {"node_id": "99", "step": step, "total": total,
                                     "mime": "image/webp",
                                     "image": base64.b64encode(_ANIM_WEBP).decode("ascii")},
                        })
                        await asyncio.sleep(delay)
            await ws.send_json({"type": "execution_success", "data": {"prompt_id": PROMPT_ID}})
            await asyncio.sleep(1.0)
    except Exception as exc:
        print(f"[mock] client closed: {type(exc).__name__}")
    return ws


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8188
    if len(sys.argv) > 2:
        globals()["CYCLES"] = int(sys.argv[2])
    app = web.Application()
    app.router.add_get("/prompt", prompt_handler)
    app.router.add_get("/comfy_widget/nodemap", nodemap_handler)
    app.router.add_get("/ws", ws_handler)
    print(f"[mock] ComfyUI mock server on ws://127.0.0.1:{port}/ws")
    web.run_app(app, host="127.0.0.1", port=port, print=None)


if __name__ == "__main__":
    main()
