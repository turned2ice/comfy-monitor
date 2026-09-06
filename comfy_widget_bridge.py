"""Comfy Widget fetch bridge.

1. GET /comfy_widget/nodemap -> running prompt's node id -> class_type map,
   so the widget doesn't scrape version-dependent /queue formats.
2. Forwards privately-routed live events (executing, progress,
   progress_state, binary previews, KJ preview-override frames and run
   terminal events) to widget sockets. ComfyUI only sends these to the
   client that queued the prompt, so a passive widget would otherwise
   never see steps/previews for web-UI-queued renders, nor learn that a
   run finished.

The widget identifies itself by sending this WS message right after connect:
  {"type": "feature_flags", "data": {"supports_preview_metadata": true, "comfy_widget": true}}

No nodes are added; this module only registers the route + a send_sync wrapper.
Loaded automatically from custom_nodes/ on ComfyUI startup.
"""

from aiohttp import web

from server import PromptServer

try:
    from protocol import BinaryEventTypes
    _PREVIEW_META = BinaryEventTypes.PREVIEW_IMAGE_WITH_METADATA
    _PREVIEW_RAW = BinaryEventTypes.UNENCODED_PREVIEW_IMAGE
except Exception:
    _PREVIEW_META, _PREVIEW_RAW = 4, 2

FORWARD_EVENTS = frozenset({
    "executing", "progress", "progress_state",
    "execution_start", "execution_success",
    "execution_error", "execution_interrupted",
    "kj_preview_override",
    _PREVIEW_META, _PREVIEW_RAW,
})


def _graph_nodes(prompt):
    if isinstance(prompt, dict):
        graph = prompt.get("prompt", prompt)
    else:
        graph = {}
    if not isinstance(graph, dict):
        return {}
    return {
        str(nid): (node.get("class_type", "") if isinstance(node, dict) else "")
        for nid, node in graph.items()
    }


@PromptServer.instance.routes.get("/comfy_widget/nodemap")
async def nodemap(request):
    running, _ = PromptServer.instance.prompt_queue.get_current_queue_volatile()
    out = []
    for item in running:
        try:
            out.append({
                "prompt_id": str(item[1]),
                "nodes": _graph_nodes(item[2]),
            })
        except Exception:
            continue
    return web.json_response({"bridge": 2, "running": out})


def _widget_sids():
    try:
        meta = PromptServer.instance.sockets_metadata
        return [
            sid for sid, m in list(meta.items())
            if isinstance(m, dict)
            and m.get("feature_flags", {}).get("comfy_widget") is True
        ]
    except Exception:
        return []


_orig_send_sync = PromptServer.instance.send_sync


def _send_sync_with_forward(event, data, sid=None):
    _orig_send_sync(event, data, sid)
    try:
        if event in FORWARD_EVENTS:
            for wsid in _widget_sids():
                if wsid != sid:
                    _orig_send_sync(event, data, wsid)
    except Exception:
        pass


PromptServer.instance.send_sync = _send_sync_with_forward


NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
