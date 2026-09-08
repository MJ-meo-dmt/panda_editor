from __future__ import annotations

import multiprocessing as mp
import queue
import threading
from typing import Callable

from .panda_process import panda_viewport_process


class ViewportHost:
    """Process boundary between pywebview and Panda3D."""

    def __init__(self, logger: Callable[[str], None], event_handler: Callable[[str, dict], None] | None = None) -> None:
        self.logger = logger
        self.event_handler = event_handler
        self.runtime = self
        self._ctx = mp.get_context('spawn')
        self._commands = None
        self._messages = None
        self._process: mp.Process | None = None
        self._message_thread: threading.Thread | None = None
        self._stop_lock = threading.RLock()
        self._started = False
        self._native_handle: int | None = None
        self._last_rect = {'x': 260, 'y': 68, 'width': 800, 'height': 560}
        self._last_entities: list[dict] = []
        self._last_selection: str | None = None
        self._visible = True
        self._exclusions: list[dict] = []
        self._clip_rect: dict | None = None
        self._tool = 'select'
        self._preview_camera_id: str | None = None
        self._play_state = 'stopped'
        self._collision_helpers_visible = True
        self._project_settings: dict = {}
        self._bullet_debug=False
        self._frame_rate_meter=False
        self._wireframe=False
        self._camera_preset='perspective'
        self._animation_preview = {'entity_id': None, 'clip': '', 'mode': 'stop', 'rate': 1.0}
        self._terrain_edit = {'enabled': False, 'entity_id': None, 'mode': 'raise', 'radius': 4.0, 'strength': 0.5, 'falloff': 0.65}

    @property
    def ready(self) -> bool:
        return bool(self._process and self._process.is_alive())

    def start(self, native_handle: int | None) -> None:
        if self._process and self._process.is_alive():
            return
        if not native_handle:
            self.logger('Viewport: native editor window handle unavailable; Panda3D viewport not started.')
            return

        self._native_handle = int(native_handle)
        self._commands = self._ctx.Queue()
        self._messages = self._ctx.Queue()
        self._process = self._ctx.Process(
            target=panda_viewport_process,
            args=(int(native_handle), self._commands, self._messages),
            name='PandaViewportProcess',
            daemon=True,
        )
        self._process.start()
        self._started = True
        self._message_thread = threading.Thread(target=self._pump_messages, name='PandaViewportMessagePump', daemon=True)
        self._message_thread.start()

        self.set_rect(self._last_rect)
        # Rendering settings must arrive before entity sync. Material components
        # choose their shader inheritance policy while they are built; syncing
        # entities first could permanently stamp Panda auto-shaders onto objects
        # before simplepbr/complexpbr was initialized.
        self.set_project_settings(self._project_settings)
        self.sync_entities(self._last_entities)
        self.select(self._last_selection)
        self.set_tool(self._tool)
        self.set_visible(self._visible)
        self.set_clip_rect(self._clip_rect)
        self.set_exclusions(self._exclusions)
        self.preview_camera(self._preview_camera_id)
        self.set_collision_helpers(self._collision_helpers_visible)
        self.set_bullet_debug(self._bullet_debug)
        self.set_frame_rate_meter(self._frame_rate_meter)
        self.set_wireframe(self._wireframe)
        self.set_camera_preset(self._camera_preset)
        if self._animation_preview.get('entity_id'):
            self.preview_animation(**self._animation_preview)
        if self._terrain_edit.get('enabled'):
            self.set_terrain_edit(**self._terrain_edit)
        self._play_state = 'stopped'

    def _pump_messages(self) -> None:
        messages = self._messages
        if messages is None:
            return
        while self._started:
            try:
                item = messages.get(timeout=0.25)
            except queue.Empty:
                if self._process and not self._process.is_alive():
                    code = self._process.exitcode
                    if code not in (None, 0):
                        self.logger(f'Viewport process exited unexpectedly (code {code}).')
                    break
                continue
            except (EOFError, OSError):
                break
            if item is None:
                break
            if isinstance(item, dict) and item.get('type') == 'event':
                if self.event_handler:
                    try:
                        self.event_handler(str(item.get('name', '')), dict(item.get('payload') or {}))
                    except Exception as exc:
                        self.logger(f'Viewport event handling failed: {exc}')
            elif isinstance(item, dict) and item.get('type') == 'log':
                self.logger(str(item.get('message', '')))
            else:
                self.logger(str(item))

    def _send(self, op: str, **payload) -> None:
        if not (self._commands and self._process and self._process.is_alive()):
            return
        try:
            self._commands.put({'op': op, **payload})
        except (BrokenPipeError, EOFError, OSError) as exc:
            self.logger(f'Viewport IPC failed: {exc}')

    def _shutdown_status(self, message: str) -> None:
        """Write shutdown progress somewhere that still exists after WebView disposal starts."""
        text = f'[Shutdown] {message}'
        try:
            print(text, flush=True)
        except Exception:
            pass
        try:
            self.logger(text)
        except Exception:
            pass

    def stop(self) -> None:
        """Bounded Panda shutdown that can never hold the editor open indefinitely.

        Heavy textures, physics or graphics-driver teardown can occasionally make
        ShowBase.destroy() stall on Windows.  The Panda viewport is deliberately
        isolated in its own process, so give it a short graceful window and then
        escalate to terminate/kill rather than freezing the pywebview close path.
        """
        with self._stop_lock:
            process = self._process
            commands = self._commands
            messages = self._messages
            thread = self._message_thread

            if process is None and commands is None and messages is None:
                self._started = False
                return

            self._shutdown_status('Viewport: graceful stop requested.')

            # Keep the message pump alive while Panda performs its own cleanup so
            # child-side shutdown diagnostics can still reach the console/output.
            if commands is not None and process is not None and process.is_alive():
                try:
                    commands.put_nowait({'op': 'stop'})
                except Exception as exc:
                    self._shutdown_status(f'Viewport: stop command could not be queued ({exc}).')

                try:
                    process.join(timeout=2.5)
                except Exception as exc:
                    self._shutdown_status(f'Viewport: graceful join failed ({exc}).')

            if process is not None and process.is_alive():
                self._shutdown_status('Viewport: graceful timeout; terminating Panda child.')
                try:
                    process.terminate()
                except Exception as exc:
                    self._shutdown_status(f'Viewport: terminate failed ({exc}).')
                try:
                    process.join(timeout=0.9)
                except Exception:
                    pass

            if process is not None and process.is_alive():
                self._shutdown_status('Viewport: terminate timeout; force-killing Panda child.')
                try:
                    kill = getattr(process, 'kill', None)
                    if callable(kill):
                        kill()
                    else:
                        process.terminate()
                except Exception as exc:
                    self._shutdown_status(f'Viewport: force-kill failed ({exc}).')
                try:
                    process.join(timeout=0.6)
                except Exception:
                    pass

            self._started = False

            # Wake the daemon message pump immediately instead of making Python
            # wait for its queue timeout during process exit.
            if messages is not None:
                try:
                    messages.put_nowait(None)
                except Exception:
                    pass
            if thread is not None and thread.is_alive() and thread is not threading.current_thread():
                try:
                    thread.join(timeout=0.5)
                except Exception:
                    pass

            for q in (commands, messages):
                if q is not None:
                    # Never wait for multiprocessing feeder threads during app exit.
                    try:
                        q.cancel_join_thread()
                    except Exception:
                        pass
                    try:
                        q.close()
                    except Exception:
                        pass

            if process is not None:
                try:
                    alive = process.is_alive()
                except Exception:
                    alive = False
                if alive:
                    self._shutdown_status('Viewport: WARNING Panda child still reports alive; host will continue closing.')
                else:
                    try:
                        process.close()
                    except Exception:
                        pass

            self._message_thread = None
            self._commands = None
            self._messages = None
            self._process = None
            self._play_state = 'stopped'
            self._shutdown_status('Viewport: stopped.')


    def restart(self) -> bool:
        """Restart only the Panda viewport process while preserving editor state.

        Render pipelines install root shaders/buffers and are not guaranteed to be
        safely interchangeable in-place. A process restart gives Built-in,
        simplepbr and complexpbr a clean render graph without restarting pywebview.
        """
        handle = self._native_handle
        if not handle:
            return False
        self.stop()
        self.start(handle)
        return self.ready

    def set_rect(self, rect: dict) -> None:
        self._last_rect = {
            'x': int(rect.get('x', 0)), 'y': int(rect.get('y', 0)),
            'width': max(64, int(rect.get('width', 640))),
            'height': max(64, int(rect.get('height', 480))),
        }
        self._send('set_rect', rect=self._last_rect)

    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)
        self._send('set_visible', visible=self._visible)

    def set_clip_rect(self, rect: dict | None) -> None:
        self._clip_rect = dict(rect) if rect else None
        self._send('set_clip_rect', rect=self._clip_rect)

    def set_exclusions(self, rects: list[dict]) -> None:
        self._exclusions = [dict(r) for r in (rects or [])]
        self._send('set_exclusions', rects=self._exclusions)

    def sync_entities(self, entities: list[dict]) -> None:
        self._last_entities = entities
        self._send('sync_entities', entities=entities)

    def select(self, entity_id: str | None) -> None:
        self._last_selection = entity_id
        self._send('select', entity_id=entity_id)

    def frame_selected(self) -> None:
        self._send('frame_selected')

    def frame_all(self) -> None:
        self._send('frame_all')

    def set_tool(self, tool: str) -> None:
        self._tool = tool
        self._send('set_tool', tool=tool)

    def toggle_projection(self) -> None:
        self._send('toggle_projection')

    def set_camera_preset(self, preset: str) -> None:
        self._camera_preset = str(preset or 'perspective')
        self._send('camera_preset', preset=self._camera_preset)

    def set_wireframe(self, enabled: bool) -> None:
        self._wireframe = bool(enabled)
        self._send('set_wireframe', enabled=self._wireframe)

    def set_collision_helpers(self, visible: bool) -> None:
        self._collision_helpers_visible = bool(visible)
        self._send('set_collision_helpers', visible=self._collision_helpers_visible)

    def set_editor_helper_visibility(self, kind: str, visible: bool) -> None:
        self._send('set_editor_helper_visibility', kind=str(kind), visible=bool(visible))

    def set_bullet_debug(self, enabled: bool) -> None:
        self._bullet_debug=bool(enabled); self._send('set_bullet_debug', enabled=self._bullet_debug)

    def set_frame_rate_meter(self, enabled: bool) -> None:
        self._frame_rate_meter=bool(enabled); self._send('set_frame_rate_meter', enabled=self._frame_rate_meter)

    def connect_pstats(self) -> None:
        self._send('connect_pstats')

    def preview_camera(self, entity_id: str | None) -> None:
        self._preview_camera_id = entity_id or None
        self._send('preview_camera', entity_id=self._preview_camera_id)

    def preview_audio(self, relative_path: str) -> None:
        self._send('preview_audio', path=str(relative_path or ''))

    def stop_audio_preview(self) -> None:
        self._send('stop_audio_preview')

    def preview_animation(self, entity_id: str | None, clip: str = '', mode: str = 'play', rate: float = 1.0) -> None:
        self._animation_preview = {'entity_id': entity_id or None, 'clip': str(clip or ''), 'mode': str(mode or 'play'), 'rate': float(rate or 1.0)}
        self._send('preview_animation', **self._animation_preview)

    def refresh_animation_info(self, entity_id: str | None) -> None:
        self._send('refresh_animation_info', entity_id=entity_id or None)

    def preview_particles(self, entity_id: str | None, mode: str = 'start', count: int | None = None, clear: bool = False) -> None:
        self._send('preview_particles', entity_id=entity_id or None, mode=str(mode or 'start'), count=count, clear=bool(clear))


    def refresh_terrain(self, entity_id: str | None) -> None:
        self._send('refresh_terrain', entity_id=entity_id or None)

    def set_terrain_edit(self, enabled: bool = False, entity_id: str | None = None, mode: str = 'raise', radius: float = 4.0, strength: float = 0.5, falloff: float = 0.65) -> None:
        self._terrain_edit = {'enabled': bool(enabled), 'entity_id': entity_id or None, 'mode': str(mode or 'raise'), 'radius': float(radius or 4.0), 'strength': float(strength or .5), 'falloff': float(falloff or .65)}
        self._send('set_terrain_edit', **self._terrain_edit)

    def preview_light_action(self, entity_id: str | None, action: str = 'toggle') -> None:
        self._send('preview_light_action', entity_id=entity_id or None, action=str(action or 'toggle'))

    def set_vfx_preview_scene(self, enabled: bool, entity_id: str | None = None) -> None:
        self._send('set_vfx_preview_scene', enabled=bool(enabled), entity_id=entity_id or None)

    def vfx_preview_camera(self, action: str) -> None:
        self._send('vfx_preview_camera', action=str(action or 'focus'))

    def vfx_preview_options(self, grid: bool = True, axes: bool = True) -> None:
        self._send('vfx_preview_options', grid=bool(grid), axes=bool(axes))

    def set_material_preview_scene(self, enabled: bool, entity_id: str | None = None, mesh: str = 'sphere', light: str = 'studio') -> None:
        self._send('set_material_preview_scene', enabled=bool(enabled), entity_id=entity_id or None, mesh=str(mesh or 'sphere'), light=str(light or 'studio'))

    def update_material_preview(self, entity_id: str | None = None) -> None:
        self._send('update_material_preview', entity_id=entity_id or None)

    def preview_material_component(self, component: dict) -> None:
        self._send('preview_material_component', component=dict(component or {}))

    def material_preview_settings(self, mesh: str = 'sphere', light: str = 'studio') -> None:
        self._send('material_preview_settings', mesh=str(mesh or 'sphere'), light=str(light or 'studio'))

    def material_preview_camera(self, action: str = 'focus') -> None:
        self._send('material_preview_camera', action=str(action or 'focus'))


    def set_project_settings(self, settings: dict) -> None:
        self._project_settings = dict(settings or {})
        self._send('set_project_settings', settings=self._project_settings)

    def start_play(self, entities: list[dict], project_settings: dict | None = None) -> None:
        self._play_state = 'playing'
        if project_settings is not None:
            self._project_settings = dict(project_settings)
        self._send('start_play', entities=entities, project_settings=self._project_settings)

    def pause_play(self, paused: bool) -> None:
        if self._play_state == 'stopped':
            return
        self._play_state = 'paused' if paused else 'playing'
        self._send('pause_play', paused=bool(paused))

    def stop_play(self) -> None:
        if self._play_state == 'stopped':
            return
        self._play_state = 'stopped'
        self._send('stop_play')
