from __future__ import annotations

import json
import threading
import atexit
from pathlib import Path

import webview

from bridge.api import EditorAPI
from editor.config import EditorSettings, ROOT
from engine.viewport import ViewportHost


class PandaEditorApplication:
    def __init__(self) -> None:
        self.settings = EditorSettings.load()
        self.window = None
        self._closing = False
        self._emit_lock = threading.RLock()
        self.viewport = ViewportHost(self._log, self._viewport_event)
        self.api = EditorAPI(self.settings, self.viewport, self._emit)
        self.api.exit_callback = self._request_exit
        self._shutdown_done = False
        self._shutdown_lock = threading.RLock()
        atexit.register(self._shutdown)

    def _log(self, message: str) -> None:
        self.api.log(message)

    def _emit(self, event: str, payload: dict) -> None:
        # pywebview logs ObjectDisposedException internally before propagating it.
        # Avoid entering evaluate_js at all once WinForms/WebView2 begins disposal.
        with self._emit_lock:
            if not self.window or self._closing:
                return
            try:
                native = getattr(self.window, 'native', None)
                if native is not None:
                    if bool(getattr(native, 'IsDisposed', False)) or bool(getattr(native, 'Disposing', False)):
                        self._closing = True
                        return
                script = f"window.EditorEvents && window.EditorEvents.emit({json.dumps(event)}, {json.dumps(payload)});"
                self.window.evaluate_js(script)
            except Exception:
                # Shutdown races must never become application errors.
                pass


    def _viewport_event(self, name: str, payload: dict) -> None:
        if name == 'selection_changed':
            entity_id = payload.get('entity_id')
            self.api.selected_id = entity_id if entity_id in self.api.scene.entities else None
            self._emit('viewport_selection', {'entity_id': self.api.selected_id})
        elif name == 'tool_changed':
            self._emit('viewport_tool', payload)
        elif name == 'projection_changed':
            self._emit('viewport_projection', payload)
        elif name == 'wireframe_changed':
            self._emit('viewport_wireframe', payload)
        elif name == 'camera_preset_changed':
            self._emit('viewport_camera_preset', payload)
        elif name == 'transform_preview':
            self._emit('viewport_transform_preview', payload)
        elif name == 'transform_constraint':
            self._emit('viewport_transform_constraint', payload)
        elif name == 'camera_preview_changed':
            self._emit('camera_preview_changed', payload)
        elif name == 'animation_clips':
            self._emit('animation_clips', payload)
        elif name == 'animation_preview_changed':
            self._emit('animation_preview_changed', payload)
        elif name == 'play_state_changed':
            state = str(payload.get('state') or 'stopped')
            self.api.play_state = state
            self._emit('play_state_changed', {'state': state})
        elif name == 'transform_committed':
            entity_id = str(payload.get('entity_id') or '')
            if entity_id in self.api.scene.entities:
                self.api.commit_viewport_transform(entity_id, payload.get('before') or {}, payload.get('after') or {})
        elif name == 'debug_snapshot':
            self._emit('debug_snapshot', payload)
        elif name == 'terrain_brush':
            self._emit('terrain_brush', payload)

    def _shown(self, window) -> None:
        native_handle = None
        try:
            native_handle = int(window.native.Handle.ToInt64())
        except Exception:
            try:
                native_handle = int(window.native.Handle.ToInt32())
            except Exception:
                pass
        self.viewport.start(native_handle)

    def _loaded(self) -> None:
        self.api._sync()

    def _request_exit(self) -> None:
        """Close from a worker tick so a JS->Python call never destroys its own host synchronously."""
        window = self.window
        if not window or self._closing:
            return
        def close_window():
            try:
                window.destroy()
            except Exception:
                self._shutdown()
        timer = threading.Timer(0.05, close_window)
        timer.daemon = True
        timer.start()


    def _shutdown_trace(self, message: str) -> None:
        """Console-safe shutdown diagnostics; WebView may already be disposing."""
        try:
            print(f'[Shutdown] {message}', flush=True)
        except Exception:
            pass

    def _shutdown(self) -> None:
        """Idempotent, bounded shutdown for WebView2, workers and Panda3D."""
        with self._shutdown_lock:
            if self._shutdown_done:
                return
            self._shutdown_done = True
            with self._emit_lock:
                self._closing = True

        started = __import__('time').perf_counter()
        self._shutdown_trace('Editor: shutdown started.')

        try:
            status = self.api.exporter.status()
            if status.get('running'):
                self._shutdown_trace('Editor: cancelling active Windows export/build.')
            self.api.cancel_windows_build()
        except Exception as exc:
            self._shutdown_trace(f'Editor: build cancellation skipped ({exc}).')

        try:
            self._shutdown_trace('Editor: stopping Panda viewport/runtime.')
            self.viewport.stop()
        except Exception as exc:
            self._shutdown_trace(f'Editor: viewport shutdown error ({exc}).')

        elapsed = __import__('time').perf_counter() - started
        self._shutdown_trace(f'Editor: shutdown complete in {elapsed:.2f}s.')

    def _closing_window(self, *args) -> None:
        """Stop background producers before WebView2 begins native disposal."""
        self._shutdown()

    def _closed_window(self, *args) -> None:
        self._shutdown()
        self.window = None

    def run(self) -> None:
        index = ROOT / 'ui' / 'index.html'
        self.window = webview.create_window(
            'Panda Editor POC 0.4.36',
            url=index.as_uri(),
            js_api=self.api,
            width=1500,
            height=900,
            min_size=(1050, 650),
            background_color='#11171f',
            text_select=True,
        )
        self.window.events.shown += self._shown
        self.window.events.loaded += self._loaded
        try:
            self.window.events.closing += self._closing_window
        except Exception:
            pass
        try:
            self.window.events.closed += self._closed_window
        except Exception:
            pass
        webview.start(debug=False)
        self._shutdown()
