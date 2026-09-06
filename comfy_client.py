import json
import time
import uuid

from PySide6.QtCore import QThread, Signal
import websocket


class ComfyClient(QThread):
    connected = Signal(bool)
    sampling = Signal(str, int, int)
    executing = Signal(str, str)
    node_map = Signal(dict)
    queue_remaining = Signal(int)
    execution_success = Signal(str)
    execution_error = Signal(str)
    preview_image = Signal(bytes)
    preview_image_kj = Signal(bytes, str)

    def __init__(self, host="127.0.0.1", port=8188, parent=None):
        super().__init__(parent)
        self._host = host
        self._port = port
        self._client_id = "comfy-widget-" + uuid.uuid4().hex[:8]
        self._running = True
        self._labels = {}
        self._prompt_id = ""
        self._active_node = ""
        self._last_sample_t = 0.0

    def stop(self):
        self._running = False
        self.wait()

    def _ws_url(self):
        return f"ws://{self._host}:{self._port}/ws?clientId={self._client_id}"

    def _http_url(self, path):
        return f"http://{self._host}:{self._port}{path}"


    def _refresh_node_labels(self, prompt_id):
        """Fetch the running prompt's graph to map node ids to class types."""
        try:
            import urllib.request
            try:
                with urllib.request.urlopen(
                    self._http_url("/comfy_widget/nodemap"), timeout=3
                ) as resp:
                    bridge = json.loads(resp.read().decode("utf-8"))
                for entry in bridge.get("running", []):
                    if str(entry.get("prompt_id")) == str(prompt_id):
                        self._labels = {
                            str(nid): ctype
                            for nid, ctype in (entry.get("nodes") or {}).items()
                        }
                        self.node_map.emit(dict(self._labels))
                        return
            except Exception:
                pass
            data = None
            for path in ("/queue", "/prompt"):
                try:
                    with urllib.request.urlopen(self._http_url(path), timeout=3) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                except Exception:
                    data = None
                if data and data.get("queue_running"):
                    break
            if not data:
                return
        except Exception:
            return
        for entry in data.get("queue_running", []):
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            # entry formats: [prompt_id, number, graph] or [number, prompt_id, graph]
            if prompt_id not in entry:
                continue
            graph = None
            for el in entry[2:]:
                if isinstance(el, dict):
                    graph = el
                    break
            if graph is None and isinstance(entry[1], dict):
                graph = entry[1]
            if graph is None:
                continue
            if isinstance(graph.get("prompt"), dict):
                graph = graph["prompt"]
            self._labels = {
                nid: node.get("class_type", nid)
                for nid, node in graph.items()
                if isinstance(node, dict)
            }
            self.node_map.emit(dict(self._labels))
            return

    def run(self):
        self.connected.emit(False)
        delay = 1.0
        while self._running:
            ws = None
            try:
                ws = websocket.create_connection(self._ws_url(), timeout=5)
                delay = 1.0
                try:
                    ws.send(json.dumps({"type": "feature_flags", "data": {
                        "supports_preview_metadata": True,
                        "comfy_widget": True,
                    }}))
                except Exception:
                    pass
                self.connected.emit(True)
                ws.settimeout(5)
                while self._running:
                    try:
                        raw = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    if not raw:
                        continue
                    if isinstance(raw, bytes):
                        self._handle_binary(raw)
                        continue
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    self._handle(msg)
            except Exception:
                self.connected.emit(False)
            finally:
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass
            if not self._running:
                break
            self.msleep(int(delay * 1000))
            delay = min(delay * 2, 10.0)

    def _handle_binary(self, raw):
        if len(raw) < 8:
            return
        event = int.from_bytes(raw[0:4], "big")
        payload = raw[4:]
        image = b""
        if event == 1:
            image = payload[4:]
        elif event == 4:
            meta_len = int.from_bytes(payload[0:4], "big")
            image = payload[4 + meta_len:]
        else:
            return
        if image:
            self.preview_image.emit(bytes(image))

    def _preview_live(self):
        if self._active_node:
            return True
        return (time.monotonic() - self._last_sample_t) < 10.0

    def _handle(self, msg):
        mtype = msg.get("type")
        data = msg.get("data") or {}
        if mtype == "kj_preview_override":
            import base64
            raw_b64 = data.get("image") or ""
            if raw_b64 and self._preview_live():
                try:
                    self.preview_image_kj.emit(
                        bytes(base64.b64decode(raw_b64)),
                        str(data.get("mime") or ""))
                except Exception:
                    pass
        elif mtype == "progress":
            node = data.get("node", "")
            value = data.get("value", 0)
            maximum = data.get("max", 0)
            self._last_sample_t = time.monotonic()
            self.sampling.emit(str(node), int(value), int(maximum))
        elif mtype == "progress_state":
            nodes = data.get("nodes") or {}
            # Only the actively running node drives sampling progress.
            # Finished nodes (e.g. a CLIP that already ran) must be ignored,
            # otherwise their state would reset the widget's run timer.
            best = None
            for node_id, state in nodes.items():
                if state.get("state") != "running":
                    continue
                value = int(state.get("value", 0))
                maximum = int(state.get("max", 0))
                if maximum > 0 and (best is None or value > best[1]):
                    best = (str(node_id), value, maximum)
            if best:
                self._last_sample_t = time.monotonic()
                self.sampling.emit(best[0], best[1], best[2])
        elif mtype == "executing":
            node = data.get("node")
            prompt_id = data.get("prompt_id", "")
            self._active_node = str(node) if node is not None else ""
            if prompt_id:
                self._prompt_id = str(prompt_id)
            if node is not None and prompt_id:
                if str(node) not in self._labels:
                    self._refresh_node_labels(prompt_id)
            self.executing.emit(str(node) if node is not None else "", str(prompt_id))
        elif mtype == "status":
            info = data.get("exec_info") or {}
            self.queue_remaining.emit(int(info.get("queue_remaining", 0)))
        elif mtype == "execution_success":
            pid = str(data.get("prompt_id", "") or self._prompt_id)
            self.execution_success.emit(pid)
        elif mtype == "execution_error":
            self.execution_error.emit(
                str(data.get("exception_message") or data.get("message") or "execution failed")
            )

    def label_for(self, node_id):
        return self._labels.get(node_id, "")
