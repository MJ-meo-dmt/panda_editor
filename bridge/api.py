from __future__ import annotations

import copy
import subprocess
import sys
import json
import shutil
import os
import re
import base64
import hashlib
import mimetypes
import math
import time
import struct
import zlib
import binascii
from pathlib import Path
from typing import Callable

import webview

from editor.commands import CommandStack, LambdaCommand
from editor.config import EditorSettings, ROOT
from editor.project_settings import ProjectSettings
from editor.game_exporter import WindowsGameExporter
from scene.entity import Entity
from scene.scene_document import SceneDocument


class EditorAPI:
    def __init__(self, settings: EditorSettings, viewport, emit: Callable[[str, dict], None]) -> None:
        self.settings = settings
        self.viewport = viewport
        self.emit = emit
        self.scene = SceneDocument('Untitled')
        self.commands = CommandStack()
        self.project_settings = ProjectSettings.load()
        self._standalone_process = None
        self.exporter = WindowsGameExporter(self.log, self.emit)
        self.selected_id: str | None = None
        self.logs: list[str] = []
        self.play_state = 'stopped'
        self.exit_callback = None
        self._terrain_edit_strokes: dict[str, dict] = {}
        self._seed_scene()

    def _seed_scene(self) -> None:
        floor = Entity('Floor')
        floor.components['primitive'] = {'type': 'plane'}
        floor.transform.scale = [6, 6, 6]
        self.scene.add(floor)
        cube = Entity('Cube')
        cube.components['primitive'] = {'type': 'cube'}
        cube.transform.position = [0, 0, 1]
        self.scene.add(cube)
        self.scene.dirty = False

    def log(self, message: str) -> None:
        self.logs.append(message)
        self.logs = self.logs[-300:]
        self.emit('log', {'message': message})

    @staticmethod
    def _dialog_kind(name: str):
        """Use the modern pywebview FileDialog enum with a legacy fallback."""
        enum = getattr(webview, 'FileDialog', None)
        if enum is not None and hasattr(enum, name):
            return getattr(enum, name)
        return getattr(webview, f'{name}_DIALOG')

    @staticmethod
    def _dialog_first_path(result) -> Path | None:
        """Normalize pywebview dialog return values across versions/backends."""
        if not result:
            return None
        value = result[0] if isinstance(result, (list, tuple)) else result
        if not value:
            return None
        return Path(value)

    def bootstrap(self) -> dict:
        return {
            'settings': self.settings.__dict__,
            'scene': self.scene.to_dict(),
            'selected_id': self.selected_id,
            'logs': self.logs,
            'root': str(ROOT),
            'play_state': self.play_state,
            'project_settings': self.project_settings.to_dict(),
            'scene_dirty': bool(self.scene.dirty),
            'scene_path': str(self.scene.file_path) if self.scene.file_path else '',
            'can_undo': self.commands.can_undo,
            'can_redo': self.commands.can_redo,
        }

    def scene_status(self) -> dict:
        return {
            'dirty': bool(self.scene.dirty),
            'name': self.scene.name,
            'path': str(self.scene.file_path) if self.scene.file_path else '',
            'can_undo': self.commands.can_undo,
            'can_redo': self.commands.can_redo,
        }

    def request_exit(self) -> bool:
        """Request a normal editor shutdown from the File menu."""
        callback = self.exit_callback
        if callable(callback):
            try:
                callback()
                return True
            except Exception as exc:
                self.log(f'Exit request failed: {exc}')
        return False

    def set_viewport_rect(self, rect: dict) -> bool:
        self.viewport.set_rect(rect)
        return True

    def set_viewport_visible(self, visible: bool) -> bool:
        self.viewport.set_visible(bool(visible))
        return True

    def set_viewport_clip(self, rect: dict | None) -> bool:
        """Clip the native Panda child to the currently visible HTML host area."""
        self.viewport.set_clip_rect(rect)
        return True

    def set_viewport_exclusions(self, rects: list[dict] | None) -> bool:
        """Clip small HTML overlays out of the native Panda child window."""
        self.viewport.set_exclusions(rects or [])
        return True

    def save_settings(self, values: dict) -> dict:
        for key, value in values.items():
            if hasattr(self.settings, key):
                setattr(self.settings, key, value)
        self.settings.save()
        return self.settings.__dict__

    def select_entity(self, entity_id: str | None) -> dict:
        self.selected_id = entity_id if entity_id in self.scene.entities else None
        self.viewport.runtime.select(self.selected_id)
        return self._selected_payload()

    def _selected_payload(self) -> dict:
        ent = self.scene.entities.get(self.selected_id or '')
        return ent.to_dict() if ent else {}

    def add_primitive(self, kind: str) -> dict:
        names = {
            'cube':'Cube', 'plane':'Plane', 'sphere':'Sphere', 'empty':'Empty', 'group':'Group',
            'camera':'Camera', 'point_light':'Point Light', 'spot_light':'Spot Light', 'directional_light':'Directional Light',
            'ui_canvas':'UI Canvas', 'ui_panel':'UI Panel', 'ui_label':'UI Label', 'ui_image':'UI Image', 'ui_button':'UI Button', 'ui_checkbox':'UI Checkbox', 'ui_progress':'UI Progress', 'ui_slider':'UI Slider', 'ui_input':'UI Text Input', 'ui_dropdown':'UI Dropdown', 'ui_radio':'UI Radio', 'particle_emitter':'Particle Emitter', 'terrain':'Terrain',
        }
        ent = Entity(names.get(kind, 'Entity'))
        if kind == 'group':
            ent.components['editor_group'] = {'editor_only': True}
            ent.transform.position = [0, 0, 0]
            ent.transform.rotation = [0, 0, 0]
            ent.transform.scale = [1, 1, 1]
        elif kind == 'camera':
            ent.components['camera'] = {'fov': 60.0, 'near': 0.1, 'far': 2000.0, 'active': False, 'projection': 'perspective', 'ortho_size': 10.0, 'rig':'fixed', 'target':'', 'offset':[0.0,-6.0,2.5], 'damping':8.0, 'look_at':True, 'distance':8.0, 'orbit_heading':0.0, 'orbit_pitch':20.0, 'orbit_min_pitch':-80.0, 'orbit_max_pitch':80.0, 'min_distance':1.0, 'max_distance':100.0}
            ent.transform.position = [0, -6, 3]
        elif kind == 'point_light':
            ent.components['light'] = {'type': 'point', 'color': [1.0, 0.92, 0.78], 'intensity': 1.0, 'range': 25.0, 'cast_shadows': False, 'shadow_resolution': 1024}
            ent.transform.position = [2, -2, 4]
        elif kind == 'spot_light':
            ent.components['light'] = {'type': 'spot', 'color': [1.0, 0.90, 0.72], 'intensity': 1.0, 'range': 30.0, 'fov': 45.0, 'exponent': 8.0, 'cast_shadows': False, 'shadow_resolution': 1024, 'shadow_near': 0.05}
            ent.transform.position = [0, -3, 4]
            ent.transform.rotation = [0, -35, 0]
        elif kind == 'directional_light':
            ent.components['light'] = {'type': 'directional', 'color': [1.0, 0.95, 0.86], 'intensity': 1.0, 'cast_shadows': False, 'shadow_resolution': 1024, 'shadow_area': 40.0, 'shadow_near': 0.1, 'shadow_far': 120.0}
            ent.transform.position = [0, 0, 4]
            ent.transform.rotation = [-35, -50, 0]
        elif kind == 'terrain':
            ent.components['terrain'] = {
                'enabled': True, 'heightfield': 'assets/textures/terrain_demo_height.png',
                'size': [64.0, 64.0], 'height_scale': 12.0,
                'block_size': 32, 'near': 24.0, 'far': 120.0, 'min_level': 0,
                'bruteforce': False, 'auto_flatten': 'off', 'border_stitching': True,
                'collision_enabled': True, 'visible': True,
                'material_paint': {'enabled': False, 'splatmap': '', 'baked_albedo': '', 'texture_scale': 8.0, 'layers': [
                    {'name':'Grass','albedo':'assets/textures/terrain_grass.png','tint':[0.55,0.82,0.48,1.0],'roughness':0.92,'metallic':0.0},
                    {'name':'Rock','albedo':'assets/textures/terrain_rock.png','tint':[0.72,0.72,0.74,1.0],'roughness':0.82,'metallic':0.0},
                    {'name':'Dirt','albedo':'assets/textures/terrain_dirt.png','tint':[0.62,0.42,0.24,1.0],'roughness':0.95,'metallic':0.0},
                    {'name':'Sand','albedo':'assets/textures/terrain_sand.png','tint':[0.88,0.79,0.56,1.0],'roughness':0.88,'metallic':0.0},
                ]},
            }
            ent.transform.position = [-32.0, -32.0, 0.0]
        elif kind == 'particle_emitter':
            ent.components['particle_emitter'] = {
                'enabled': True, 'autoplay': True, 'loop': True, 'rate': 18.0, 'burst_count': 24,
                'lifetime': 1.4, 'speed': 2.5, 'spread': 35.0, 'gravity': [0.0,0.0,-1.5],
                'shape': 'point', 'radius': 0.25, 'box_size': [0.5,0.5,0.5],
                'size_start': 0.16, 'size_end': 0.04,
                'color_start': [1.0,0.55,0.12,1.0], 'color_end': [0.22,0.06,0.02,0.0],
                'texture': '', 'max_particles': 256, 'speed_variation':0.0, 'lifetime_variation':0.0, 'drag':0.0,
                'duration': 0.0, 'local_space': True, 'rotation_start': 0.0, 'rotation_speed': 0.0,
                'blend_mode': 'alpha', 'emit_signal_finished': True, 'factory_type':'point', 'mass':1.0, 'mass_variation':0.0, 'terminal_velocity':0.0, 'renderer_type':'sprite', 'renderer_model':'', 'line_length':0.35, 'line_thickness':2.0, 'sparkle_scale':1.0, 'point_size':0.08, 'inner_radius':0.0, 'emission_angle':360.0, 'velocity_mode':'outward'
            }
            ent.transform.position = [0,0,1]
        elif kind.startswith('ui_'):
            ui_type = kind.removeprefix('ui_')
            defaults = {
                'canvas': {'type':'canvas','anchor':'center','offset':[0,0],'size':[1280,720],'visible':True},
                'panel': {'type':'panel','anchor':'center','offset':[0,0],'size':[360,180],'color':[0.06,0.09,0.13,0.88],'visible':True},
                'label': {'type':'label','anchor':'top_left','offset':[28,28],'size':[420,48],'text':'HUD Label','font_size':24,'text_color':[0.95,0.97,1.0,1.0],'align':'left','visible':True},
                'image': {'type':'image','anchor':'center','offset':[0,0],'size':[256,256],'image':'','color':[1,1,1,1],'visible':True},
                'button': {'type':'button','anchor':'bottom','offset':[0,-48],'size':[220,56],'text':'Button','font_size':22,'color':[0.10,0.28,0.43,0.96],'text_color':[1,1,1,1],'signal_name':'clicked','connections':[],'event_name':'ui_click','enabled':True,'visible':True},
                'checkbox': {'type':'checkbox','anchor':'top_left','offset':[28,92],'size':[260,42],'text':'Checkbox','font_size':20,'checked':False,'color':[0.10,0.28,0.43,0.96],'text_color':[1,1,1,1],'signal_name':'changed','connections':[],'enabled':True,'visible':True},
                'progress': {'type':'progress','anchor':'top_left','offset':[28,148],'size':[320,34],'value':50.0,'range':100.0,'color':[0.10,0.55,0.82,1.0],'background_color':[0.04,0.07,0.10,0.92],'visible':True},
                'slider': {'type':'slider','anchor':'top_left','offset':[28,204],'size':[320,38],'value':50.0,'min_value':0.0,'max_value':100.0,'page_size':1.0,'color':[0.10,0.55,0.82,1.0],'background_color':[0.04,0.07,0.10,0.92],'signal_name':'changed','connections':[],'enabled':True,'visible':True},
                'input': {'type':'input','anchor':'top_left','offset':[28,260],'size':[360,44],'text':'','placeholder':'Type here...','font_size':20,'color':[0.05,0.08,0.12,0.96],'text_color':[1,1,1,1],'signal_name':'submitted','connections':[],'enabled':True,'visible':True},
                'dropdown': {'type':'dropdown','anchor':'top_left','offset':[28,316],'size':[320,44],'options':['Option A','Option B','Option C'],'selected_index':0,'font_size':20,'color':[0.08,0.16,0.24,0.98],'text_color':[1,1,1,1],'signal_name':'changed','connections':[],'enabled':True,'visible':True},
                'radio': {'type':'radio','anchor':'top_left','offset':[28,372],'size':[280,42],'text':'Radio Option','font_size':20,'selected':False,'group':'default','color':[0.10,0.28,0.43,0.96],'text_color':[1,1,1,1],'signal_name':'changed','connections':[],'enabled':True,'visible':True},
            }
            ent.components['ui'] = copy.deepcopy(defaults.get(ui_type, defaults['label']))
            ent.transform.position = [0,0,0]; ent.transform.rotation=[0,0,0]; ent.transform.scale=[1,1,1]
        else:
            ent.components['primitive'] = {'type': kind}
            if kind != 'plane':
                ent.transform.position = [0, 0, 1]

        def do(): self.scene.add(ent); self._sync()
        def undo(): self.scene.remove(ent.id); self._sync()
        self.commands.execute(LambdaCommand(f'Add {ent.name}', do, undo))
        self.selected_id = ent.id
        self.viewport.runtime.select(ent.id)
        self._changed()
        return ent.to_dict()

    def duplicate_entities(self, entity_ids: list[str], include_children: bool = True) -> dict:
        """Duplicate multiple Outliner roots as one undoable command."""
        requested=[str(x) for x in (entity_ids or []) if str(x) in self.scene.entities]
        if not requested:
            return {'ok':False,'entities':[]}
        selected=set(requested); roots=[]
        for eid in requested:
            cursor=self.scene.entities[eid].parent; nested=False
            while cursor:
                if cursor in selected:
                    nested=True; break
                parent=self.scene.entities.get(cursor); cursor=parent.parent if parent else None
            if not nested: roots.append(eid)
        source_ids=[]
        for root_id in roots:
            if root_id not in source_ids: source_ids.append(root_id)
            if include_children:
                q=[root_id]
                while q:
                    parent=q.pop(0); kids=[e.id for e in self.scene.entities.values() if e.parent==parent and e.id not in source_ids]; source_ids.extend(kids); q.extend(kids)
        snapshots=[copy.deepcopy(self.scene.entities[eid].to_dict()) for eid in source_ids]
        id_map={raw['id']:Entity('duplicate').id for raw in snapshots}
        created_raw=[]
        for raw in snapshots:
            clone=copy.deepcopy(raw); clone['id']=id_map[raw['id']]; clone['parent']=id_map.get(raw.get('parent'),raw.get('parent'))
            if raw['id'] in roots:
                clone['name']=str(raw.get('name','Entity'))+'_Copy'
                if not (clone.get('components') or {}).get('editor_group'):
                    pos=list((clone.get('transform') or {}).get('position') or [0,0,0]); pos[0]=float(pos[0])+1.0; clone.setdefault('transform',{})['position']=pos
            created_raw.append(clone)
        created_ids=[raw['id'] for raw in created_raw]; created_roots=[id_map[x] for x in roots]
        def do():
            for raw in created_raw:
                ent=Entity.from_dict(copy.deepcopy(raw)); self.scene.entities[ent.id]=ent
            self.selected_id=created_roots[0] if created_roots else None; self.scene.dirty=True; self._sync()
        def undo():
            for eid in created_ids: self.scene.entities.pop(eid,None)
            if self.selected_id in created_ids: self.selected_id=roots[0] if roots else None
            self.scene.dirty=True; self._sync()
        self.commands.execute(LambdaCommand(f'Duplicate {len(roots)} Selection'+('s' if len(roots)!=1 else ''),do,undo))
        self._changed()
        return {'ok':True,'entities':[self.scene.entities[eid].to_dict() for eid in created_roots if eid in self.scene.entities],'selected_ids':created_roots}

    def duplicate_selected(self) -> dict:
        src = self.scene.entities.get(self.selected_id or '')
        if not src:
            return {}
        clone = Entity.from_dict(copy.deepcopy(src.to_dict()))
        clone.id = Entity('x').id
        clone.name = src.name + '_Copy'
        clone.transform.position[0] += 1.0
        self.scene.add(clone)
        self.selected_id = clone.id
        self._changed()
        return clone.to_dict()

    def duplicate_entity(self, entity_id: str, include_children: bool = True) -> dict:
        """Duplicate an Outliner node, optionally including its descendant subtree."""
        source = self.scene.entities.get(str(entity_id or ''))
        if not source:
            return {}
        ids = [source.id]
        if include_children:
            queue_ids = [source.id]
            while queue_ids:
                parent = queue_ids.pop(0)
                kids = [e.id for e in self.scene.entities.values() if e.parent == parent and e.id not in ids]
                ids.extend(kids); queue_ids.extend(kids)
        snapshots = [copy.deepcopy(self.scene.entities[eid].to_dict()) for eid in ids]
        id_map = {old['id']: Entity('duplicate').id for old in snapshots}
        created = []
        for raw in snapshots:
            clone = Entity.from_dict(copy.deepcopy(raw))
            clone.id = id_map[raw['id']]
            clone.name = raw.get('name', 'Entity') + ('_Copy' if raw['id'] == source.id else '')
            old_parent = raw.get('parent')
            clone.parent = id_map.get(old_parent, old_parent)
            if raw['id'] == source.id and not clone.components.get('editor_group'):
                clone.transform.position[0] += 1.0
            self.scene.add(clone); created.append(clone)
        self.selected_id = created[0].id if created else None
        self._changed()
        return created[0].to_dict() if created else {}

    def delete_entity(self, entity_id: str, include_children: bool = True) -> bool:
        """Delete an Outliner node. Groups/subtrees can be removed as one operation."""
        eid = str(entity_id or '')
        if eid not in self.scene.entities:
            return False
        ids = [eid]
        if include_children:
            queue_ids = [eid]
            while queue_ids:
                parent = queue_ids.pop(0)
                kids = [e.id for e in self.scene.entities.values() if e.parent == parent and e.id not in ids]
                ids.extend(kids); queue_ids.extend(kids)
        snapshots = [copy.deepcopy(self.scene.entities[x]) for x in ids]
        for x in reversed(ids): self.scene.remove(x)
        if self.selected_id in ids: self.selected_id = None
        self._changed()
        return True

    def delete_entities(self, entity_ids: list[str], include_children: bool = True) -> dict:
        """Delete multiple Outliner selections as one undoable command."""
        requested = [str(x) for x in (entity_ids or []) if str(x) in self.scene.entities]
        if not requested:
            return {'ok': False, 'deleted': 0}
        selected = set(requested)
        roots = []
        for eid in requested:
            cursor = self.scene.entities[eid].parent
            nested = False
            while cursor:
                if cursor in selected:
                    nested = True
                    break
                parent = self.scene.entities.get(cursor)
                cursor = parent.parent if parent else None
            if not nested:
                roots.append(eid)
        delete_ids = []
        for root_id in roots:
            if root_id not in delete_ids:
                delete_ids.append(root_id)
            if include_children:
                queue_ids = [root_id]
                while queue_ids:
                    parent = queue_ids.pop(0)
                    kids = [e.id for e in self.scene.entities.values() if e.parent == parent and e.id not in delete_ids]
                    delete_ids.extend(kids)
                    queue_ids.extend(kids)
        snapshots = [copy.deepcopy(self.scene.entities[eid].to_dict()) for eid in delete_ids]
        old_selected = self.selected_id

        def do():
            for eid in delete_ids:
                self.scene.entities.pop(eid, None)
            for ent in self.scene.entities.values():
                if ent.parent in delete_ids:
                    ent.parent = None
            if self.selected_id in delete_ids:
                self.selected_id = None
            self.scene.dirty = True
            self._sync()

        def undo():
            for raw in snapshots:
                ent = Entity.from_dict(copy.deepcopy(raw))
                self.scene.entities[ent.id] = ent
            self.selected_id = old_selected if old_selected in self.scene.entities else None
            self.scene.dirty = True
            self._sync()

        label = f"Delete {len(delete_ids)} Scene Node" + ('s' if len(delete_ids) != 1 else '')
        self.commands.execute(LambdaCommand(label, do, undo))
        self._changed()
        return {'ok': True, 'deleted': len(delete_ids), 'selected_id': self.selected_id}

    def delete_selected(self) -> bool:
        ent = self.scene.entities.get(self.selected_id or '')
        if not ent:
            return False
        snapshot = copy.deepcopy(ent)
        eid = ent.id
        def do(): self.scene.remove(eid); self._sync()
        def undo(): self.scene.add(snapshot); self._sync()
        self.commands.execute(LambdaCommand(f'Delete {ent.name}', do, undo))
        self.selected_id = None
        self._changed()
        return True

    def update_entity(self, entity_id: str, patch: dict) -> dict:
        ent = self.scene.entities.get(entity_id)
        if not ent:
            return {}
        before = copy.deepcopy(ent.to_dict())

        if 'name' in patch: ent.name = str(patch['name'])[:120]
        if 'visible' in patch: ent.visible = bool(patch['visible'])
        if 'enabled' in patch: ent.enabled = bool(patch['enabled'])
        t = patch.get('transform', {})
        for attr in ('position', 'rotation', 'scale'):
            if attr in t:
                setattr(ent.transform, attr, [float(v) for v in t[attr]][:3])
        if 'components' in patch:
            ent.components = copy.deepcopy(patch['components'])
        ent_after = copy.deepcopy(ent.to_dict())

        def apply(data):
            restored = Entity.from_dict(copy.deepcopy(data))
            self.scene.entities[entity_id] = restored
            self.scene.dirty = True
            self._sync()

        self.commands.execute(LambdaCommand('Edit Entity', lambda: apply(ent_after), lambda: apply(before)))
        self._changed()
        return self.scene.entities[entity_id].to_dict()


    def commit_viewport_transform(self, entity_id: str, before: dict, after: dict) -> dict:
        """Commit one completed viewport drag as a single undoable transform command."""
        ent = self.scene.entities.get(entity_id)
        if not ent:
            return {}

        def normalized(raw: dict) -> dict:
            return {
                'position': [float(v) for v in raw.get('position', [0, 0, 0])][:3],
                'rotation': [float(v) for v in raw.get('rotation', [0, 0, 0])][:3],
                'scale': [max(0.001, float(v)) for v in raw.get('scale', [1, 1, 1])][:3],
            }

        before_t = normalized(before)
        after_t = normalized(after)

        def apply(t: dict) -> None:
            current = self.scene.entities.get(entity_id)
            if not current:
                return
            current.transform.position = list(t['position'])
            current.transform.rotation = list(t['rotation'])
            current.transform.scale = list(t['scale'])
            self.scene.dirty = True
            self._sync()

        label = {'move': 'Move Entity', 'rotate': 'Rotate Entity', 'scale': 'Scale Entity'}.get(
            getattr(self.viewport, '_tool', ''), 'Transform Entity'
        )
        self.commands.execute(LambdaCommand(label, lambda: apply(after_t), lambda: apply(before_t)))
        self._changed()
        return self.scene.entities[entity_id].to_dict()


    def reparent_entity(self, entity_id: str, parent_id: str | None) -> dict:
        """Reparent an entity in the authoring hierarchy with cycle protection."""
        ent = self.scene.entities.get(entity_id)
        if not ent:
            return {}
        parent_id = parent_id or None
        if parent_id == entity_id or (parent_id and parent_id not in self.scene.entities):
            return {}

        # Prevent cycles by walking upward from the proposed parent.
        cursor = parent_id
        while cursor:
            if cursor == entity_id:
                return {}
            parent = self.scene.entities.get(cursor)
            cursor = parent.parent if parent else None

        before = ent.parent
        if before == parent_id:
            return ent.to_dict()

        def apply(value):
            current = self.scene.entities.get(entity_id)
            if not current:
                return
            current.parent = value
            self.scene.dirty = True
            self._sync()

        label = 'Parent Entity' if parent_id else 'Unparent Entity'
        self.commands.execute(LambdaCommand(label, lambda: apply(parent_id), lambda: apply(before)))
        self._changed()
        return self.scene.entities[entity_id].to_dict()


    def update_component(self, entity_id: str, component_name: str, value: dict) -> dict:
        ent = self.scene.entities.get(entity_id)
        if not ent:
            return {}
        name = str(component_name).strip().lower()
        before = copy.deepcopy(ent.components.get(name))
        after = copy.deepcopy(value or {})

        def apply(component_value):
            current = self.scene.entities.get(entity_id)
            if not current:
                return
            if component_value is None:
                current.components.pop(name, None)
            else:
                current.components[name] = copy.deepcopy(component_value)
            self.scene.dirty = True
            self._sync()

        self.commands.execute(LambdaCommand(f'Edit {name.title()} Component', lambda: apply(after), lambda: apply(before)))
        self._changed()
        return self.scene.entities[entity_id].to_dict()

    def remove_component(self, entity_id: str, component_name: str) -> dict:
        ent = self.scene.entities.get(entity_id)
        if not ent:
            return {}
        name = str(component_name).strip().lower()
        if name not in ent.components:
            return ent.to_dict()
        before = copy.deepcopy(ent.components[name])

        def do():
            current = self.scene.entities.get(entity_id)
            if current:
                current.components.pop(name, None)
                self.scene.dirty = True
                self._sync()

        def undo():
            current = self.scene.entities.get(entity_id)
            if current:
                current.components[name] = copy.deepcopy(before)
                self.scene.dirty = True
                self._sync()

        self.commands.execute(LambdaCommand(f'Remove {name.title()} Component', do, undo))
        self._changed()
        return self.scene.entities[entity_id].to_dict()

    def add_component(self, entity_id: str, kind: str) -> dict:
        ent = self.scene.entities.get(entity_id)
        if not ent:
            return {}
        kind = str(kind).strip().lower()
        if kind == 'script':
            return self.add_script_component(entity_id)
        defaults = {
            'camera': {'fov': 60.0, 'near': 0.1, 'far': 2000.0, 'active': False, 'projection': 'perspective', 'ortho_size': 10.0, 'rig':'fixed', 'target':'', 'offset':[0.0,-6.0,2.5], 'damping':8.0, 'look_at':True, 'distance':8.0, 'orbit_heading':0.0, 'orbit_pitch':20.0, 'orbit_min_pitch':-80.0, 'orbit_max_pitch':80.0, 'min_distance':1.0, 'max_distance':100.0},
            'point_light': {'type': 'point', 'color': [1.0, 0.92, 0.78], 'intensity': 1.0, 'range': 25.0, 'cast_shadows': False, 'shadow_resolution': 1024},
            'spot_light': {'type': 'spot', 'color': [1.0, 0.90, 0.72], 'intensity': 1.0, 'range': 30.0, 'fov': 45.0, 'exponent': 8.0, 'cast_shadows': False, 'shadow_resolution': 1024, 'shadow_near': 0.05},
            'directional_light': {'type': 'directional', 'color': [1.0, 0.95, 0.86], 'intensity': 1.0, 'cast_shadows': False, 'shadow_resolution': 1024, 'shadow_area': 40.0, 'shadow_near': 0.1, 'shadow_far': 120.0},
            'collider': {'shape': 'box', 'size': [1.0, 1.0, 1.0], 'radius': 0.5, 'height': 1.0, 'offset': [0.0, 0.0, 0.0], 'trigger': False, 'enabled': True, 'layer': 0, 'mask': 4294967295},
            'rigid_body': {'body_type': 'dynamic', 'mass': 1.0, 'friction': 0.5, 'restitution': 0.0, 'linear_damping': 0.05, 'angular_damping': 0.05},
            'character_controller': {'radius': 0.45, 'height': 1.2, 'step_height': 0.35, 'jump_speed': 6.0, 'fall_speed': 35.0, 'max_jump_height': 1.5, 'max_slope': 45.0, 'ghost_sweep': True},
            'navigation_surface': {'enabled':True,'size':[20.0,20.0],'override_size':False,'cell_size':1.0,'diagonal':True,'debug':True},
            'navigation_agent': {'enabled':True,'surface':'','speed':3.5,'acceleration':12.0,'radius':0.35,'stopping_distance':0.25,'repath_interval':0.5,'face_movement':True,'movement_mode':'auto','behavior':'none','target':'','patrol_points':[],'patrol_loop':True,'flee_distance':8.0,'finished_event':'navigation_finished','finished_signal':'navigation_finished'},
            'navigation_obstacle': {'enabled':True,'radius':1.0,'height':2.0,'carve':True},
            'ai_behavior': {'enabled':True,'initial_state':'idle','disposition':'aggressive','target_mode':'explicit','target':'','target_tag':'player','think_interval':0.2,'sight_distance':15.0,'field_of_view':120.0,'require_los':False,'attack_distance':1.75,'attack_cooldown':1.0,'memory_time':2.0,'auto_navigation':True,'sync_fsm':True,'patrol_points':[],'patrol_loop':True,'flee_distance':8.0,'states':{'idle':'Idle','patrol':'Patrol','chase':'Chase','attack':'Attack','flee':'Flee','search':'Search'},'target_acquired_event':'ai_target_acquired','target_acquired_signal':'ai_target_acquired','target_lost_event':'ai_target_lost','target_lost_signal':'ai_target_lost','state_changed_event':'ai_state_changed','state_changed_signal':'ai_state_changed','attack_ready_event':'ai_attack_ready','attack_ready_signal':'ai_attack_ready','blackboard':{}},
            'audio_source': {'clip': '', 'bus': 'sfx', 'volume': 1.0, 'loop': False, 'autoplay': False, 'spatial': True, 'min_distance': 1.0, 'max_distance': 40.0},
            'lod': {'enabled':True,'near':0.0,'far':250.0,'fade_band':0.0,'scope':'entity'},
            'material': {'base_color': [1.0,1.0,1.0,1.0], 'base_texture': '', 'metallic': 0.0, 'roughness': 0.5, 'normal_texture': '', 'emission_texture': '', 'occlusion_texture': '', 'metal_rough_texture': '', 'uv_scale':[1.0,1.0], 'uv_offset':[0.0,0.0], 'uv_rotation':0.0, 'wrap_u':'repeat', 'wrap_v':'repeat', 'min_filter':'trilinear', 'mag_filter':'linear', 'anisotropic_degree':1, 'emission': [0.0,0.0,0.0], 'specular': [0.15,0.15,0.15], 'shininess': 16.0, 'alpha': 1.0, 'transparent': False, 'two_sided': False, 'unlit': False, 'shader_auto': True, 'shader_policy':'inherit', 'graph': {'version':1,'nodes':[{'id':'surface','type':'principled','x':420,'y':150,'name':'Principled Surface'},{'id':'output','type':'output','x':700,'y':170,'name':'Material Output'}],'links':[{'from':'surface','out':'surface','to':'output','in':'surface'}]}},
            'animation': {'enabled': True, 'default_clip': '', 'autoplay': True, 'loop': True, 'play_rate': 1.0},
            'fsm': {'enabled':True,'initial_state':'Idle','state_changed_signal':'state_changed','states':[{'name':'Idle','animation_clip':'','loop':True,'rate':1.0,'enter_event':'','exit_event':''}], 'transitions':[]},
            'tasks_events': {'enabled':True,'tasks':[{'name':'Heartbeat','mode':'interval','delay':0.0,'interval':1.0,'repeat':-1,'event':'heartbeat','signal':'','payload':None,'finished_event':'','finished_signal':'','enabled':True,'autostart':True}], 'events':[{'name':'heartbeat','script_event':'heartbeat','signal':'','enabled':True}]},
            'intervals': {'enabled':True,'clips':[{'name':'Move Demo','composition':'sequence','autostart':False,'loop':False,'play_rate':1.0,'finished_event':'','finished_signal':'','enabled':True,'steps':[{'type':'move','target':'self','duration':1.0,'to':[0.0,3.0,0.0],'blend':'easeInOut'},{'type':'wait','duration':0.25},{'type':'move','target':'self','duration':1.0,'to':[0.0,0.0,0.0],'blend':'easeInOut'}]}]},
            'render_attributes': {'enabled':True,'depth_test':True,'depth_write':True,'cull':'back','transparency':'inherit','color_scale':[1.0,1.0,1.0,1.0],'bin':'inherit','sort':0,'depth_offset':0,'billboard':'none','light_off':False,'shader_off':False},
            'shader': {'enabled':True,'language':'glsl','vertex':'assets/shaders/basic.vert','fragment':'assets/shaders/basic.frag','geometry':'','priority':20,'input_priority':0,'inputs':{'tint':{'type':'vec4','value':[1.0,1.0,1.0,1.0]}}},
            'signals': {'signal_name':'signal','connections':[]},
            'terrain': {'enabled':True,'heightfield':'assets/textures/terrain_demo_height.png','size':[64.0,64.0],'height_scale':12.0,'block_size':32,'near':24.0,'far':120.0,'min_level':0,'bruteforce':False,'auto_flatten':'off','border_stitching':True,'collision_enabled':True,'visible':True,'material_paint':{'enabled':False,'splatmap':'','baked_albedo':'','texture_scale':8.0,'layers':[{'name':'Grass','albedo':'assets/textures/terrain_grass.png','tint':[0.55,0.82,0.48,1.0],'roughness':0.92,'metallic':0.0},{'name':'Rock','albedo':'assets/textures/terrain_rock.png','tint':[0.72,0.72,0.74,1.0],'roughness':0.82,'metallic':0.0},{'name':'Dirt','albedo':'assets/textures/terrain_dirt.png','tint':[0.62,0.42,0.24,1.0],'roughness':0.95,'metallic':0.0},{'name':'Sand','albedo':'assets/textures/terrain_sand.png','tint':[0.88,0.79,0.56,1.0],'roughness':0.88,'metallic':0.0}]}},
            'ui_canvas': {'type':'canvas','anchor':'center','offset':[0,0],'size':[1280,720],'visible':True},
            'ui_panel': {'type':'panel','anchor':'center','offset':[0,0],'size':[360,180],'color':[0.06,0.09,0.13,0.88],'visible':True},
            'ui_label': {'type':'label','anchor':'top_left','offset':[28,28],'size':[420,48],'text':'HUD Label','font_size':24,'text_color':[0.95,0.97,1.0,1.0],'align':'left','visible':True},
            'ui_image': {'type':'image','anchor':'center','offset':[0,0],'size':[256,256],'image':'','color':[1,1,1,1],'visible':True},
            'ui_button': {'type':'button','anchor':'bottom','offset':[0,-48],'size':[220,56],'text':'Button','font_size':22,'color':[0.10,0.28,0.43,0.96],'text_color':[1,1,1,1],'signal_name':'clicked','connections':[],'event_name':'ui_click','enabled':True,'visible':True},
            'ui_checkbox': {'type':'checkbox','anchor':'top_left','offset':[28,92],'size':[260,42],'text':'Checkbox','font_size':20,'checked':False,'color':[0.10,0.28,0.43,0.96],'text_color':[1,1,1,1],'signal_name':'changed','connections':[],'enabled':True,'visible':True},
            'ui_progress': {'type':'progress','anchor':'top_left','offset':[28,148],'size':[320,34],'value':50.0,'range':100.0,'color':[0.10,0.55,0.82,1.0],'background_color':[0.04,0.07,0.10,0.92],'visible':True},
            'ui_slider': {'type':'slider','anchor':'top_left','offset':[28,204],'size':[320,38],'value':50.0,'min_value':0.0,'max_value':100.0,'page_size':1.0,'color':[0.10,0.55,0.82,1.0],'background_color':[0.04,0.07,0.10,0.92],'signal_name':'changed','connections':[],'enabled':True,'visible':True},
            'ui_input': {'type':'input','anchor':'top_left','offset':[28,260],'size':[360,44],'text':'','placeholder':'Type here...','font_size':20,'color':[0.05,0.08,0.12,0.96],'text_color':[1,1,1,1],'signal_name':'submitted','connections':[],'enabled':True,'visible':True},
            'ui_dropdown': {'type':'dropdown','anchor':'top_left','offset':[28,316],'size':[320,44],'options':['Option A','Option B','Option C'],'selected_index':0,'font_size':20,'color':[0.08,0.16,0.24,0.98],'text_color':[1,1,1,1],'signal_name':'changed','connections':[],'enabled':True,'visible':True},
            'ui_radio': {'type':'radio','anchor':'top_left','offset':[28,372],'size':[280,42],'text':'Radio Option','font_size':20,'selected':False,'group':'default','color':[0.10,0.28,0.43,0.96],'text_color':[1,1,1,1],'signal_name':'changed','connections':[],'enabled':True,'visible':True},
            'particle_emitter': {'enabled':True,'autoplay':True,'loop':True,'rate':18.0,'burst_count':24,'lifetime':1.4,'speed':2.5,'spread':35.0,'gravity':[0.0,0.0,-1.5],'shape':'point','radius':0.25,'box_size':[0.5,0.5,0.5],'size_start':0.16,'size_end':0.04,'color_start':[1.0,0.55,0.12,1.0],'color_end':[0.22,0.06,0.02,0.0],'texture':'','max_particles':256,'speed_variation':0.0,'lifetime_variation':0.0,'drag':0.0,'duration':0.0,'local_space':True,'rotation_start':0.0,'rotation_speed':0.0,'blend_mode':'alpha','emit_signal_finished':True,'factory_type':'point','mass':1.0,'mass_variation':0.0,'terminal_velocity':0.0,'renderer_type':'sprite','renderer_model':'','line_length':0.35,'line_thickness':2.0,'sparkle_scale':1.0,'point_size':0.08,'inner_radius':0.0,'emission_angle':360.0,'velocity_mode':'outward'},
        }
        component_name = 'light' if kind in {'point_light', 'spot_light', 'directional_light'} else ('ui' if kind.startswith('ui_') else kind)
        if component_name in ent.components:
            return ent.to_dict()
        value = copy.deepcopy(defaults.get(kind))
        if value is None:
            return ent.to_dict()
        if kind == 'collider':
            primitive = str((ent.components.get('primitive') or {}).get('type') or '').lower()
            if primitive == 'plane':
                value['shape'] = 'box'; value['size'] = [2.0, 2.0, 0.08]
            elif primitive == 'sphere':
                value['shape'] = 'sphere'; value['radius'] = 0.75
        if kind == 'character_controller' and 'collider' not in ent.components:
            ent.components['collider'] = {'shape': 'capsule', 'size': [1.0,1.0,1.0], 'radius': 0.45, 'height': 1.2, 'offset': [0.0,0.0,0.9], 'trigger': False, 'enabled': True, 'layer': 1, 'mask': 4294967295}
        return self.update_component(entity_id, component_name, value)

    def set_active_camera(self, entity_id: str, active: bool = True) -> dict:
        target = self.scene.entities.get(entity_id)
        if not target or 'camera' not in target.components:
            return {}
        before = {eid: copy.deepcopy(e.components.get('camera')) for eid, e in self.scene.entities.items() if 'camera' in e.components}

        def apply(active_id: str | None):
            for eid, current in self.scene.entities.items():
                cam = current.components.get('camera')
                if cam is not None:
                    cam['active'] = bool(active_id and eid == active_id)
            self.scene.dirty = True
            self._sync()

        def undo():
            for eid, value in before.items():
                current = self.scene.entities.get(eid)
                if current is not None:
                    current.components['camera'] = copy.deepcopy(value)
            self.scene.dirty = True
            self._sync()

        active_id = entity_id if active else None
        self.commands.execute(LambdaCommand('Set Active Camera', lambda: apply(active_id), undo))
        self._changed()
        return self.scene.entities[entity_id].to_dict()

    def preview_camera(self, entity_id: str | None) -> bool:
        if entity_id and (entity_id not in self.scene.entities or 'camera' not in self.scene.entities[entity_id].components):
            return False
        self.viewport.runtime.preview_camera(entity_id)
        return True

    def preview_animation(self, entity_id: str, clip: str = '', mode: str = 'play', rate: float = 1.0) -> bool:
        if entity_id not in self.scene.entities:
            return False
        self.viewport.preview_animation(entity_id, clip, mode, rate)
        return True

    def refresh_animation_info(self, entity_id: str) -> bool:
        if entity_id not in self.scene.entities:
            return False
        self.viewport.refresh_animation_info(entity_id)
        return True

    def preview_particles(self, entity_id: str, mode: str = 'start', count: int = 0, clear: bool = False) -> bool:
        if entity_id not in self.scene.entities or 'particle_emitter' not in self.scene.entities[entity_id].components:
            return False
        self.viewport.preview_particles(entity_id, mode, count if count else None, clear)
        return True

    def preview_light_action(self, entity_id: str, action: str = 'toggle') -> bool:
        if entity_id not in self.scene.entities or 'light' not in self.scene.entities[entity_id].components:
            return False
        self.viewport.preview_light_action(entity_id, action)
        return True

    def set_vfx_preview_scene(self, enabled: bool, entity_id: str = '') -> bool:
        if entity_id and (entity_id not in self.scene.entities or 'particle_emitter' not in self.scene.entities[entity_id].components):
            entity_id = ''
        self.viewport.set_vfx_preview_scene(bool(enabled), entity_id or None)
        return True

    def vfx_preview_camera(self, action: str = 'focus') -> bool:
        self.viewport.vfx_preview_camera(action)
        return True

    def vfx_preview_options(self, grid: bool = True, axes: bool = True) -> bool:
        self.viewport.vfx_preview_options(bool(grid), bool(axes))
        return True

    def set_material_preview_scene(self, enabled: bool, entity_id: str = '', mesh: str = 'sphere', light: str = 'studio') -> bool:
        if entity_id and (entity_id not in self.scene.entities or 'material' not in self.scene.entities[entity_id].components): entity_id=''
        self.viewport.set_material_preview_scene(bool(enabled), entity_id or None, mesh, light); return True

    def update_material_preview(self, entity_id: str = '') -> bool:
        if entity_id and entity_id not in self.scene.entities: return False
        self.viewport.update_material_preview(entity_id or None); return True

    def preview_material_component(self, component: dict) -> bool:
        self.viewport.preview_material_component(dict(component or {})); return True

    def material_preview_settings(self, mesh: str = 'sphere', light: str = 'studio') -> bool:
        self.viewport.material_preview_settings(mesh, light); return True

    def material_preview_camera(self, action: str = 'focus') -> bool:
        self.viewport.material_preview_camera(action); return True

    @staticmethod
    def _normalize_project_path(relative_path: str) -> str:
        return str(relative_path or '').strip().replace('\\', '/')

    def _script_template(self) -> str:
        return (
            '"""Panda Editor entity script."""\n\n'
            'class EntityScript:\n'
            '    def on_start(self, entity, world):\n'
            '        pass\n\n'
            '    def on_update(self, entity, world, dt):\n'
            '        pass\n\n'
            '    def on_event(self, entity, world, event_name, payload):\n'
            '        pass\n\n'
            '    def on_stop(self, entity, world):\n'
            '        pass\n'
        )

    def attach_script_file(self, entity_id: str, relative_path: str, enabled: bool = True) -> dict:
        """Attach an existing project Python file to an entity."""
        ent = self.scene.entities.get(entity_id)
        if not ent:
            return {}
        rel = self._normalize_project_path(relative_path)
        path = (ROOT / rel).resolve()
        scripts_root = (ROOT / 'scripts').resolve()
        if scripts_root not in path.parents or path.suffix.lower() != '.py' or not path.exists():
            raise ValueError('Script must be an existing .py file under the project scripts folder.')
        return self.update_component(entity_id, 'script', {'path': rel, 'enabled': bool(enabled)})

    def detach_script_file(self, entity_id: str) -> dict:
        """Detach the Script component without deleting the shared Python file."""
        return self.remove_component(entity_id, 'script')

    def create_and_attach_script(self, entity_id: str, file_name: str = '') -> dict:
        ent = self.scene.entities.get(entity_id)
        if not ent:
            return {}
        requested = str(file_name or '').strip()
        if not requested:
            requested = f"{ent.name.lower().replace(' ', '_')}.py"
        item = self.create_script_file(requested)
        return self.attach_script_file(entity_id, item['path'], True)

    def add_script_component(self, entity_id: str) -> dict:
        """Backwards-compatible quick action: create a script only when none is attached."""
        ent = self.scene.entities.get(entity_id)
        if not ent:
            return {}
        if ent.components.get('script'):
            return ent.to_dict()
        return self.create_and_attach_script(entity_id)

    def list_script_files(self) -> list[dict]:
        """Return project Python scripts with lightweight entity attachment metadata."""
        scripts_dir = ROOT / 'scripts'
        scripts_dir.mkdir(exist_ok=True)
        attached: dict[str, list[dict]] = {}
        for ent in self.scene.entities.values():
            comp = ent.components.get('script') or {}
            path = str(comp.get('path') or '').replace('\\', '/')
            if path:
                attached.setdefault(path, []).append({'id': ent.id, 'name': ent.name})
        result = []
        for path in sorted(scripts_dir.rglob('*.py')):
            rel = path.relative_to(ROOT).as_posix()
            stat = path.stat()
            result.append({
                'path': rel,
                'name': path.name,
                'size': stat.st_size,
                'attached_to': attached.get(rel, []),
            })
        return result

    def create_script_file(self, file_name: str = 'new_script.py') -> dict:
        scripts_dir = ROOT / 'scripts'
        scripts_dir.mkdir(exist_ok=True)
        name = Path(str(file_name or 'new_script.py')).name
        if not name.lower().endswith('.py'):
            name += '.py'
        stem = Path(name).stem or 'new_script'
        candidate = scripts_dir / f'{stem}.py'
        index = 2
        while candidate.exists():
            candidate = scripts_dir / f'{stem}_{index}.py'
            index += 1
        candidate.write_text(self._script_template(), encoding='utf-8')
        rel = str(candidate.relative_to(ROOT)).replace('\\', '/')
        self.log(f'Script created: {rel}')
        return {'path': rel, 'name': candidate.name, 'attached_to': []}

    def read_text_file(self, relative_path: str) -> str:
        path = (ROOT / relative_path).resolve()
        if ROOT.resolve() not in path.parents and path != ROOT.resolve():
            raise ValueError('Path outside project root.')
        return path.read_text(encoding='utf-8')

    def validate_python(self, relative_path: str, content: str) -> dict:
        """Compile script text without executing it and return editor-friendly diagnostics."""
        try:
            compile(str(content), str(relative_path or '<script>'), 'exec')
            return {'ok': True, 'message': 'Syntax OK', 'line': None, 'offset': None}
        except SyntaxError as exc:
            return {
                'ok': False,
                'message': str(exc.msg or 'Syntax error'),
                'line': exc.lineno,
                'offset': exc.offset,
                'text': (exc.text or '').rstrip(),
            }

    def write_text_file(self, relative_path: str, content: str) -> bool:
        path = (ROOT / relative_path).resolve()
        if ROOT.resolve() not in path.parents and path != ROOT.resolve():
            raise ValueError('Path outside project root.')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        self.log(f'Script saved: {relative_path}')
        return True

    def delete_script_file(self, relative_path: str) -> dict:
        rel = self._normalize_project_path(relative_path)
        attached = []
        for ent in self.scene.entities.values():
            comp = ent.components.get('script') or {}
            if self._normalize_project_path(comp.get('path')) == rel:
                attached.append({'id': ent.id, 'name': ent.name})
        if attached:
            return {'ok': False, 'reason': 'attached', 'attached_to': attached}
        path = (ROOT / rel).resolve()
        scripts_root = (ROOT / 'scripts').resolve()
        if scripts_root not in path.parents or path.suffix.lower() != '.py':
            return {'ok': False, 'reason': 'invalid'}
        if path.exists():
            path.unlink()
            self.log(f'Script deleted: {rel}')
        return {'ok': True}

    def list_prefab_files(self) -> list[dict]:
        prefabs_dir = ROOT / 'prefabs'
        prefabs_dir.mkdir(exist_ok=True)
        result = []
        for path in sorted(prefabs_dir.rglob('*.pprefab')):
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                count = len(data.get('entities') or [])
            except Exception:
                count = 0
            result.append({'path': str(path.relative_to(ROOT)).replace('\\','/'), 'name': path.stem, 'entities': count})
        return result

    def create_prefab_from_selected(self, file_name: str = '') -> dict:
        root = self.scene.entities.get(self.selected_id or '')
        if not root:
            return {}
        descendants = []
        pending = [root.id]
        seen = set()
        while pending:
            eid = pending.pop(0)
            if eid in seen:
                continue
            seen.add(eid)
            ent = self.scene.entities.get(eid)
            if ent:
                descendants.append(copy.deepcopy(ent.to_dict()))
                pending.extend(e.id for e in self.scene.entities.values() if e.parent == eid)
        prefabs_dir = ROOT / 'prefabs'
        prefabs_dir.mkdir(exist_ok=True)
        base = Path(str(file_name or root.name)).stem or 'Prefab'
        target = prefabs_dir / f'{base}.pprefab'
        idx = 2
        while target.exists():
            target = prefabs_dir / f'{base}_{idx}.pprefab'; idx += 1
        payload = {'prefab_version': 1, 'name': target.stem, 'root_id': root.id, 'entities': descendants}
        target.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        rel = str(target.relative_to(ROOT)).replace('\\','/')
        self.log(f'Prefab created: {rel} ({len(descendants)} entities)')
        return {'path': rel, 'name': target.stem, 'entities': len(descendants)}

    def instantiate_prefab(self, relative_path: str) -> dict:
        rel = str(relative_path or '').replace('\\','/')
        path = (ROOT / rel).resolve()
        prefabs_root = (ROOT / 'prefabs').resolve()
        if prefabs_root not in path.parents or path.suffix.lower() != '.pprefab' or not path.exists():
            raise ValueError('Invalid prefab path.')
        data = json.loads(path.read_text(encoding='utf-8'))
        raws = data.get('entities') or []
        if not raws:
            return {}
        id_map = {}
        for raw in raws:
            old = str(raw.get('id') or '')
            id_map[old] = Entity('Prefab').id
        clones = []
        old_root = str(data.get('root_id') or raws[0].get('id') or '')
        for raw in raws:
            clone_raw = copy.deepcopy(raw)
            old_id = str(clone_raw.get('id') or '')
            clone_raw['id'] = id_map[old_id]
            old_parent = clone_raw.get('parent')
            clone_raw['parent'] = id_map.get(str(old_parent)) if old_parent else None
            clone = Entity.from_dict(clone_raw)
            clones.append(clone)
        root_new = id_map.get(old_root, clones[0].id)
        root_clone = next((e for e in clones if e.id == root_new), clones[0])
        root_clone.transform.position[0] += 1.0
        root_clone.components['prefab_instance'] = {'source': rel}
        for ent in clones:
            self.scene.add(ent)
        self.selected_id = root_clone.id
        self.scene.dirty = True
        self._changed()
        self.viewport.runtime.select(root_clone.id)
        self.log(f'Prefab instantiated: {rel}')
        return root_clone.to_dict()

    def new_scene(self) -> dict:
        self.scene = SceneDocument('Untitled')
        self.selected_id = None
        self.commands.clear()
        self._changed(False)
        return self.scene.to_dict()

    def save_scene(self) -> str:
        path = self.scene.file_path
        if path is None:
            result = webview.windows[0].create_file_dialog(self._dialog_kind('SAVE'), save_filename='scene.pscene', file_types=('Panda Scene (*.pscene)',))
            path = self._dialog_first_path(result)
            if path is None:
                return ''
        target = self.scene.save(path)
        self.log(f'Scene saved: {target}')
        self._changed(False)
        return str(target)

    def open_scene_path(self, relative_path: str) -> dict:
        rel = self._normalize_project_path(relative_path)
        path = (ROOT / rel).resolve()
        if ROOT.resolve() not in path.parents or path.suffix.lower() != '.pscene' or not path.exists():
            return {}
        self.scene = SceneDocument.load(path)
        self.selected_id = None
        self.commands.clear()
        self.log(f'Scene opened: {rel}')
        self._changed(False)
        return self.scene.to_dict()

    def open_scene(self) -> dict:
        result = webview.windows[0].create_file_dialog(self._dialog_kind('OPEN'), file_types=('Panda Scene (*.pscene)',))
        path = self._dialog_first_path(result)
        if path is None:
            return {}
        self.scene = SceneDocument.load(path)
        self.selected_id = None
        self.commands.clear()
        self.log(f'Scene opened: {path}')
        self._changed(False)
        return self.scene.to_dict()

    def list_project_scenes(self) -> list[dict]:
        """Return project .pscene files for Scene Flow authoring."""
        rows = []
        for path in ROOT.rglob('*.pscene'):
            try:
                rel = str(path.relative_to(ROOT)).replace('\\','/')
                if any(part in {'.panda_editor','.panda_export','build_exports','dist','build'} for part in path.parts):
                    continue
                rows.append({'path': rel, 'name': path.stem, 'startup': rel == self.project_settings.startup_scene, 'current': self.scene.file_path is not None and path.resolve() == Path(self.scene.file_path).resolve()})
            except Exception:
                continue
        rows.sort(key=lambda x: (not x['startup'], x['path'].lower()))
        return rows

    def set_startup_scene_path(self, relative_path: str) -> dict:
        rel = self._normalize_project_path(relative_path)
        path = (ROOT / rel).resolve()
        if ROOT.resolve() not in path.parents or path.suffix.lower() != '.pscene' or not path.exists():
            return {'ok': False, 'error': 'Scene must be an existing .pscene inside this project.'}
        self.project_settings.startup_scene = rel
        self.project_settings.save()
        self.emit('project_settings_changed', {'settings': self.project_settings.to_dict()})
        return {'ok': True, 'startup_scene': rel}

    def import_model(self) -> dict:
        item = self.import_asset('models')
        return self.instantiate_model_asset(item['path']) if item else {}


    def list_audio_files(self) -> list[dict]:
        audio_dir = ROOT / 'assets' / 'audio'
        audio_dir.mkdir(parents=True, exist_ok=True)
        result = []
        for ext in ('*.wav', '*.ogg', '*.mp3', '*.flac'):
            for path in audio_dir.rglob(ext):
                stat = path.stat()
                result.append({'path': str(path.relative_to(ROOT)).replace('\\','/'), 'name': path.name, 'size': stat.st_size})
        result.sort(key=lambda item: item['name'].lower())
        return result

    def import_audio(self) -> dict:
        return self.import_asset('audio')


    # ------------------------------------------------------------------
    # Project asset manager
    # ------------------------------------------------------------------
    _ASSET_EXTENSIONS = {
        'models': {'.glb', '.gltf', '.bam', '.egg'},
        'textures': {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tga'},
        'audio': {'.wav', '.ogg', '.mp3', '.flac'},
        'scripts': {'.py'},
        'prefabs': {'.pprefab'},
        'scenes': {'.pscene'},
        'materials': {'.pma', '.material', '.json'},
        'shaders': {'.glsl', '.vert', '.frag', '.geom', '.tesc', '.tese', '.comp', '.sha'},
    }

    def _asset_category_for(self, path: Path) -> str:
        rel = path.relative_to(ROOT).as_posix()
        suffix = path.suffix.lower()
        if rel.startswith('scripts/'):
            return 'scripts'
        if rel.startswith('prefabs/'):
            return 'prefabs'
        if rel.startswith('project_templates/') and suffix == '.pscene':
            return 'scenes'
        if rel.startswith('assets/audio/'):
            return 'audio'
        if rel.startswith('assets/models/'):
            return 'models'
        if rel.startswith('assets/textures/'):
            return 'textures'
        if rel.startswith('assets/materials/'):
            return 'materials'
        if rel.startswith('assets/shaders/'):
            return 'shaders'
        for category, extensions in self._ASSET_EXTENSIONS.items():
            if suffix in extensions:
                return category
        return 'other'

    def _asset_references(self, relative_path: str) -> list[dict]:
        rel = self._normalize_project_path(relative_path)
        refs: list[dict] = []
        for ent in self.scene.entities.values():
            for component_name, component in ent.components.items():
                if not isinstance(component, dict):
                    continue
                candidates = []
                if component_name == 'script': candidates.append(component.get('path'))
                if component_name == 'audio_source': candidates.append(component.get('clip'))
                if component_name == 'model': candidates.append(component.get('asset'))
                if component_name == 'prefab_instance': candidates.append(component.get('source'))
                if component_name == 'material': candidates.extend(component.get(k) for k in ('base_texture','metal_rough_texture','normal_texture','emission_texture','occlusion_texture'))
                if component_name == 'shader':
                    candidates.extend(component.get(k) for k in ('vertex','fragment','geometry'))
                    for _v in (component.get('inputs') or {}).values():
                        if isinstance(_v,dict) and str(_v.get('type','')).lower()=='texture': candidates.append(_v.get('value'))
                if component_name == 'ui': candidates.append(component.get('image'))
                if component_name == 'particle_emitter':
                    candidates.extend(component.get(k) for k in ('texture','renderer_model'))
                if component_name == 'terrain':
                    candidates.append(component.get('heightfield'))
                    mp = component.get('material_paint') or {}
                    candidates.append(mp.get('splatmap')); candidates.append(mp.get('baked_albedo'))
                    candidates.extend((layer or {}).get('albedo') for layer in (mp.get('layers') or []))
                if any(self._normalize_project_path(v) == rel for v in candidates if v):
                    refs.append({'entity_id': ent.id, 'entity_name': ent.name, 'component': component_name})
        # Project-wide asset references are surfaced alongside entity references so the
        # Assets pane can explain why an environment asset is still in use.
        if self._normalize_project_path(getattr(self.project_settings, 'world_skybox_model', '') or '') == rel:
            refs.append({'entity_id': '', 'entity_name': 'Project Settings', 'component': 'world_skybox'})
        return refs

    def list_assets(self, category: str = 'all') -> list[dict]:
        """Return project assets with metadata and current-scene reference counts."""
        roots = [ROOT / 'assets', ROOT / 'scripts', ROOT / 'prefabs', ROOT / 'project_templates']
        result: list[dict] = []
        wanted = str(category or 'all').lower()
        for root in roots:
            if not root.exists():
                continue
            for path in root.rglob('*'):
                if not path.is_file() or path.name.startswith('.') or '__pycache__' in path.parts:
                    continue
                cat = self._asset_category_for(path)
                if cat == 'other' or (wanted not in {'all', 'project'} and cat != wanted):
                    continue
                rel = path.relative_to(ROOT).as_posix()
                stat = path.stat()
                refs = self._asset_references(rel)
                meta = {}
                if cat == 'prefabs':
                    try:
                        data = json.loads(path.read_text(encoding='utf-8'))
                        meta['entities'] = len(data.get('entities') or [])
                    except Exception:
                        meta['entities'] = 0
                elif cat == 'scripts':
                    meta['attached'] = len(refs)
                result.append({
                    'path': rel,
                    'name': path.name,
                    'stem': path.stem,
                    'extension': path.suffix.lower(),
                    'category': cat,
                    'size': stat.st_size,
                    'modified': int(stat.st_mtime),
                    'references': refs,
                    'reference_count': len(refs),
                    'meta': meta,
                })
        result.sort(key=lambda item: (item['category'], item['name'].lower()))
        return result


    def create_asset_template(self, kind: str, name: str, folder: str = '') -> dict:
        """Create an editable project asset without requiring a scene entity first."""
        kind = str(kind or '').strip().lower()
        clean = re.sub(r'[^A-Za-z0-9_. -]+', '_', str(name or '').strip()).strip(' ._') or 'New Asset'
        requested = self._normalize_project_path(folder or '')
        if kind == 'material':
            base = (ROOT / requested).resolve() if requested.startswith('assets/materials') else (ROOT / 'assets' / 'materials').resolve()
            base.mkdir(parents=True, exist_ok=True)
            stem = Path(clean).stem
            path = base / f'{stem}.material'
            i = 2
            while path.exists():
                path = base / f'{stem}_{i}.material'
                i += 1
            material = {
                'base_color':[1.0,1.0,1.0,1.0], 'base_texture':'', 'metallic':0.0, 'roughness':0.5,
                'normal_texture':'', 'emission_texture':'', 'occlusion_texture':'', 'metal_rough_texture':'',
                'uv_scale':[1.0,1.0], 'uv_offset':[0.0,0.0], 'uv_rotation':0.0, 'wrap_u':'repeat', 'wrap_v':'repeat',
                'min_filter':'trilinear', 'mag_filter':'linear', 'anisotropic_degree':1,
                'emission':[0.0,0.0,0.0], 'specular':[0.15,0.15,0.15], 'shininess':16.0, 'alpha':1.0,
                'transparent':False, 'two_sided':False, 'unlit':False, 'shader_auto':True, 'shader_policy':'inherit',
                'graph':{'version':1,'nodes':[
                    {'id':'surface','type':'principled','x':420,'y':150,'name':'Principled Surface'},
                    {'id':'output','type':'output','x':700,'y':170,'name':'Material Output'}
                ],'links':[{'from':'surface','out':'surface','to':'output','in':'surface'}]}
            }
            path.write_text(json.dumps({'format':'panda_editor_material','version':1,'name':path.stem,'material':material}, indent=2), encoding='utf-8')
            rel = path.relative_to(ROOT).as_posix()
            self.log(f'Material asset created: {rel}')
            return {'ok':True,'kind':'material','path':rel,'paths':[rel]}
        if kind == 'shader':
            base = (ROOT / 'assets' / 'shaders').resolve()
            base.mkdir(parents=True, exist_ok=True)
            stem = Path(clean).stem
            vert = base / f'{stem}.vert'
            frag = base / f'{stem}.frag'
            i = 2
            while vert.exists() or frag.exists():
                vert = base / f'{stem}_{i}.vert'
                frag = base / f'{stem}_{i}.frag'
                i += 1
            vert.write_text('#version 130\n\nin vec4 p3d_Vertex;\nuniform mat4 p3d_ModelViewProjectionMatrix;\n\nvoid main() {\n    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;\n}\n', encoding='utf-8')
            frag.write_text('#version 130\n\nout vec4 fragColor;\nuniform vec4 tint;\n\nvoid main() {\n    fragColor = tint;\n}\n', encoding='utf-8')
            paths = [vert.relative_to(ROOT).as_posix(), frag.relative_to(ROOT).as_posix()]
            self.log(f'GLSL shader assets created: {paths[0]}, {paths[1]}')
            return {'ok':True,'kind':'shader','path':paths[1],'paths':paths}
        if kind == 'script':
            base = (ROOT / 'scripts').resolve()
            base.mkdir(parents=True, exist_ok=True)
            stem = Path(clean).stem
            path = base / f'{stem}.py'
            i = 2
            while path.exists():
                path = base / f'{stem}_{i}.py'
                i += 1
            template = "class EntityScript:\n    def on_start(self, entity, world):\n        pass\n\n    def on_update(self, entity, world, dt):\n        pass\n\n    def on_event(self, entity, world, event_name, payload):\n        pass\n"
            path.write_text(template, encoding='utf-8')
            rel = path.relative_to(ROOT).as_posix()
            self.log(f'Python script asset created: {rel}')
            return {'ok':True,'kind':'script','path':rel,'paths':[rel]}
        return {'ok':False,'reason':'unsupported_asset_kind'}

    def asset_thumbnail(self, relative_path: str) -> dict:
        """Return a cached/data-URI thumbnail for a project asset."""
        rel = self._normalize_project_path(relative_path)
        path = (ROOT / rel).resolve()
        if ROOT.resolve() not in path.parents or not path.exists() or not path.is_file():
            return {'ok': False, 'reason': 'missing'}
        cat = self._asset_category_for(path)

        def data_uri(file_path: Path) -> str:
            mime = mimetypes.guess_type(file_path.name)[0] or 'application/octet-stream'
            return f"data:{mime};base64," + base64.b64encode(file_path.read_bytes()).decode('ascii')

        if cat == 'textures':
            try:
                return {'ok': True, 'uri': '../' + rel, 'kind': 'image'}
            except Exception as exc:
                return {'ok': False, 'reason': str(exc)}

        if cat == 'materials':
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                material = data.get('material', data) if isinstance(data, dict) else {}
                tex = self._normalize_project_path(material.get('base_texture')) if isinstance(material, dict) and material.get('base_texture') else ''
                if tex:
                    tex_path = (ROOT / tex).resolve()
                    if tex_path.exists() and tex_path.is_file() and ROOT.resolve() in tex_path.parents:
                        return {'ok': True, 'uri': '../' + tex, 'kind': 'material-texture'}
                color = material.get('base_color', [0.45, 0.55, 0.68, 1.0]) if isinstance(material, dict) else [0.45,0.55,0.68,1.0]
                rgb = [max(0,min(255,round(float(color[i] if i < len(color) else 0.5)*255))) for i in range(3)]
                hx = '#%02x%02x%02x' % tuple(rgb)
                svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="240" height="150">'
                       '<defs><linearGradient id="g" x2="0" y2="1">'
                       f'<stop stop-color="{hx}"/><stop offset="1" stop-color="#111820"/>'
                       '</linearGradient></defs><rect width="240" height="150" fill="#0b1118"/>'
                       '<rect x="14" y="14" width="212" height="122" rx="8" fill="url(#g)" stroke="#607286"/>'
                       f'<circle cx="73" cy="62" r="32" fill="{hx}" stroke="#d9e7f1" stroke-opacity=".35"/>'
                       '<path d="M118 48h86M118 68h68M118 88h78" stroke="#d8e6f0" stroke-opacity=".55" stroke-width="6"/>'
                       '</svg>')
                return {'ok': True, 'uri': 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode()).decode('ascii'), 'kind': 'material'}
            except Exception as exc:
                return {'ok': False, 'reason': str(exc)}

        if cat == 'models':
            try:
                st = path.stat()
                key = hashlib.sha1(f"{rel}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()[:24]
                cache_dir = ROOT / '.panda_editor' / 'thumbnails'
                cache_dir.mkdir(parents=True, exist_ok=True)
                thumb = cache_dir / f'{key}.png'
                if not thumb.exists():
                    worker = ROOT / 'editor' / 'thumbnail_worker.py'
                    proc = subprocess.run([sys.executable, str(worker), str(path), str(thumb)], cwd=str(ROOT), capture_output=True, text=True, timeout=20)
                    if proc.returncode != 0 or not thumb.exists():
                        reason = (proc.stderr or proc.stdout or 'thumbnail render failed').strip()[-1000:]
                        return {'ok': False, 'reason': reason}
                return {'ok': True, 'uri': '../' + thumb.relative_to(ROOT).as_posix(), 'kind': 'model'}
            except subprocess.TimeoutExpired:
                return {'ok': False, 'reason': 'thumbnail render timed out'}
            except Exception as exc:
                return {'ok': False, 'reason': str(exc)}

        if cat in {'prefabs','scenes'}:
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                count = len(data.get('entities') or []) if isinstance(data, dict) else 0
            except Exception:
                count = 0
            label = 'PREFAB' if cat == 'prefabs' else 'SCENE'
            accent = '#67b7ff' if cat == 'prefabs' else '#84aeca'
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="240" height="150">'
                   '<rect width="240" height="150" fill="#0b1118"/>'
                   f'<path d="M38 102V50l43-25 43 25v52l-43 25z" fill="none" stroke="{accent}" stroke-width="4"/>'
                   f'<path d="M81 25v102M38 50l43 25 43-25" stroke="{accent}" stroke-opacity=".55" stroke-width="2"/>'
                   f'<text x="142" y="65" fill="#d7e8f4" font-family="Segoe UI,Arial" font-size="19" font-weight="700">{label}</text>'
                   f'<text x="142" y="91" fill="#7d93a8" font-family="Segoe UI,Arial" font-size="15">{count} entities</text></svg>')
            return {'ok': True, 'uri': 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode()).decode('ascii'), 'kind': cat}

        return {'ok': False, 'reason': 'no_thumbnail'}

    def asset_details(self, relative_path: str) -> dict:
        rel = self._normalize_project_path(relative_path)
        path = (ROOT / rel).resolve()
        if ROOT.resolve() not in path.parents or not path.exists() or not path.is_file():
            return {}
        stat = path.stat()
        refs = self._asset_references(rel)
        return {
            'path': rel, 'name': path.name, 'category': self._asset_category_for(path),
            'extension': path.suffix.lower(), 'size': stat.st_size, 'modified': int(stat.st_mtime),
            'references': refs, 'reference_count': len(refs),
        }

    def import_asset(self, category: str) -> dict:
        category = str(category or '').lower()
        types = {
            'models': ('3D Models (*.glb;*.gltf;*.bam;*.egg)', {'.glb','.gltf','.bam','.egg'}),
            'textures': ('Images (*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.tga)', {'.png','.jpg','.jpeg','.webp','.bmp','.tga'}),
            'audio': ('Audio (*.wav;*.ogg;*.mp3;*.flac)', {'.wav','.ogg','.mp3','.flac'}),
        }
        if category not in types:
            raise ValueError('This asset category cannot be imported from an external file.')
        label, allowed = types[category]
        result = webview.windows[0].create_file_dialog(self._dialog_kind('OPEN'), file_types=(label, 'All files (*.*)'))
        source = self._dialog_first_path(result)
        if source is None:
            return {}
        if source.suffix.lower() not in allowed:
            raise ValueError(f'Unsupported {category} file type.')
        target_dir = ROOT / 'assets' / category
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        index = 2
        while target.exists() and target.resolve() != source.resolve():
            target = target_dir / f'{source.stem}_{index}{source.suffix}'
            index += 1
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        rel = str(target.relative_to(ROOT)).replace('\\', '/')
        self.log(f'Asset imported: {rel}')
        return self.asset_details(rel)

    @staticmethod
    def _write_gray_png(path: Path, width: int, height: int, samples: list[int]) -> None:
        """Write a compact 8-bit grayscale PNG without adding another dependency."""
        def chunk(kind: bytes, data: bytes) -> bytes:
            crc = binascii.crc32(kind + data) & 0xFFFFFFFF
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', crc)
        rows = []
        for y in range(height):
            start = y * width
            rows.append(b'\x00' + bytes(samples[start:start + width]))
        png = (b'\x89PNG\r\n\x1a\n' +
               chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0)) +
               chunk(b'IDAT', zlib.compress(b''.join(rows), 9)) + chunk(b'IEND', b''))
        path.write_bytes(png)


    @staticmethod
    def _read_gray_png(path: Path) -> tuple[int, int, list[int]]:
        """Read editor-generated 8-bit grayscale PNG heightfields.

        Terrain sculpting intentionally targets the editor's generated heightfields.
        Imported images remain valid for GeoMipTerrain, but can be converted to an
        editor-generated heightfield before destructive painting.
        """
        data = path.read_bytes()
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Editable terrain heightfields must be PNG files.')
        pos = 8; width = height = None; color_type = bit_depth = None; payload = bytearray()
        while pos + 8 <= len(data):
            length = struct.unpack('>I', data[pos:pos+4])[0]; kind = data[pos+4:pos+8]
            chunk = data[pos+8:pos+8+length]; pos += 12 + length
            if kind == b'IHDR':
                width, height, bit_depth, color_type, _comp, _filter, _interlace = struct.unpack('>IIBBBBB', chunk)
            elif kind == b'IDAT': payload.extend(chunk)
            elif kind == b'IEND': break
        if not width or not height or bit_depth != 8 or color_type != 0:
            raise ValueError('Terrain sculpting currently requires an 8-bit grayscale PNG generated by Panda Editor.')
        raw = zlib.decompress(bytes(payload)); stride = width
        rows=[]; off=0; previous=[0]*stride
        for _y in range(height):
            filter_type=raw[off]; off+=1; scan=list(raw[off:off+stride]); off+=stride
            recon=[0]*stride
            for x,val in enumerate(scan):
                a=recon[x-1] if x else 0; b=previous[x]; c=previous[x-1] if x else 0
                if filter_type==0: r=val
                elif filter_type==1: r=(val+a)&255
                elif filter_type==2: r=(val+b)&255
                elif filter_type==3: r=(val+((a+b)//2))&255
                elif filter_type==4:
                    pr=a+b-c; pa=abs(pr-a); pb=abs(pr-b); pc=abs(pr-c); predictor=a if pa<=pb and pa<=pc else (b if pb<=pc else c)
                    r=(val+predictor)&255
                else: raise ValueError('Unsupported PNG filter.')
                recon[x]=r
            rows.extend(recon); previous=recon
        return int(width), int(height), rows

    @staticmethod
    def _write_rgba_png(path: Path, width: int, height: int, samples: list[int]) -> None:
        """Write an 8-bit RGBA PNG for terrain splat weights."""
        def chunk(kind: bytes, data: bytes) -> bytes:
            crc = binascii.crc32(kind + data) & 0xFFFFFFFF
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', crc)
        rows=[]
        stride=width*4
        for y in range(height):
            start=y*stride; rows.append(b'\x00'+bytes(samples[start:start+stride]))
        png=(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows),9))+chunk(b'IEND',b''))
        path.write_bytes(png)

    @staticmethod
    def _read_rgba_png(path: Path) -> tuple[int,int,list[int]]:
        data=path.read_bytes()
        if not data.startswith(b'\x89PNG\r\n\x1a\n'): raise ValueError('Splat map must be a PNG file.')
        pos=8; width=height=None; payload=bytearray(); bit_depth=color_type=None
        while pos+8<=len(data):
            length=struct.unpack('>I',data[pos:pos+4])[0]; kind=data[pos+4:pos+8]; chunk=data[pos+8:pos+8+length]; pos+=12+length
            if kind==b'IHDR': width,height,bit_depth,color_type,_c,_f,_i=struct.unpack('>IIBBBBB',chunk)
            elif kind==b'IDAT': payload.extend(chunk)
            elif kind==b'IEND': break
        if not width or not height or bit_depth!=8 or color_type!=6: raise ValueError('Terrain material painting requires an 8-bit RGBA splat PNG.')
        raw=zlib.decompress(bytes(payload)); stride=width*4; rows=[]; off=0; previous=[0]*stride
        for _y in range(height):
            ft=raw[off]; off+=1; scan=list(raw[off:off+stride]); off+=stride; recon=[0]*stride
            for x,val in enumerate(scan):
                a=recon[x-4] if x>=4 else 0; b=previous[x]; c=previous[x-4] if x>=4 else 0
                if ft==0:r=val
                elif ft==1:r=(val+a)&255
                elif ft==2:r=(val+b)&255
                elif ft==3:r=(val+((a+b)//2))&255
                elif ft==4:
                    pr=a+b-c; pa=abs(pr-a); pb=abs(pr-b); pc=abs(pr-c); pred=a if pa<=pb and pa<=pc else (b if pb<=pc else c); r=(val+pred)&255
                else: raise ValueError('Unsupported PNG filter.')
                recon[x]=r
            rows.extend(recon); previous=recon
        return int(width),int(height),rows

    def create_terrain_splatmap(self, entity_id: str, resolution: int = 256) -> dict:
        ent=self.scene.entities.get(str(entity_id)); terrain=(ent.components if ent else {}).get('terrain') or {}
        if not ent or not terrain: return {'ok':False,'reason':'no_terrain'}
        res=max(64,min(1024,int(resolution or 256))); folder=ROOT/'assets'/'textures'; folder.mkdir(parents=True,exist_ok=True)
        base='terrain_splat_'+''.join(c for c in ent.name.lower().replace(' ','_') if c.isalnum() or c=='_'); target=folder/f'{base}.png'; i=2
        while target.exists(): target=folder/f'{base}_{i}.png'; i+=1
        samples=[]
        for _ in range(res*res): samples.extend((255,0,0,0))
        self._write_rgba_png(target,res,res,samples); rel=target.relative_to(ROOT).as_posix()
        baked_target=target.with_name(target.stem+'_painted.png'); baked_rel=baked_target.relative_to(ROOT).as_posix()
        mp=copy.deepcopy(terrain.get('material_paint') or {}); mp['enabled']=True; mp['splatmap']=rel; mp['baked_albedo']=baked_rel; mp.setdefault('texture_scale',8.0); terrain['material_paint']=mp
        ent.components['terrain']=terrain; self.scene.dirty=True; self.viewport.runtime.refresh_terrain(ent.id)
        self.log(f'Terrain splat map created: {rel} ({res}x{res})')
        return {'ok':True,'path':rel,'asset':self.asset_details(rel)}

    def terrain_material_info(self, entity_id: str) -> dict:
        ent=self.scene.entities.get(str(entity_id)); terrain=(ent.components if ent else {}).get('terrain') or {}; mp=terrain.get('material_paint') or {}
        rel=self._normalize_project_path(mp.get('splatmap')); path=(ROOT/rel).resolve() if rel else None
        if not path or not path.is_file(): return {'editable':False,'reason':'missing_splatmap','path':rel}
        try:w,h,_=self._read_rgba_png(path)
        except Exception as exc:return {'editable':False,'reason':'format','path':rel,'message':str(exc)}
        return {'editable':True,'path':rel,'width':w,'height':h,'layers':copy.deepcopy(mp.get('layers') or [])}

    def terrain_edit_info(self, entity_id: str) -> dict:
        ent=self.scene.entities.get(str(entity_id))
        terrain=(ent.components if ent else {}).get('terrain') or {}
        if not ent or not terrain:
            return {'editable':False,'reason':'no_terrain'}
        rel=self._normalize_project_path(terrain.get('heightfield'))
        path=(ROOT/rel).resolve() if rel else None
        if not path or not path.is_file():
            return {'editable':False,'reason':'missing_heightfield','path':rel}
        try:
            w,h,_=self._read_gray_png(path)
        except Exception as exc:
            return {'editable':False,'reason':'format','path':rel,'message':str(exc)}
        return {'editable':True,'path':rel,'width':w,'height':h}

    def _apply_terrain_brush(self, samples: list[int], width: int, height: int, cx: float, cy: float, radius_px: float, mode: str, strength: float, falloff: float, flatten_value: float | None) -> None:
        radius=max(1.0,float(radius_px)); strength=max(0.0,min(1.0,float(strength))); falloff=max(0.05,min(1.0,float(falloff)))
        xmin=max(0,int(math.floor(cx-radius))); xmax=min(width-1,int(math.ceil(cx+radius)))
        ymin=max(0,int(math.floor(cy-radius))); ymax=min(height-1,int(math.ceil(cy+radius)))
        source=samples[:] if mode=='smooth' else samples
        if mode=='flatten' and flatten_value is None:
            ix=max(0,min(width-1,round(cx))); iy=max(0,min(height-1,round(cy))); flatten_value=float(samples[iy*width+ix])
        for py in range(ymin,ymax+1):
            for px in range(xmin,xmax+1):
                d=math.hypot(px-cx,py-cy)
                if d>radius: continue
                t=max(0.0,1.0-d/radius)
                weight=(t ** (1.0/max(.05,falloff))) * strength
                idx=py*width+px; old=float(samples[idx])
                if mode=='raise': target=255.0
                elif mode=='lower': target=0.0
                elif mode=='flatten': target=float(flatten_value if flatten_value is not None else old)
                elif mode=='smooth':
                    total=count=0
                    for oy in (-1,0,1):
                        sy=max(0,min(height-1,py+oy))
                        for ox in (-1,0,1):
                            sx=max(0,min(width-1,px+ox)); total+=source[sy*width+sx]; count+=1
                    target=total/max(1,count)
                else: continue
                samples[idx]=max(0,min(255,round(old+(target-old)*weight*.18)))

    def terrain_brush_stroke(self, entity_id: str, phase: str, local_x: float = 0.0, local_y: float = 0.0, mode: str = 'raise', radius: float = 4.0, strength: float = 0.5, falloff: float = 0.65, flatten_level: float | None = None) -> dict:
        """Apply one interactive authoring stroke to a generated heightfield."""
        eid=str(entity_id); phase=str(phase or 'move').lower(); mode=str(mode or 'raise').lower()
        ent=self.scene.entities.get(eid); terrain=(ent.components if ent else {}).get('terrain') or {}
        if not ent or not terrain: return {'ok':False,'reason':'no_terrain'}
        if mode.startswith('paint'):
            try: layer=max(0,min(3,int(mode[5:] or 0)))
            except Exception: layer=0
            mp=terrain.get('material_paint') or {}; rel=self._normalize_project_path(mp.get('splatmap')); path=(ROOT/rel).resolve() if rel else None
            if not path or not path.is_file(): return {'ok':False,'reason':'missing_splatmap'}
            key=eid+':material'; stroke=self._terrain_edit_strokes.get(key)
            if phase=='start' or stroke is None:
                try:w,h,samples=self._read_rgba_png(path)
                except Exception as exc:return {'ok':False,'reason':'format','message':str(exc)}
                stroke={'path':path,'before':path.read_bytes(),'width':w,'height':h,'samples':samples}; self._terrain_edit_strokes[key]=stroke
            w=int(stroke['width']); h=int(stroke['height']); size=list(terrain.get('size') or [64,64])+[64,64]; sx=max(.001,float(size[0])); sy=max(.001,float(size[1]))
            px=max(0.0,min(w-1,(float(local_x)/sx)*(w-1))); py=max(0.0,min(h-1,(1.0-(float(local_y)/sy))*(h-1))); radius_px=max(1.0,float(radius)*.5*((w-1)/sx+(h-1)/sy))
            rr=max(1.0,radius_px); st=max(.0,min(1.0,float(strength))); fo=max(.05,min(1.0,float(falloff))); xmin=max(0,int(math.floor(px-rr))); xmax=min(w-1,int(math.ceil(px+rr))); ymin=max(0,int(math.floor(py-rr))); ymax=min(h-1,int(math.ceil(py+rr)))
            for yy in range(ymin,ymax+1):
                for xx in range(xmin,xmax+1):
                    d=math.hypot(xx-px,yy-py)
                    if d>rr: continue
                    weight=(max(0.0,1.0-d/rr)**(1.0/fo))*st*.28; idx=(yy*w+xx)*4; vals=[float(v) for v in stroke['samples'][idx:idx+4]]; vals[layer]=vals[layer]+(255.0-vals[layer])*weight
                    other=sum(vals[i] for i in range(4) if i!=layer)
                    target_other=max(0.0,255.0-vals[layer])
                    if other>0:
                        scale=target_other/other
                        for i in range(4):
                            if i!=layer: vals[i]*=scale
                    else:
                        for i in range(4):
                            if i!=layer: vals[i]=target_other/3.0
                    q=[max(0,min(255,round(v))) for v in vals]; delta=255-sum(q); q[layer]=max(0,min(255,q[layer]+delta)); stroke['samples'][idx:idx+4]=q
            # 0.4.8: live paint feedback is handled in Panda memory by the viewport.
            # Persist the RGBA splat map once at stroke end instead of PNG encode + full
            # terrain rebuild for every mouse sample.
            if phase=='end':
                self._write_rgba_png(path,w,h,stroke['samples'])
                after=path.read_bytes(); before=stroke['before']; self._terrain_edit_strokes.pop(key,None)
                if after!=before:
                    def apply_bytes(blob: bytes): path.write_bytes(blob); self.viewport.runtime.refresh_terrain(eid); self.scene.dirty=True
                    self.commands.execute(LambdaCommand(f'Terrain Material Layer {layer+1} Stroke',lambda:apply_bytes(after),lambda:apply_bytes(before))); self.scene.dirty=True
                return {'ok':True,'committed':after!=before}
            return {'ok':True,'committed':False}
        rel=self._normalize_project_path(terrain.get('heightfield')); path=(ROOT/rel).resolve() if rel else None
        if not path or not path.is_file(): return {'ok':False,'reason':'missing_heightfield'}
        stroke=self._terrain_edit_strokes.get(eid)
        if phase=='start' or stroke is None:
            try: w,h,samples=self._read_gray_png(path)
            except Exception as exc: return {'ok':False,'reason':'format','message':str(exc)}
            stroke={'path':path,'before':path.read_bytes(),'width':w,'height':h,'samples':samples,'flatten':None,'last_flush':0.0}
            self._terrain_edit_strokes[eid]=stroke
        w=int(stroke['width']); h=int(stroke['height']); size=list(terrain.get('size') or [64,64])+[64,64]
        sx=max(.001,float(size[0])); sy=max(.001,float(size[1]))
        px=max(0.0,min(w-1,(float(local_x)/sx)*(w-1)))
        # GeoMipTerrain/PNM terrain-space Y increases in the opposite direction to
        # serialized PNG scanlines (PNG row 0 is the top row).  The viewport brush
        # hit is already in correct Terrain-local coordinates, so only the raw PNG
        # authoring row must be mirrored here.  Without this conversion sculpting
        # appears on the opposite side of the visible terrain from the brush cursor.
        py=max(0.0,min(h-1,(1.0-(float(local_y)/sy))*(h-1)))
        radius_px=max(1.0,float(radius)*.5*((w-1)/sx+(h-1)/sy))
        if mode=='flatten' and stroke.get('flatten') is None:
            stroke['flatten']=float(stroke['samples'][max(0,min(h-1,round(py)))*w+max(0,min(w-1,round(px)))]) if flatten_level is None else max(0,min(255,float(flatten_level)*255.0))
        self._apply_terrain_brush(stroke['samples'],w,h,px,py,radius_px,mode,strength,falloff,stroke.get('flatten'))
        # High-resolution heightfields made the old per-mouse-event PNG encode + GeoMip
        # rebuild noticeably hitch.  Coalesce authoring refreshes while dragging and always
        # flush the final stroke state on mouse-up.
        now=time.perf_counter(); due=(phase=='end' or now-float(stroke.get('last_flush',0.0))>=0.065)
        if due:
            self._write_gray_png(path,w,h,stroke['samples']); stroke['last_flush']=now
            self.viewport.runtime.refresh_terrain(eid)
        if phase=='end':
            after=path.read_bytes(); before=stroke['before']; self._terrain_edit_strokes.pop(eid,None)
            if after!=before:
                def apply_bytes(blob: bytes):
                    path.write_bytes(blob); self.viewport.runtime.refresh_terrain(eid); self.scene.dirty=True
                self.commands.execute(LambdaCommand(f'Terrain {mode.title()} Stroke', lambda: apply_bytes(after), lambda: apply_bytes(before)))
                self.scene.dirty=True
            return {'ok':True,'committed':after!=before}
        return {'ok':True,'committed':False}


    def refine_terrain_heightfield(self, entity_id: str, resolution: int = 513) -> dict:
        """Create a higher-resolution editable copy of the selected terrain heightfield.

        The source asset is never overwritten. Bilinear interpolation preserves the current
        landscape shape while increasing the number of editable GeoMip vertices/quads.
        """
        ent=self.scene.entities.get(str(entity_id)); terrain=(ent.components if ent else {}).get('terrain') or {}
        if not ent or not terrain: return {'ok':False,'reason':'no_terrain'}
        rel=self._normalize_project_path(terrain.get('heightfield')); src=(ROOT/rel).resolve() if rel else None
        if not src or not src.is_file(): return {'ok':False,'reason':'missing_heightfield'}
        try: sw,sh,samples=self._read_gray_png(src)
        except Exception as exc: return {'ok':False,'reason':'format','message':str(exc)}
        target=int(resolution or 513)
        allowed=(65,129,257,513,1025,2049)
        target=min(allowed,key=lambda v:abs(v-target))
        if target <= max(sw,sh):
            return {'ok':False,'reason':'not_higher','message':f'Choose a resolution above the current {sw}x{sh} heightfield.'}
        out=[0]*(target*target)
        for y in range(target):
            sy=(y/(target-1))*max(1,sh-1); y0=int(math.floor(sy)); y1=min(sh-1,y0+1); fy=sy-y0
            for x in range(target):
                sx=(x/(target-1))*max(1,sw-1); x0=int(math.floor(sx)); x1=min(sw-1,x0+1); fx=sx-x0
                a=samples[y0*sw+x0]*(1-fx)+samples[y0*sw+x1]*fx
                b=samples[y1*sw+x0]*(1-fx)+samples[y1*sw+x1]*fx
                out[y*target+x]=max(0,min(255,round(a*(1-fy)+b*fy)))
        folder=ROOT/'assets'/'textures'; folder.mkdir(parents=True,exist_ok=True)
        base=(src.stem+f'_refined_{target}'); dest=folder/(base+'.png'); i=2
        while dest.exists(): dest=folder/(f'{base}_{i}.png'); i+=1
        self._write_gray_png(dest,target,target,out); new_rel=dest.relative_to(ROOT).as_posix()
        terrain=copy.deepcopy(terrain); terrain['heightfield']=new_rel; ent.components['terrain']=terrain; self.scene.dirty=True
        self.viewport.runtime.refresh_terrain(ent.id)
        self.log(f'Terrain heightfield refined: {sw}x{sh} -> {target}x{target}: {new_rel}')
        return {'ok':True,'path':new_rel,'width':target,'height':target,'asset':self.asset_details(new_rel)}

    def create_terrain_heightfield(self, preset: str = 'rolling', resolution: int = 257, name: str = '') -> dict:
        """Create a project-local grayscale heightfield for Terrain authoring."""
        preset = str(preset or 'rolling').lower()
        if preset not in {'flat','rolling','ridge','island'}:
            preset = 'rolling'
        requested = max(33, min(513, int(resolution or 129)))
        # GeoMipTerrain works best with power-of-two + 1 dimensions.
        candidates = [33,65,129,257,513]
        resolution = min(candidates, key=lambda x: abs(x-requested))
        values: list[int] = []
        for y in range(resolution):
            ny = (y / (resolution - 1)) * 2.0 - 1.0
            for x in range(resolution):
                nx = (x / (resolution - 1)) * 2.0 - 1.0
                if preset == 'flat':
                    value = 0.22
                elif preset == 'ridge':
                    value = 0.14 + 0.62 * math.exp(-(nx * nx) * 10.0) * (0.62 + 0.38 * math.cos(ny * 5.0))
                    value += 0.05 * math.sin(ny * 9.0)
                elif preset == 'island':
                    r = math.sqrt(nx*nx + ny*ny)
                    value = max(0.0, 0.72 * (1.0-r)) + 0.08*math.sin(nx*8.0)*math.cos(ny*7.0)
                else:
                    value = 0.18 + 0.42*math.exp(-((nx+0.28)**2+(ny-0.12)**2)*4.5)
                    value += 0.22*math.exp(-((nx-0.38)**2+(ny+0.30)**2)*9.0)
                    value += 0.06*math.sin(nx*7.0)*math.cos(ny*6.0)
                values.append(max(0, min(255, round(max(0.0,min(1.0,value))*255))))
        folder = ROOT / 'assets' / 'textures'; folder.mkdir(parents=True, exist_ok=True)
        base = Path(str(name or f'terrain_{preset}_{resolution}')).stem
        clean = ''.join(c for c in base if c not in '<>:"/\\|?*').strip().strip('.') or 'terrain_heightfield'
        target = folder / f'{clean}.png'; i = 2
        while target.exists():
            target = folder / f'{clean}_{i}.png'; i += 1
        self._write_gray_png(target, resolution, resolution, values)
        rel = target.relative_to(ROOT).as_posix()
        self.log(f'Terrain heightfield created: {rel} ({resolution}x{resolution}, {preset})')
        return {'ok': True, 'asset': self.asset_details(rel), 'preset': preset, 'resolution': resolution}

    def save_material_preset(self, entity_id: str, name: str = '') -> dict:
        ent = self.scene.entities.get(entity_id)
        material = copy.deepcopy((ent.components if ent else {}).get('material') or {})
        if not ent or not material:
            return {'ok': False, 'reason': 'no_material'}
        folder = ROOT / 'assets' / 'materials'
        folder.mkdir(parents=True, exist_ok=True)
        raw = Path(str(name or f'{ent.name}_Material')).stem
        clean = ''.join(c for c in raw if c not in '<>:"/\\|?*').strip().strip('.') or 'Material'
        path = folder / f'{clean}.pmat.json'
        i = 2
        while path.exists():
            path = folder / f'{clean}_{i}.pmat.json'; i += 1
        payload = {'format':'panda_editor_material','version':1,'name':clean,'material':material}
        path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        rel = path.relative_to(ROOT).as_posix()
        self.log(f'Material preset created: {rel}')
        return {'ok': True, 'asset': self.asset_details(rel)}

    def load_material_asset(self, relative_path: str) -> dict:
        """Read a project material preset for the Material/Shader browser without mutating the scene."""
        rel = self._normalize_project_path(relative_path)
        path = (ROOT / rel).resolve()
        materials_root = (ROOT / 'assets' / 'materials').resolve()
        if materials_root not in path.parents or not path.is_file():
            raise ValueError('Invalid material asset.')
        data = json.loads(path.read_text(encoding='utf-8'))
        material = copy.deepcopy(data.get('material') or data)
        if not isinstance(material, dict):
            raise ValueError('Invalid material preset.')
        return {'ok': True, 'path': rel, 'name': str(data.get('name') or path.stem), 'material': material}

    def apply_material_asset(self, entity_id: str, relative_path: str) -> dict:
        ent = self.scene.entities.get(entity_id)
        if not ent:
            return {}
        rel = self._normalize_project_path(relative_path)
        path = (ROOT / rel).resolve()
        materials_root = (ROOT / 'assets' / 'materials').resolve()
        if materials_root not in path.parents or not path.is_file():
            raise ValueError('Invalid material asset.')
        data = json.loads(path.read_text(encoding='utf-8'))
        material = copy.deepcopy(data.get('material') or data)
        if not isinstance(material, dict):
            raise ValueError('Invalid material preset.')
        return self.update_component(entity_id, 'material', material)

    def instantiate_model_asset(self, relative_path: str) -> dict:
        rel = self._normalize_project_path(relative_path)
        path = (ROOT / rel).resolve()
        models_root = (ROOT / 'assets' / 'models').resolve()
        if models_root not in path.parents or path.suffix.lower() not in self._ASSET_EXTENSIONS['models'] or not path.exists():
            raise ValueError('Invalid model asset.')
        ent = Entity(path.stem)
        ent.components['model'] = {'asset': rel}
        self.scene.add(ent)
        self.selected_id = ent.id
        self._changed()
        self.viewport.runtime.select(ent.id)
        return ent.to_dict()

    def rename_asset(self, relative_path: str, new_name: str) -> dict:
        rel = self._normalize_project_path(relative_path)
        source = (ROOT / rel).resolve()
        if ROOT.resolve() not in source.parents or not source.exists():
            return {'ok': False, 'reason': 'missing'}
        clean = Path(str(new_name or '')).name.strip()
        if not clean:
            return {'ok': False, 'reason': 'name'}
        if Path(clean).suffix == '':
            clean += source.suffix
        if Path(clean).suffix.lower() != source.suffix.lower():
            return {'ok': False, 'reason': 'extension'}
        target = source.with_name(clean)
        if target.exists() and target != source:
            return {'ok': False, 'reason': 'exists'}
        old_rel = rel
        source.rename(target)
        new_rel = str(target.relative_to(ROOT)).replace('\\', '/')
        # Keep scene references intact when project resources move.
        for ent in self.scene.entities.values():
            script = ent.components.get('script') or {}
            audio = ent.components.get('audio_source') or {}
            model = ent.components.get('model') or {}
            prefab = ent.components.get('prefab_instance') or {}
            material = ent.components.get('material') or {}
            ui = ent.components.get('ui') or {}
            terrain = ent.components.get('terrain') or {}
            if self._normalize_project_path(script.get('path')) == old_rel: script['path'] = new_rel
            if self._normalize_project_path(audio.get('clip')) == old_rel: audio['clip'] = new_rel
            if self._normalize_project_path(model.get('asset')) == old_rel: model['asset'] = new_rel
            if self._normalize_project_path(prefab.get('source')) == old_rel: prefab['source'] = new_rel
            for key in ('base_texture','metal_rough_texture','normal_texture','emission_texture','occlusion_texture'):
                if self._normalize_project_path(material.get(key)) == old_rel: material[key] = new_rel
            if self._normalize_project_path(ui.get('image')) == old_rel: ui['image'] = new_rel
            if self._normalize_project_path(terrain.get('heightfield')) == old_rel: terrain['heightfield'] = new_rel
            mp = terrain.get('material_paint') or {}
            if self._normalize_project_path(mp.get('splatmap')) == old_rel: mp['splatmap'] = new_rel
            if self._normalize_project_path(mp.get('baked_albedo')) == old_rel: mp['baked_albedo'] = new_rel
            for layer in mp.get('layers') or []:
                if self._normalize_project_path((layer or {}).get('albedo')) == old_rel: layer['albedo'] = new_rel
        self.scene.dirty = True
        self._changed()
        self.log(f'Asset renamed: {old_rel} -> {new_rel}')
        return {'ok': True, 'asset': self.asset_details(new_rel)}

    def delete_asset(self, relative_path: str) -> dict:
        rel = self._normalize_project_path(relative_path)
        path = (ROOT / rel).resolve()
        if ROOT.resolve() not in path.parents or not path.exists() or not path.is_file():
            return {'ok': False, 'reason': 'missing'}
        refs = self._asset_references(rel)
        if refs:
            return {'ok': False, 'reason': 'referenced', 'references': refs}
        # Protect shipped templates from accidental deletion through the browser.
        if rel.startswith('project_templates/'):
            return {'ok': False, 'reason': 'protected'}
        path.unlink()
        self.log(f'Asset deleted: {rel}')
        return {'ok': True}

    def reveal_asset(self, relative_path: str) -> bool:
        rel = self._normalize_project_path(relative_path)
        path = (ROOT / rel).resolve()
        if not path.exists():
            return False
        try:
            if os.name == 'nt':
                os.system(f'explorer /select,"{path}"')
            else:
                os.system(f'xdg-open "{path.parent}" >/dev/null 2>&1 &')
            return True
        except Exception:
            return False

    def preview_audio_asset(self, relative_path: str) -> dict:
        rel = self._normalize_project_path(relative_path)
        path = (ROOT / rel).resolve()
        if ROOT.resolve() not in path.parents or not path.is_file() or path.suffix.lower() not in self._ASSET_EXTENSIONS['audio']:
            return {'ok': False, 'reason': 'invalid_audio'}
        self.viewport.preview_audio(rel)
        self.log(f'Audio preview requested: {rel}')
        return {'ok': True, 'path': rel}

    def stop_audio_preview(self) -> bool:
        self.viewport.stop_audio_preview()
        return True

    def validate_project(self) -> dict:
        """Lightweight build/readiness validation; does not mutate project content."""
        issues: list[dict] = []
        warnings: list[dict] = []
        checked = 0
        for ent in self.scene.entities.values():
            comps = ent.components or {}
            for comp_name, key, label in [
                ('model','asset','Model'), ('audio_source','clip','Audio'),
                ('script','path','Script'), ('prefab_instance','source','Prefab'), ('material','base_texture','Texture'), ('ui','image','UI Image'), ('particle_emitter','texture','Particle Texture')
            ]:
                comp = comps.get(comp_name) or {}
                raw = str(comp.get(key) or '').strip()
                if not raw:
                    continue
                checked += 1
                rel = self._normalize_project_path(raw)
                path = (ROOT / rel).resolve()
                if ROOT.resolve() not in path.parents or not path.exists():
                    issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':label,'path':rel,'message':f'Missing {label.lower()} resource'})
            if 'material' in comps:
                material = comps.get('material') or {}
                try:
                    scale=list(material.get('uv_scale') or [1,1])+[1,1]
                    if float(scale[0]) == 0 or float(scale[1]) == 0:
                        issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Material','path':'','message':'Texture UV Scale U/V must be non-zero.'})
                    if str(material.get('wrap_u','repeat')).lower() not in {'repeat','clamp','mirror','border'} or str(material.get('wrap_v','repeat')).lower() not in {'repeat','clamp','mirror','border'}:
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Material','path':'','message':'Unknown texture wrap mode; Repeat will be used at runtime.'})
                    if str(material.get('min_filter','trilinear')).lower() not in {'nearest','linear','trilinear'} or str(material.get('mag_filter','linear')).lower() not in {'nearest','linear'}:
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Material','path':'','message':'Unknown texture filtering mode; Linear/Trilinear defaults will be used.'})
                    policy=str(material.get('shader_policy') or ('inherit' if bool(material.get('shader_auto',True)) else 'off')).lower()
                    if policy not in {'inherit','panda_auto','off'}:
                        issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Material','path':'','message':'Unknown Material Shader Policy. Use inherit, panda_auto or off.'})
                    pipeline=str(self.project_settings.world_render_pipeline or 'builtin').lower()
                    if pipeline in {'simplepbr','complexpbr'} and policy == 'panda_auto':
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Material','path':'','message':f'Force Panda Auto Shader overrides the selected {pipeline} PBR shader on this object. Inherit is recommended.'})
                    if pipeline in {'simplepbr','complexpbr'} and policy == 'off' and not bool(material.get('unlit',False)):
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Material','path':'','message':f'Shader Off bypasses the selected {pipeline} PBR shader on this object. Use Inherit for normal lit materials.'})
                except Exception:
                    issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Material','path':'','message':'Material texture transform values must be numeric.'})
            if 'particle_emitter' in comps:
                fx = comps.get('particle_emitter') or {}
                renderer = str(fx.get('renderer_type','sprite') or 'sprite').lower()
                factory = str(fx.get('factory_type','point') or 'point').lower()
                shape = str(fx.get('shape','point') or 'point').lower()
                if renderer not in {'sprite','point','line','sparkle','geom'}:
                    issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Particle Emitter','path':'','message':'Unknown particle renderer. Use sprite, point, line, sparkle or geom.'})
                if factory not in {'point','zspin'}:
                    issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Particle Emitter','path':'','message':'Unknown particle factory. Use point or zspin.'})
                if shape not in {'point','box','disc','rectangle','ring','sphere','sphere_surface','sphere_volume','tangent_ring','cone'}:
                    issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Particle Emitter','path':'','message':'Unknown particle emitter shape.'})
                if renderer == 'geom':
                    model = str(fx.get('renderer_model') or '').strip()
                    if not model:
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Particle Emitter','path':'','message':'Geom renderer has no Renderer Model assigned.'})
                    else:
                        checked += 1
                        rel = self._normalize_project_path(model); path = (ROOT / rel).resolve()
                        if ROOT.resolve() not in path.parents or not path.exists():
                            issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Particle Geom','path':rel,'message':'Missing particle renderer model'})
                if renderer == 'sprite' and not str(fx.get('texture') or '').strip():
                    warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Particle Emitter','path':'','message':'Sprite renderer has no texture assigned; it will render as a plain card.'})

            if 'audio_source' in comps:
                audio = comps.get('audio_source') or {}
                clip = str(audio.get('clip') or '').strip()
                if clip and Path(clip).suffix.lower() == '.mp3' and bool(audio.get('spatial', True)):
                    warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Audio','path':clip,'message':'Spatial MP3 may be stereo; mono WAV/OGG is recommended for 3D audio.'})
            if 'ui' in comps:
                ui = comps.get('ui') or {}
                kind = str(ui.get('type') or 'label').lower()
                size = list(ui.get('size') or [0, 0]) + [0, 0]
                if kind != 'canvas' and (float(size[0] or 0) < 8 or float(size[1] or 0) < 8):
                    issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Game UI','path':'','message':'UI width and height must be at least 8 px.'})
                if kind == 'slider':
                    try:
                        mn = float(ui.get('min_value', 0)); mx = float(ui.get('max_value', 100)); val = float(ui.get('value', mn))
                        if mx <= mn:
                            issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Game UI','path':'','message':'Slider Max must be greater than Min.'})
                        elif val < mn or val > mx:
                            warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Game UI','path':'','message':'Slider Value is outside Min/Max and will be clamped at runtime.'})
                    except Exception:
                        issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Game UI','path':'','message':'Slider Min/Max/Value must be numeric.'})
                if kind == 'progress':
                    try:
                        rng = float(ui.get('range', 100)); val = float(ui.get('value', 0))
                        if rng <= 0:
                            issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Game UI','path':'','message':'Progress Range must be greater than zero.'})
                        elif val < 0 or val > rng:
                            warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Game UI','path':'','message':'Progress Value is outside its Range and will be clamped at runtime.'})
                    except Exception:
                        issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Game UI','path':'','message':'Progress Range/Value must be numeric.'})
                if kind == 'dropdown':
                    opts = [str(x) for x in (ui.get('options') or [])]
                    if not opts:
                        issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Game UI','path':'','message':'Dropdown needs at least one option.'})
                    else:
                        try:
                            idx = int(ui.get('selected_index', 0) or 0)
                            if idx < 0 or idx >= len(opts):
                                warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Game UI','path':'','message':'Dropdown Selected Index is outside the option list.'})
                        except Exception:
                            issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Game UI','path':'','message':'Dropdown Selected Index must be numeric.'})
                if kind == 'radio' and not str(ui.get('group') or '').strip():
                    warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Game UI','path':'','message':'Radio control has no group name.'})
            if 'light' in comps:
                light = comps.get('light') or {}; lt=str(light.get('type','point')).lower()
                if lt not in {'point','spot','directional'}:
                    issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Light','path':'','message':f'Unsupported light type: {lt}'})
                if lt in {'point','spot'} and float(light.get('range',0) or 0) <= 0:
                    issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Light','path':'','message':'Point/Spot light Range must be greater than zero.'})
                if lt == 'spot':
                    try:
                        fov=float(light.get('fov',45)); exp=float(light.get('exponent',8))
                        if fov <= 0 or fov >= 180: issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Light','path':'','message':'Spot Light FOV must be between 1 and 175 degrees.'})
                        if exp < 0: issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Light','path':'','message':'Spot Light exponent cannot be negative.'})
                    except Exception:
                        issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Light','path':'','message':'Spot Light FOV/exponent must be numeric.'})
                if bool(light.get('cast_shadows',False)):
                    try:
                        res=int(light.get('shadow_resolution',1024) or 1024)
                        if res < 128 or res > 4096:
                            warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Light','path':'','message':'Shadow Resolution should normally be between 128 and 4096.'})
                    except Exception:
                        issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Light','path':'','message':'Shadow Resolution must be numeric.'})
                    pipeline=str(self.project_settings.world_render_pipeline or 'builtin').lower()
                    if pipeline == 'simplepbr' and lt == 'point':
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Light','path':'','message':'simplepbr does not support Point Light shadow casters. This shadow request will be disabled at runtime; use Spot or Directional for shadows.'})
                    if lt == 'directional':
                        try:
                            area=float(light.get('shadow_area',40) or 40); near=float(light.get('shadow_near',.1) or .1); far=float(light.get('shadow_far',120) or 120)
                            if area <= 0: issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Light','path':'','message':'Directional shadow area must be greater than zero.'})
                            if far <= near: issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Light','path':'','message':'Directional shadow Far must be greater than Near.'})
                        except Exception:
                            issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Light','path':'','message':'Directional shadow area/near/far values must be numeric.'})
            if 'rigid_body' in comps and 'collider' not in comps:
                warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Physics','path':'','message':'Rigid Body has no Collider component.'})
            if 'animation' in comps and 'model' not in comps:
                warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Animation','path':'','message':'Animation component has no Model component to load as a Panda3D Actor.'})
            if 'terrain' in comps:
                terrain = comps.get('terrain') or {}
                heightfield = str(terrain.get('heightfield') or '').strip()
                if not heightfield:
                    issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Terrain','path':'','message':'Terrain has no heightfield image.'})
                else:
                    hp = (ROOT / self._normalize_project_path(heightfield)).resolve()
                    if ROOT.resolve() not in hp.parents or not hp.exists():
                        issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Terrain','path':heightfield,'message':'Missing terrain heightfield image.'})
                    elif hp.suffix.lower() not in {'.png','.jpg','.jpeg','.bmp','.tga','.pgm','.ppm'}:
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Terrain','path':heightfield,'message':'PNM-compatible grayscale/image heightfield recommended (PNG/BMP/PGM).'} )
                size = list(terrain.get('size') or [0,0]) + [0,0]
                if float(size[0] or 0) <= 0 or float(size[1] or 0) <= 0:
                    issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Terrain','path':'','message':'Terrain world size must be greater than zero.'})
                try:
                    block = int(terrain.get('block_size',32))
                    if block < 2 or (block & (block - 1)) != 0:
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Terrain','path':'','message':'GeoMipTerrain block size should be a power of two (for example 16, 32 or 64).'})
                except Exception:
                    pass
                mp = terrain.get('material_paint') or {}
                if mp.get('enabled'):
                    splat = str(mp.get('splatmap') or '').strip()
                    if not splat:
                        issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Terrain Material','path':'','message':'Terrain material painting is enabled but no RGBA splat map is assigned.'})
                    else:
                        sp = (ROOT / self._normalize_project_path(splat)).resolve()
                        if ROOT.resolve() not in sp.parents or not sp.exists():
                            issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Terrain Material','path':splat,'message':'Missing terrain material splat map.'})
                    layers = list(mp.get('layers') or [])
                    if len(layers) < 4:
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Terrain Material','path':'','message':'Terrain material painting expects four RGBA layer definitions.'})
                    for i, layer in enumerate(layers[:4]):
                        tex = str((layer or {}).get('albedo') or '').strip()
                        if not tex:
                            warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Terrain Material','path':'','message':f'Terrain material layer {i+1} has no albedo texture.'})
                            continue
                        tp = (ROOT / self._normalize_project_path(tex)).resolve()
                        if ROOT.resolve() not in tp.parents or not tp.exists():
                            issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Terrain Material','path':tex,'message':f'Missing terrain layer {i+1} albedo texture.'})
            if 'lod' in comps:
                lod = comps.get('lod') or {}
                try:
                    near = float(lod.get('near',0.0)); far = float(lod.get('far',250.0))
                    if near < 0 or far < 0:
                        issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'LOD','path':'','message':'LOD near/far distances cannot be negative.'})
                    elif far < near:
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'LOD','path':'','message':'LOD far distance is less than near distance; runtime will clamp far to near.'})
                except Exception:
                    issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'LOD','path':'','message':'LOD near/far settings must be numeric.'})
            if 'fsm' in comps:
                fsm = comps.get('fsm') or {}
                states = [str(x.get('name') or '').strip() for x in (fsm.get('states') or []) if str(x.get('name') or '').strip()]
                state_set = set(states)
                initial = str(fsm.get('initial_state') or '').strip()
                if not states:
                    warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'FSM','path':'','message':'FSM has no states.'})
                elif initial not in state_set:
                    warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'FSM','path':'','message':'FSM initial state does not match an authored state.'})
                for tr in fsm.get('transitions') or []:
                    src = str(tr.get('from') or '*').strip() or '*'
                    dst = str(tr.get('to') or '').strip()
                    sig = str(tr.get('signal') or '').strip()
                    if not sig or not dst or (src != '*' and src not in state_set) or dst not in state_set:
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'FSM','path':'','message':f'Invalid FSM transition: {src} --{sig or "?"}--> {dst or "?"}'})
                if any(str(x.get('animation_clip') or '').strip() for x in (fsm.get('states') or [])) and 'animation' not in comps:
                    warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'FSM','path':'','message':'FSM maps animation clips but the entity has no Animation / Actor component.'})
            if 'tasks_events' in comps:
                te = comps.get('tasks_events') or {}
                task_names=[]
                for task in te.get('tasks') or []:
                    name=str(task.get('name') or '').strip()
                    if not name:
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Tasks / Events','path':'','message':'Managed task has no name.'})
                        continue
                    if name in task_names:
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Tasks / Events','path':'','message':f'Duplicate managed task name: {name}'})
                    task_names.append(name)
                    mode=str(task.get('mode','interval')).lower()
                    if mode not in {'once','interval','frame'}:
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Tasks / Events','path':'','message':f'Unknown task mode for {name}: {mode}'})
                    try:
                        if mode=='interval' and float(task.get('interval',0)) <= 0:
                            warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Tasks / Events','path':'','message':f'Interval task {name} should use an interval greater than zero.'})
                    except Exception:
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Tasks / Events','path':'','message':f'Invalid timing value on task: {name}'})
                event_names=[str(x.get('name') or '').strip() for x in (te.get('events') or []) if str(x.get('name') or '').strip()]
                if len(event_names)!=len(set(event_names)):
                    warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Tasks / Events','path':'','message':'Duplicate custom event hook names are authored on this entity.'})
            if 'intervals' in comps:
                ivc=comps.get('intervals') or {}; names=[]
                for clip in ivc.get('clips') or []:
                    name=str(clip.get('name') or '').strip()
                    if not name:
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Intervals','path':'','message':'Interval has no name.'}); continue
                    if name in names:
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Intervals','path':'','message':f'Duplicate interval name: {name}'})
                    names.append(name)
                    compo=str(clip.get('composition','sequence')).lower()
                    if compo not in {'sequence','parallel'}:
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Intervals','path':'','message':f'Unknown interval composition for {name}: {compo}'})
                    if not (clip.get('steps') or []):
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Intervals','path':'','message':f'Interval {name} has no steps.'})
                    for step in clip.get('steps') or []:
                        typ=str(step.get('type','wait')).lower()
                        if typ not in {'wait','move','rotate','scale','event','signal','animation','sound'}:
                            warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Intervals','path':'','message':f'Unknown interval step type in {name}: {typ}'})
                        try:
                            if typ in {'wait','move','rotate','scale','animation','sound'} and float(step.get('duration',0) or 0)<0:
                                issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Intervals','path':'','message':f'Negative interval duration in {name}.'})
                        except Exception:
                            issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Intervals','path':'','message':f'Invalid duration in interval {name}.'})
            if 'navigation_surface' in comps:
                nv=comps.get('navigation_surface') or {}
                try:
                    size=list(nv.get('size',[20,20]))+[20,20]
                    if float(size[0])<=0 or float(size[1])<=0: warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Navigation Surface','path':'','message':'Navigation surface size must be greater than zero.'})
                    if float(nv.get('cell_size',1.0))<=0: warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Navigation Surface','path':'','message':'Navigation cell size must be greater than zero.'})
                except Exception: warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Navigation Surface','path':'','message':'Navigation surface contains invalid numeric values.'})
            if 'navigation_agent' in comps:
                ag=comps.get('navigation_agent') or {}
                if str(ag.get('behavior','none')) not in {'none','patrol','chase','flee'}: warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Navigation Agent','path':'','message':'Unknown navigation behavior.'})
                try:
                    if float(ag.get('speed',3.5))<0: warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Navigation Agent','path':'','message':'Navigation speed cannot be negative.'})
                    if float(ag.get('repath_interval',.5))<=0: warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Navigation Agent','path':'','message':'Repath interval must be greater than zero.'})
                except Exception: pass
                target=str(ag.get('target') or '').strip()
                if target and target not in self.scene.entities and not any(x.name==target for x in self.scene.entities.values()): warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Navigation Agent','path':'','message':f'Navigation target not found: {target}'})
            if 'navigation_obstacle' in comps:
                ob=comps.get('navigation_obstacle') or {}
                try:
                    if float(ob.get('radius',1.0))<=0: warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Navigation Obstacle','path':'','message':'Obstacle radius must be greater than zero.'})
                except Exception: pass
            if 'ai_behavior' in comps:
                ai=comps.get('ai_behavior') or {}
                if str(ai.get('disposition','aggressive')).lower() not in {'aggressive','avoid','scripted'}:
                    warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'AI Behavior','path':'','message':'Unknown AI disposition.'})
                if str(ai.get('target_mode','explicit')).lower() not in {'explicit','tag','nearest_tag'}:
                    warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'AI Behavior','path':'','message':'Unknown AI target mode.'})
                try:
                    if float(ai.get('think_interval',.2))<=0: warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'AI Behavior','path':'','message':'Think interval must be greater than zero.'})
                    if float(ai.get('sight_distance',15))<0: warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'AI Behavior','path':'','message':'Sight distance cannot be negative.'})
                    fov=float(ai.get('field_of_view',120))
                    if fov<=0 or fov>360: warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'AI Behavior','path':'','message':'Field of view must be within 0..360 degrees.'})
                    if float(ai.get('attack_distance',1.75))<0: warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'AI Behavior','path':'','message':'Attack distance cannot be negative.'})
                except Exception:
                    warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'AI Behavior','path':'','message':'AI Behavior contains invalid numeric values.'})
                if ai.get('auto_navigation',True) and 'navigation_agent' not in comps:
                    warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'AI Behavior','path':'','message':'Auto Navigation is enabled but this entity has no Navigation Agent.'})
                if ai.get('sync_fsm',True) and 'fsm' not in comps:
                    warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'AI Behavior','path':'','message':'FSM Sync is enabled but this entity has no FSM component.'})
            if 'render_attributes' in comps:
                ra=comps.get('render_attributes') or {}
                if str(ra.get('cull','back')).lower() not in {'inherit','back','front','none'}:
                    warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Render Attributes','path':'','message':'Unknown cull mode.'})
                if str(ra.get('transparency','inherit')).lower() not in {'inherit','none','alpha','binary','multisample'}:
                    warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Render Attributes','path':'','message':'Unknown transparency mode.'})
                cs=list(ra.get('color_scale') or [])
                if cs and len(cs)!=4:
                    warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Render Attributes','path':'','message':'Color Scale should contain four RGBA values.'})
            if 'shader' in comps:
                sh=comps.get('shader') or {}
                if sh.get('enabled',True):
                    if str(sh.get('language','glsl')).lower()!='glsl':
                        warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Shader','path':'','message':'Only GLSL shader components are supported in this pass.'})
                    for key,label,exts in [('vertex','Vertex',('.vert','.glsl')),('fragment','Fragment',('.frag','.glsl'))]:
                        rel=self._normalize_project_path(sh.get(key))
                        if not rel:
                            issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Shader','path':'','message':f'{label} shader is required.'})
                        else:
                            path=(ROOT/rel).resolve()
                            if not path.is_file(): issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Shader','path':rel,'message':f'Missing {label.lower()} shader file.'})
                            elif path.suffix.lower() not in exts: warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Shader','path':rel,'message':f'{label} shader extension looks unusual.'})
                    geom=self._normalize_project_path(sh.get('geometry'))
                    if geom and not (ROOT/geom).resolve().is_file(): issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Shader','path':geom,'message':'Missing geometry shader file.'})
        for ent in self.scene.entities.values():
            cam=ent.components.get('camera') or {}
            if not cam: continue
            projection=str(cam.get('projection','perspective')).lower()
            if projection not in {'perspective','orthographic'}:
                warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Camera','path':'','message':'Camera projection must be perspective or orthographic.'})
            rig=str(cam.get('rig','fixed')).lower()
            if rig not in {'fixed','look_at','follow','orbit'}:
                warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Camera','path':'','message':f'Unknown camera rig: {rig}.'})
            try:
                near=float(cam.get('near',.1)); far=float(cam.get('far',2000)); fov=float(cam.get('fov',60)); size=float(cam.get('ortho_size',10))
                if near<=0: issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Camera','path':'','message':'Near clip must be greater than zero.'})
                if far<=near: issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Camera','path':'','message':'Far clip must be greater than near clip.'})
                if projection=='perspective' and not (1<=fov<179): warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Camera','path':'','message':'Perspective FOV should be between 1 and 178 degrees.'})
                if projection=='orthographic' and size<=0: issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Camera','path':'','message':'Orthographic size must be greater than zero.'})
            except Exception:
                issues.append({'severity':'error','entity_id':ent.id,'entity_name':ent.name,'component':'Camera','path':'','message':'Camera lens values contain invalid numbers.'})
            if rig in {'look_at','follow','orbit'}:
                target=str(cam.get('target','') or '').strip()
                if not target: warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Camera','path':'','message':f'{rig.title()} rig has no target entity configured.'})
                else:
                    found=target in self.scene.entities or any(e.name.lower()==target.lower() for e in self.scene.entities.values())
                    if not found: warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Camera','path':'','message':f'Camera rig target not found: {target}'})
            if rig=='orbit':
                try:
                    mn=float(cam.get('min_distance',1)); mx=float(cam.get('max_distance',100)); d=float(cam.get('distance',8)); lo=float(cam.get('orbit_min_pitch',-80)); hi=float(cam.get('orbit_max_pitch',80))
                    if mx<mn: warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Camera','path':'','message':'Orbit max distance is less than min distance.'})
                    if not (mn<=d<=mx): warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Camera','path':'','message':'Orbit distance lies outside min/max range.'})
                    if hi<lo: warnings.append({'severity':'warning','entity_id':ent.id,'entity_name':ent.name,'component':'Camera','path':'','message':'Orbit max pitch is less than min pitch.'})
                except Exception: pass
        active_cameras=[e for e in self.scene.entities.values() if (e.components.get('camera') or {}).get('active')]
        if len(active_cameras) > 1:
            warnings.append({'severity':'warning','entity_id':'','entity_name':'Scene','component':'Camera','path':'','message':'More than one camera is marked active.'})
        scripts_root=ROOT/'scripts'
        for script in scripts_root.rglob('*.py') if scripts_root.exists() else []:
            try:
                compile(script.read_text(encoding='utf-8'), str(script), 'exec')
            except Exception as exc:
                issues.append({'severity':'error','entity_id':'','entity_name':script.name,'component':'Script','path':script.relative_to(ROOT).as_posix(),'message':f'Python syntax error: {exc}'})
        return {'ok': not issues, 'errors': issues, 'warnings': warnings, 'checked_references': checked, 'summary': {'errors':len(issues),'warnings':len(warnings)}}

    # Safe project asset folders -------------------------------------------------
    def list_asset_folders(self) -> list[dict]:
        base = (ROOT / 'assets').resolve(); base.mkdir(parents=True, exist_ok=True)
        result = [{'path':'assets','name':'assets','parent':None}]
        for path in sorted([p for p in base.rglob('*') if p.is_dir() and '__pycache__' not in p.parts], key=lambda p: str(p).lower()):
            rel = path.relative_to(ROOT).as_posix()
            parent = path.parent.relative_to(ROOT).as_posix()
            result.append({'path':rel,'name':path.name,'parent':parent,'child_count':sum(1 for _ in path.iterdir())})
        return result

    def create_asset_folder(self, parent_relative: str = 'assets', name: str = 'New Folder') -> dict:
        base=(ROOT/'assets').resolve(); base.mkdir(parents=True, exist_ok=True)
        parent=(ROOT/self._normalize_project_path(parent_relative or 'assets')).resolve()
        if parent != base and base not in parent.parents:
            return {'ok':False,'reason':'outside_assets'}
        clean=''.join(c for c in Path(str(name or 'New Folder')).name if c not in '<>:"/\\|?*').strip().strip('.')
        if not clean: clean='New Folder'
        target=parent/clean; i=2
        while target.exists(): target=parent/f'{clean}_{i}'; i+=1
        target.mkdir(parents=False,exist_ok=False)
        rel=target.relative_to(ROOT).as_posix()
        self.log(f'Asset folder created: {rel}')
        return {'ok':True,'path':rel,'name':target.name}

    def move_asset_to_folder(self, relative_path: str, folder_relative: str) -> dict:
        base=(ROOT/'assets').resolve()
        src=(ROOT/self._normalize_project_path(relative_path)).resolve()
        dst_dir=(ROOT/self._normalize_project_path(folder_relative)).resolve()
        if base not in src.parents or (dst_dir != base and base not in dst_dir.parents) or not src.is_file() or not dst_dir.is_dir():
            return {'ok':False,'reason':'unsafe'}
        dst=dst_dir/src.name
        if dst.exists(): return {'ok':False,'reason':'exists'}
        old_rel=src.relative_to(ROOT).as_posix()
        src.rename(dst)
        new_rel=dst.relative_to(ROOT).as_posix()
        for ent in self.scene.entities.values():
            for comp_name,key in [('script','path'),('audio_source','clip'),('model','asset'),('prefab_instance','source'),('material','base_texture'),('material','metal_rough_texture'),('material','normal_texture'),('material','emission_texture'),('material','occlusion_texture'),('ui','image'),('particle_emitter','texture')]:
                comp=ent.components.get(comp_name) or {}
                if self._normalize_project_path(comp.get(key)) == old_rel: comp[key]=new_rel
            terrain=ent.components.get('terrain') or {}
            if self._normalize_project_path(terrain.get('heightfield')) == old_rel: terrain['heightfield']=new_rel
            mp=terrain.get('material_paint') or {}
            if self._normalize_project_path(mp.get('splatmap')) == old_rel: mp['splatmap']=new_rel
            if self._normalize_project_path(mp.get('baked_albedo')) == old_rel: mp['baked_albedo']=new_rel
            for layer in mp.get('layers') or []:
                if self._normalize_project_path((layer or {}).get('albedo')) == old_rel: layer['albedo']=new_rel
        self.scene.dirty=True; self._changed(); self.log(f'Asset moved: {old_rel} -> {new_rel}')
        return {'ok':True,'asset':self.asset_details(new_rel)}

    def delete_asset_folder(self, folder_relative: str) -> dict:
        base=(ROOT/'assets').resolve(); folder=(ROOT/self._normalize_project_path(folder_relative)).resolve()
        if folder == base or base not in folder.parents or not folder.is_dir(): return {'ok':False,'reason':'unsafe'}
        if any(folder.iterdir()): return {'ok':False,'reason':'not_empty'}
        folder.rmdir(); self.log(f'Asset folder deleted: {folder_relative}'); return {'ok':True}

    def get_debug_snapshot(self) -> dict:
        entities=list(self.scene.entities.values())
        return {
            'entities':len(entities),
            'groups':sum(1 for e in entities if 'editor_group' in e.components),
            'colliders':sum(1 for e in entities if 'collider' in e.components),
            'rigid_bodies':sum(1 for e in entities if 'rigid_body' in e.components),
            'characters':sum(1 for e in entities if 'character_controller' in e.components),
            'navigation_surfaces':sum(1 for e in entities if 'navigation_surface' in e.components),
            'navigation_agents':sum(1 for e in entities if 'navigation_agent' in e.components),
            'navigation_obstacles':sum(1 for e in entities if 'navigation_obstacle' in e.components),
            'ai_behaviors':sum(1 for e in entities if 'ai_behavior' in e.components),
            'scripts':sum(1 for e in entities if 'script' in e.components),
            'audio_sources':sum(1 for e in entities if 'audio_source' in e.components),
            'ui_elements':sum(1 for e in entities if 'ui' in e.components),
            'particle_emitters':sum(1 for e in entities if 'particle_emitter' in e.components),
            'task_event_components':sum(1 for e in entities if 'tasks_events' in e.components),
            'interval_components':sum(1 for e in entities if 'intervals' in e.components),
            'render_attribute_components':sum(1 for e in entities if 'render_attributes' in e.components),
            'shader_components':sum(1 for e in entities if 'shader' in e.components),
            'terrains':sum(1 for e in entities if 'terrain' in e.components),
            'lights':sum(1 for e in entities if 'light' in e.components),
            'cameras':sum(1 for e in entities if 'camera' in e.components),
            'play_state':self.play_state,
        }

    def set_bullet_debug(self, enabled: bool) -> bool:
        self.viewport.set_bullet_debug(bool(enabled)); return bool(enabled)

    def set_frame_rate_meter(self, enabled: bool) -> bool:
        self.viewport.set_frame_rate_meter(bool(enabled)); return bool(enabled)

    def connect_pstats(self) -> bool:
        self.viewport.connect_pstats(); return True

    def launch_pstats(self) -> dict:
        import subprocess, sys
        candidates=[Path(sys.executable).with_name('pstats.exe'), Path(sys.executable).parent/'Scripts'/'pstats.exe']
        found=shutil.which('pstats') or shutil.which('pstats.exe')
        if found: candidates.insert(0,Path(found))
        for exe in candidates:
            if exe and Path(exe).exists():
                try:
                    subprocess.Popen([str(exe)], cwd=str(ROOT)); return {'ok':True,'path':str(exe)}
                except Exception as exc: return {'ok':False,'reason':str(exc)}
        return {'ok':False,'reason':'pstats executable was not found in PATH or beside the Python environment.'}

    def undo(self) -> str:
        result = self.commands.undo() or ''
        if result:
            self._changed()
        return result

    def redo(self) -> str:
        result = self.commands.redo() or ''
        if result:
            self._changed()
        return result

    def frame_selected(self) -> bool:
        self.viewport.runtime.frame_selected()
        return True

    def frame_all(self) -> bool:
        self.viewport.runtime.frame_all()
        return True

    def set_viewport_tool(self, tool: str) -> bool:
        if tool not in {'select', 'move', 'rotate', 'scale'}:
            return False
        self.viewport.runtime.set_tool(tool)
        return True

    def set_terrain_edit_mode(self, enabled: bool, entity_id: str | None = None, mode: str = 'raise', radius: float = 4.0, strength: float = 0.5, falloff: float = 0.65) -> bool:
        if enabled:
            ent=self.scene.entities.get(str(entity_id or ''))
            if not ent or 'terrain' not in ent.components:
                return False
            info=self.terrain_edit_info(str(entity_id))
            if not info.get('editable'):
                return False
        self.viewport.runtime.set_terrain_edit(bool(enabled), entity_id, mode, radius, strength, falloff)
        return True

    def toggle_viewport_projection(self) -> bool:
        self.viewport.runtime.toggle_projection()
        return True

    def set_viewport_camera_preset(self, preset: str) -> bool:
        if str(preset).lower() not in {'perspective','front','back','left','right','top','bottom'}:
            return False
        self.viewport.runtime.set_camera_preset(str(preset).lower())
        return True

    def set_viewport_wireframe(self, enabled: bool) -> bool:
        self.viewport.runtime.set_wireframe(bool(enabled))
        return True

    def set_collision_helpers(self, visible: bool) -> bool:
        self.viewport.runtime.set_collision_helpers(bool(visible))
        return True

    def set_editor_helper_visibility(self, kind: str, visible: bool) -> bool:
        if str(kind).lower() not in {'grid','axes','axis','scene','helpers'}:
            return False
        self.viewport.runtime.set_editor_helper_visibility(str(kind).lower(), bool(visible))
        return True



    def set_current_as_startup_scene(self) -> dict:
        path = self.scene.file_path
        if path is None:
            return {'ok': False, 'error': 'Save the current scene before setting it as the startup scene.'}
        try:
            rel = path.resolve().relative_to(ROOT.resolve()).as_posix()
        except Exception:
            return {'ok': False, 'error': 'Startup scenes must be stored inside the project folder.'}
        self.project_settings.startup_scene = rel
        self.project_settings.save()
        self.log(f'Startup scene set: {rel}')
        self.emit('project_settings_changed', self.project_settings.to_dict())
        return {'ok': True, 'startup_scene': rel}

    def run_standalone(self, use_current_scene: bool = True) -> dict:
        if self._standalone_process is not None and self._standalone_process.poll() is None:
            return {'ok': False, 'error': 'A standalone game instance is already running.'}
        scene_arg = None
        if use_current_scene:
            if self.scene.file_path is None:
                return {'ok': False, 'error': 'Save the current scene before running it standalone.'}
            if self.scene.dirty:
                return {'ok': False, 'error': 'Save the current scene changes before running standalone.'}
            scene_arg = str(self.scene.file_path.resolve())
        runner = ROOT / 'run_game.py'
        args = [sys.executable, str(runner)]
        if scene_arg:
            args.append(scene_arg)
        try:
            self._standalone_process = subprocess.Popen(args, cwd=str(ROOT))
            self.log('Standalone Runtime: launched independent Panda3D game process.')
            return {'ok': True, 'pid': self._standalone_process.pid, 'scene': scene_arg or self.project_settings.startup_scene}
        except Exception as exc:
            self._standalone_process = None
            return {'ok': False, 'error': str(exc)}

    def run_scene_standalone(self, relative_path: str) -> dict:
        if self._standalone_process is not None and self._standalone_process.poll() is None:
            return {'ok': False, 'error': 'A standalone game instance is already running.'}
        rel = self._normalize_project_path(relative_path)
        path = (ROOT / rel).resolve()
        if ROOT.resolve() not in path.parents or path.suffix.lower() != '.pscene' or not path.is_file():
            return {'ok': False, 'error': 'Scene must be an existing project .pscene file.'}
        runner = ROOT / 'run_game.py'
        try:
            self._standalone_process = subprocess.Popen([sys.executable, str(runner), str(path)], cwd=str(ROOT))
            self.log(f'Standalone Runtime: launched {rel}.')
            return {'ok': True, 'pid': self._standalone_process.pid, 'scene': rel}
        except Exception as exc:
            self._standalone_process = None
            return {'ok': False, 'error': str(exc)}

    def standalone_status(self) -> dict:
        proc = self._standalone_process
        if proc is None:
            return {'running': False}
        code = proc.poll()
        return {'running': code is None, 'pid': proc.pid, 'exit_code': code}



    def choose_export_icon(self) -> dict:
        result = webview.windows[0].create_file_dialog(
            self._dialog_kind('OPEN'),
            file_types=('Image files (*.png;*.jpg;*.jpeg)', 'All files (*.*)')
        )
        source = self._dialog_first_path(result)
        if not source:
            return {'ok': False, 'cancelled': True}
        if source.suffix.lower() not in {'.png','.jpg','.jpeg'}:
            return {'ok': False, 'error': 'Export icon must be PNG or JPEG.'}
        target_dir = ROOT / 'assets' / 'icons'
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / ('game_icon' + source.suffix.lower())
        try:
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
            rel = target.relative_to(ROOT).as_posix()
            self.project_settings.export_icon_path = rel
            self.project_settings.save()
            self.log(f'Export icon configured: {rel}')
            return {'ok': True, 'path': rel, 'name': target.name}
        except Exception as exc:
            return {'ok': False, 'error': str(exc)}

    def clear_export_icon(self) -> dict:
        self.project_settings.export_icon_path = ''
        self.project_settings.save()
        return {'ok': True}

    def package_windows_game(self) -> dict:
        if self.scene.dirty:
            return {'ok': False, 'error': 'Save the current scene before packaging.'}
        return self.exporter.package(self.project_settings)

    def reveal_export_packages(self) -> dict:
        path = (ROOT / str(self.project_settings.export_output_dir or 'build_exports') / 'packages').resolve()
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.name == 'nt': subprocess.Popen(['explorer', str(path)])
            else: subprocess.Popen(['xdg-open', str(path)])
            return {'ok': True, 'path': str(path)}
        except Exception as exc:
            return {'ok': False, 'error': str(exc)}

    def reveal_release_log(self) -> dict:
        exe = re.sub(r'[^A-Za-z0-9_.-]+','',str(self.project_settings.export_executable_name or 'Panda3DGame')) or 'Panda3DGame'
        if os.name == 'nt':
            base = Path(os.environ.get('APPDATA') or Path.home()) / exe / 'logs'
        else:
            base = Path.home() / '.local' / 'share' / exe / 'logs'
        try:
            base.mkdir(parents=True, exist_ok=True)
            if os.name == 'nt': subprocess.Popen(['explorer', str(base)])
            else: subprocess.Popen(['xdg-open', str(base)])
            return {'ok': True, 'path': str(base)}
        except Exception as exc:
            return {'ok': False, 'error': str(exc)}

    def get_export_status(self) -> dict:
        return self.exporter.status()

    def validate_windows_export(self) -> dict:
        result = self.exporter.validate(self.project_settings)
        raw_validation = self.validate_project()
        summary = raw_validation.get('summary') or {}
        project_validation = {
            'errors': int(summary.get('errors', 0)),
            'warnings': int(summary.get('warnings', 0)),
            'checked': int(raw_validation.get('checked_references', 0)),
        }
        result['project_validation'] = project_validation
        if project_validation['errors']:
            result['ok'] = False
            result.setdefault('errors', []).append(
                f"Project validation found {project_validation['errors']} blocking error(s)."
            )
        return result

    def generate_windows_export_files(self) -> dict:
        return self.exporter.generate(self.project_settings)

    def build_windows_game(self) -> dict:
        if self.scene.dirty:
            return {'ok': False, 'error': 'Save the current scene before building.'}
        return self.exporter.start(self.project_settings)

    def cancel_windows_build(self) -> dict:
        return self.exporter.cancel()

    def clean_windows_build(self) -> dict:
        return self.exporter.clean(self.project_settings)

    def reveal_export_output(self) -> dict:
        path = (ROOT / str(self.project_settings.export_output_dir or 'build_exports')).resolve()
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.name == 'nt':
                subprocess.Popen(['explorer', str(path)])
            else:
                subprocess.Popen(['xdg-open', str(path)])
            return {'ok': True, 'path': str(path)}
        except Exception as exc:
            return {'ok': False, 'error': str(exc)}

    def get_project_settings(self) -> dict:
        return self.project_settings.to_dict()

    def save_project_settings(self, values: dict) -> dict:
        old_pipeline = str(self.project_settings.world_render_pipeline or 'builtin').lower()
        self.project_settings.update_from_dict(values or {})
        self.project_settings.save()
        current = self.project_settings.to_dict()
        new_pipeline = str(current.get('world_render_pipeline','builtin') or 'builtin').lower()
        self.viewport.runtime.set_project_settings(current)
        if old_pipeline != new_pipeline and self.play_state == 'stopped':
            # simplepbr / complexpbr install root render state and auxiliary buffers.
            # Restarting only the child viewport is the reliable way to guarantee
            # there is no shader/buffer residue when switching profiles.
            self.log(f'Rendering pipeline changed: {old_pipeline} -> {new_pipeline}; restarting Panda viewport cleanly.')
            self.viewport.restart()
        elif old_pipeline != new_pipeline:
            self.log('Rendering pipeline changed during Play; new profile will be cleanly applied after Play stops / viewport restarts.')
        self.log('Project settings saved.')
        return current

    def play_scene(self) -> dict:
        if self.play_state != 'stopped':
            return {'state': self.play_state}
        entities = [copy.deepcopy(e.to_dict()) for e in self.scene.entities.values()]
        self.play_state = 'playing'
        play_settings = self.project_settings.to_dict()
        if self.scene.file_path:
            try: play_settings['_current_scene'] = str(Path(self.scene.file_path).resolve().relative_to(ROOT.resolve())).replace('\\','/')
            except Exception: pass
        self.viewport.runtime.start_play(entities, play_settings)
        self.emit('play_state_changed', {'state': self.play_state})
        self.log('Play Mode: starting runtime scene copy.')
        return {'state': self.play_state}

    def pause_play(self, paused: bool | None = None) -> dict:
        if self.play_state == 'stopped':
            return {'state': self.play_state}
        should_pause = (self.play_state != 'paused') if paused is None else bool(paused)
        self.play_state = 'paused' if should_pause else 'playing'
        self.viewport.runtime.pause_play(should_pause)
        self.emit('play_state_changed', {'state': self.play_state})
        return {'state': self.play_state}

    def stop_play(self) -> dict:
        if self.play_state == 'stopped':
            return {'state': self.play_state}
        self.play_state = 'stopped'
        self.viewport.runtime.stop_play()
        self.emit('play_state_changed', {'state': self.play_state})
        self.log('Play Mode: stopped; authoring scene restored.')
        return {'state': self.play_state}

    def _sync(self) -> None:
        self.viewport.runtime.sync_entities([e.to_dict() for e in self.scene.entities.values()])

    def _changed(self, dirty: bool | None = None) -> None:
        """Synchronize authoring state and publish one complete scene-change snapshot.

        ``dirty`` is optional so ordinary edit operations preserve the dirty state
        already set by SceneDocument/commands, while New/Open/Save can explicitly
        publish a clean scene with ``_changed(False)``.
        """
        if dirty is not None:
            self.scene.dirty = bool(dirty)
        self._sync()
        self.emit('scene_changed', {
            'scene': self.scene.to_dict(),
            'selected_id': self.selected_id,
            'dirty': bool(self.scene.dirty),
            'scene_path': str(self.scene.file_path) if self.scene.file_path else '',
            'can_undo': self.commands.can_undo,
            'can_redo': self.commands.can_redo,
        })
