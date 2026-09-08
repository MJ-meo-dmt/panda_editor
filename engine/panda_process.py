from __future__ import annotations

import math
import json
import copy
import importlib
import importlib.util
import sys
import os
import queue
import time
import traceback
import random
import contextlib
import io
import heapq
from pathlib import Path

from panda3d.core import (
    AmbientLight,
    BitMask32,
    ClockObject,
    ColorBlendAttrib,
    CullFaceAttrib,
    PStatClient,
    CardMaker,
    CollisionBox,
    CollisionCapsule,
    CollisionSphere,
    CollisionHandlerQueue,
    CollisionNode,
    CollisionRay,
    CollisionTraverser,
    DirectionalLight,
    Filename,
    Fog,
    GeoMipTerrain,
    PNMImage,
    KeyboardButton,
    LineSegs,
    MouseButton,
    NativeWindowHandle,
    NodePath,
    Material,
    TransparencyAttrib,
    TextNode,
    OrthographicLens,
    PerspectiveLens,
    Shader,
    Texture,
    TexturePool,
    TextureStage,
    Point3,
    PointLight,
    Spotlight,
    TransformState,
    Vec2,
    Vec3,
    Vec4,
    WindowProperties,
    loadPrcFileData,
)
from direct.showbase.ShowBase import ShowBase
from direct.showbase import Audio3DManager
from direct.actor.Actor import Actor
from direct.interval.IntervalGlobal import Sequence, Parallel, Wait, Func, LerpPosInterval, LerpHprInterval, LerpScaleInterval
try:
    from direct.interval.ActorInterval import ActorInterval
except Exception:
    ActorInterval = None
try:
    from direct.interval.SoundInterval import SoundInterval
except Exception:
    SoundInterval = None
from direct.gui.DirectGui import DirectButton, DirectFrame, DirectLabel, DirectWaitBar, DirectSlider, DirectEntry, DirectOptionMenu
from direct.gui import DirectGuiGlobals as DGG
try:
    from direct.filter.CommonFilters import CommonFilters
except Exception:
    CommonFilters = None

try:
    from panda3d.bullet import (
        BulletBoxShape, BulletCapsuleShape, BulletCharacterControllerNode, BulletGhostNode, BulletRigidBodyNode,
        BulletSphereShape, BulletCylinderShape, BulletConeShape, BulletPlaneShape, BulletConvexHullShape,
        BulletTriangleMesh, BulletTriangleMeshShape, BulletDebugNode, BulletWorld, ZUp,
    )
    PHYSICS_AVAILABLE = True
except Exception:
    BulletBoxShape = BulletCapsuleShape = BulletCharacterControllerNode = BulletGhostNode = BulletRigidBodyNode = None
    BulletSphereShape = BulletCylinderShape = BulletConeShape = BulletPlaneShape = BulletConvexHullShape = None
    BulletTriangleMesh = BulletTriangleMeshShape = BulletDebugNode = BulletWorld = None
    ZUp = 2
    PHYSICS_AVAILABLE = False

from scene.entity import Entity

PROJECT_ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]


loadPrcFileData('', 'window-title Panda Editor Viewport')
loadPrcFileData('', 'sync-video false')
loadPrcFileData('', 'show-frame-rate-meter false')
loadPrcFileData('', 'audio-library-name p3openal_audio')
loadPrcFileData('', 'audio-sfx-active true')
loadPrcFileData('', 'audio-music-active true')
# Keep Panda3D audio enabled; Audio Source components are runtime-only.
loadPrcFileData('', 'notify-level warning')


class RuntimeEntity:
    """Script-facing runtime entity. Changes affect only the current Play session."""
    def __init__(self, runtime: 'PandaProcessRuntime', entity_id: str) -> None:
        self._runtime = runtime
        self.id = entity_id

    @property
    def node(self) -> NodePath | None:
        return self._runtime.nodes.get(self.id)

    @property
    def name(self) -> str:
        raw = self._runtime.entity_data.get(self.id, {})
        return str(raw.get('name', self.id))

    @property
    def position(self) -> list[float]:
        n = self.node
        return [float(v) for v in n.getPos()] if n else [0.0, 0.0, 0.0]

    @position.setter
    def position(self, value) -> None:
        n = self.node
        if n:
            vals = list(value)[:3]
            n.setPos(float(vals[0]), float(vals[1]), float(vals[2]))
            self._runtime._sync_physics_body_from_entity(self.id)

    @property
    def rotation(self) -> list[float]:
        n = self.node
        return [float(v) for v in n.getHpr()] if n else [0.0, 0.0, 0.0]

    @rotation.setter
    def rotation(self, value) -> None:
        n = self.node
        if n:
            vals = list(value)[:3]
            n.setHpr(float(vals[0]), float(vals[1]), float(vals[2]))
            self._runtime._sync_physics_body_from_entity(self.id)

    @property
    def scale(self) -> list[float]:
        n = self.node
        return [float(v) for v in n.getScale()] if n else [1.0, 1.0, 1.0]

    @scale.setter
    def scale(self, value) -> None:
        n = self.node
        if n:
            vals = list(value)[:3]
            n.setScale(float(vals[0]), float(vals[1]), float(vals[2]))

    @property
    def world_position(self) -> list[float]:
        n = self.node
        if not n or not self._runtime.base:
            return self.position
        v = n.getPos(self._runtime.base.render)
        return [float(v.x), float(v.y), float(v.z)]

    @world_position.setter
    def world_position(self, value) -> None:
        n = self.node
        if n and self._runtime.base:
            vals = list(value)[:3]
            n.setPos(self._runtime.base.render, float(vals[0]), float(vals[1]), float(vals[2]))
            self._runtime._sync_physics_body_from_entity(self.id)

    @property
    def world_rotation(self) -> list[float]:
        n = self.node
        if not n or not self._runtime.base:
            return self.rotation
        v = n.getHpr(self._runtime.base.render)
        return [float(v.x), float(v.y), float(v.z)]

    @world_rotation.setter
    def world_rotation(self, value) -> None:
        n = self.node
        if n and self._runtime.base:
            vals = list(value)[:3]
            n.setHpr(self._runtime.base.render, float(vals[0]), float(vals[1]), float(vals[2]))
            self._runtime._sync_physics_body_from_entity(self.id)

    @property
    def forward(self) -> list[float]:
        n = self.node
        if not n:
            return [0.0, 1.0, 0.0]
        v = n.getQuat(self._runtime.base.render if self._runtime.base else n.getParent()).xform(Vec3(0,1,0))
        return [float(v.x), float(v.y), float(v.z)]

    @property
    def right(self) -> list[float]:
        n = self.node
        if not n:
            return [1.0, 0.0, 0.0]
        v = n.getQuat(self._runtime.base.render if self._runtime.base else n.getParent()).xform(Vec3(1,0,0))
        return [float(v.x), float(v.y), float(v.z)]

    @property
    def up(self) -> list[float]:
        n = self.node
        if not n:
            return [0.0, 0.0, 1.0]
        v = n.getQuat(self._runtime.base.render if self._runtime.base else n.getParent()).xform(Vec3(0,0,1))
        return [float(v.x), float(v.y), float(v.z)]

    def look_at(self, target, keep_upright: bool = False) -> bool:
        n = self.node
        if not n or not self._runtime.base:
            return False
        try:
            if isinstance(target, RuntimeEntity):
                target = target.world_position
            vals = list(target)[:3]
            n.lookAt(self._runtime.base.render, Point3(float(vals[0]), float(vals[1]), float(vals[2])))
            if keep_upright:
                h = n.getH(self._runtime.base.render)
                n.setHpr(self._runtime.base.render, h, 0.0, 0.0)
            self._runtime._sync_physics_body_from_entity(self.id)
            return True
        except Exception:
            return False

    def distance_to(self, target) -> float:
        if isinstance(target, RuntimeEntity):
            target = target.world_position
        a = Vec3(*self.world_position); b = Vec3(*[float(v) for v in list(target)[:3]])
        return float((b-a).length())

    def direction_to(self, target, normalized: bool = True) -> list[float]:
        if isinstance(target, RuntimeEntity):
            target = target.world_position
        a = Vec3(*self.world_position); b = Vec3(*[float(v) for v in list(target)[:3]])
        d = b-a
        if normalized and d.lengthSquared() > 1e-12:
            d.normalize()
        return [float(d.x), float(d.y), float(d.z)]

    def translate(self, x: float = 0, y: float = 0, z: float = 0, local: bool = False) -> None:
        n = self.node
        if not n:
            return
        delta = Vec3(float(x), float(y), float(z))
        if local:
            n.setPos(n, delta)
        else:
            n.setPos(n.getPos() + delta)
        self._runtime._sync_physics_body_from_entity(self.id)

    def rotate(self, h: float = 0, p: float = 0, r: float = 0) -> None:
        n = self.node
        if n:
            n.setHpr(n.getHpr() + Vec3(float(h), float(p), float(r)))
            self._runtime._sync_physics_body_from_entity(self.id)

    @property
    def linear_velocity(self) -> list[float]:
        body = self._runtime._physics_body_node(self.id)
        if not body:
            return [0.0, 0.0, 0.0]
        v = body.getLinearVelocity()
        return [float(v.x), float(v.y), float(v.z)]

    @linear_velocity.setter
    def linear_velocity(self, value) -> None:
        body = self._runtime._physics_body_node(self.id)
        if body:
            vals = list(value)[:3]
            body.setLinearVelocity(Vec3(float(vals[0]), float(vals[1]), float(vals[2])))
            body.setActive(True, True)

    @property
    def angular_velocity(self) -> list[float]:
        body = self._runtime._physics_body_node(self.id)
        if not body:
            return [0.0, 0.0, 0.0]
        v = body.getAngularVelocity()
        return [float(v.x), float(v.y), float(v.z)]

    @angular_velocity.setter
    def angular_velocity(self, value) -> None:
        body = self._runtime._physics_body_node(self.id)
        if body:
            vals = list(value)[:3]
            body.setAngularVelocity(Vec3(float(vals[0]), float(vals[1]), float(vals[2])))
            body.setActive(True, True)

    def apply_force(self, x: float = 0, y: float = 0, z: float = 0) -> None:
        body = self._runtime._physics_body_node(self.id)
        if body:
            body.applyCentralForce(Vec3(float(x), float(y), float(z)))
            body.setActive(True, True)

    def apply_impulse(self, x: float = 0, y: float = 0, z: float = 0) -> None:
        body = self._runtime._physics_body_node(self.id)
        if body:
            body.applyCentralImpulse(Vec3(float(x), float(y), float(z)))
            body.setActive(True, True)

    @property
    def physics_body_type(self) -> str:
        if self.id in self._runtime.physics_characters: return 'character'
        if self.id in self._runtime.physics_ghost_nodes: return 'trigger'
        return str(self._runtime.physics_body_types.get(self.id, ''))

    @property
    def mass(self) -> float:
        body=self._runtime._physics_body_node(self.id)
        try: return float(body.getMass()) if body else 0.0
        except Exception: return 0.0

    @mass.setter
    def mass(self, value: float) -> None:
        body=self._runtime._physics_body_node(self.id)
        if body:
            try: body.setMass(max(0.0,float(value))); body.setActive(True,True)
            except Exception: pass

    @property
    def friction(self) -> float:
        body=self._runtime._physics_body_node(self.id)
        try: return float(body.getFriction()) if body else 0.0
        except Exception: return 0.0

    @friction.setter
    def friction(self, value: float) -> None:
        body=self._runtime._physics_body_node(self.id)
        if body:
            try: body.setFriction(max(0.0,float(value)))
            except Exception: pass

    @property
    def restitution(self) -> float:
        body=self._runtime._physics_body_node(self.id)
        try: return float(body.getRestitution()) if body else 0.0
        except Exception: return 0.0

    @restitution.setter
    def restitution(self, value: float) -> None:
        body=self._runtime._physics_body_node(self.id)
        if body:
            try: body.setRestitution(max(0.0,min(1.0,float(value))))
            except Exception: pass

    def apply_torque(self, x: float=0, y: float=0, z: float=0) -> None:
        body=self._runtime._physics_body_node(self.id)
        if body:
            try: body.applyTorque(Vec3(float(x),float(y),float(z))); body.setActive(True,True)
            except Exception: pass

    def apply_torque_impulse(self, x: float=0, y: float=0, z: float=0) -> None:
        body=self._runtime._physics_body_node(self.id)
        if body:
            try: body.applyTorqueImpulse(Vec3(float(x),float(y),float(z))); body.setActive(True,True)
            except Exception: pass

    def clear_forces(self) -> None:
        body=self._runtime._physics_body_node(self.id)
        if body:
            try: body.clearForces()
            except Exception: pass

    def wake(self) -> None:
        body = self._runtime._physics_body_node(self.id)
        if body:
            body.setActive(True, True)

    def raycast(self, x: float = 0, y: float = 1, z: float = 0, distance: float = 100.0, mask: int = 0xFFFFFFFF):
        n = self.node
        if not n or not self._runtime.base:
            return None
        origin = n.getPos(self._runtime.base.render)
        direction = n.getQuat(self._runtime.base.render).xform(Vec3(float(x), float(y), float(z)))
        return self._runtime._runtime_raycast(origin, direction, distance, mask, ignore_entity=self.id)

    @property
    def has_physics(self) -> bool:
        return self.id in self._runtime.physics_nodes or self.id in self._runtime.physics_ghost_nodes

    @property
    def has_material(self) -> bool:
        raw=(self._runtime.entity_data.get(self.id,{}) or {}).get('components') or {}
        return 'material' in raw

    @property
    def material_config(self) -> dict:
        raw=((self._runtime.entity_data.get(self.id,{}) or {}).get('components') or {}).get('material') or {}
        return copy.deepcopy(raw)

    def material_configure(self, **settings) -> bool:
        raw=(self._runtime.entity_data.get(self.id,{}) or {})
        comps=raw.setdefault('components',{})
        if 'material' not in comps: return False
        allowed={'base_color','base_texture','metallic','roughness','normal_texture','emission_texture','occlusion_texture','metal_rough_texture','uv_scale','uv_offset','uv_rotation','wrap_u','wrap_v','min_filter','mag_filter','anisotropic_degree','emission','specular','shininess','alpha','transparent','two_sided','unlit','shader_auto','shader_policy'}
        changed=False
        for key,value in settings.items():
            if key in allowed:
                comps['material'][key]=copy.deepcopy(value); changed=True
        if changed:
            root=self.node
            if root: self._runtime._apply_material_component(root, comps['material'])
        return changed

    def material_set_texture_transform(self, scale=None, offset=None, rotation=None) -> bool:
        values={}
        if scale is not None: values['uv_scale']=list(scale)[:2]
        if offset is not None: values['uv_offset']=list(offset)[:2]
        if rotation is not None: values['uv_rotation']=float(rotation)
        return self.material_configure(**values) if values else False

    @property
    def has_ui(self) -> bool:
        return self.id in self._runtime.ui_nodes

    @property
    def ui_text(self) -> str:
        raw = (self._runtime.entity_data.get(self.id, {}).get('components') or {}).get('ui') or {}
        return str(raw.get('text', ''))

    @ui_text.setter
    def ui_text(self, value) -> None:
        self._runtime._ui_set_text(self.id, str(value))

    @property
    def ui_value(self) -> float:
        raw=(self._runtime.entity_data.get(self.id,{}).get('components') or {}).get('ui') or {}
        return float(raw.get('value',0.0) or 0.0)

    @ui_value.setter
    def ui_value(self, value) -> None:
        self._runtime._ui_set_value(self.id, float(value))

    def ui_show(self) -> None:
        self._runtime._ui_set_visible(self.id, True)

    def ui_hide(self) -> None:
        self._runtime._ui_set_visible(self.id, False)

    def ui_set_color(self, r: float, g: float, b: float, a: float = 1.0) -> None:
        self._runtime._ui_set_color(self.id, [float(r), float(g), float(b), float(a)])

    def component(self, name: str, default=None):
        return copy.deepcopy((self._runtime.entity_data.get(self.id, {}).get('components') or {}).get(name, default))

    @property
    def component_names(self) -> list[str]:
        return sorted(str(k) for k in ((self._runtime.entity_data.get(self.id, {}).get('components') or {}).keys()))

    def has_component(self, name: str) -> bool:
        return str(name) in (self._runtime.entity_data.get(self.id, {}).get('components') or {})

    @property
    def tags(self) -> list[str]:
        return [str(v) for v in (self._runtime.entity_data.get(self.id, {}).get('tags') or [])]

    def has_tag(self, tag: str) -> bool:
        needle=str(tag).lower(); return any(str(v).lower()==needle for v in self.tags)

    @property
    def parent(self):
        pid=self._runtime.entity_data.get(self.id, {}).get('parent')
        return RuntimeEntity(self._runtime, str(pid)) if pid and str(pid) in self._runtime.nodes else None

    @property
    def children(self) -> list['RuntimeEntity']:
        return [RuntimeEntity(self._runtime,eid) for eid,raw in self._runtime.entity_data.items() if raw.get('parent')==self.id and eid in self._runtime.nodes]

    @property
    def visible(self) -> bool:
        n=self.node
        return bool(n and not n.isHidden())


    @property
    def has_character_controller(self) -> bool:
        return self.id in self._runtime.physics_characters

    @property
    def grounded(self) -> bool:
        np = self._runtime.physics_characters.get(self.id)
        if not np:
            return False
        try:
            return bool(np.node().isOnGround())
        except Exception:
            return False

    def character_move(self, x: float = 0, y: float = 0, z: float = 0, local: bool = True) -> None:
        np = self._runtime.physics_characters.get(self.id)
        if not np:
            return
        try:
            np.node().setLinearMovement(Vec3(float(x), float(y), float(z)), bool(local))
            self._runtime._character_move_written.add(self.id)
        except Exception:
            pass

    def character_jump(self) -> None:
        np = self._runtime.physics_characters.get(self.id)
        if not np:
            return
        try:
            np.node().doJump()
        except Exception:
            pass

    @property
    def character_rotation(self) -> list[float]:
        np=self._runtime.physics_characters.get(self.id)
        if not np or not self._runtime.base: return self.world_rotation
        v=np.getHpr(self._runtime.base.render); return [float(v.x),float(v.y),float(v.z)]

    @character_rotation.setter
    def character_rotation(self, value) -> None:
        np=self._runtime.physics_characters.get(self.id); root=self.node
        if not np or not self._runtime.base: return
        vals=list(value)[:3]
        np.setHpr(self._runtime.base.render,float(vals[0]),float(vals[1]),float(vals[2]))
        if root: root.setHpr(self._runtime.base.render,float(vals[0]),float(vals[1]),float(vals[2]))

    @property
    def character_heading(self) -> float:
        return float(self.character_rotation[0])

    @character_heading.setter
    def character_heading(self, value: float) -> None:
        r=self.character_rotation; r[0]=float(value); self.character_rotation=r

    def character_rotate(self, h: float=0, p: float=0, r: float=0) -> None:
        rot=self.character_rotation
        self.character_rotation=[rot[0]+float(h),rot[1]+float(p),rot[2]+float(r)]

    def character_turn(self, degrees_per_second: float) -> None:
        """Set Bullet character angular movement in degrees/second.

        Panda3D's Bullet character-controller examples pass values such as 120.0
        directly to setAngularMovement(); converting to radians here made turning
        roughly 57x too slow.
        """
        np=self._runtime.physics_characters.get(self.id)
        if not np: return
        try:
            np.node().setAngularMovement(float(degrees_per_second))
            self._runtime._character_turn_written.add(self.id)
        except Exception:
            # Fallback keeps the public API usable on Bullet builds without angular movement.
            self.character_rotate(h=float(degrees_per_second) * float(self._runtime.runtime_world.dt or 0.0))

    def character_turn_to(self, heading: float, speed: float = 180.0) -> bool:
        """Turn toward an absolute heading at up to ``speed`` degrees/sec."""
        if not self.has_character_controller: return False
        current=float(self.character_heading); target=float(heading)
        delta=((target-current+180.0)%360.0)-180.0
        dt=max(0.0,float(self._runtime.runtime_world.dt or 0.0))
        if dt<=0.0: return False
        step=max(0.0,float(speed))*dt
        if abs(delta)<=step:
            self.character_heading=target; self.character_stop_turn(); return True
        self.character_turn((1.0 if delta>0 else -1.0)*max(0.0,float(speed)))
        return False

    def character_face_direction(self, direction, speed: float | None = None) -> bool:
        vals=list(direction)[:3]
        if len(vals)<2: return False
        x,y=float(vals[0]),float(vals[1])
        if abs(x)+abs(y)<=1e-8: return False
        heading=math.degrees(math.atan2(x,y))
        if speed is None:
            self.character_heading=heading; return True
        return self.character_turn_to(heading,float(speed))

    @property
    def character_max_slope(self) -> float:
        np=self._runtime.physics_characters.get(self.id)
        if not np: return 0.0
        try: return float(np.node().getMaxSlope())
        except Exception: return 0.0

    @character_max_slope.setter
    def character_max_slope(self, value: float) -> None:
        np=self._runtime.physics_characters.get(self.id)
        if np:
            try: np.node().setMaxSlope(float(value))
            except Exception: pass

    def character_stop_turn(self) -> None:
        np=self._runtime.physics_characters.get(self.id)
        if np:
            try: np.node().setAngularMovement(0.0)
            except Exception: pass

    def character_configure(self, **settings) -> bool:
        np=self._runtime.physics_characters.get(self.id)
        if not np: return False
        node=np.node(); changed=False
        mapping={'gravity':'setGravity','jump_speed':'setJumpSpeed','fall_speed':'setFallSpeed','max_jump_height':'setMaxJumpHeight','max_slope':'setMaxSlope'}
        for key,method in mapping.items():
            if key in settings and hasattr(node,method):
                try: getattr(node,method)(max(0.0,float(settings[key]))); changed=True
                except Exception: pass
        if 'ghost_sweep' in settings and hasattr(node, 'setUseGhostSweepTest'):
            try: node.setUseGhostSweepTest(bool(settings['ghost_sweep'])); changed=True
            except Exception: pass
        return changed

    @property
    def has_animation(self) -> bool:
        return self.id in self._runtime.entity_actors

    @property
    def animation_names(self) -> list[str]:
        actor = self._runtime.entity_actors.get(self.id)
        if not actor:
            return []
        try:
            return list(actor.getAnimNames())
        except Exception:
            return []

    def animation_play(self, name: str | None = None, loop: bool = False, restart: bool = True, rate: float | None = None) -> bool:
        return self._runtime._animation_play(self.id, name=name, loop=loop, restart=restart, rate=rate)

    def animation_loop(self, name: str | None = None, restart: bool = True, rate: float | None = None) -> bool:
        return self._runtime._animation_play(self.id, name=name, loop=True, restart=restart, rate=rate)

    def animation_stop(self, name: str | None = None) -> bool:
        actor = self._runtime.entity_actors.get(self.id)
        if not actor:
            return False
        try:
            if name:
                actor.stop(str(name))
            else:
                actor.stop()
            return True
        except Exception:
            return False

    def animation_pose(self, name: str, frame: int) -> bool:
        actor = self._runtime.entity_actors.get(self.id)
        if not actor:
            return False
        try:
            actor.pose(str(name), int(frame))
            return True
        except Exception:
            return False

    def animation_is_playing(self, name: str | None = None) -> bool:
        actor = self._runtime.entity_actors.get(self.id)
        if not actor:
            return False
        try:
            if name:
                control = actor.getAnimControl(str(name))
                return bool(control and control.isPlaying())
            for clip in actor.getAnimNames():
                control = actor.getAnimControl(clip)
                if control and control.isPlaying():
                    return True
            return False
        except Exception:
            return False

    def animation_frame(self, name: str) -> int:
        actor = self._runtime.entity_actors.get(self.id)
        if not actor:
            return 0
        try:
            control = actor.getAnimControl(str(name))
            return int(control.getFrame()) if control else 0
        except Exception:
            return 0

    def animation_num_frames(self, name: str) -> int:
        actor=self._runtime.entity_actors.get(self.id)
        if not actor: return 0
        try:
            control=actor.getAnimControl(str(name)); return int(control.getNumFrames()) if control else 0
        except Exception: return 0

    def animation_duration(self, name: str) -> float:
        actor=self._runtime.entity_actors.get(self.id)
        if not actor: return 0.0
        try:
            control=actor.getAnimControl(str(name))
            if not control: return 0.0
            frames=float(control.getNumFrames()); fps=float(control.getFrameRate())
            return frames/fps if fps>1e-8 else 0.0
        except Exception: return 0.0

    def animation_set_rate(self, rate: float, name: str | None = None) -> bool:
        actor = self._runtime.entity_actors.get(self.id)
        if not actor:
            return False
        try:
            if name:
                actor.setPlayRate(float(rate), str(name))
            else:
                for clip in actor.getAnimNames():
                    actor.setPlayRate(float(rate), clip)
            return True
        except Exception:
            return False

    @property
    def has_fsm(self) -> bool:
        return self.id in self._runtime.fsm_states

    @property
    def fsm_state(self) -> str:
        return str(self._runtime.fsm_states.get(self.id, ''))

    @property
    def fsm_states(self) -> list[str]:
        raw = (self._runtime.entity_data.get(self.id, {}).get('components') or {}).get('fsm') or {}
        return [str(x.get('name')) for x in (raw.get('states') or []) if str(x.get('name') or '').strip()]

    def fsm_request(self, state: str, payload=None) -> bool:
        return self._runtime._fsm_request(self.id, str(state), payload)

    def fsm_send(self, signal: str, payload=None) -> bool:
        return self._runtime._fsm_send(self.id, str(signal), payload)

    @property
    def has_terrain(self) -> bool:
        return self.id in self._runtime.terrains

    @property
    def terrain_config(self) -> dict:
        state = self._runtime.terrains.get(self.id) or {}
        comp = state.get('component') or (self._runtime.entity_data.get(self.id, {}).get('components') or {}).get('terrain') or {}
        return copy.deepcopy(comp)

    def terrain_get(self, name: str, default=None):
        return copy.deepcopy(self.terrain_config.get(str(name), default))

    def terrain_set(self, name: str, value) -> bool:
        return self._runtime._terrain_configure(self.id, {str(name): value})

    def terrain_configure(self, **settings) -> bool:
        return self._runtime._terrain_configure(self.id, settings)

    def terrain_height(self, x: float, y: float, world_space: bool = True) -> float | None:
        return self._runtime._terrain_height(self.id, float(x), float(y), bool(world_space))

    def terrain_normal(self, x: float, y: float, world_space: bool = True) -> list[float] | None:
        return self._runtime._terrain_normal(self.id, float(x), float(y), bool(world_space))

    def terrain_regenerate(self) -> bool:
        return self._runtime._terrain_regenerate(self.id)

    @property
    def has_lod(self) -> bool:
        return bool(((self._runtime.entity_data.get(self.id, {}).get('components') or {}).get('lod')))

    @property
    def lod_config(self) -> dict:
        return copy.deepcopy(((self._runtime.entity_data.get(self.id, {}).get('components') or {}).get('lod') or {}))

    def lod_set(self, name: str, value) -> bool:
        raw=self._runtime.entity_data.get(self.id, {}); comps=raw.setdefault('components', {}); lod=comps.get('lod')
        if not lod: return False
        if name not in {'enabled','near','far','fade_band','scope'}: return False
        lod[str(name)]=value
        return True

    @property
    def has_render_attributes(self) -> bool:
        return bool(((self._runtime.entity_data.get(self.id, {}).get('components') or {}).get('render_attributes')))

    @property
    def render_attributes(self) -> dict:
        return copy.deepcopy(((self._runtime.entity_data.get(self.id, {}).get('components') or {}).get('render_attributes') or {}))

    def render_set(self, name: str, value) -> bool:
        return self._runtime._render_attribute_set(self.id, str(name), value)

    def render_reset(self) -> bool:
        return self._runtime._render_attributes_reset(self.id)

    @property
    def has_shader(self) -> bool:
        return bool(((self._runtime.entity_data.get(self.id, {}).get('components') or {}).get('shader')))

    @property
    def shader_config(self) -> dict:
        return copy.deepcopy(((self._runtime.entity_data.get(self.id, {}).get('components') or {}).get('shader') or {}))

    def shader_reload(self) -> bool:
        return self._runtime._shader_reload_entity(self.id)

    def shader_set_input(self, name: str, value) -> bool:
        return self._runtime._shader_set_input(self.id, str(name), value)

    def shader_clear_input(self, name: str) -> bool:
        return self._runtime._shader_clear_input(self.id, str(name))

    def shader_clear(self) -> bool:
        return self._runtime._shader_clear_entity(self.id)

    @property
    def interval_names(self) -> list[str]:
        comp=((self._runtime.entity_data.get(self.id,{}).get('components') or {}).get('intervals') or {})
        return [str(x.get('name')) for x in (comp.get('clips') or []) if str(x.get('name') or '').strip()]

    def interval_start(self, name: str, restart: bool = True) -> bool:
        return self._runtime._interval_start(self.id, str(name), bool(restart))

    def interval_pause(self, name: str) -> bool:
        return self._runtime._interval_pause(self.id, str(name))

    def interval_resume(self, name: str) -> bool:
        return self._runtime._interval_resume(self.id, str(name))

    def interval_finish(self, name: str) -> bool:
        return self._runtime._interval_finish(self.id, str(name))

    def interval_is_playing(self, name: str) -> bool:
        return self._runtime._interval_is_playing(self.id, str(name))

    def interval_info(self, name: str) -> dict | None:
        item=self._runtime._interval_item(self.id,str(name))
        if not item: return None
        iv=item.get('interval'); out={'name':str(name),'config':copy.deepcopy(item.get('config') or {}),'playing':self.interval_is_playing(name)}
        try: out['time']=float(iv.getT()); out['duration']=float(iv.getDuration()); out['play_rate']=float(iv.getPlayRate())
        except Exception: pass
        return out

    def interval_set_rate(self, name: str, rate: float) -> bool:
        item=self._runtime._interval_item(self.id,str(name))
        if not item: return False
        try: item['interval'].setPlayRate(max(0.001,float(rate))); return True
        except Exception: return False

    def set_visible(self, visible: bool) -> None:
        n = self.node
        if n:
            n.show() if visible else n.hide()

    @property
    def has_camera(self) -> bool:
        return self.has_component('camera')

    @property
    def camera_config(self) -> dict:
        comp=(self._runtime.entity_data.get(self.id,{}).get('components') or {}).get('camera') or {}
        live=self._runtime.runtime_camera_overrides.get(self.id,{})
        out=copy.deepcopy(comp); out.update(copy.deepcopy(live)); return out

    def camera_set(self, name: str, value) -> bool:
        return self._runtime._camera_set(self.id, str(name), value)

    def camera_configure(self, **settings) -> bool:
        ok=True
        for key,value in settings.items():
            ok=self._runtime._camera_set(self.id,str(key),value) and ok
        return ok

    def camera_activate(self, blend: float=0.0, ease: str='easeInOut') -> bool:
        return self._runtime._camera_activate(self.id, float(blend), str(ease))

    def camera_follow(self, target=None, offset=None, damping: float | None=None, look_at: bool | None=None) -> bool:
        settings={'rig':'follow'}
        if target is not None: settings['target']=target.id if isinstance(target,RuntimeEntity) else str(target)
        if offset is not None: settings['offset']=list(offset)[:3]
        if damping is not None: settings['damping']=float(damping)
        if look_at is not None: settings['look_at']=bool(look_at)
        return self.camera_configure(**settings)

    def camera_orbit(self, target=None, distance: float | None=None, heading: float | None=None, pitch: float | None=None, damping: float | None=None) -> bool:
        settings={'rig':'orbit'}
        if target is not None: settings['target']=target.id if isinstance(target,RuntimeEntity) else str(target)
        if distance is not None: settings['distance']=float(distance)
        if heading is not None: settings['orbit_heading']=float(heading)
        if pitch is not None: settings['orbit_pitch']=float(pitch)
        if damping is not None: settings['damping']=float(damping)
        return self.camera_configure(**settings)

    def camera_orbit_input(self, heading_delta: float=0.0, pitch_delta: float=0.0, zoom_delta: float=0.0) -> bool:
        return self._runtime._camera_orbit_input(self.id,float(heading_delta),float(pitch_delta),float(zoom_delta))

    def camera_shake(self, strength: float=0.25, duration: float=0.35, frequency: float=20.0, rotation: float=1.5) -> bool:
        return self._runtime._camera_shake(self.id,float(strength),float(duration),float(frequency),float(rotation))

    def camera_stop_shake(self) -> bool:
        return self._runtime._camera_stop_shake(self.id)

    @property
    def has_light(self) -> bool:
        return self.id in self._runtime.entity_lights

    @property
    def light_enabled(self) -> bool:
        return bool(self._runtime.runtime_light_enabled.get(self.id, self.has_light))

    @light_enabled.setter
    def light_enabled(self, value: bool) -> None:
        self._runtime._set_runtime_light_enabled(self.id, bool(value))

    def light_set_intensity(self, intensity: float) -> bool:
        return self._runtime._set_runtime_light_intensity(self.id, max(0.0,float(intensity)))

    @property
    def light_config(self) -> dict:
        raw=copy.deepcopy((self._data().get('components') or {}).get('light') or {})
        raw['enabled_runtime']=self.light_enabled
        supported,note=self._runtime._light_shadow_supported(str(raw.get('type','point')))
        raw['shadow_supported_runtime']=bool(supported)
        raw['shadow_support_note']=str(note or '')
        return raw

    def light_configure(self, **settings) -> bool:
        """Adjust live light settings without rewriting the authored scene."""
        return self._runtime._configure_runtime_light(self.id, settings)

    @property
    def has_audio(self) -> bool:
        return self.id in self._runtime.audio_sources

    def audio_play(self, restart: bool = True) -> None:
        self._runtime._audio_play(self.id, restart=bool(restart))

    def audio_stop(self) -> None:
        self._runtime._audio_stop(self.id)

    @property
    def audio_volume(self) -> float:
        return self._runtime._audio_get_volume(self.id)

    @audio_volume.setter
    def audio_volume(self, value: float) -> None:
        self._runtime._audio_set_volume(self.id, float(value))

    @property
    def audio_loop(self) -> bool:
        item=self._runtime.audio_sources.get(self.id); sound=item.get('sound') if item else None
        try: return bool(sound.getLoop()) if sound else False
        except Exception: return False

    @audio_loop.setter
    def audio_loop(self, value: bool) -> None:
        item=self._runtime.audio_sources.get(self.id); sound=item.get('sound') if item else None
        if sound:
            try: sound.setLoop(bool(value))
            except Exception: pass

    @property
    def audio_rate(self) -> float:
        item=self._runtime.audio_sources.get(self.id); sound=item.get('sound') if item else None
        try: return float(sound.getPlayRate()) if sound else 1.0
        except Exception: return 1.0

    @audio_rate.setter
    def audio_rate(self, value: float) -> None:
        item=self._runtime.audio_sources.get(self.id); sound=item.get('sound') if item else None
        if sound:
            try: sound.setPlayRate(max(0.01,float(value)))
            except Exception: pass

    @property
    def has_particles(self) -> bool:
        return self.id in self._runtime.particle_emitters

    def particles_start(self) -> bool:
        return self._runtime._particle_set_running(self.id, True)

    def particles_stop(self, clear: bool = False) -> bool:
        ok = self._runtime._particle_set_running(self.id, False)
        if clear:
            self._runtime._particle_clear(self.id)
        return ok

    def particles_burst(self, count: int | None = None) -> bool:
        return self._runtime._particle_burst(self.id, count)

    @property
    def particle_config(self) -> dict:
        state = self._runtime.particle_emitters.get(self.id) or {}
        comp = state.get('component') or (self._runtime.entity_data.get(self.id, {}).get('components') or {}).get('particle_emitter') or {}
        return copy.deepcopy(comp)

    def particles_get(self, name: str, default=None):
        return copy.deepcopy(self.particle_config.get(str(name), default))

    def particles_set(self, name: str, value) -> bool:
        return self._runtime._particle_configure(self.id, {str(name): value})

    def particles_configure(self, **settings) -> bool:
        return self._runtime._particle_configure(self.id, settings)

    @property
    def particle_rate(self) -> float:
        return float(self.particles_get('rate', 0.0) or 0.0)

    @particle_rate.setter
    def particle_rate(self, value: float) -> None:
        self.particles_set('rate', float(value))

    @property
    def particle_speed(self) -> float:
        return float(self.particles_get('speed', 0.0) or 0.0)

    @particle_speed.setter
    def particle_speed(self, value: float) -> None:
        self.particles_set('speed', float(value))

    @property
    def particle_lifetime(self) -> float:
        return float(self.particles_get('lifetime', 0.0) or 0.0)

    @particle_lifetime.setter
    def particle_lifetime(self, value: float) -> None:
        self.particles_set('lifetime', float(value))

    @property
    def particle_spread(self) -> float:
        return float(self.particles_get('spread', 0.0) or 0.0)

    @particle_spread.setter
    def particle_spread(self, value: float) -> None:
        self.particles_set('spread', float(value))

    @property
    def particle_gravity(self) -> list[float]:
        return list(self.particles_get('gravity', [0.0,0.0,0.0]))

    @particle_gravity.setter
    def particle_gravity(self, value) -> None:
        self.particles_set('gravity', list(value)[:3])

    @property
    def task_names(self) -> list[str]:
        comp=(self._runtime.entity_data.get(self.id,{}).get('components') or {}).get('tasks_events') or {}
        return [str(x.get('name')) for x in (comp.get('tasks') or []) if str(x.get('name') or '').strip()]

    def task_start(self, name: str) -> bool:
        return self._runtime._managed_task_start(self.id, str(name))

    def task_stop(self, name: str) -> bool:
        return self._runtime._managed_task_stop(self.id, str(name))

    def task_trigger(self, name: str, payload=None) -> bool:
        return self._runtime._managed_task_trigger(self.id, str(name), payload)

    def task_pause(self, name: str) -> bool:
        return self._runtime._runtime_task_pause(self._runtime._task_key(self.id,str(name)))

    def task_resume(self, name: str) -> bool:
        return self._runtime._runtime_task_resume(self._runtime._task_key(self.id,str(name)))

    def task_info(self, name: str) -> dict | None:
        return self._runtime._runtime_task_info(self._runtime._task_key(self.id,str(name)))

    def event_send(self, event_name: str, payload=None) -> None:
        self._runtime._send_custom_event(str(event_name), payload, self.id)

    def emit(self, event_name: str, payload=None, target: str | None = None) -> None:
        self._runtime._dispatch_script_event(event_name, payload, target, self.id)

    def signal(self, signal_name: str, payload=None) -> None:
        """Emit a serialized Signals 2.0 output from this entity."""
        self._runtime._emit_entity_signal(self.id, str(signal_name), payload)


    @property
    def has_navigation_agent(self) -> bool:
        return self.has_component('navigation_agent')

    @property
    def navigation_config(self) -> dict:
        comp=(self._runtime.entity_data.get(self.id,{}).get('components') or {}).get('navigation_agent') or {}
        live=self._runtime.nav_agents.get(self.id) or {}
        out=copy.deepcopy(comp)
        for key in ('target','behavior','speed','stopping_distance','repath_interval','face_movement','surface'):
            if key in live: out[key]=copy.deepcopy(live[key])
        return out

    @property
    def navigation_path(self) -> list[list[float]]:
        state=self._runtime.nav_agents.get(self.id) or {}
        return [list(p) for p in (state.get('path') or [])]

    @property
    def navigation_target(self):
        state=self._runtime.nav_agents.get(self.id) or {}
        value=state.get('target')
        if not value: return None
        return self._runtime.runtime_world.get_entity(str(value)) or copy.deepcopy(value)

    @property
    def navigation_finished(self) -> bool:
        state=self._runtime.nav_agents.get(self.id) or {}
        return bool(state.get('finished', not bool(state.get('path'))))

    @property
    def navigation_next_position(self) -> list[float] | None:
        state=self._runtime.nav_agents.get(self.id) or {}
        path=state.get('path') or []
        return list(path[0]) if path else None

    def navigation_set_target(self, target, surface=None) -> bool:
        return self._runtime._navigation_agent_set_target(self.id, target, surface)

    def navigation_stop(self) -> bool:
        return self._runtime._navigation_agent_stop(self.id)

    def navigation_repath(self) -> bool:
        return self._runtime._navigation_agent_repath(self.id)

    def navigation_patrol(self, points, loop: bool=True) -> bool:
        return self._runtime._navigation_agent_patrol(self.id, points, bool(loop))

    def navigation_chase(self, target, repath_interval: float | None=None) -> bool:
        return self._runtime._navigation_agent_chase(self.id, target, repath_interval)

    def navigation_flee(self, target, distance: float=8.0, repath_interval: float | None=None) -> bool:
        return self._runtime._navigation_agent_flee(self.id, target, float(distance), repath_interval)

    @property
    def has_ai_behavior(self) -> bool:
        return self.has_component('ai_behavior')

    @property
    def ai_config(self) -> dict:
        comp=(self._runtime.entity_data.get(self.id,{}).get('components') or {}).get('ai_behavior') or {}
        live=self._runtime.ai_behaviors.get(self.id) or {}
        out=copy.deepcopy(comp)
        for key in ('state','target','paused','last_seen','disposition'):
            if key in live: out[key]=copy.deepcopy(live[key])
        return out

    @property
    def ai_state(self) -> str:
        return str((self._runtime.ai_behaviors.get(self.id) or {}).get('state','idle'))

    @property
    def ai_target(self):
        value=(self._runtime.ai_behaviors.get(self.id) or {}).get('target')
        if not value: return None
        return self._runtime.runtime_world.get_entity(str(value)) or copy.deepcopy(value)

    @property
    def ai_has_target(self) -> bool:
        return bool((self._runtime.ai_behaviors.get(self.id) or {}).get('target'))

    @property
    def ai_last_seen_position(self) -> list[float] | None:
        value=(self._runtime.ai_behaviors.get(self.id) or {}).get('last_seen')
        return list(value) if isinstance(value,(list,tuple)) and len(value)>=3 else None

    @property
    def ai_blackboard(self) -> dict:
        return copy.deepcopy((self._runtime.ai_behaviors.get(self.id) or {}).get('blackboard') or {})

    def ai_blackboard_get(self, key: str, default=None):
        return copy.deepcopy(((self._runtime.ai_behaviors.get(self.id) or {}).get('blackboard') or {}).get(str(key),default))

    def ai_blackboard_set(self, key: str, value) -> bool:
        state=self._runtime.ai_behaviors.get(self.id)
        if not state: return False
        state.setdefault('blackboard',{})[str(key)]=copy.deepcopy(value); return True

    def ai_set_state(self, state: str, reason: str='script') -> bool:
        return self._runtime._ai_set_state(self.id,str(state),str(reason))

    def ai_set_target(self, target) -> bool:
        return self._runtime._ai_set_target(self.id,target)

    def ai_clear_target(self, reason: str='script') -> bool:
        return self._runtime._ai_clear_target(self.id,str(reason))

    def ai_scan(self) -> list['RuntimeEntity']:
        return self._runtime._ai_scan_entities(self.id)

    def ai_think_now(self) -> bool:
        return self._runtime._ai_think(self.id,force=True)

    def ai_pause(self, paused: bool=True) -> bool:
        state=self._runtime.ai_behaviors.get(self.id)
        if not state: return False
        state['paused']=bool(paused)
        if paused and self.id in self._runtime.nav_agents: self._runtime._navigation_agent_stop(self.id)
        return True

    def ai_resume(self) -> bool:
        return self.ai_pause(False)

    def __repr__(self) -> str:
        return f'<RuntimeEntity name={self.name!r} id={self.id[:8]}>'


class RuntimeWorld:
    """Small, stable Play Mode API passed to entity scripts."""
    def __init__(self, runtime: 'PandaProcessRuntime') -> None:
        self._runtime = runtime
        self.time = 0.0
        self.dt = 0.0

    def get_entity(self, identifier: str) -> RuntimeEntity | None:
        if identifier in self._runtime.nodes:
            return RuntimeEntity(self._runtime, identifier)
        needle = str(identifier).lower()
        for eid, raw in self._runtime.entity_data.items():
            if str(raw.get('name', '')).lower() == needle:
                return RuntimeEntity(self._runtime, eid)
        return None

    def find(self, name: str) -> RuntimeEntity | None:
        return self.get_entity(name)

    @property
    def entities(self) -> list[RuntimeEntity]:
        return [RuntimeEntity(self._runtime, eid) for eid in self._runtime.nodes]

    def find_all(self, name: str | None=None, component: str | None=None, tag: str | None=None) -> list[RuntimeEntity]:
        out=[]; needle=str(name).lower() if name is not None else None; comp=str(component) if component else None; tag_l=str(tag).lower() if tag else None
        for eid,raw in self._runtime.entity_data.items():
            if eid not in self._runtime.nodes: continue
            if needle is not None and needle not in str(raw.get('name','')).lower(): continue
            if comp and comp not in (raw.get('components') or {}): continue
            if tag_l and not any(str(v).lower()==tag_l for v in (raw.get('tags') or [])): continue
            out.append(RuntimeEntity(self._runtime,eid))
        return out

    def entities_with_component(self, component: str) -> list[RuntimeEntity]:
        return self.find_all(component=str(component))

    def entities_with_tag(self, tag: str) -> list[RuntimeEntity]:
        return self.find_all(tag=str(tag))

    def has_entity(self, identifier: str) -> bool:
        return self.get_entity(str(identifier)) is not None

    @property
    def active_camera(self):
        return RuntimeEntity(self._runtime,self._runtime.play_camera_id) if self._runtime.play_camera_id in self._runtime.nodes else None

    def set_active_camera(self, camera, blend: float=0.0, ease: str='easeInOut') -> bool:
        ent=self.get_entity(camera) if not isinstance(camera,RuntimeEntity) else camera
        if not ent or not ent.has_component('camera'): return False
        return self._runtime._camera_activate(ent.id,float(blend),str(ease))

    def camera_blend_to(self, camera, duration: float=0.5, ease: str='easeInOut') -> bool:
        return self.set_active_camera(camera,blend=float(duration),ease=str(ease))

    def camera_shake(self, strength: float=0.25, duration: float=0.35, frequency: float=20.0, rotation: float=1.5) -> bool:
        if not self._runtime.play_camera_id: return False
        return self._runtime._camera_shake(self._runtime.play_camera_id,float(strength),float(duration),float(frequency),float(rotation))

    def log(self, message: object) -> None:
        self._runtime.log('[Game] ' + str(message))

    def emit(self, event_name: str, payload=None, target: str | None = None) -> None:
        self._runtime._dispatch_script_event(event_name, payload, target, None)

    def signal(self, sender, signal_name: str, payload=None) -> None:
        entity = self.get_entity(sender) if not isinstance(sender, RuntimeEntity) else sender
        if entity:
            self._runtime._emit_entity_signal(entity.id, str(signal_name), payload)

    def event_send(self, event_name: str, payload=None, target: str | None = None) -> None:
        self._runtime._send_custom_event(str(event_name), payload, target)

    def call_later(self, delay: float, event_name: str | None = None, payload=None, target: str | None = None, name: str | None = None, *, method: str | None = None) -> str:
        """Schedule a one-shot event or named script method.

        event_name routes through on_event(). method invokes a named method on the
        target entity's EntityScript with (entity, world, payload). Choose one.
        """
        event=str(event_name or '').strip(); method_name=str(method or '').strip()
        if not event and not method_name:
            raise ValueError('call_later() requires event_name or method=')
        return self._runtime._schedule_runtime_task(name or f'call_later_{time.time_ns()}', max(0.0,float(delay)), 0.0, 1, event, payload, target, method_name=method_name)

    def task_every(self, interval: float, event_name: str | None = None, payload=None, target: str | None = None, name: str | None = None, repeat: int = -1, *, method: str | None = None) -> str:
        """Schedule a repeating event or named script method.

        Runtime-created tasks start immediately; do not call entity.task_start()
        unless you are controlling an authored Tasks / Events component task.
        """
        event=str(event_name or '').strip(); method_name=str(method or '').strip()
        if not event and not method_name:
            raise ValueError('task_every() requires event_name or method=')
        iv=max(0.001,float(interval)); return self._runtime._schedule_runtime_task(name or f'task_{time.time_ns()}', iv, iv, int(repeat), event, payload, target, method_name=method_name)

    def task_cancel(self, name: str) -> bool:
        return self._runtime._cancel_runtime_task(str(name))

    def task_exists(self, name: str) -> bool:
        return self._runtime._runtime_task_exists(str(name))

    @property
    def tasks(self) -> list[str]:
        return sorted(str(v.get('public_name',k)) for k,v in self._runtime.managed_tasks.items() if v.get('enabled',True))

    def task_info(self, name: str) -> dict | None:
        return self._runtime._runtime_task_info(str(name))

    def task_pause(self, name: str) -> bool:
        return self._runtime._runtime_task_pause(str(name))

    def task_resume(self, name: str) -> bool:
        return self._runtime._runtime_task_resume(str(name))

    def interval_sequence(self, name: str, steps: list[dict], owner: str | None = None, loop: bool = False, play_rate: float = 1.0) -> bool:
        return self._runtime._runtime_interval_create(str(name), steps, owner, 'sequence', bool(loop), float(play_rate))

    def interval_parallel(self, name: str, steps: list[dict], owner: str | None = None, loop: bool = False, play_rate: float = 1.0) -> bool:
        return self._runtime._runtime_interval_create(str(name), steps, owner, 'parallel', bool(loop), float(play_rate))

    def load_scene(self, scene_path: str) -> None:
        self._runtime._request_scene_action('load', str(scene_path))

    def restart_scene(self) -> None:
        self._runtime._request_scene_action('restart', None)

    def quit_game(self) -> None:
        self._runtime._request_scene_action('quit', None)

    def key_down(self, key: str) -> bool:
        return self._runtime._key_down(str(key))

    def key_pressed(self, key: str) -> bool:
        """Return True only on the frame a direct keyboard key becomes pressed."""
        return str(key).strip().lower() in self._runtime._keys_pressed

    def key_released(self, key: str) -> bool:
        """Return True only on the frame a direct keyboard key is released."""
        return str(key).strip().lower() in self._runtime._keys_released

    def action_down(self, action: str) -> bool:
        return self._runtime._action_down(str(action))

    def action_pressed(self, action: str) -> bool:
        return str(action) in self._runtime._actions_pressed

    def action_released(self, action: str) -> bool:
        return str(action) in self._runtime._actions_released

    def action_axis(self, negative: str, positive: str) -> float:
        return float(self.action_down(positive)) - float(self.action_down(negative))

    @property
    def mouse_position(self) -> list[float]:
        return [float(self._runtime._mouse_position[0]), float(self._runtime._mouse_position[1])]

    @property
    def mouse_delta(self) -> list[float]:
        return [float(self._runtime._mouse_delta[0]), float(self._runtime._mouse_delta[1])]

    def mouse_down(self, button: str = 'mouse1') -> bool:
        return self._runtime._mouse_button_down(str(button))

    def mouse_pressed(self, button: str = 'mouse1') -> bool:
        """Return True only on the frame a mouse button becomes pressed."""
        return self._runtime._canonical_mouse_button(button) in self._runtime._mouse_buttons_pressed

    def mouse_released(self, button: str = 'mouse1') -> bool:
        """Return True only on the frame a mouse button is released."""
        return self._runtime._canonical_mouse_button(button) in self._runtime._mouse_buttons_released

    @property
    def mouse_captured(self) -> bool:
        return bool(self._runtime._mouse_captured)

    def capture_mouse(self, captured: bool = True) -> None:
        self._runtime._set_mouse_capture(bool(captured))

    def raycast(self, origin, direction, distance: float = 100.0, mask: int = 0xFFFFFFFF):
        """Cast a Bullet ray and return the closest interaction-layer match.

        Result is ``None`` or a dict containing entity/id/name/position/normal/
        fraction/distance.  ``mask`` is a 32-bit interaction-layer mask.
        """
        return self._runtime._runtime_raycast(origin, direction, distance, mask)

    def raycast_between(self, start, end, mask: int = 0xFFFFFFFF):
        a = Vec3(*[float(v) for v in list(start)[:3]])
        b = Vec3(*[float(v) for v in list(end)[:3]])
        d = b - a
        length = d.length()
        if length <= 1e-8:
            return None
        return self._runtime._runtime_raycast(a, d / length, length, mask)

    @property
    def gravity(self) -> list[float]:
        g = list(self._runtime.project_settings.get('gravity', [0.0, 0.0, -9.81])) + [0.0, 0.0, -9.81]
        return [float(g[0]), float(g[1]), float(g[2])]

    def set_gravity(self, x: float=0.0, y: float=0.0, z: float=-9.81) -> bool:
        g=[float(x),float(y),float(z)]
        self._runtime.project_settings['gravity']=g
        if self._runtime.physics_world is not None:
            try: self._runtime.physics_world.setGravity(Vec3(*g))
            except Exception: return False
        return True


    @property
    def navigation_surfaces(self) -> list[str]:
        return [str(v.get('name') or k) for k,v in self._runtime.nav_surfaces.items()]

    def navigation_find_path(self, start, end, surface=None, agent_radius: float=0.0) -> list[list[float]]:
        return self._runtime._navigation_find_path(start, end, surface, float(agent_radius))

    def navigation_nearest_point(self, point, surface=None) -> list[float] | None:
        return self._runtime._navigation_nearest_point(point, surface)

    def navigation_surface_info(self, surface=None) -> dict | None:
        return self._runtime._navigation_surface_info(surface)

    @property
    def ai_entities(self) -> list[RuntimeEntity]:
        return [RuntimeEntity(self._runtime,eid) for eid in self._runtime.ai_behaviors if eid in self._runtime.nodes]

    def ai_find_targets(self, origin, tag: str='', radius: float=20.0, fov: float=360.0, line_of_sight: bool=False) -> list[RuntimeEntity]:
        return self._runtime._ai_find_targets(origin,str(tag),float(radius),float(fov),bool(line_of_sight))

    def ai_broadcast(self, event_name: str, payload=None, tag: str='') -> int:
        count=0; wanted=str(tag or '').lower()
        for eid in list(self._runtime.ai_behaviors):
            ent=RuntimeEntity(self._runtime,eid)
            if wanted and not ent.has_tag(wanted): continue
            self._runtime._dispatch_script_event(str(event_name),payload,target=eid,sender=None); count+=1
        return count

    @property
    def render_pipeline(self) -> str:
        return str(self._runtime.project_settings.get('world_render_pipeline','builtin'))

    @property
    def post_process(self) -> dict:
        return self._runtime._post_process_config()

    def post_process_set(self, name: str, enabled: bool = True, **settings) -> bool:
        return self._runtime._post_process_set(str(name), bool(enabled), **settings)

    def post_process_clear(self) -> bool:
        return self._runtime._post_process_clear()


class PandaProcessRuntime:
    PICK_MASK = BitMask32.bit(1)
    GIZMO_MASK = BitMask32.bit(2)

    def __init__(self, parent_hwnd: int, commands, messages) -> None:
        self.parent_hwnd = int(parent_hwnd)
        self.commands = commands
        self.messages = messages
        self.base: ShowBase | None = None
        self.nodes: dict[str, NodePath] = {}
        self.pick_nodes: dict[str, NodePath] = {}
        self.rect = (260, 68, 800, 560)
        self.viewport_clip_rect = None
        self.viewport_exclusions = []
        self.selected: str | None = None
        self.selection_helper: NodePath | None = None
        self.running = True
        self.tool_mode = 'select'
        self.perspective = True
        self.wireframe = False
        self.camera_preset = 'perspective'

        self.camera_target = Vec3(0, 0, 1)
        self.camera_distance = 18.5
        self.camera_heading = -32.0
        self.camera_pitch = 27.0
        self._last_mouse: tuple[float, float] | None = None
        self._dragging = False
        self._drag_start_mouse: tuple[float, float] | None = None
        self._drag_start_transform: dict | None = None
        self._axis_constraint: str | None = None
        self.gizmo: NodePath | None = None
        self.gizmo_hit_nodes: list[NodePath] = []
        self.entity_lights: dict[str, NodePath] = {}
        self.entity_actors: dict[str, Actor] = {}
        self.animation_clips: dict[str, list[str]] = {}
        self.animation_preview_entity: str | None = None
        self._paused_animation_rates: dict[tuple[str, str], float] = {}
        self.node_components: dict[str, str] = {}
        self.entity_data: dict[str, dict] = {}
        self.preview_camera_id: str | None = None
        self._child_hwnd: int | None = None
        self._last_preview_event = 0.0
        self.play_mode = False
        self.play_paused = False
        self.play_camera_id: str | None = None
        self.runtime_camera_overrides: dict[str,dict] = {}
        self.camera_rig_state: dict[str,dict] = {}
        self.camera_transition: dict | None = None
        self.camera_shakes: dict[str,dict] = {}
        self._authoring_entities: list[dict] = []
        self._play_saved_selection: str | None = None
        self._play_saved_tool = 'select'
        self.script_instances: dict[str, object] = {}
        self.fsm_states: dict[str, str] = {}
        self.managed_tasks: dict[str, dict] = {}
        self.play_intervals: dict[str, dict] = {}
        self._paused_intervals: set[str] = set()
        self._task_clock = 0.0
        self._custom_event_names: set[str] = set()
        self.script_failed: set[str] = set()
        self.runtime_world = RuntimeWorld(self)
        self._play_start_time = 0.0
        self._play_last_time = 0.0
        self.grid_np: NodePath | None = None
        self.world_axis_np: NodePath | None = None
        self.collider_helpers_visible = True
        # Editor-only helper visibility is independent from authored world state.
        # These preferences are applied on top of workspace context visibility.
        self.editor_grid_visible = True
        self.editor_axes_visible = True
        self.editor_scene_helpers_visible = True
        self.physics_world = None
        self.physics_nodes: dict[str, NodePath] = {}
        self.physics_body_types: dict[str, str] = {}
        self.physics_ghost_nodes: dict[str, NodePath] = {}
        self.physics_characters: dict[str, NodePath] = {}
        self._character_move_written: set[str] = set()
        self._character_turn_written: set[str] = set()
        self.project_settings: dict = {'gravity':[0.0,0.0,-9.81], 'collision_layers':['Default']*32, 'input_actions':{}}
        self._actions_current: set[str] = set()
        self._actions_previous: set[str] = set()
        self._actions_pressed: set[str] = set()
        self._actions_released: set[str] = set()
        self._keys_current: set[str] = set()
        self._keys_previous: set[str] = set()
        self._keys_pressed: set[str] = set()
        self._keys_released: set[str] = set()
        self._mouse_buttons_current: set[str] = set()
        self._mouse_buttons_previous: set[str] = set()
        self._mouse_buttons_pressed: set[str] = set()
        self._mouse_buttons_released: set[str] = set()
        self._mouse_position = (0.0, 0.0)
        self._mouse_delta = (0.0, 0.0)
        self._play_mouse_last: tuple[float, float] | None = None
        self._mouse_captured = False
        # Ignore warp-generated pointer deltas for the first couple of captured frames.
        self._mouse_capture_suppress_frames = 0
        self._shadow_warning_keys: set[str] = set()
        self.audio_sources: dict[str, dict] = {}
        self.audio3d = None
        self.audio_preview_sound = None
        self.audio_preview_path: str | None = None
        self.ui_nodes: dict[str, object] = {}
        self.ui_root: NodePath | None = None
        self.particle_emitters: dict[str, dict] = {}
        self.terrains: dict[str, dict] = {}
        self.nav_surfaces: dict[str, dict] = {}
        self.nav_agents: dict[str, dict] = {}
        self.nav_obstacles: dict[str, dict] = {}
        self.ai_behaviors: dict[str, dict] = {}
        self._nav_debug_root: NodePath | None = None
        self.particle_preview_entity: str | None = None
        self._particle_preview_last_time = time.perf_counter()
        self.vfx_preview_mode = False
        self.vfx_preview_source: str | None = None
        self.vfx_preview_root: NodePath | None = None
        self.vfx_preview_emitter_root: NodePath | None = None
        self.vfx_preview_show_grid = True
        self.vfx_preview_show_axes = True
        # Central authoring viewport context.  Preview workspaces must never
        # inherit screen-space HUD, helpers, or unrelated scene state by
        # accident.  0.4.18 keeps this intentionally small and additive.
        self.editor_view_context = 'level'
        self.material_preview_mode = False
        self.material_preview_entity: str | None = None
        self.material_preview_root: NodePath | None = None
        self.material_preview_mesh_np: NodePath | None = None
        self.material_preview_mesh = 'sphere'
        self.material_preview_light = 'studio'
        # Dedicated offscreen material preview state.
        self.material_preview_buffer = None
        self.material_preview_texture: Texture | None = None
        self.material_preview_camera_np: NodePath | None = None
        self.material_preview_display_np: NodePath | None = None
        self.material_preview_scene_root: NodePath | None = None
        self._material_preview_previous_camera_mask = None
        self._terrain_paint_live: dict[str, dict] = {}
        self.world_fog = None
        self.simplepbr_pipeline = None
        self.complexpbr_module = None
        self.complexpbr_enabled = False
        self.complexpbr_screenspace_enabled = False
        self.common_filters = None
        self.shader_cache: dict[tuple[str,str,str], Shader] = {}
        self.world_skybox_np: NodePath | None = None
        self.editor_ambient_np: NodePath | None = None
        self.editor_sun_np: NodePath | None = None
        self.runtime_light_enabled: dict[str, bool] = {}
        self.bullet_debug_enabled = False
        self.bullet_debug_np: NodePath | None = None
        self.frame_rate_meter_enabled = False
        self._debug_last_emit = 0.0
        # Runtime-only physics interaction bookkeeping.  Layer/mask filtering is
        # currently used for script events and ray queries; Bullet physical
        # response remains broad until a project-wide collision matrix is added.
        self._contact_pairs: set[tuple[str, str]] = set()
        self._trigger_pairs: set[tuple[str, str]] = set()
        self.current_runtime_scene: str = ''
        self._pending_scene_action: tuple[str, object] | None = None
        self._standalone_game = False

        self.picker: CollisionTraverser | None = None
        self.pick_queue: CollisionHandlerQueue | None = None
        self.pick_ray: CollisionRay | None = None
        self.pick_ray_np: NodePath | None = None
        self.terrain_edit_enabled = False
        self.terrain_edit_entity: str | None = None
        self.terrain_edit_mode = 'raise'
        self.terrain_edit_radius = 4.0
        self.terrain_edit_strength = 0.5
        self.terrain_edit_falloff = 0.65
        self._terrain_brush_down = False
        self._terrain_brush_last_emit = 0.0
        self._terrain_brush_cursor: NodePath | None = None
        self._terrain_brush_last_point: tuple[str, float, float] | None = None

    def log(self, message: str) -> None:
        try:
            self.messages.put({'type': 'log', 'message': message})
        except Exception:
            pass

    def event(self, name: str, **payload) -> None:
        try:
            self.messages.put({'type': 'event', 'name': name, 'payload': payload})
        except Exception:
            pass

    def run(self) -> None:
        self.base = ShowBase(windowType='none')
        self.base.disableMouse()

        props = WindowProperties()
        x, y, w, h = self.rect
        props.setSize(w, h)
        props.setOrigin(x, y)
        props.setUndecorated(True)
        try:
            props.setForeground(False)
        except Exception:
            pass
        props.setParentWindow(NativeWindowHandle.makeInt(self.parent_hwnd))

        opened = self.base.openDefaultWindow(props=props)
        if not opened or not self.base.win:
            self.log('Viewport: Panda3D could not create the embedded graphics window.')
            return

        self._build_editor_world()
        self._bind_input()
        try:
            mgr = self.base.sfxManagerList[0] if self.base.sfxManagerList else None
            self.log(f'Audio: manager={mgr.__class__.__name__ if mgr else "none"}; OpenAL requested.')
        except Exception as exc:
            self.log(f'Audio: manager diagnostic failed: {exc}')
        self.log('Viewport: renderer initialized; picking and editor camera input are active.')

        while self.running:
            self._drain_commands()
            self.base.taskMgr.step()
            self._emit_debug_snapshot_periodic()
            time.sleep(0.001)

        # Ordered runtime cleanup matters on Windows/WebView2 shutdown.  Keep this
        # best-effort and observable: the host enforces a hard timeout and will
        # terminate this isolated process if a graphics driver/resource teardown
        # stalls (seen most often after large textures + lights/physics previews).
        def shutdown_trace(message: str) -> None:
            try:
                print(f'[Shutdown] Panda: {message}', flush=True)
            except Exception:
                pass
            try:
                self.log(f'[Shutdown] Panda: {message}')
            except Exception:
                pass

        shutdown_trace('cleanup started.')
        try:
            if self.play_mode:
                shutdown_trace('stopping Play Mode/scripts.')
                self._stop_play()
        except Exception as exc:
            shutdown_trace(f'Play cleanup warning: {exc}')
        try:
            shutdown_trace('stopping audio preview.')
            self._stop_audio_preview()
        except Exception as exc:
            shutdown_trace(f'audio cleanup warning: {exc}')
        try:
            shutdown_trace('clearing particle previews.')
            self._stop_all_particles(clear=True)
            for emitter_id in list(self.particle_emitters):
                self._destroy_particle_emitter(emitter_id)
        except Exception as exc:
            shutdown_trace(f'particle cleanup warning: {exc}')
        try:
            shutdown_trace('destroying material preview/render buffer.')
            self._destroy_material_preview()
        except Exception as exc:
            shutdown_trace(f'material preview cleanup warning: {exc}')
        try:
            # Drop editor-side shader/resource references before ShowBase asks the
            # graphics backend to release the window and VRAM allocations.
            self.shader_cache.clear()
            self.entity_actors.clear()
            self.animation_clips.clear()
            self.entity_lights.clear()
        except Exception:
            pass
        try:
            shutdown_trace('destroying Panda ShowBase / graphics window.')
            self.base.destroy()
            shutdown_trace('ShowBase destroyed cleanly.')
        except Exception as exc:
            shutdown_trace(f'ShowBase destroy warning: {exc}')

    def _drain_commands(self) -> None:
        while True:
            try:
                cmd = self.commands.get_nowait()
            except queue.Empty:
                break
            except (EOFError, OSError):
                self.running = False
                break

            op = cmd.get('op')
            try:
                if op == 'stop':
                    self.running = False
                    return
                if op == 'set_rect':
                    self._apply_rect(cmd.get('rect', {}))
                elif op == 'set_visible':
                    self._set_visible(bool(cmd.get('visible', True)))
                elif op == 'set_clip_rect':
                    self.viewport_clip_rect = copy.deepcopy(cmd.get('rect'))
                    self._apply_exclusions(self.viewport_exclusions)
                elif op == 'set_exclusions':
                    self.viewport_exclusions = copy.deepcopy(cmd.get('rects', []))
                    self._apply_exclusions(self.viewport_exclusions)
                elif op == 'sync_entities':
                    incoming = copy.deepcopy(cmd.get('entities', []))
                    self._authoring_entities = incoming
                    if not self.play_mode:
                        self._sync_entities(incoming)
                elif op == 'set_project_settings':
                    old_pipeline = str(self.project_settings.get('world_render_pipeline','builtin') or 'builtin').lower()
                    old_shader_auto = bool(self.project_settings.get('world_shader_auto', True))
                    self.project_settings = copy.deepcopy(cmd.get('settings') or self.project_settings)
                    self._refresh_ui_reference_layout(rebuild=True)
                    self._apply_world_settings()
                    new_pipeline = str(self.project_settings.get('world_render_pipeline','builtin') or 'builtin').lower()
                    new_shader_auto = bool(self.project_settings.get('world_shader_auto', True))
                    # A same-pipeline Built-in shader-auto change must refresh local
                    # material inheritance. Cross-pipeline changes are handled by a
                    # clean viewport-process restart in EditorAPI.
                    if not self.play_mode and old_pipeline == new_pipeline and old_shader_auto != new_shader_auto:
                        self._sync_entities(copy.deepcopy(self._authoring_entities))
                elif op == 'start_play':
                    self._start_play(copy.deepcopy(cmd.get('entities', [])), copy.deepcopy(cmd.get('project_settings') or self.project_settings))
                elif op == 'pause_play':
                    self._set_play_paused(bool(cmd.get('paused', False)))
                elif op == 'stop_play':
                    self._stop_play()
                elif op == 'select':
                    self._select(cmd.get('entity_id'))
                elif op == 'frame_selected':
                    self._frame_selected()
                elif op == 'frame_all':
                    self._frame_all()
                elif op == 'set_tool':
                    self.tool_mode = str(cmd.get('tool', 'select'))
                    self._axis_constraint = None
                    self._rebuild_gizmo()
                elif op == 'set_collision_helpers':
                    self._set_collision_helpers_visible(bool(cmd.get('visible', True)))
                elif op == 'set_editor_helper_visibility':
                    self._set_editor_helper_visibility(str(cmd.get('kind', 'scene')), bool(cmd.get('visible', True)))
                elif op == 'set_bullet_debug':
                    self._set_bullet_debug(bool(cmd.get('enabled', False)))
                elif op == 'set_frame_rate_meter':
                    self.frame_rate_meter_enabled = bool(cmd.get('enabled', False))
                    if self.base: self.base.setFrameRateMeter(self.frame_rate_meter_enabled)
                elif op == 'connect_pstats':
                    try:
                        ok = bool(PStatClient.connect())
                        self.log('PStats: client connected.' if ok else 'PStats: client connection request sent; ensure pstats server is running.')
                    except Exception as exc:
                        self.log(f'PStats connection failed: {exc}')
                elif op == 'toggle_projection':
                    self._toggle_projection()
                elif op == 'camera_preset':
                    self._set_camera_preset(str(cmd.get('preset', 'perspective')))
                elif op == 'set_wireframe':
                    self._set_wireframe(bool(cmd.get('enabled', False)))
                elif op == 'preview_camera':
                    self._preview_camera(cmd.get('entity_id'))
                elif op == 'preview_audio':
                    self._preview_audio(cmd.get('path'))
                elif op == 'stop_audio_preview':
                    self._stop_audio_preview()
                elif op == 'preview_animation':
                    self._preview_animation(cmd.get('entity_id'), cmd.get('clip'), cmd.get('mode', 'play'), cmd.get('rate'))
                elif op == 'refresh_animation_info':
                    self._emit_animation_info(cmd.get('entity_id'))
                elif op == 'preview_particles':
                    self._preview_particles(cmd.get('entity_id'), cmd.get('mode','start'), cmd.get('count'), bool(cmd.get('clear', False)))
                elif op == 'set_vfx_preview_scene':
                    self._set_vfx_preview_scene(bool(cmd.get('enabled', False)), cmd.get('entity_id'))
                elif op == 'vfx_preview_camera':
                    self._vfx_preview_camera(str(cmd.get('action','focus')))
                elif op == 'vfx_preview_options':
                    self._vfx_preview_options(bool(cmd.get('grid', True)), bool(cmd.get('axes', True)))
                elif op == 'set_material_preview_scene':
                    self._set_material_preview_scene(bool(cmd.get('enabled',False)),cmd.get('entity_id'),cmd.get('mesh','sphere'),cmd.get('light','studio'))
                elif op == 'update_material_preview':
                    self._update_material_preview(cmd.get('entity_id'))
                elif op == 'preview_material_component':
                    self._apply_material_preview_component(cmd.get('component') or {})
                elif op == 'material_preview_settings':
                    self._material_preview_settings(cmd.get('mesh','sphere'),cmd.get('light','studio'))
                elif op == 'material_preview_camera':
                    self._material_preview_camera(str(cmd.get('action','focus')))
                elif op == 'preview_light_action':
                    self._preview_light_action(cmd.get('entity_id'), cmd.get('action','toggle'))
                elif op == 'refresh_terrain':
                    self._refresh_authoring_terrain(cmd.get('entity_id'))
                elif op == 'set_terrain_edit':
                    self._set_terrain_edit(bool(cmd.get('enabled', False)), cmd.get('entity_id'), cmd.get('mode','raise'), cmd.get('radius',4.0), cmd.get('strength',.5), cmd.get('falloff',.65))
            except Exception as exc:
                self.log(f'Viewport command {op!r} failed: {exc}')

    def _build_editor_world(self) -> None:
        assert self.base
        self.base.render.setShaderAuto()
        self.base.setBackgroundColor(0.028, 0.036, 0.048, 1)

        lens = PerspectiveLens()
        # A moderate editor FOV keeps nearby primitives from looking stretched.
        lens.setFov(48)
        lens.setAspectRatio(max(0.1, self.rect[2] / max(1, self.rect[3])))
        lens.setNearFar(0.10, 5000)
        self.base.cam.node().setLens(lens)
        self._apply_editor_camera()

        ambient = AmbientLight('editorAmbient')
        ambient.setColor(Vec4(0.38, 0.41, 0.46, 1))
        self.editor_ambient_np = self.base.render.attachNewNode(ambient)
        self.base.render.setLight(self.editor_ambient_np)

        sun = DirectionalLight('editorSun')
        sun.setColor(Vec4(0.94, 0.92, 0.86, 1))
        sun_np = self.base.render.attachNewNode(sun)
        sun_np.setHpr(-35, -55, 0)
        self.editor_sun_np = sun_np
        self.base.render.setLight(sun_np)
        self._apply_world_settings()

        self._create_grid()
        self._create_axis()
        self._create_picker()

    def _create_grid(self, extent: int = 50, step: int = 1) -> None:
        assert self.base
        segs = LineSegs('editor-grid')
        segs.setThickness(1)
        for i in range(-extent, extent + 1, step):
            alpha = 0.30 if i % 5 == 0 else 0.12
            segs.setColor(0.30, 0.39, 0.48, alpha)
            segs.moveTo(i, -extent, 0)
            segs.drawTo(i, extent, 0)
            segs.moveTo(-extent, i, 0)
            segs.drawTo(extent, i, 0)
        grid = self.base.render.attachNewNode(segs.create())
        self.grid_np = grid
        self._isolate_editor_helper(grid)
        grid.setTransparency(True)
        grid.setDepthWrite(False)

    def _create_axis(self) -> None:
        assert self.base
        segs = LineSegs('world-axis')
        segs.setThickness(2)
        segs.setColor(0.88, 0.20, 0.20, 1)
        segs.moveTo(0, 0, 0.012); segs.drawTo(4, 0, 0.012)
        segs.setColor(0.20, 0.80, 0.36, 1)
        segs.moveTo(0, 0, 0.012); segs.drawTo(0, 4, 0.012)
        segs.setColor(0.26, 0.50, 0.96, 1)
        segs.moveTo(0, 0, 0.012); segs.drawTo(0, 0, 4)
        axis = self.base.render.attachNewNode(segs.create())
        self.world_axis_np = axis
        self._isolate_editor_helper(axis)
        axis.setDepthWrite(False)

    def _create_picker(self) -> None:
        assert self.base
        self.picker = CollisionTraverser('editorPicker')
        self.pick_queue = CollisionHandlerQueue()
        picker_node = CollisionNode('editorPickRay')
        picker_node.setFromCollideMask(self.PICK_MASK | self.GIZMO_MASK)
        picker_node.setIntoCollideMask(BitMask32.allOff())
        self.pick_ray = CollisionRay()
        picker_node.addSolid(self.pick_ray)
        self.pick_ray_np = self.base.camera.attachNewNode(picker_node)
        self.picker.addCollider(self.pick_ray_np, self.pick_queue)

    def _bind_input(self) -> None:
        assert self.base
        self.base.accept('mouse1', self._mouse1_down)
        self.base.accept('mouse1-up', self._mouse1_up)
        self.base.accept('wheel_up', lambda: self._zoom_camera(-1))
        self.base.accept('wheel_down', lambda: self._zoom_camera(1))
        self.base.accept('f', self._frame_selected)
        self.base.accept('g', lambda: self._set_tool_from_input('move'))
        self.base.accept('r', lambda: self._set_tool_from_input('rotate'))
        self.base.accept('s', lambda: self._set_tool_from_input('scale'))
        self.base.accept('q', lambda: self._set_tool_from_input('select'))
        self.base.accept('x', lambda: self._set_axis_constraint('x'))
        self.base.accept('y', lambda: self._set_axis_constraint('y'))
        self.base.accept('z', lambda: self._set_axis_constraint('z'))
        self.base.accept('escape', self._cancel_transform)
        self.base.taskMgr.add(self._camera_input_task, 'editorCameraInput')
        self.base.taskMgr.add(self._play_update_task, 'playModeUpdate')

    def _set_tool_from_input(self, tool: str) -> None:
        if self.play_mode:
            return
        self.tool_mode = tool
        self._axis_constraint = None
        self._rebuild_gizmo()
        self.event('tool_changed', tool=tool)

    def _set_axis_constraint(self, axis: str) -> None:
        if self.play_mode:
            return
        if self.tool_mode not in {'move', 'rotate', 'scale'} or not self.selected:
            return
        self._axis_constraint = None if self._axis_constraint == axis else axis
        self._rebuild_gizmo()
        self.event('transform_constraint', axis=self._axis_constraint)

    def _camera_input_task(self, task):
        assert self.base
        if self.play_mode or self.preview_camera_id:
            self._last_mouse = None
            return task.cont
        watcher = self.base.mouseWatcherNode
        if not watcher.hasMouse():
            self._last_mouse = None
            return task.cont

        self._ensure_arrow_cursor()
        m = watcher.getMouse()
        now = (float(m.x), float(m.y))
        middle = watcher.isButtonDown(MouseButton.two())
        if middle and self._last_mouse is not None:
            dx = now[0] - self._last_mouse[0]
            dy = now[1] - self._last_mouse[1]
            shift = watcher.isButtonDown(KeyboardButton.shift())
            if shift:
                self._pan_camera(dx, dy)
            else:
                self.camera_heading -= dx * 145.0
                self.camera_pitch = max(-82.0, min(82.0, self.camera_pitch + dy * 145.0))
                if self.camera_preset != 'custom':
                    self.camera_preset = 'custom'
                    self._apply_grid_for_preset('perspective')
                    self.event('camera_preset_changed', preset='custom')
                self._apply_editor_camera()
        self._last_mouse = now if middle else None
        if self._dragging:
            self._update_transform_drag(now)
        if self.terrain_edit_enabled:
            self._update_terrain_brush_cursor()
            if self._terrain_brush_down and watcher.isButtonDown(MouseButton.one()):
                tnow=time.monotonic()
                if tnow-self._terrain_brush_last_emit >= 1.0/12.0:
                    self._terrain_brush_last_emit=tnow
                    self._emit_terrain_brush_point('move')
        self._update_gizmo_scale()
        return task.cont

    def _apply_editor_camera(self) -> None:
        if not self.base:
            return
        h = math.radians(self.camera_heading)
        p = math.radians(self.camera_pitch)
        cp = math.cos(p)
        offset = Vec3(
            math.sin(h) * cp * self.camera_distance,
            -math.cos(h) * cp * self.camera_distance,
            math.sin(p) * self.camera_distance,
        )
        self.base.camera.setPos(self.camera_target + offset)
        self.base.camera.lookAt(self.camera_target)

    def _pan_camera(self, dx: float, dy: float) -> None:
        if not self.base:
            return
        scale = max(0.02, self.camera_distance * 0.65)
        right = self.base.camera.getQuat(self.base.render).getRight()
        up = self.base.camera.getQuat(self.base.render).getUp()
        self.camera_target += (-right * dx + up * dy) * scale
        self._apply_editor_camera()

    def _zoom_camera(self, direction: int) -> None:
        self.camera_distance = max(0.8, min(1000.0, self.camera_distance * (1.12 if direction > 0 else 0.89)))
        self._apply_editor_camera()
        self._update_lens_geometry()

    def _pick_at_mouse(self) -> tuple[str, str | None] | None:
        if not (self.base and self.picker and self.pick_queue and self.pick_ray and self.base.mouseWatcherNode.hasMouse()):
            return None
        m = self.base.mouseWatcherNode.getMouse()
        self.pick_ray.setFromLens(self.base.camNode, m.x, m.y)
        self.pick_queue.clearEntries()
        self.picker.traverse(self.base.render)
        if self.pick_queue.getNumEntries() <= 0:
            return None
        self.pick_queue.sortEntries()
        entity_hit = None
        for i in range(self.pick_queue.getNumEntries()):
            np = self.pick_queue.getEntry(i).getIntoNodePath()
            walk = np
            while not walk.isEmpty() and walk != self.base.render:
                if walk.hasTag('gizmo_axis'):
                    return ('gizmo', walk.getTag('gizmo_axis'))
                eid = walk.getTag('entity_id') if walk.hasTag('entity_id') else ''
                if eid and entity_hit is None:
                    entity_root = self.nodes.get(eid)
                    locked = bool(entity_root and entity_root.hasTag('editor_locked') and entity_root.getTag('editor_locked') == '1')
                    if not locked:
                        entity_hit = ('entity', eid)
                walk = walk.getParent()
        return entity_hit

    def _pick_entity_at_mouse(self) -> str | None:
        hit = self._pick_at_mouse()
        return hit[1] if hit and hit[0] == 'entity' else None

    def _mouse1_down(self) -> None:
        if self.play_mode:
            return
        if not self.base or not self.base.mouseWatcherNode.hasMouse():
            return
        if self.terrain_edit_enabled and self.terrain_edit_entity:
            if self._emit_terrain_brush_point('start'):
                self._terrain_brush_down = True
                self._terrain_brush_last_emit = time.monotonic()
            return
        picked = self._pick_at_mouse()
        if picked and picked[0] == 'gizmo' and self.tool_mode in {'move', 'rotate', 'scale'}:
            self._axis_constraint = picked[1]
            self._rebuild_gizmo()
            self.event('transform_constraint', axis=self._axis_constraint)
            hit = self.selected
        else:
            hit = picked[1] if picked and picked[0] == 'entity' else None
        if self.tool_mode == 'select':
            self._select(hit)
            self.event('selection_changed', entity_id=hit)
            return
        if hit and hit != self.selected:
            self._select(hit)
            self.event('selection_changed', entity_id=hit)
            return
        if not self.selected or hit != self.selected:
            return
        root = self.nodes.get(self.selected)
        if not root:
            return
        if root.hasTag('editor_locked') and root.getTag('editor_locked') == '1':
            return
        m = self.base.mouseWatcherNode.getMouse()
        self._dragging = True
        self._drag_start_mouse = (float(m.x), float(m.y))
        self._drag_start_transform = {
            'position': [float(v) for v in root.getPos()],
            'rotation': [float(v) for v in root.getHpr()],
            'scale': [float(v) for v in root.getScale()],
        }

    def _mouse1_up(self) -> None:
        if self.terrain_edit_enabled and self._terrain_brush_down:
            self._emit_terrain_brush_point('end')
            self._terrain_brush_down = False
            return
        if not self._dragging or not self.selected or not self._drag_start_transform:
            return
        root = self.nodes.get(self.selected)
        before = self._drag_start_transform
        self._dragging = False
        self._drag_start_mouse = None
        self._drag_start_transform = None
        if not root:
            return
        after = {
            'position': [float(v) for v in root.getPos()],
            'rotation': [float(v) for v in root.getHpr()],
            'scale': [float(v) for v in root.getScale()],
        }
        if before != after:
            self.event('transform_committed', entity_id=self.selected, before=before, after=after)

    def _cancel_transform(self) -> None:
        if not self._dragging or not self.selected or not self._drag_start_transform:
            return
        root = self.nodes.get(self.selected)
        if root:
            t = self._drag_start_transform
            root.setPos(*t['position']); root.setHpr(*t['rotation']); root.setScale(*t['scale'])
        self._dragging = False
        self._drag_start_mouse = None
        self._drag_start_transform = None
        self._rebuild_gizmo()

    def _axis_screen_direction(self, axis: str) -> tuple[float, float]:
        """Return the signed screen-space direction of a positive world axis.

        This keeps axis dragging visually consistent as the editor camera orbits into
        different quadrants; the old dx+dy method changed sign unpredictably.
        """
        assert self.base
        world_axis = {'x': Vec3(1, 0, 0), 'y': Vec3(0, 1, 0), 'z': Vec3(0, 0, 1)}[axis]
        quat = self.base.camera.getQuat(self.base.render)
        screen_x = float(world_axis.dot(quat.getRight()))
        screen_y = float(world_axis.dot(quat.getUp()))
        mag = math.hypot(screen_x, screen_y)
        if mag < 1e-4:
            # Axis is almost aimed into the camera; use a stable vertical fallback.
            return (0.0, 1.0)
        return (screen_x / mag, screen_y / mag)

    def _update_transform_drag(self, now: tuple[float, float]) -> None:
        if not (self.base and self.selected and self._drag_start_mouse and self._drag_start_transform):
            return
        root = self.nodes.get(self.selected)
        if not root:
            return
        sx, sy = self._drag_start_mouse
        dx, dy = now[0] - sx, now[1] - sy
        start = self._drag_start_transform
        axis = self._axis_constraint
        fine = self.base.mouseWatcherNode.isButtonDown(KeyboardButton.shift())
        factor = 0.25 if fine else 1.0

        if self.tool_mode == 'move':
            distance_scale = max(0.1, self.camera_distance * 0.48) * factor
            delta = self.base.camera.getQuat(self.base.render).getRight() * (dx * distance_scale)
            delta += self.base.camera.getQuat(self.base.render).getUp() * (dy * distance_scale)
            if axis:
                screen_axis = self._axis_screen_direction(axis)
                amount = (dx * screen_axis[0] + dy * screen_axis[1]) * distance_scale
                delta = {'x': Vec3(amount,0,0), 'y': Vec3(0,amount,0), 'z': Vec3(0,0,amount)}[axis]
            root.setPos(Vec3(*start['position']) + delta)
        elif self.tool_mode == 'rotate':
            amount = (dx + dy) * 140.0 * factor
            hpr = list(start['rotation'])
            if axis == 'x': hpr[2] += amount
            elif axis == 'y': hpr[1] += amount
            else: hpr[0] += amount
            root.setHpr(*hpr)
        elif self.tool_mode == 'scale':
            amount = max(0.05, 1.0 + (dx + dy) * 1.6 * factor)
            scale = list(start['scale'])
            if axis == 'x': scale[0] = max(0.01, scale[0] * amount)
            elif axis == 'y': scale[1] = max(0.01, scale[1] * amount)
            elif axis == 'z': scale[2] = max(0.01, scale[2] * amount)
            else: scale = [max(0.01, v * amount) for v in scale]
            root.setScale(*scale)
        self._update_gizmo_scale()
        now_t = time.monotonic()
        if now_t - self._last_preview_event >= 1.0 / 30.0:
            self._last_preview_event = now_t
            self.event('transform_preview', entity_id=self.selected, transform={
                'position': [float(v) for v in root.getPos()],
                'rotation': [float(v) for v in root.getHpr()],
                'scale': [float(v) for v in root.getScale()],
            })

    def _find_child_hwnd(self) -> int | None:
        """Find the Panda graphics child HWND created inside the pywebview parent."""
        if self._child_hwnd:
            return self._child_hwnd
        if os.name != 'nt':
            return None
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            found: list[int] = []
            current_pid = os.getpid()
            CALLBACK = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            def enum_proc(hwnd, _lparam):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == current_pid:
                    found.append(int(hwnd))
                return True
            user32.EnumChildWindows(wintypes.HWND(self.parent_hwnd), CALLBACK(enum_proc), 0)
            if found:
                self._child_hwnd = found[-1]
            return self._child_hwnd
        except Exception as exc:
            self.log(f'Viewport: could not resolve child HWND for clipping: {exc}')
            return None

    def _apply_exclusions(self, rects: list[dict]) -> None:
        """Apply the visible HTML-host clip and subtract HTML overlays from the Win32 child.

        The embedded Panda viewport is a native child HWND.  Chromium can scroll the
        HTML host without automatically clipping that child, so the region must start
        from ``viewport_clip_rect`` rather than always using the full Panda window.
        """
        if os.name != 'nt':
            return
        hwnd = self._find_child_hwnd()
        if not hwnd:
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            w, h = self.rect[2], self.rect[3]
            clip = self.viewport_clip_rect

            # No explicit host clip means the complete Panda child is visible.
            if clip is None and not rects:
                user32.SetWindowRgn(hwnd, 0, True)
                return

            if clip is None:
                cx, cy, cw, ch = 0, 0, w, h
            else:
                cx = max(0, int(clip.get('x', 0)))
                cy = max(0, int(clip.get('y', 0)))
                cw = max(0, int(clip.get('width', 0)))
                ch = max(0, int(clip.get('height', 0)))

            # A zero-sized clip intentionally hides the native child while its HTML
            # host is completely scrolled out of view.
            right = min(w, cx + cw)
            bottom = min(h, cy + ch)
            if cw <= 0 or ch <= 0 or right <= cx or bottom <= cy:
                region = gdi32.CreateRectRgn(0, 0, 0, 0)
            else:
                region = gdi32.CreateRectRgn(cx, cy, right, bottom)

            RGN_DIFF = 4
            try:
                for raw in rects:
                    x = max(0, int(raw.get('x', 0)))
                    y = max(0, int(raw.get('y', 0)))
                    rw = max(0, int(raw.get('width', 0)))
                    rh = max(0, int(raw.get('height', 0)))
                    if rw <= 0 or rh <= 0:
                        continue
                    cut = gdi32.CreateRectRgn(x, y, min(w, x + rw), min(h, y + rh))
                    try:
                        gdi32.CombineRgn(region, region, cut, RGN_DIFF)
                    finally:
                        gdi32.DeleteObject(cut)
                # Ownership of region transfers to Windows when successful.
                if not user32.SetWindowRgn(hwnd, region, True):
                    gdi32.DeleteObject(region)
            except Exception:
                gdi32.DeleteObject(region)
                raise
        except Exception as exc:
            self.log(f'Viewport: overlay clipping failed: {exc}')

    def _set_visible(self, visible: bool) -> None:
        if self.base and self.base.win:
            props = WindowProperties()
            props.setMinimized(not visible)
            self.base.win.requestProperties(props)

    def _apply_rect(self, rect: dict) -> None:
        self.rect = (
            int(rect.get('x', 0)), int(rect.get('y', 0)),
            max(64, int(rect.get('width', 640))),
            max(64, int(rect.get('height', 480))),
        )
        if self.base and self.base.win:
            props = WindowProperties()
            props.setOrigin(self.rect[0], self.rect[1])
            props.setSize(self.rect[2], self.rect[3])
            self.base.win.requestProperties(props)
            self._update_lens_geometry()
            # Material preview is a square RTT.  Keep that texture square inside a wide
            # editor host instead of stretching it to the native child-window aspect.
            if self.material_preview_mode and self.material_preview_display_np:
                try:
                    aspect=max(0.001,float(self.rect[2])/max(1.0,float(self.rect[3])))
                    self.material_preview_display_np.setScale(1.0/aspect if aspect>1.0 else 1.0,1.0,aspect if aspect<1.0 else 1.0)
                except Exception: pass
            self._refresh_ui_reference_layout(rebuild=False)
            for eid, raw in list(self.entity_data.items()):
                ui = (raw.get('components') or {}).get('ui') or {}
                if ui:
                    self._build_ui_component(eid, str(raw.get('name', eid)), ui)

    def _update_lens_geometry(self) -> None:
        if not self.base:
            return
        if self.play_mode and self.play_camera_id:
            self._apply_game_camera()
            return
        if self.preview_camera_id:
            self._apply_preview_camera()
        if self.vfx_preview_mode:
            # Entity syncs can rebuild normal scene roots. Reassert VFX isolation immediately
            # so adding/editing an emitter never flashes the authored level into the preview.
            self._set_editor_view_context('vfx')
            for normal_root in self.nodes.values():
                try: normal_root.hide()
                except Exception: pass
            self._ensure_vfx_preview_scene(self.vfx_preview_source)
            if self.vfx_preview_root and not self.vfx_preview_root.isEmpty():
                self.vfx_preview_root.show()
            return
        lens = self.base.cam.node().getLens()
        aspect = max(0.1, self.rect[2] / max(1, self.rect[3]))
        if self.perspective:
            try:
                lens.setAspectRatio(aspect)
            except Exception:
                pass
        else:
            height = max(0.5, self.camera_distance * 0.90)
            try:
                lens.setFilmSize(height * aspect, height)
            except Exception:
                pass


    def _set_authoring_ui_visible(self, visible: bool) -> None:
        """Show/hide the authored DirectGUI root without destroying it.

        Preview workspaces are editor tools, not game scenes.  Keeping this
        decision in one place prevents HUD controls from leaking into VFX or
        material previews and avoids per-workspace ad-hoc visibility toggles.
        """
        if self.ui_root and not self.ui_root.isEmpty():
            try:
                self.ui_root.show() if visible else self.ui_root.hide()
            except Exception:
                pass

    def _set_editor_view_context(self, context: str) -> None:
        """Apply shared visibility rules for authoring/preview contexts.

        This is deliberately a lifecycle coordinator rather than a new render
        architecture.  Existing VFX and Material preview implementations stay
        intact while common HUD/helper isolation is centralized.
        """
        context = str(context or 'level').lower()
        if context not in {'level', 'vfx', 'material'}:
            context = 'level'
        self.editor_view_context = context
        preview = context in {'vfx', 'material'}
        self._set_authoring_ui_visible(not preview)
        self._set_editor_helpers_visible(not preview)
        if self._nav_debug_root and not self._nav_debug_root.isEmpty():
            try:
                self._nav_debug_root.hide() if preview else self._nav_debug_root.show()
            except Exception:
                pass
        if self.bullet_debug_np and not self.bullet_debug_np.isEmpty():
            try:
                if preview or not self.bullet_debug_enabled:
                    self.bullet_debug_np.hide()
                else:
                    self.bullet_debug_np.show()
            except Exception:
                pass

    def _isolate_editor_helper(self, np: NodePath | None) -> NodePath | None:
        """Keep authoring helpers visually independent from game-world render state.

        Helper geometry is part of the editor, not the authored scene.  Because many
        helpers intentionally remain parented under entity roots so they follow object
        transforms, they can otherwise inherit world lights, custom shaders, fog,
        textures, materials or colour-scale overrides.  High-priority state overrides
        make helper colours deterministic without changing the game/world renderer.
        """
        if not np or np.isEmpty():
            return np
        try: np.setTag('editor_helper', '1')
        except Exception: pass
        priority = 10000
        for method, args in (
            ('setLightOff', (priority,)),
            ('setShaderOff', (priority,)),
            ('setTextureOff', (priority,)),
            ('setFogOff', (priority,)),
            ('setMaterialOff', (priority,)),
            ('setColorScaleOff', (priority,)),
        ):
            try:
                fn=getattr(np, method, None)
                if fn: fn(*args)
            except Exception:
                pass
        return np

    def _set_editor_helper_visibility(self, kind: str, visible: bool) -> None:
        """Set authoring helper visibility without changing authored entities."""
        kind=str(kind or 'scene').lower()
        if kind == 'grid': self.editor_grid_visible=bool(visible)
        elif kind in {'axes','axis'}: self.editor_axes_visible=bool(visible)
        elif kind in {'scene','helpers'}: self.editor_scene_helpers_visible=bool(visible)
        else: return
        self._set_editor_helpers_visible(self.editor_view_context == 'level' and not self.play_mode)

    def _set_editor_helpers_visible(self, visible: bool) -> None:
        level_visible=bool(visible) and not self.play_mode
        if self.grid_np and not self.grid_np.isEmpty():
            self._isolate_editor_helper(self.grid_np)
            self.grid_np.show() if level_visible and self.editor_grid_visible else self.grid_np.hide()
        if self.world_axis_np and not self.world_axis_np.isEmpty():
            self._isolate_editor_helper(self.world_axis_np)
            self.world_axis_np.show() if level_visible and self.editor_axes_visible else self.world_axis_np.hide()
        for np in (self.selection_helper, self.gizmo):
            if np and not np.isEmpty():
                self._isolate_editor_helper(np)
                np.show() if level_visible and self.editor_scene_helpers_visible else np.hide()
        for root in self.nodes.values():
            if root and not root.isEmpty():
                for helper in root.findAllMatches('**/*helper*'):
                    self._isolate_editor_helper(helper)
                    helper.show() if level_visible and self.editor_scene_helpers_visible else helper.hide()
        if level_visible and self.editor_scene_helpers_visible:
            self._apply_collision_helper_visibility()
        else:
            for root in self.nodes.values():
                if root and not root.isEmpty():
                    for helper in root.findAllMatches('**/*collider-helper*'):
                        helper.hide()

    def _set_collision_helpers_visible(self, visible: bool) -> None:
        self.collider_helpers_visible = bool(visible)
        self._apply_collision_helper_visibility()

    def _apply_collision_helper_visibility(self) -> None:
        for root in self.nodes.values():
            if root and not root.isEmpty():
                for helper in root.findAllMatches('**/*collider-helper*'):
                    if self.collider_helpers_visible and not self.play_mode:
                        helper.show()
                    else:
                        helper.hide()

    def _start_play(self, entities: list[dict], project_settings: dict | None = None) -> None:
        if not self.base:
            return
        if self.play_mode:
            self._stop_play()
        self._authoring_entities = copy.deepcopy(entities)
        if project_settings is not None:
            self.project_settings = copy.deepcopy(project_settings)
        self._play_saved_selection = self.selected
        self._play_saved_tool = self.tool_mode
        self.play_mode = True
        self.play_paused = False
        self.preview_camera_id = None
        self.selected = None
        self.tool_mode = 'select'
        self._sync_entities(copy.deepcopy(entities))
        self._start_play_animations()
        self._select(None)
        self._set_editor_helpers_visible(False)
        self._play_start_time = time.perf_counter()
        self._play_last_time = self._play_start_time
        self._build_play_physics()
        self._build_play_audio()
        self.particle_preview_entity = None
        self._start_play_particles()
        self._play_mouse_last = None
        self._mouse_delta = (0.0, 0.0)
        self._keys_current.clear(); self._keys_previous.clear(); self._keys_pressed.clear(); self._keys_released.clear()
        self._mouse_buttons_current.clear(); self._mouse_buttons_previous.clear(); self._mouse_buttons_pressed.clear(); self._mouse_buttons_released.clear()
        self.runtime_world.time = 0.0
        self.runtime_world.dt = 0.0
        self._initialize_fsms()
        self._initialize_tasks_events()
        self._initialize_intervals()
        self._initialize_navigation()
        self._initialize_ai_behaviors()
        # Camera runtime state must exist before script on_start() callbacks.
        # This makes camera_configure()/camera_activate() valid from on_start
        # instead of clearing those API changes immediately after scripts load.
        self.runtime_camera_overrides.clear(); self.camera_rig_state.clear(); self.camera_transition=None; self.camera_shakes.clear()
        self.play_camera_id = self._find_active_camera()
        self._load_play_scripts()
        self._refresh_ui_interaction_state()
        if self.play_camera_id:
            self._apply_game_camera()
        else:
            self._restore_editor_lens()
            self._apply_editor_camera()
        self.log(f'Play Mode: running {len(self.nodes)} entities, {len(self.script_instances)} scripts.')
        self.event('play_state_changed', state='playing', camera_id=self.play_camera_id)

    def _set_play_paused(self, paused: bool) -> None:
        if not self.play_mode:
            return
        paused = bool(paused)
        if paused and not self.play_paused:
            self._paused_animation_rates.clear()
            for eid, actor in list(self.entity_actors.items()):
                try:
                    for clip in actor.getAnimNames():
                        control = actor.getAnimControl(clip)
                        if control and control.isPlaying():
                            self._paused_animation_rates[(eid, str(clip))] = float(control.getPlayRate())
                            actor.setPlayRate(0.0, clip)
                except Exception:
                    pass
        elif not paused and self.play_paused:
            for (eid, clip), rate in list(self._paused_animation_rates.items()):
                actor = self.entity_actors.get(eid)
                if actor is not None:
                    try: actor.setPlayRate(float(rate), clip)
                    except Exception: pass
            self._paused_animation_rates.clear()
        self.play_paused = paused
        self._set_intervals_paused(paused)
        self._refresh_ui_interaction_state()
        self._play_last_time = time.perf_counter()
        self.event('play_state_changed', state='paused' if self.play_paused else 'playing', camera_id=self.play_camera_id)

    def _stop_play(self) -> None:
        if not self.play_mode:
            return
        for eid, instance in list(self.script_instances.items()):
            callback = getattr(instance, 'on_stop', None)
            if callable(callback):
                try:
                    self._call_script_callback(eid, callback, RuntimeEntity(self, eid), self.runtime_world)
                except Exception:
                    self.log(f'Script on_stop error [{eid}]:\n{traceback.format_exc()}')
        self._clear_tasks_events()
        self._clear_intervals()
        self._clear_ai_behaviors()
        self._clear_navigation_runtime()
        self.script_instances.clear()
        self.script_failed.clear()
        self._destroy_play_audio()
        self._stop_all_particles(clear=True)
        self._destroy_play_physics()
        self._set_mouse_capture(False)
        self._keys_current.clear(); self._keys_previous.clear(); self._keys_pressed.clear(); self._keys_released.clear()
        self._mouse_buttons_current.clear(); self._mouse_buttons_previous.clear(); self._mouse_buttons_pressed.clear(); self._mouse_buttons_released.clear()
        self._reset_animations_to_authoring_pose()
        self.play_mode = False
        self.play_paused = False
        self.play_camera_id = None
        # Runtime terrain configuration is intentionally temporary. Force terrain
        # entity mirrors to rebuild from the authored snapshot on Stop, even when
        # the original serialized component signature itself did not change.
        for terrain_id in list(self.terrains):
            self._destroy_terrain(terrain_id)
            self.node_components.pop(terrain_id, None)
        self._sync_entities(copy.deepcopy(self._authoring_entities))
        self._refresh_ui_interaction_state()
        self.tool_mode = self._play_saved_tool
        self.selected = self._play_saved_selection
        self._restore_editor_lens()
        self._apply_editor_camera()
        self._select(self.selected)
        self._set_editor_helpers_visible(True)
        self.event('play_state_changed', state='stopped', camera_id=None)

    def _start_play_animations(self) -> None:
        for eid, actor in list(self.entity_actors.items()):
            try: actor.stop()
            except Exception: pass
            raw = self.entity_data.get(eid, {})
            comp = (raw.get('components') or {}).get('animation') or {}
            if comp.get('enabled', True) is False or not comp.get('autoplay', False):
                continue
            clips = list(self.animation_clips.get(eid) or [])
            if not clips:
                try: clips = list(actor.getAnimNames())
                except Exception: clips = []
            requested = str(comp.get('default_clip') or '').strip()
            clip = requested if requested in clips else (clips[0] if clips else '')
            if clip:
                self._animation_play(eid, clip, loop=bool(comp.get('loop', True)), restart=True, rate=float(comp.get('play_rate', 1.0) or 1.0))

    def _reset_animations_to_authoring_pose(self) -> None:
        self._paused_animation_rates.clear()
        for eid, actor in list(self.entity_actors.items()):
            try:
                actor.stop()
                clips = list(self.animation_clips.get(eid) or actor.getAnimNames())
                raw = self.entity_data.get(eid, {})
                comp = (raw.get('components') or {}).get('animation') or {}
                requested = str(comp.get('default_clip') or '').strip()
                clip = requested if requested in clips else (clips[0] if clips else '')
                if clip:
                    actor.pose(clip, 0)
            except Exception:
                pass

    def _find_active_camera(self) -> str | None:
        for eid, raw in self.entity_data.items():
            camera = (raw.get('components') or {}).get('camera')
            if camera and camera.get('active'):
                return eid
        return None

    def _load_play_scripts(self) -> None:
        self.script_instances.clear()
        self.script_failed.clear()
        for eid, raw in self.entity_data.items():
            script = (raw.get('components') or {}).get('script') or {}
            if not script or script.get('enabled', True) is False:
                continue
            rel = str(script.get('path') or '').strip()
            if not rel:
                continue
            path = (PROJECT_ROOT / rel).resolve()
            if PROJECT_ROOT.resolve() not in path.parents and path != PROJECT_ROOT.resolve():
                self.log(f'Script blocked outside project root: {rel}')
                continue
            try:
                if path.exists():
                    module_name = f'panda_editor_runtime_{eid}_{time.time_ns()}'
                    spec = importlib.util.spec_from_file_location(module_name, path)
                    if not spec or not spec.loader:
                        raise RuntimeError('Could not create Python module spec.')
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                else:
                    # build_apps freezes project scripts as regular Python modules.
                    # Fall back to module import when the source file is not shipped.
                    module_name = rel.replace('\\', '/').removesuffix('.py').replace('/', '.')
                    if not module_name or any(not part.isidentifier() for part in module_name.split('.')):
                        raise RuntimeError(f'Script is not available as a frozen module: {rel}')
                    module = importlib.import_module(module_name)
                script_type = getattr(module, 'EntityScript', None)
                if script_type is None:
                    raise RuntimeError('Script must define class EntityScript.')
                instance = script_type()
                self.script_instances[eid] = instance
                start = getattr(instance, 'on_start', None)
                if callable(start):
                    self._call_script_callback(eid, start, RuntimeEntity(self, eid), self.runtime_world)
                self.log(f'Script loaded: {rel} -> {raw.get("name", eid)}')
            except Exception:
                self.script_failed.add(eid)
                self.log(f'Script load/start error [{raw.get("name", eid)}]:\n{traceback.format_exc()}')

    def _call_script_callback(self, eid: str, callback, *args):
        """Run project script callbacks while routing print() into editor/game logging."""
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                return callback(*args)
        finally:
            text = buf.getvalue().strip()
            if text:
                for line in text.splitlines():
                    self.log('[Script] ' + line)

    def _play_update_task(self, task):
        self._update_terrains()
        self._update_entity_lod()
        if not self.play_mode:
            if self.particle_preview_entity:
                now = time.perf_counter(); dt = max(0.0, min(0.1, now - self._particle_preview_last_time)); self._particle_preview_last_time = now
                self._update_particle_emitters(dt, authoring_preview=True)
            return task.cont
        now = time.perf_counter()
        dt = max(0.0, min(0.1, now - self._play_last_time))
        self._play_last_time = now
        if not self.play_paused:
            self._update_play_mouse()
            self._update_raw_input_states()
            self._update_action_states()
            self._character_move_written.clear()
            self._character_turn_written.clear()
            for _eid, _np in list(self.physics_characters.items()):
                try: _np.node().setLinearMovement(Vec3(0,0,0), True)
                except Exception: pass
                try: _np.node().setAngularMovement(0.0)
                except Exception: pass
            self.runtime_world.dt = dt
            self.runtime_world.time = max(0.0, now - self._play_start_time)
            self._task_clock += dt
            self._update_managed_tasks(dt)
            self._update_particle_emitters(dt)
            for eid, instance in list(self.script_instances.items()):
                if eid in self.script_failed:
                    continue
                callback = getattr(instance, 'on_update', None)
                if callable(callback):
                    try:
                        self._call_script_callback(eid, callback, RuntimeEntity(self, eid), self.runtime_world, dt)
                    except Exception:
                        self.script_failed.add(eid)
                        raw = self.entity_data.get(eid, {})
                        self.log(f'Script update disabled after error [{raw.get("name", eid)}]:\n{traceback.format_exc()}')
            self._update_ai_behaviors(dt)
            self._update_navigation_agents(dt)
            if self.physics_world is not None and dt > 0.0:
                self._sync_non_dynamic_physics()
                self.physics_world.doPhysics(dt, 4, 1.0 / 240.0)
                self._sync_dynamic_from_physics()
                self._sync_characters_from_physics()
                self._process_physics_interactions()
        if self.play_camera_id or self.camera_transition:
            self._apply_game_camera(dt)
        if self._pending_scene_action:
            self._perform_pending_scene_action()
        return task.cont

    def _task_key(self, owner: str | None, name: str) -> str:
        return f'{owner or "world"}:{str(name)}'

    def _schedule_runtime_task(self, name: str, delay: float, interval: float, repeat: int, event_name: str, payload=None, target: str | None = None, signal: str = '', method_name: str = '') -> str:
        public=str(name or f'task_{time.time_ns()}'); key=self._task_key(target,public)
        self.managed_tasks[key]={'public_name':public,'owner':target,'due':self._task_clock+max(0.0,float(delay)),'interval':max(0.0,float(interval)),'repeat':int(repeat),'remaining':int(repeat),'event':str(event_name or ''),'method':str(method_name or ''),'signal':str(signal or ''),'payload':copy.deepcopy(payload),'enabled':True,'frame':False}
        return public

    def _cancel_runtime_task(self, name: str) -> bool:
        name=str(name); found=False
        for key,item in list(self.managed_tasks.items()):
            if key==name or str(item.get('public_name'))==name:
                self.managed_tasks.pop(key,None); found=True
        return found

    def _runtime_task_exists(self, name: str) -> bool:
        name=str(name); return any(key==name or str(v.get('public_name'))==name for key,v in self.managed_tasks.items())

    def _runtime_task_info(self, name: str) -> dict | None:
        name=str(name)
        for key,item in self.managed_tasks.items():
            if key==name or str(item.get('public_name'))==name:
                out=copy.deepcopy(item); out['key']=key; out['time_until']=max(0.0,float(item.get('due',self._task_clock))-self._task_clock) if not item.get('frame') else 0.0
                return out
        return None

    def _runtime_task_pause(self, name: str) -> bool:
        info=self._find_task_item(name)
        if not info: return False
        _,item=info; item['enabled']=False; item['_paused_remaining']=max(0.0,float(item.get('due',self._task_clock))-self._task_clock); return True

    def _runtime_task_resume(self, name: str) -> bool:
        info=self._find_task_item(name)
        if not info: return False
        _,item=info; item['enabled']=True; item['due']=self._task_clock+max(0.0,float(item.pop('_paused_remaining',0.0))); return True

    def _find_task_item(self, name: str):
        name=str(name)
        for key,item in self.managed_tasks.items():
            if key==name or str(item.get('public_name'))==name: return key,item
        return None

    def _managed_task_start(self, owner: str, name: str) -> bool:
        key=self._task_key(owner,name); item=self.managed_tasks.get(key)
        if item:
            item['enabled']=True; mode=str(item.get('mode','interval')); wait=float(item.get('delay',0.0) or 0.0); wait=wait if wait>0 or mode!='interval' else float(item.get('interval',0.0)); item['due']=self._task_clock+max(0.0,wait); item['remaining']=int(item.get('repeat',-1)); return True
        raw=(self.entity_data.get(owner,{}).get('components') or {}).get('tasks_events') or {}
        cfg=next((x for x in (raw.get('tasks') or []) if str(x.get('name'))==str(name)),None)
        if not cfg: return False
        self._install_authored_task(owner,cfg,force_enabled=True); return True

    def _managed_task_stop(self, owner: str, name: str) -> bool:
        item=self.managed_tasks.get(self._task_key(owner,name))
        if not item: return False
        item['enabled']=False; return True

    def _managed_task_trigger(self, owner: str, name: str, payload=None) -> bool:
        item=self.managed_tasks.get(self._task_key(owner,name))
        if not item:
            raw=(self.entity_data.get(owner,{}).get('components') or {}).get('tasks_events') or {}
            cfg=next((x for x in (raw.get('tasks') or []) if str(x.get('name'))==str(name)),None)
            if not cfg: return False
            item={'owner':owner,'event':str(cfg.get('event') or name),'signal':str(cfg.get('signal') or ''),'payload':copy.deepcopy(cfg.get('payload'))}
        self._fire_managed_task(item,payload); return True

    def _install_authored_task(self, owner: str, cfg: dict, force_enabled: bool = False) -> None:
        name=str(cfg.get('name') or '').strip()
        if not name: return
        mode=str(cfg.get('mode','interval')).lower(); delay=max(0.0,float(cfg.get('delay',0.0) or 0.0)); interval=max(.001,float(cfg.get('interval',1.0) or 1.0))
        repeat=int(cfg.get('repeat',-1) if mode!='once' else 1); repeat=(-1 if repeat<0 else max(1,repeat)); enabled=bool(force_enabled or (cfg.get('enabled',True) and cfg.get('autostart',True)))
        key=self._task_key(owner,name)
        self.managed_tasks[key]={'public_name':name,'owner':owner,'mode':mode,'due':self._task_clock+(delay if delay>0 else (interval if mode=='interval' else 0.0)),'delay':delay,'interval':interval,'repeat':repeat,'remaining':repeat,'event':str(cfg.get('event') or name),'signal':str(cfg.get('signal') or ''),'payload':copy.deepcopy(cfg.get('payload')),'finished_event':str(cfg.get('finished_event') or ''),'finished_signal':str(cfg.get('finished_signal') or ''),'enabled':enabled,'frame':mode=='frame'}

    def _initialize_tasks_events(self) -> None:
        self._clear_tasks_events(); self._task_clock=0.0
        event_names=set()
        for eid,raw in self.entity_data.items():
            comp=(raw.get('components') or {}).get('tasks_events') or {}
            if not comp or comp.get('enabled',True) is False: continue
            for cfg in (comp.get('tasks') or []): self._install_authored_task(eid,cfg)
            for hook in (comp.get('events') or []):
                name=str(hook.get('name') or '').strip()
                if name and hook.get('enabled',True): event_names.add(name)
        if self.base:
            for name in event_names:
                internal='panda_editor_event::'+name
                self.base.accept(internal, lambda payload=None, n=name: self._receive_custom_event(n,payload))
                self._custom_event_names.add(name)
        self.log(f'Tasks / Events: {len(self.managed_tasks)} managed task(s), {len(self._custom_event_names)} custom event channel(s).')

    def _clear_tasks_events(self) -> None:
        if self.base:
            for name in list(self._custom_event_names):
                try: self.base.ignore('panda_editor_event::'+name)
                except Exception: pass
        self._custom_event_names.clear(); self.managed_tasks.clear(); self._task_clock=0.0

    def _send_custom_event(self, event_name: str, payload=None, default_target: str | None = None) -> None:
        name=str(event_name or '').strip()
        if not name: return
        if self.base and name in self._custom_event_names:
            try: self.base.messenger.send('panda_editor_event::'+name,[copy.deepcopy(payload)]); return
            except Exception: pass
        self._receive_custom_event(name,payload,default_target)

    def _receive_custom_event(self, event_name: str, payload=None, default_target: str | None = None) -> None:
        matched=False
        for eid,raw in self.entity_data.items():
            comp=(raw.get('components') or {}).get('tasks_events') or {}
            for hook in (comp.get('events') or []):
                if hook.get('enabled',True) is False or str(hook.get('name') or '')!=str(event_name): continue
                matched=True; script_event=str(hook.get('script_event') or event_name).strip(); signal=str(hook.get('signal') or '').strip()
                if script_event: self._dispatch_script_event(script_event, {'event':event_name,'data':copy.deepcopy(payload)}, target=eid, sender=default_target)
                if signal: self._emit_entity_signal(eid,signal,{'event':event_name,'data':copy.deepcopy(payload)})
        if not matched and default_target:
            self._dispatch_script_event(str(event_name),copy.deepcopy(payload),target=default_target,sender=default_target)

    def _fire_managed_task(self, item: dict, override_payload=None) -> None:
        owner=item.get('owner'); payload=copy.deepcopy(item.get('payload') if override_payload is None else override_payload)
        event_name=str(item.get('event') or '').strip(); method_name=str(item.get('method') or '').strip(); signal=str(item.get('signal') or '').strip()
        task_payload={'task':item.get('public_name'),'data':payload}
        if method_name:
            if not owner or not self._dispatch_script_method(str(owner), method_name, task_payload):
                item['enabled']=False
        if event_name: self._send_custom_event(event_name,task_payload,owner)
        if signal and owner: self._emit_entity_signal(str(owner),signal,task_payload)

    def _dispatch_script_method(self, target: str, method_name: str, payload=None) -> bool:
        """Invoke a named method on one entity script for managed task callbacks."""
        resolved=self.runtime_world.get_entity(str(target)) if self.runtime_world else None
        eid=resolved.id if resolved else str(target); instance=self.script_instances.get(eid)
        if not instance:
            self.log(f'Task callback skipped [{method_name}]: target {target} has no active script.')
            return False
        callback=getattr(instance,str(method_name),None)
        if not callable(callback):
            raw=self.entity_data.get(eid,{})
            self.log(f'Task callback disabled [{raw.get("name",eid)}]: method {method_name}() was not found.')
            return False
        try:
            self._call_script_callback(eid, callback, RuntimeEntity(self,eid), self.runtime_world, copy.deepcopy(payload))
            return True
        except Exception:
            self.script_failed.add(eid)
            raw=self.entity_data.get(eid,{})
            self.log(f'Task callback disabled after error [{raw.get("name",eid)}.{method_name}]:\n{traceback.format_exc()}')
            return False

    def _update_managed_tasks(self, dt: float) -> None:
        for key,item in list(self.managed_tasks.items()):
            if not item.get('enabled',True): continue
            if item.get('frame'):
                self._fire_managed_task(item)
                remaining=int(item.get('remaining',-1))
                if remaining>0:
                    remaining-=1; item['remaining']=remaining
                    if remaining<=0:
                        finished_event=str(item.get('finished_event') or '').strip(); finished_signal=str(item.get('finished_signal') or '').strip(); owner=item.get('owner')
                        if finished_event: self._send_custom_event(finished_event, {'task':item.get('public_name')}, owner)
                        if finished_signal and owner: self._emit_entity_signal(str(owner),finished_signal,{'task':item.get('public_name')})
                        self.managed_tasks.pop(key,None)
                continue
            if self._task_clock + 1e-9 < float(item.get('due',0.0)): continue
            self._fire_managed_task(item)
            remaining=int(item.get('remaining',-1))
            if remaining>0:
                remaining-=1; item['remaining']=remaining
                if remaining<=0:
                    finished_event=str(item.get('finished_event') or '').strip(); finished_signal=str(item.get('finished_signal') or '').strip(); owner=item.get('owner')
                    if finished_event: self._send_custom_event(finished_event, {'task':item.get('public_name')}, owner)
                    if finished_signal and owner: self._emit_entity_signal(str(owner),finished_signal,{'task':item.get('public_name')})
                    self.managed_tasks.pop(key,None); continue
            interval=float(item.get('interval',0.0))
            if interval<=0.0: self.managed_tasks.pop(key,None)
            else:
                # Move from the old due time so a long frame does not permanently drift cadence.
                item['due']=max(self._task_clock+0.0001,float(item.get('due',self._task_clock))+interval)

    def _interval_key(self, owner: str | None, name: str) -> str:
        return f'{owner or "world"}:{name}'

    def _interval_step(self, owner: str | None, step: dict):
        typ=str(step.get('type','wait')).lower(); duration=max(0.0,float(step.get('duration',1.0) or 0.0))
        target=str(step.get('target') or owner or '')
        if target in {'self','owner'} and owner: target=str(owner)
        node=self.nodes.get(target) if target else None
        if typ=='wait': return Wait(duration)
        if typ=='event':
            event_name=str(step.get('event') or '').strip(); payload=copy.deepcopy(step.get('payload'))
            return Func(lambda e=event_name,p=payload,t=target: self._send_custom_event(e,p,t))
        if typ=='signal':
            signal=str(step.get('signal') or '').strip()
            return Func(lambda t=target,s=signal,p=copy.deepcopy(step.get('payload')): self._emit_entity_signal(t,s,p) if t and s else None)
        if typ in {'move','rotate','scale'} and node:
            to=list(step.get('to') or ([0,0,0] if typ!='scale' else [1,1,1]))+[0,0,0]
            blend=str(step.get('blend','easeInOut'))
            if typ=='move': return LerpPosInterval(node,duration,Vec3(float(to[0]),float(to[1]),float(to[2])),blendType=blend)
            if typ=='rotate': return LerpHprInterval(node,duration,Vec3(float(to[0]),float(to[1]),float(to[2])),blendType=blend)
            return LerpScaleInterval(node,duration,Vec3(float(to[0]),float(to[1]),float(to[2])),blendType=blend)
        if typ=='animation' and target in self.entity_actors and ActorInterval:
            actor=self.entity_actors[target]; clip=str(step.get('clip') or '').strip()
            if clip:
                kwargs={'loop':int(bool(step.get('loop',False))),'playRate':float(step.get('rate',1.0) or 1.0)}
                if duration>0: kwargs['duration']=duration
                return ActorInterval(actor,clip,**kwargs)
        if typ=='sound' and target in self.audio_sources and SoundInterval:
            snd=(self.audio_sources.get(target) or {}).get('sound')
            if snd:
                kwargs={'volume':float(step.get('volume',1.0) or 1.0),'loop':int(bool(step.get('loop',False)))}
                if duration>0: kwargs['duration']=duration
                return SoundInterval(snd,**kwargs)
        return Wait(duration)

    def _build_interval(self, owner: str | None, cfg: dict):
        parts=[self._interval_step(owner,x or {}) for x in (cfg.get('steps') or [])]
        composition=str(cfg.get('composition','sequence')).lower()
        iv=Parallel(*parts) if composition=='parallel' else Sequence(*parts)
        try: iv.setPlayRate(max(0.001,float(cfg.get('play_rate',1.0) or 1.0)))
        except Exception: pass
        return iv

    def _register_interval(self, owner: str | None, cfg: dict, runtime_created: bool=False) -> bool:
        name=str(cfg.get('name') or '').strip()
        if not name: return False
        key=self._interval_key(owner,name)
        try: group=self._build_interval(owner,cfg)
        except Exception as exc:
            self.log(f'Interval build failed [{name}]: {exc}'); return False
        ev=str(cfg.get('finished_event') or '').strip(); sig=str(cfg.get('finished_signal') or '').strip()
        if ev or sig:
            def finished(o=owner,n=name,e=ev,sg=sig):
                if e: self._send_custom_event(e,{'interval':n},o)
                if sg and o: self._emit_entity_signal(str(o),sg,{'interval':n})
            iv=Sequence(group,Func(finished))
        else:
            iv=group
        try: iv.setPlayRate(max(0.001,float(cfg.get('play_rate',1.0) or 1.0)))
        except Exception: pass
        self.play_intervals[key]={'owner':owner,'name':name,'config':copy.deepcopy(cfg),'interval':iv,'runtime':runtime_created}
        if cfg.get('autostart',False) and cfg.get('enabled',True) is not False:
            try:
                if bool(cfg.get('loop',False)): iv.loop()
                else: iv.start()
            except Exception as exc: self.log(f'Interval start failed [{name}]: {exc}')
        return True

    def _initialize_intervals(self) -> None:
        self._clear_intervals()
        for eid,raw in self.entity_data.items():
            comp=(raw.get('components') or {}).get('intervals') or {}
            if not comp or comp.get('enabled',True) is False: continue
            for cfg in (comp.get('clips') or []): self._register_interval(eid,cfg)
        self.log(f'Intervals: {len(self.play_intervals)} authored interval(s).')

    def _clear_intervals(self) -> None:
        # Stop registered intervals without calling finish(): finish() deliberately
        # executes remaining Func steps, including authored finished events/signals.
        # Play Stop/shutdown must tear runtime state down silently.
        for item in list(self.play_intervals.values()):
            try: item['interval'].pause()
            except Exception: pass
        self.play_intervals.clear(); self._paused_intervals.clear()

    def _set_intervals_paused(self, paused: bool) -> None:
        if paused:
            self._paused_intervals.clear()
            for key,item in self.play_intervals.items():
                try:
                    if item['interval'].isPlaying(): item['interval'].pause(); self._paused_intervals.add(key)
                except Exception: pass
        else:
            for key in list(self._paused_intervals):
                item=self.play_intervals.get(key)
                if item:
                    try: item['interval'].resume()
                    except Exception: pass
            self._paused_intervals.clear()

    def _interval_item(self, owner: str | None, name: str):
        return self.play_intervals.get(self._interval_key(owner,name))

    def _interval_start(self, owner: str, name: str, restart: bool=True) -> bool:
        item=self._interval_item(owner,name)
        if not item: return False
        try:
            if restart:
                if bool((item.get('config') or {}).get('loop',False)): item['interval'].loop()
                else: item['interval'].start()
            else: item['interval'].resume()
            return True
        except Exception: return False

    def _interval_pause(self, owner: str, name: str) -> bool:
        item=self._interval_item(owner,name)
        if not item: return False
        try: item['interval'].pause(); return True
        except Exception: return False

    def _interval_resume(self, owner: str, name: str) -> bool:
        item=self._interval_item(owner,name)
        if not item: return False
        try: item['interval'].resume(); return True
        except Exception: return False

    def _interval_finish(self, owner: str, name: str) -> bool:
        item=self._interval_item(owner,name)
        if not item: return False
        try: item['interval'].finish(); return True
        except Exception: return False

    def _interval_is_playing(self, owner: str, name: str) -> bool:
        item=self._interval_item(owner,name)
        if not item: return False
        try: return bool(item['interval'].isPlaying())
        except Exception: return False

    def _runtime_interval_create(self, name: str, steps: list[dict], owner: str | None, composition: str, loop: bool, play_rate: float) -> bool:
        cfg={'name':name,'composition':composition,'steps':copy.deepcopy(steps or []),'loop':loop,'play_rate':play_rate,'autostart':True,'enabled':True}
        key=self._interval_key(owner,name)
        old=self.play_intervals.pop(key,None)
        if old:
            try: old['interval'].pause()
            except Exception: pass
        return self._register_interval(owner,cfg,True)

    def _fsm_component(self, entity_id: str) -> dict:
        return (self.entity_data.get(str(entity_id), {}).get('components') or {}).get('fsm') or {}

    def _initialize_fsms(self) -> None:
        self.fsm_states.clear()
        for eid, raw in self.entity_data.items():
            comp = (raw.get('components') or {}).get('fsm') or {}
            if not comp or comp.get('enabled', True) is False:
                continue
            names = [str(x.get('name') or '').strip() for x in (comp.get('states') or [])]
            names = [x for x in names if x]
            if not names:
                continue
            initial = str(comp.get('initial_state') or '').strip()
            if initial not in names:
                initial = names[0]
            self.fsm_states[eid] = ''
            self._fsm_request(eid, initial, {'initial': True}, force=True)

    def _fsm_state_def(self, entity_id: str, state_name: str) -> dict | None:
        for state in self._fsm_component(entity_id).get('states') or []:
            if str(state.get('name') or '') == str(state_name):
                return state
        return None

    def _fsm_request(self, entity_id: str, state_name: str, payload=None, force: bool = False) -> bool:
        eid = str(entity_id); target = str(state_name or '').strip(); comp = self._fsm_component(eid)
        if not comp or comp.get('enabled', True) is False:
            return False
        target_def = self._fsm_state_def(eid, target)
        if not target_def:
            self.log(f'FSM [{self.entity_data.get(eid,{}).get("name",eid)}]: unknown state {target!r}')
            return False
        previous = str(self.fsm_states.get(eid, ''))
        if previous == target and not force:
            return True
        previous_def = self._fsm_state_def(eid, previous) if previous else None
        if previous_def:
            event_name = str(previous_def.get('exit_event') or '').strip()
            if event_name:
                self._dispatch_script_event(event_name, {'from':previous,'to':target,'data':payload}, target=eid, sender=eid)
        self.fsm_states[eid] = target
        clip = str(target_def.get('animation_clip') or '').strip()
        if clip and eid in self.entity_actors:
            self._animation_play(eid, clip, loop=bool(target_def.get('loop', True)), restart=True, rate=float(target_def.get('rate', 1.0) or 1.0))
        event_name = str(target_def.get('enter_event') or '').strip()
        if event_name:
            self._dispatch_script_event(event_name, {'from':previous,'to':target,'data':payload}, target=eid, sender=eid)
        change = {'from':previous,'to':target,'state':target,'data':payload}
        signal_name = str(comp.get('state_changed_signal') or 'state_changed').strip() or 'state_changed'
        self._emit_entity_signal(eid, signal_name, change)
        self.event('fsm_state_changed', entity_id=eid, previous=previous, state=target)
        return True

    def _fsm_send(self, entity_id: str, signal: str, payload=None) -> bool:
        eid = str(entity_id); signal = str(signal or '').strip(); current = str(self.fsm_states.get(eid, '')); comp = self._fsm_component(eid)
        if not comp or not current or not signal:
            return False
        for transition in comp.get('transitions') or []:
            source = str(transition.get('from') or '*').strip() or '*'
            if source not in {'*', current}:
                continue
            if str(transition.get('signal') or '').strip() != signal:
                continue
            return self._fsm_request(eid, str(transition.get('to') or ''), {'signal':signal,'data':payload})
        self._dispatch_script_event(signal, payload, target=eid, sender=eid)
        return False

    def _dispatch_script_event(self, event_name: str, payload=None, target: str | None = None, sender: str | None = None) -> None:
        if not self.play_mode:
            return
        if target:
            entity = self.runtime_world.get_entity(target)
            recipients = [entity.id] if entity and entity.id in self.script_instances else []
        else:
            recipients = list(self.script_instances)
        data = {'data': payload, 'sender': sender}
        for eid in recipients:
            if eid in self.script_failed:
                continue
            callback = getattr(self.script_instances[eid], 'on_event', None)
            if callable(callback):
                try:
                    self._call_script_callback(eid, callback, RuntimeEntity(self, eid), self.runtime_world, str(event_name), data)
                except Exception:
                    self.script_failed.add(eid)
                    self.log(f'Script event disabled after error [{eid}]:\n{traceback.format_exc()}')

    def _emit_entity_signal(self, sender_id: str, signal_name: str, payload=None) -> None:
        raw = self.entity_data.get(sender_id, {})
        components = raw.get('components') or {}
        data = {'entity_id': sender_id, 'entity_name': raw.get('name', sender_id), 'signal': str(signal_name), 'data': payload}
        connections = []
        ui = components.get('ui') or {}
        if str(ui.get('signal_name') or '') == str(signal_name):
            connections.extend(list(ui.get('connections') or []))
        sig = components.get('signals') or {}
        if str(sig.get('signal_name') or '') == str(signal_name):
            connections.extend(list(sig.get('connections') or []))
        for out in list(sig.get('outputs') or []):
            if str(out.get('name') or '') == str(signal_name):
                connections.extend(list(out.get('connections') or []))
        if connections:
            for c in connections:
                self._execute_signal_connection(sender_id, str(signal_name), data, c)
        else:
            # Script signals still have a useful local fallback without becoming a project-wide broadcast.
            self._dispatch_script_event(str(signal_name), data, target=sender_id, sender=sender_id)

    def _request_scene_action(self, action: str, value=None) -> None:
        if not self.play_mode:
            return
        self._pending_scene_action = (str(action), value)

    def _perform_pending_scene_action(self) -> None:
        pending = self._pending_scene_action
        self._pending_scene_action = None
        if not pending:
            return
        action, value = pending
        if action == 'quit':
            if self._standalone_game and self.base:
                try: self.base.userExit()
                except Exception: self.running = False
            else:
                self._stop_play()
                self.event('play_state_changed', state='stopped')
            return
        rel = self.current_runtime_scene if action == 'restart' else str(value or '').replace('\\','/').lstrip('/')
        if not rel:
            self.log('Scene Flow: no scene path is available for transition.')
            return
        path = (PROJECT_ROOT / rel).resolve()
        try:
            if PROJECT_ROOT.resolve() not in path.parents or path.suffix.lower() != '.pscene' or not path.is_file():
                raise FileNotFoundError(rel)
            from scene.serialization import load_scene
            scene = load_scene(path)
            entities = [copy.deepcopy(e.to_dict()) for e in scene.entities.values()]
            settings = copy.deepcopy(self.project_settings)
            settings['_current_scene'] = rel
            self.log(f'Scene Flow: loading {rel}')
            self._stop_play()
            self._start_play(entities, settings)
            self.current_runtime_scene = rel
            self.event('runtime_scene_changed', scene=rel)
        except Exception as exc:
            self.log(f'Scene Flow: could not load {rel}: {exc}')

    def _execute_signal_connection(self, sender_id: str, signal_name: str, payload: dict, connection: dict) -> None:
        """Execute one serialized signal connection from a component/UI source."""
        action = str(connection.get('action') or 'event').lower()
        target = str(connection.get('target') or '').strip() or None
        value = connection.get('value')
        if action == 'event':
            event_name = str(connection.get('event') or signal_name or 'signal')
            data = dict(payload); data['connection'] = copy.deepcopy(connection)
            self._dispatch_script_event(event_name, data, target=target, sender=sender_id)
            return
        if action == 'scene_load':
            self._request_scene_action('load', value); return
        if action == 'scene_restart':
            self._request_scene_action('restart', None); return
        if action == 'game_quit':
            self._request_scene_action('quit', None); return
        entity = self.runtime_world.get_entity(target) if target else None
        if not entity:
            self.log(f'Signal {signal_name}: target not found: {target!r}')
            return
        if action == 'set_visible':
            visible = bool(value) if isinstance(value, bool) else str(value).strip().lower() not in {'0','false','off','no',''}
            entity.set_visible(visible)
            if entity.has_ui: entity.ui_show() if visible else entity.ui_hide()
        elif action == 'toggle_visible':
            if entity.has_ui:
                widget = self.ui_nodes.get(entity.id)
                try:
                    hidden = bool(widget.isHidden())
                except Exception:
                    hidden = False
                entity.ui_show() if hidden else entity.ui_hide()
            else:
                n = entity.node
                if n: entity.set_visible(n.isHidden())
        elif action == 'ui_text':
            entity.ui_text = '' if value is None else str(value)
        elif action == 'particles_start':
            entity.particles_start()
        elif action == 'particles_stop':
            entity.particles_stop(clear=bool(connection.get('clear', False)))
        elif action == 'particles_burst':
            try: count = int(value) if value not in (None, '') else None
            except Exception: count = None
            entity.particles_burst(count)
        elif action == 'light_toggle':
            self._set_runtime_light_enabled(entity.id, not self.runtime_light_enabled.get(entity.id, True))
        elif action == 'light_set_enabled':
            enabled = bool(value) if isinstance(value, bool) else str(value).strip().lower() not in {'0','false','off','no',''}
            self._set_runtime_light_enabled(entity.id, enabled)
        elif action == 'light_set_intensity':
            try: intensity = max(0.0, float(value))
            except Exception: intensity = 1.0
            self._set_runtime_light_intensity(entity.id, intensity)
        elif action == 'audio_play':
            entity.audio_play()
        elif action == 'audio_stop':
            entity.audio_stop()
        elif action == 'animation_play':
            entity.animation_play(str(value or '') or None, loop=False)
        elif action == 'animation_loop':
            entity.animation_play(str(value or '') or None, loop=True)
        elif action == 'animation_stop':
            entity.animation_stop(str(value or '') or None)
        elif action == 'task_start':
            entity.task_start(str(value or ''))
        elif action == 'task_stop':
            entity.task_stop(str(value or ''))
        elif action == 'task_trigger':
            entity.task_trigger(str(value or ''), payload)
        elif action == 'interval_start':
            entity.interval_start(str(value or ''), True)
        elif action == 'interval_pause':
            entity.interval_pause(str(value or ''))
        elif action == 'interval_resume':
            entity.interval_resume(str(value or ''))
        elif action == 'interval_finish':
            entity.interval_finish(str(value or ''))
        elif action == 'camera_activate':
            try: blend=float(value or 0.0)
            except Exception: blend=0.0
            entity.camera_activate(blend)
        elif action == 'camera_shake':
            try: strength=float(value or .25)
            except Exception: strength=.25
            entity.camera_shake(strength=strength)
        elif action == 'camera_stop_shake':
            entity.camera_stop_shake()
        elif action == 'navigation_target':
            entity.navigation_set_target(str(value or ''))
        elif action == 'navigation_stop':
            entity.navigation_stop()
        elif action == 'navigation_repath':
            entity.navigation_repath()
        elif action == 'ai_set_state':
            entity.ai_set_state(str(value or 'idle'),'signal')
        elif action == 'ai_set_target':
            entity.ai_set_target(str(value or ''))
        elif action == 'ai_clear_target':
            entity.ai_clear_target('signal')
        elif action == 'ai_think':
            entity.ai_think_now()
        elif action == 'ui_value':
            try: entity.ui_value = float(value)
            except Exception: pass
        elif action == 'scene_load':
            self._request_scene_action('load', value)
        elif action == 'scene_restart':
            self._request_scene_action('restart', None)
        elif action == 'game_quit':
            self._request_scene_action('quit', None)
        else:
            self.log(f'Signal {signal_name}: unsupported action {action!r}')

    def _canonical_mouse_button(self, button: str) -> str:
        key = str(button).strip().lower()
        return {
            'left':'mouse1', 'mouse1':'mouse1',
            'middle':'mouse2', 'mouse2':'mouse2',
            'right':'mouse3', 'mouse3':'mouse3',
        }.get(key, key)

    def _mouse_button_down(self, button: str) -> bool:
        if not self.base:
            return False
        key = self._canonical_mouse_button(button)
        buttons = {
            'mouse1': MouseButton.one(),
            'mouse2': MouseButton.two(),
            'mouse3': MouseButton.three(),
        }
        try:
            b = buttons.get(key)
            return bool(b and self.base.mouseWatcherNode.isButtonDown(b))
        except Exception:
            return False

    def _set_mouse_capture(self, captured: bool) -> None:
        self._mouse_captured = bool(captured and self.play_mode)
        self._play_mouse_last = None
        self._mouse_delta = (0.0, 0.0)
        # Window pointer warps are asynchronous on some Windows drivers.  Without
        # a short suppression window, the warp itself can be reported as mouse
        # movement and produce the familiar slow up/left free-look drift.
        self._mouse_capture_suppress_frames = 2 if self._mouse_captured else 0
        if not (self.base and self.base.win):
            return
        try:
            props = WindowProperties()
            props.setCursorHidden(self._mouse_captured)
            self.base.win.requestProperties(props)
            if self._mouse_captured:
                cx=max(1,int(self.base.win.getXSize() or self.rect[2])//2)
                cy=max(1,int(self.base.win.getYSize() or self.rect[3])//2)
                self.base.win.movePointer(0,cx,cy)
        except Exception as exc:
            self.log(f'Mouse capture request failed: {exc}')

    def _update_play_mouse(self) -> None:
        if not (self.base and self.base.win):
            self._mouse_delta = (0.0, 0.0)
            return

        # Captured look uses the real window pointer relative to the viewport
        # centre.  This is more reliable on Windows/pywebview than repeatedly
        # reading MouseWatcher normalized coordinates immediately after a warp.
        if self._mouse_captured:
            try:
                width=max(2,int(self.base.win.getXSize() or self.rect[2]))
                height=max(2,int(self.base.win.getYSize() or self.rect[3]))
                cx,cy=width//2,height//2
                pointer=self.base.win.getPointer(0)
                px,py=int(pointer.getX()),int(pointer.getY())
                dx_px=px-cx
                dy_px=cy-py  # screen Y grows downward; runtime mouse Y grows upward
                if self._mouse_capture_suppress_frames > 0:
                    self._mouse_capture_suppress_frames -= 1
                    dx_px=dy_px=0
                # Sub-pixel/one-pixel jitter around the centre should never rotate
                # a development camera when the physical mouse is stationary.
                if abs(dx_px) <= 1: dx_px=0
                if abs(dy_px) <= 1: dy_px=0
                self._mouse_delta=(float(dx_px)/(width*0.5), float(dy_px)/(height*0.5))
                self._mouse_position=(0.0,0.0)
                self.base.win.movePointer(0,cx,cy)
                self._play_mouse_last=(0.0,0.0)
                return
            except Exception:
                # Fall through to MouseWatcher if a backend does not expose a
                # usable pointer object.
                pass

        if not self.base.mouseWatcherNode.hasMouse():
            self._mouse_delta = (0.0, 0.0)
            return
        m = self.base.mouseWatcherNode.getMouse()
        current = (float(m.x), float(m.y))
        self._mouse_position = current
        if self._mouse_captured:
            # Fallback captured path: still suppress warp frames and dead-zone
            # tiny normalized jitter before re-centering.
            dx,dy=current
            if self._mouse_capture_suppress_frames > 0:
                self._mouse_capture_suppress_frames -= 1
                dx=dy=0.0
            if abs(dx) < 0.002: dx=0.0
            if abs(dy) < 0.002: dy=0.0
            self._mouse_delta=(dx,dy)
            try:
                self.base.win.movePointer(0,max(1,self.rect[2]//2),max(1,self.rect[3]//2))
            except Exception:
                pass
            self._play_mouse_last=(0.0,0.0)
        else:
            if self._play_mouse_last is None:
                self._mouse_delta=(0.0,0.0)
            else:
                self._mouse_delta=(current[0]-self._play_mouse_last[0], current[1]-self._play_mouse_last[1])
            self._play_mouse_last=current

    def _emit_debug_snapshot_periodic(self) -> None:
        now=time.time()
        if now-self._debug_last_emit < 0.5:
            return
        self._debug_last_emit=now
        try:
            clock=ClockObject.getGlobalClock()
            fps=float(clock.getAverageFrameRate() or 0.0)
        except Exception:
            fps=0.0
        self.event('debug_snapshot', fps=round(fps,1), nodes=len(self.nodes), physics_bodies=len(self.physics_nodes), triggers=len(self.physics_ghost_nodes), characters=len(self.physics_characters), audio_sources=len(self.audio_sources), ui_elements=len(self.ui_nodes), particle_emitters=len(self.particle_emitters), terrains=len(self.terrains), actors=len(self.entity_actors), fsms=len(self.fsm_states), navigation_agents=len(self.nav_agents), ai_behaviors=len(self.ai_behaviors), managed_tasks=len(self.managed_tasks), custom_events=len(self._custom_event_names), scripts=len(self.script_instances), viewport_context=self.editor_view_context, preview_vfx=bool(self.vfx_preview_mode), preview_material=bool(self.material_preview_mode), editor_grid=bool(self.editor_grid_visible), editor_axes=bool(self.editor_axes_visible), editor_scene_helpers=bool(self.editor_scene_helpers_visible), collision_helpers=bool(self.collider_helpers_visible), play_state='paused' if self.play_paused else ('playing' if self.play_mode else 'stopped'))

    def _set_bullet_debug(self, enabled: bool) -> None:
        self.bullet_debug_enabled=bool(enabled)
        if self.physics_world is None or BulletDebugNode is None or not self.base:
            if not enabled and self.bullet_debug_np:
                try: self.bullet_debug_np.removeNode()
                except Exception: pass
                self.bullet_debug_np=None
            return
        if enabled:
            if not self.bullet_debug_np or self.bullet_debug_np.isEmpty():
                node=BulletDebugNode('BulletDebug')
                node.showWireframe(True); node.showConstraints(True); node.showBoundingBoxes(True); node.showNormals(False)
                self.bullet_debug_np=self.base.render.attachNewNode(node)
                self._isolate_editor_helper(self.bullet_debug_np)
                self.physics_world.setDebugNode(node)
            self.bullet_debug_np.show()
        elif self.bullet_debug_np:
            self.bullet_debug_np.hide()


    @staticmethod
    def _panda_filename(path: Path | str) -> Filename:
        """Return Panda3D's platform-normalized Filename for an OS path."""
        return Filename.fromOsSpecific(str(Path(path).resolve()))

    def _stop_audio_preview(self) -> None:
        sound = self.audio_preview_sound
        self.audio_preview_sound = None
        old = self.audio_preview_path
        self.audio_preview_path = None
        if sound is not None:
            try:
                sound.stop()
            except Exception:
                pass
        if old:
            self.event('audio_preview_changed', path=None, playing=False)

    def _preview_audio(self, relative_path: str | None) -> None:
        self._stop_audio_preview()
        if not self.base or not relative_path:
            return
        rel = str(relative_path).replace('\\', '/').lstrip('/')
        path = (PROJECT_ROOT / rel).resolve()
        try:
            if PROJECT_ROOT.resolve() not in path.parents or not path.is_file():
                self.log(f'Audio preview rejected unsafe/missing path: {relative_path}')
                return
            if path.suffix.lower() not in {'.wav','.ogg','.mp3','.flac'}:
                self.log(f'Audio preview unsupported type: {path.suffix}')
                return
            panda_path = self._panda_filename(path)
            sound = self.base.loader.loadSfx(panda_path.getFullpath())
            if not sound:
                raise RuntimeError('Panda3D returned no AudioSound.')
            sound.setVolume(1.0)
            sound.setLoop(False)
            sound.play()
            self.audio_preview_sound = sound
            self.audio_preview_path = rel
            self.log(f'Audio preview: {rel} | panda={panda_path.getFullpath()} | status={sound.status()}')
            self.event('audio_preview_changed', path=rel, playing=True)
        except Exception as exc:
            self.log(f'Audio preview failed: {rel}: {exc}')
            self.event('audio_preview_changed', path=rel, playing=False)

    def _emit_animation_info(self, entity_id: str | None) -> None:
        eid = str(entity_id or '')
        actor = self.entity_actors.get(eid)
        clips = []
        if actor is not None:
            try: clips = sorted({str(x) for x in actor.getAnimNames()})
            except Exception: clips = []
        self.animation_clips[eid] = clips
        self.event('animation_clips', entity_id=eid, clips=clips)

    def _animation_play(self, entity_id: str, name: str | None = None, loop: bool = False, restart: bool = True, rate: float | None = None) -> bool:
        actor = self.entity_actors.get(str(entity_id))
        if actor is None:
            return False
        try:
            clips = list(actor.getAnimNames())
            clip = str(name or '').strip()
            if not clip:
                raw = self.entity_data.get(str(entity_id), {})
                comp = (raw.get('components') or {}).get('animation') or {}
                clip = str(comp.get('default_clip') or '').strip()
            if not clip and clips:
                clip = str(clips[0])
            if not clip or clip not in clips:
                return False
            if rate is None:
                raw = self.entity_data.get(str(entity_id), {})
                comp = (raw.get('components') or {}).get('animation') or {}
                rate = float(comp.get('play_rate', 1.0) or 1.0)
            actor.setPlayRate(float(rate), clip)
            if loop:
                actor.loop(clip, restart=bool(restart))
            else:
                if restart:
                    actor.play(clip)
                else:
                    actor.loop(clip, restart=False)
                    actor.stop(clip)
                    actor.play(clip)
            return True
        except Exception as exc:
            self.log(f'Animation playback failed [{entity_id}]: {exc}')
            return False

    def _preview_animation(self, entity_id: str | None, clip: str | None, mode: str = 'play', rate=None) -> None:
        if self.play_mode:
            return
        eid = str(entity_id or '')
        actor = self.entity_actors.get(eid)
        if actor is None:
            self.event('animation_preview_changed', entity_id=eid, clip=None, playing=False)
            return
        mode = str(mode or 'play').lower()
        try:
            if mode == 'stop':
                actor.stop()
                self.animation_preview_entity = None
                self.event('animation_preview_changed', entity_id=eid, clip=None, playing=False)
                return
            ok = self._animation_play(eid, clip, loop=(mode == 'loop'), restart=True, rate=rate)
            self.animation_preview_entity = eid if ok else None
            self.event('animation_preview_changed', entity_id=eid, clip=str(clip or ''), playing=bool(ok), loop=(mode == 'loop'))
        except Exception as exc:
            self.log(f'Animation preview failed [{eid}]: {exc}')

    def _build_play_audio(self) -> None:
        self._stop_audio_preview()
        self._destroy_play_audio()
        self._stop_all_particles(clear=True)
        if not self.base:
            return
        try:
            if self.base.sfxManagerList:
                self.audio3d = Audio3DManager.Audio3DManager(self.base.sfxManagerList[0], self.base.camera, root=self.base.render)
                try: self.audio3d.setDistanceFactor(1.0)
                except Exception: pass
        except Exception as exc:
            self.audio3d = None
            self.log(f'Audio3D initialization unavailable: {exc}')
        master = max(0.0, min(1.0, float(self.project_settings.get('audio_master_volume', 1.0))))
        sfx_volume = max(0.0, min(1.0, float(self.project_settings.get('audio_sfx_volume', 1.0))))
        music_volume = max(0.0, min(1.0, float(self.project_settings.get('audio_music_volume', 0.85))))
        for eid, raw in self.entity_data.items():
            comp = (raw.get('components') or {}).get('audio_source') or {}
            rel = str(comp.get('clip') or '').strip()
            if not rel:
                continue
            path = (PROJECT_ROOT / rel).resolve() if not Path(rel).is_absolute() else Path(rel)
            if not path.exists():
                self.log(f'Audio missing [{raw.get("name", eid)}]: {rel}')
                continue
            try:
                bus = str(comp.get('bus','sfx')).lower()
                spatial = bool(comp.get('spatial',True))
                panda_path = self._panda_filename(path)
                # Panda3D's Filename uses forward-slash/internal syntax even on Windows.
                # Passing a raw D:\... string causes FFmpeg/OpenAL loaders to reject the path.
                if spatial and self.audio3d is not None:
                    sound = self.audio3d.loadSfx(panda_path.getFullpath())
                elif bus == 'music':
                    sound = self.base.loader.loadMusic(panda_path.getFullpath())
                else:
                    sound = self.base.loader.loadSfx(panda_path.getFullpath())
                if not sound:
                    raise RuntimeError('Panda3D returned no AudioSound.')
                bus_vol = music_volume if bus == 'music' else sfx_volume
                volume = max(0.0, min(1.0, float(comp.get('volume',1.0))))
                sound.setVolume(master * bus_vol * volume)
                sound.setLoop(bool(comp.get('loop',False)))
                root = self.nodes.get(eid)
                if spatial and root is not None and self.audio3d is not None:
                    self.audio3d.attachSoundToObject(sound, root)
                    try: self.audio3d.setSoundMinDistance(sound, max(0.01,float(comp.get('min_distance',1.0))))
                    except Exception: pass
                    try: self.audio3d.setSoundMaxDistance(sound, max(0.02,float(comp.get('max_distance',40.0))))
                    except Exception: pass
                self.audio_sources[eid] = {'sound': sound, 'component': copy.deepcopy(comp), 'base_volume': volume, 'bus_volume': bus_vol, 'master': master}
                self.log(f'Audio loaded [{raw.get("name", eid)}]: {path.name} | {"3D" if spatial else "2D"} | bus={bus} | volume={master*bus_vol*volume:.2f}')
                if comp.get('autoplay',False):
                    sound.play()
                    self.log(f'Audio autoplay [{raw.get("name", eid)}]: status={sound.status()}')
            except Exception as exc:
                self.log(f'Audio load failed [{raw.get("name", eid)}]: {rel}: {exc}')
        if self.audio_sources:
            self.log(f'Audio: loaded {len(self.audio_sources)} source(s).')

    def _destroy_play_audio(self) -> None:
        for item in list(self.audio_sources.values()):
            sound = item.get('sound')
            if sound:
                try: sound.stop()
                except Exception: pass
                try:
                    if self.audio3d is not None: self.audio3d.detachSound(sound)
                except Exception: pass
        self.audio_sources.clear()
        if self.audio3d is not None:
            try: self.audio3d.disable()
            except Exception: pass
        self.audio3d = None

    def _audio_play(self, entity_id: str, restart: bool = True) -> None:
        item = self.audio_sources.get(entity_id)
        if not item: return
        sound = item.get('sound')
        if not sound: return
        try:
            if restart: sound.stop()
            sound.play()
        except Exception: pass

    def _audio_stop(self, entity_id: str) -> None:
        item = self.audio_sources.get(entity_id)
        if item and item.get('sound'):
            try: item['sound'].stop()
            except Exception: pass

    def _audio_get_volume(self, entity_id: str) -> float:
        item = self.audio_sources.get(entity_id)
        return float(item.get('base_volume',0.0)) if item else 0.0

    def _audio_set_volume(self, entity_id: str, value: float) -> None:
        item = self.audio_sources.get(entity_id)
        if not item: return
        value = max(0.0,min(1.0,float(value)))
        item['base_volume'] = value
        sound = item.get('sound')
        if sound:
            try: sound.setVolume(float(item.get('master',1.0))*float(item.get('bus_volume',1.0))*value)
            except Exception: pass

    def _key_down(self, key: str) -> bool:
        if not self.base:
            return False
        k = key.strip().lower()
        watcher = self.base.mouseWatcherNode
        special = {
            'space': KeyboardButton.space(), 'enter': KeyboardButton.enter(),
            'escape': KeyboardButton.escape(), 'up': KeyboardButton.up(),
            'down': KeyboardButton.down(), 'left': KeyboardButton.left(), 'right': KeyboardButton.right(),
            'shift': KeyboardButton.shift(),
        }
        try:
            button = special.get(k) or (KeyboardButton.asciiKey(k[0]) if len(k) == 1 else None)
            return bool(button and watcher.isButtonDown(button))
        except Exception:
            return False

    def _action_down(self, action: str) -> bool:
        actions = self.project_settings.get('input_actions') or {}
        keys = actions.get(str(action), [])
        if isinstance(keys, str): keys = [keys]
        return any(self._key_down(str(k)) for k in keys)

    def _update_action_states(self) -> None:
        actions = self.project_settings.get('input_actions') or {}
        current = {str(name) for name in actions if self._action_down(str(name))}
        self._actions_pressed = current - self._actions_previous
        self._actions_released = self._actions_previous - current
        self._actions_current = current
        self._actions_previous = set(current)

    def _update_raw_input_states(self) -> None:
        """Track direct keyboard/mouse edge transitions for beginner/debug scripts.

        Input Map actions remain the preferred gameplay abstraction.  This direct
        state is intentionally broad enough for editor examples, free cameras and
        one-off development controls without requiring an Input Map entry first.
        """
        keys = set('abcdefghijklmnopqrstuvwxyz0123456789')
        keys.update({'space','enter','escape','up','down','left','right','shift'})
        for mapped in (self.project_settings.get('input_actions') or {}).values():
            if isinstance(mapped, str):
                mapped = [mapped]
            for key in mapped or []:
                keys.add(str(key).strip().lower())
        current = {key for key in keys if self._key_down(key)}
        self._keys_pressed = current - self._keys_previous
        self._keys_released = self._keys_previous - current
        self._keys_current = current
        self._keys_previous = set(current)

        mouse_current = {name for name in ('mouse1','mouse2','mouse3') if self._mouse_button_down(name)}
        self._mouse_buttons_pressed = mouse_current - self._mouse_buttons_previous
        self._mouse_buttons_released = self._mouse_buttons_previous - mouse_current
        self._mouse_buttons_current = mouse_current
        self._mouse_buttons_previous = set(mouse_current)

    def _camera_component(self, entity_id: str) -> dict:
        raw=self.entity_data.get(entity_id,{})
        comp=copy.deepcopy((raw.get('components') or {}).get('camera') or {})
        comp.update(copy.deepcopy(self.runtime_camera_overrides.get(entity_id,{}) or {}))
        return comp

    def _camera_set(self, entity_id: str, name: str, value) -> bool:
        if entity_id not in self.nodes or not (self.entity_data.get(entity_id,{}).get('components') or {}).get('camera'):
            return False
        key=str(name)
        allowed={'projection','fov','ortho_size','near','far','rig','target','offset','damping','look_at','up','distance','orbit_heading','orbit_pitch','orbit_min_pitch','orbit_max_pitch','min_distance','max_distance','active'}
        if key not in allowed: return False
        if key in {'offset','up'}:
            try: value=[float(x) for x in list(value)[:3]]
            except Exception: return False
        elif key in {'fov','ortho_size','near','far','damping','distance','orbit_heading','orbit_pitch','orbit_min_pitch','orbit_max_pitch','min_distance','max_distance'}:
            try: value=float(value)
            except Exception: return False
        elif key in {'look_at','active'}: value=bool(value)
        else: value=str(value)
        self.runtime_camera_overrides.setdefault(entity_id,{})[key]=value
        return True

    def _resolve_camera_target(self, target):
        if isinstance(target,RuntimeEntity): return self.nodes.get(target.id)
        if not target: return None
        key=str(target)
        if key in self.nodes: return self.nodes.get(key)
        low=key.lower()
        for eid,raw in self.entity_data.items():
            if str(raw.get('name','')).lower()==low: return self.nodes.get(eid)
        return None

    def _ease_camera_t(self, t: float, ease: str) -> float:
        t=max(0.0,min(1.0,float(t))); e=str(ease or '').lower()
        if e in {'linear','none'}: return t
        if e in {'easein','in'}: return t*t
        if e in {'easeout','out'}: return 1.0-(1.0-t)*(1.0-t)
        return t*t*(3.0-2.0*t)

    def _camera_activate(self, entity_id: str, blend: float=0.0, ease: str='easeInOut') -> bool:
        if entity_id not in self.nodes or not (self.entity_data.get(entity_id,{}).get('components') or {}).get('camera'): return False
        if not self.base: return False
        duration=max(0.0,float(blend))
        if duration>0.0 and self.play_mode:
            self.camera_transition={'target':entity_id,'elapsed':0.0,'duration':duration,'ease':str(ease),'start_pos':self.base.camera.getPos(self.base.render),'start_hpr':self.base.camera.getHpr(self.base.render)}
        else:
            self.camera_transition=None; self.play_camera_id=entity_id
        return True

    def _camera_orbit_input(self, entity_id: str, heading_delta: float, pitch_delta: float, zoom_delta: float) -> bool:
        if entity_id not in self.nodes: return False
        st=self.camera_rig_state.setdefault(entity_id,{})
        comp=self._camera_component(entity_id)
        st['heading']=float(st.get('heading',comp.get('orbit_heading',0.0)))+float(heading_delta)
        lo=float(comp.get('orbit_min_pitch',-80.0)); hi=float(comp.get('orbit_max_pitch',80.0))
        st['pitch']=max(lo,min(hi,float(st.get('pitch',comp.get('orbit_pitch',20.0)))+float(pitch_delta)))
        mn=max(.05,float(comp.get('min_distance',1.0))); mx=max(mn,float(comp.get('max_distance',100.0)))
        st['distance']=max(mn,min(mx,float(st.get('distance',comp.get('distance',8.0)))+float(zoom_delta)))
        return True

    def _camera_shake(self, entity_id: str, strength: float, duration: float, frequency: float, rotation: float) -> bool:
        if entity_id not in self.nodes: return False
        self.camera_shakes[entity_id]={'elapsed':0.0,'duration':max(.001,duration),'strength':max(0.0,strength),'frequency':max(.1,frequency),'rotation':max(0.0,rotation),'seed':random.random()*1000.0}
        return True

    def _camera_stop_shake(self, entity_id: str) -> bool:
        return self.camera_shakes.pop(entity_id,None) is not None

    def _camera_desired_transform(self, entity_id: str, dt: float=0.0):
        root=self.nodes.get(entity_id); comp=self._camera_component(entity_id)
        if not root or not comp or not self.base: return None
        rig=str(comp.get('rig','fixed')).lower()
        pos=root.getPos(self.base.render); hpr=root.getHpr(self.base.render)
        target=self._resolve_camera_target(comp.get('target'))
        state=self.camera_rig_state.setdefault(entity_id,{})
        if rig=='follow' and target:
            off=comp.get('offset',[0.0,-6.0,2.5]); off=Vec3(float(off[0]),float(off[1]),float(off[2]))
            desired=target.getMat(self.base.render).xformPoint(off)
            damping=max(0.0,float(comp.get('damping',8.0))); a=1.0 if damping<=0 or dt<=0 else 1.0-math.exp(-damping*dt)
            prev=state.get('pos',pos); pos=Vec3(prev)+(Vec3(desired)-Vec3(prev))*a; state['pos']=Vec3(pos)
            if bool(comp.get('look_at',True)):
                temp=NodePath('camera-look'); temp.setPos(self.base.render,pos); temp.lookAt(target.getPos(self.base.render)); hpr=temp.getHpr(self.base.render); temp.removeNode()
        elif rig=='orbit' and target:
            h=float(state.get('heading',comp.get('orbit_heading',0.0))); p=float(state.get('pitch',comp.get('orbit_pitch',20.0))); d=max(.05,float(state.get('distance',comp.get('distance',8.0))))
            state.update({'heading':h,'pitch':p,'distance':d})
            hr=math.radians(h); pr=math.radians(p); cp=math.cos(pr)
            offset=Vec3(math.sin(hr)*cp*d,-math.cos(hr)*cp*d,math.sin(pr)*d)
            desired=target.getPos(self.base.render)+offset
            damping=max(0.0,float(comp.get('damping',10.0))); a=1.0 if damping<=0 or dt<=0 else 1.0-math.exp(-damping*dt)
            prev=state.get('pos',desired); pos=Vec3(prev)+(Vec3(desired)-Vec3(prev))*a; state['pos']=Vec3(pos)
            temp=NodePath('camera-orbit-look'); temp.setPos(self.base.render,pos); temp.lookAt(target.getPos(self.base.render)); hpr=temp.getHpr(self.base.render); temp.removeNode()
        elif rig=='look_at' and target:
            temp=NodePath('camera-look'); temp.setPos(self.base.render,pos); temp.lookAt(target.getPos(self.base.render)); hpr=temp.getHpr(self.base.render); temp.removeNode()
        return Vec3(pos),Vec3(hpr),comp

    def _apply_camera_lens(self, component: dict) -> None:
        aspect=max(0.1,self.rect[2]/max(1,self.rect[3])); near=max(.001,float(component.get('near',.1))); far=max(near+.01,float(component.get('far',2000.0)))
        if str(component.get('projection','perspective')).lower()=='orthographic':
            lens=OrthographicLens(); size=max(.1,float(component.get('ortho_size',10.0))); lens.setFilmSize(size*aspect,size); lens.setNearFar(near,far)
        else:
            lens=PerspectiveLens(); lens.setFov(max(1.0,min(179.0,float(component.get('fov',60.0))))); lens.setAspectRatio(aspect); lens.setNearFar(near,far)
        self.base.cam.node().setLens(lens)

    def _apply_game_camera(self, dt: float=0.0) -> None:
        if not self.base: return
        if self.camera_transition:
            tr=self.camera_transition; target_id=str(tr.get('target','')); desired=self._camera_desired_transform(target_id,dt)
            if not desired: self.camera_transition=None; return
            tr['elapsed']=float(tr.get('elapsed',0.0))+max(0.0,dt); t=self._ease_camera_t(tr['elapsed']/max(.001,float(tr.get('duration',.001))),str(tr.get('ease','easeInOut')))
            tp,th,comp=desired; sp=Vec3(tr['start_pos']); sh=Vec3(tr['start_hpr']); pos=sp+(tp-sp)*t; hpr=sh+(th-sh)*t
            self.base.camera.setPos(self.base.render,pos); self.base.camera.setHpr(self.base.render,hpr); self._apply_camera_lens(comp)
            if tr['elapsed']>=tr['duration']: self.play_camera_id=target_id; self.camera_transition=None
            return
        if not self.play_camera_id: return
        desired=self._camera_desired_transform(self.play_camera_id,dt)
        if not desired: self.play_camera_id=None; return
        pos,hpr,component=desired
        shake=self.camera_shakes.get(self.play_camera_id)
        if shake:
            shake['elapsed']+=max(0.0,dt); life=max(0.0,1.0-shake['elapsed']/max(.001,shake['duration'])); phase=(shake['elapsed']*shake['frequency']+shake['seed'])*math.tau
            s=shake['strength']*life; r=shake['rotation']*life
            pos+=Vec3(math.sin(phase)*s,math.sin(phase*1.37+1.1)*s,math.sin(phase*1.71+2.2)*s*.6)
            hpr+=Vec3(math.sin(phase*1.19)*r,math.sin(phase*1.53+1.4)*r*.6,math.sin(phase*1.83+2.0)*r*.35)
            if shake['elapsed']>=shake['duration']: self.camera_shakes.pop(self.play_camera_id,None)
        self.base.camera.setPos(self.base.render,pos); self.base.camera.setHpr(self.base.render,hpr); self._apply_camera_lens(component)

    def _sync_entities(self, entities: list[dict]) -> None:
        if not self.base:
            return
        incoming = {e['id']: e for e in entities}
        self.entity_data = incoming
        for entity_id in list(self.nodes):
            if entity_id not in incoming:
                light_np = self.entity_lights.pop(entity_id, None)
                self.runtime_light_enabled.pop(entity_id, None)
                if light_np:
                    try: self.base.render.clearLight(light_np)
                    except Exception: pass
                actor = self.entity_actors.pop(entity_id, None)
                self.animation_clips.pop(entity_id, None)
                if actor is not None:
                    try: actor.cleanup()
                    except Exception: pass
                self.nodes.pop(entity_id).removeNode()
                self.node_components.pop(entity_id, None)
                self._destroy_ui_node(entity_id)
                self._destroy_particle_emitter(entity_id)
                self._destroy_terrain(entity_id)
                picker = self.pick_nodes.pop(entity_id, None)
                if picker:
                    picker.removeNode()
        parsed = [Entity.from_dict(raw) for raw in entities]
        for ent in parsed:
            self._upsert(ent)
        # Mirror authoring hierarchy after all roots exist. Entity transforms remain local
        # to their parent, matching the .pscene document model.
        for ent in parsed:
            root = self.nodes.get(ent.id)
            if not root:
                continue
            parent = self.nodes.get(ent.parent or '') if ent.parent else None
            target_parent = parent if parent else self.base.render
            if root.getParent() != target_parent:
                root.reparentTo(target_parent)
            t = ent.transform
            root.setPos(*t.position); root.setHpr(*t.rotation); root.setScale(*t.scale)
        if self.selected:
            self._select(self.selected)
        if self.preview_camera_id:
            self._apply_preview_camera()

    def _upsert(self, ent: Entity) -> None:
        assert self.base
        signature = json.dumps(ent.components, sort_keys=True, default=str)
        root = self.nodes.get(ent.id)
        if root is not None and root.isEmpty():
            self.nodes.pop(ent.id, None)
            self.pick_nodes.pop(ent.id, None)
            self.node_components.pop(ent.id, None)
            root = None
        if root is not None and self.node_components.get(ent.id) != signature:
            light_np = self.entity_lights.pop(ent.id, None)
            self.runtime_light_enabled.pop(ent.id, None)
            if light_np:
                try: self.base.render.clearLight(light_np)
                except Exception: pass
            picker = self.pick_nodes.pop(ent.id, None)
            if picker:
                try: picker.removeNode()
                except Exception: pass
            actor = self.entity_actors.pop(ent.id, None)
            self.animation_clips.pop(ent.id, None)
            self._destroy_ui_node(ent.id)
            self._destroy_particle_emitter(ent.id)
            self._destroy_terrain(ent.id)
            if actor is not None:
                try: actor.cleanup()
                except Exception: pass
            # Preserve child entity roots before replacing this visual/component root.
            for child_id, child_root in list(self.nodes.items()):
                if child_id != ent.id and not child_root.isEmpty() and child_root.getParent() == root:
                    child_root.reparentTo(self.base.render)
            try: root.removeNode()
            except Exception: pass
            self.nodes.pop(ent.id, None)
            root = None
        if root is None:
            root = self._make_entity_node(ent)
            self.nodes[ent.id] = root
            self.node_components[ent.id] = signature
            if ent.components.get('terrain'):
                self._enable_terrain_geometry_picking(ent.id, root)
            elif ent.components.get('model', {}).get('asset'):
                self._enable_model_geometry_picking(ent.id, root)
            elif ent.components.get('ui') and not ent.components.get('primitive'):
                pass  # UI-only entities are selected from the Outliner, not 3D picking.
            else:
                self._build_pick_bounds(ent.id, root)
        root.setName(ent.name)
        root.setTag('entity_id', ent.id)
        editor_state = ent.components.get('editor_state', {}) or {}
        root.setTag('editor_locked', '1' if bool(editor_state.get('locked', False)) else '0')
        t = ent.transform
        root.setPos(*t.position)
        root.setHpr(*t.rotation)
        root.setScale(*t.scale)
        editor_hidden = bool(editor_state.get('hidden', False)) and not self.play_mode
        if ent.visible and ent.enabled and not editor_hidden:
            root.show()
        else:
            root.hide()
        ui_widget = self.ui_nodes.get(ent.id)
        ui_comp = ent.components.get('ui') or {}
        if ui_widget is not None:
            try:
                if ent.visible and ent.enabled and not editor_hidden and ui_comp.get('visible', True) is not False: ui_widget.show()
                else: ui_widget.hide()
            except Exception: pass

    def _make_entity_node(self, ent: Entity) -> NodePath:
        """Build one composable runtime mirror for an authoring entity.

        Visual, light and camera components may coexist on the same entity.  Earlier
        POC builds returned after the first recognized component, which made adding a
        Light component to a mesh replace the mesh instead of augmenting it.
        """
        assert self.base
        root = self.base.render.attachNewNode(ent.name)
        root.setTag('entity_id', ent.id)
        model_component = ent.components.get('model', {})
        primitive = ent.components.get('primitive', {}).get('type')
        asset = model_component.get('asset')
        light_component = ent.components.get('light', {})
        camera_component = ent.components.get('camera', {})

        # Geometry / visible representation.  Entities with an Animation component
        # use Panda3D's Actor wrapper so model formats such as glTF can expose
        # embedded animation clips through the same runtime used by Play/Standalone.
        animation_component = ent.components.get('animation', {})
        if asset:
            try:
                asset_path = (PROJECT_ROOT / str(asset)).resolve() if not Path(str(asset)).is_absolute() else Path(str(asset))
                panda_path = self._panda_filename(asset_path)
                if animation_component and animation_component.get('enabled', True) is not False:
                    self.log(f'Viewport actor load: {asset} -> {panda_path}')
                    actor = Actor(str(panda_path))
                    if actor is None or actor.isEmpty():
                        raise RuntimeError(f'Panda Actor returned an empty model for {panda_path}')
                    actor.reparentTo(root)
                    actor.setTag('editor_geometry_source', '1')
                    self.entity_actors[ent.id] = actor
                    clips = sorted({str(x) for x in actor.getAnimNames()})
                    self.animation_clips[ent.id] = clips
                    self.event('animation_clips', entity_id=ent.id, clips=clips)
                    self._apply_visual_render_mode(actor)
                    if self.play_mode and animation_component.get('autoplay', False) and clips:
                        requested = str(animation_component.get('default_clip') or '').strip()
                        clip = requested if requested in clips else clips[0]
                        self._animation_play(ent.id, clip, loop=bool(animation_component.get('loop', True)), restart=True, rate=float(animation_component.get('play_rate', 1.0) or 1.0))
                else:
                    self.log(f'Viewport model load: {asset} -> {panda_path}')
                    model = self.base.loader.loadModel(panda_path)
                    if model is None or model.isEmpty():
                        raise RuntimeError(f'Panda loader returned an empty model for {panda_path}')
                    model.reparentTo(root)
                    model.setTag('editor_geometry_source', '1')
                    self._apply_visual_render_mode(model)
            except Exception as exc:
                self.log(f'Viewport: failed to load {asset}: {exc}')
        elif primitive == 'plane':
            cm = CardMaker(ent.name + '-visual')
            cm.setFrame(-1, 1, -1, 1)
            # Lit/PBR materials require vertex normals. CardMaker does not
            # generate them unless explicitly requested.
            cm.setHasNormals(True)
            visual = root.attachNewNode(cm.generate())
            visual.setTag('editor_geometry_source', '1')
            visual.setP(-90)
            visual.setColor(0.23, 0.27, 0.32, 1)
            visual.setTextureOff(1)
            visual.setTwoSided(True)
            self._apply_visual_render_mode(visual)
        elif primitive:
            try:
                model_name = 'models/misc/sphere' if primitive == 'sphere' else 'models/box'
                visual = self.base.loader.loadModel(model_name)
                visual.reparentTo(root)
                visual.setTag('editor_geometry_source', '1')
                visual.setTextureOff(1)
                self._apply_visual_render_mode(visual)
                try:
                    lo, hi = visual.getTightBounds(root)
                    if lo is not None and hi is not None:
                        center = (lo + hi) * 0.5
                        visual.setPos(visual.getPos() - center)
                except Exception:
                    pass
                if primitive == 'sphere':
                    visual.setScale(0.75)
                    visual.setColor(0.46, 0.62, 0.80, 1)
                elif primitive == 'empty':
                    visual.setScale(0.16)
                    visual.setColor(1.0, 0.60, 0.12, 1)
                else:
                    visual.setColor(0.42, 0.56, 0.70, 1)
            except Exception:
                pass

        # Material/render override component.  This is deliberately applied after
        # the visual is created so it works for primitives and imported models alike.
        material_component = ent.components.get('material', {})
        if material_component:
            self._apply_material_component(root, material_component)

        shader_component = ent.components.get('shader', {})
        if shader_component:
            self._apply_shader_component(ent.id, root, shader_component)

        # Screen-space UI is built under aspect2d, separate from the 3D entity root.
        ui_component = ent.components.get('ui', {})
        if ui_component:
            self._build_ui_component(ent.id, ent.name, ui_component)

        particle_component = ent.components.get('particle_emitter', {})
        if particle_component:
            self._build_particle_emitter(ent.id, root, ent.name, particle_component)

        terrain_component = ent.components.get('terrain', {})
        if terrain_component:
            self._build_terrain_component(ent.id, root, ent.name, terrain_component)

        # Collider component is visualized as an authoring-only wire helper.
        collider_component = ent.components.get('collider', {})
        if collider_component and collider_component.get('enabled', True) is not False:
            self._build_collider_helper(root, ent.name, collider_component)

        # Light component augments, rather than replaces, the visual component.
        if light_component:
            light_type = str(light_component.get('type', 'point')).lower()
            color = list(light_component.get('color', [1.0, 0.95, 0.85])) + [1.0, 1.0, 1.0]
            intensity = max(0.0, float(light_component.get('intensity', 1.0)))
            rgba = Vec4(float(color[0]) * intensity, float(color[1]) * intensity, float(color[2]) * intensity, 1)
            if light_type == 'directional':
                light = DirectionalLight(ent.name + '-light')
                light.setColor(rgba)
                light_np = root.attachNewNode(light)
                segs = LineSegs(ent.name + '-helper'); segs.setThickness(2.2); segs.setColor(1.0, 0.78, 0.28, 1)
                segs.moveTo(0,0,0); segs.drawTo(0,1.2,0)
                segs.moveTo(0,1.2,0); segs.drawTo(-.18,.9,.12); segs.moveTo(0,1.2,0); segs.drawTo(.18,.9,.12)
                helper = root.attachNewNode(segs.create()); self._isolate_editor_helper(helper); helper.setDepthTest(False); helper.setBin('fixed', 25)
            elif light_type == 'spot':
                light = Spotlight(ent.name + '-light')
                light.setColor(rgba)
                range_value = max(0.5, float(light_component.get('range', 30.0)))
                fov = max(1.0, min(175.0, float(light_component.get('fov', 45.0))))
                exponent = max(0.0, float(light_component.get('exponent', 8.0)))
                lens = PerspectiveLens(); lens.setFov(fov); lens.setNearFar(0.05, range_value)
                light.setLens(lens); light.setExponent(exponent)
                light.setAttenuation(Vec3(1.0, 0.0, 16.0 / (range_value * range_value)))
                if hasattr(light, 'setMaxDistance'): light.setMaxDistance(range_value)
                light_np = root.attachNewNode(light)
                # Wire cone follows the light entity transform, while remaining editor-render isolated.
                depth = min(2.0, max(.8, range_value * .08)); half = math.tan(math.radians(fov * .5)) * depth
                segs = LineSegs(ent.name + '-helper'); segs.setThickness(2.0); segs.setColor(1.0, 0.62, 0.20, 1)
                corners=[Vec3(-half,depth,-half),Vec3(half,depth,-half),Vec3(half,depth,half),Vec3(-half,depth,half)]
                for c in corners: segs.moveTo(0,0,0); segs.drawTo(c)
                for i in range(4): segs.moveTo(corners[i]); segs.drawTo(corners[(i+1)%4])
                helper = root.attachNewNode(segs.create()); self._isolate_editor_helper(helper); helper.setDepthTest(False); helper.setBin('fixed', 25)
            else:
                light = PointLight(ent.name + '-light')
                light.setColor(rgba)
                range_value = max(0.5, float(light_component.get('range', 25.0)))
                light.setAttenuation(Vec3(1.0, 0.0, 16.0 / (range_value * range_value)))
                if hasattr(light, 'setMaxDistance'): light.setMaxDistance(range_value)
                light_np = root.attachNewNode(light)
                segs = LineSegs(ent.name + '-helper'); segs.setThickness(2.2); segs.setColor(1.0, 0.78, 0.28, 1)
                for axis in (Vec3(.35,0,0), Vec3(0,.35,0), Vec3(0,0,.35)):
                    segs.moveTo(-axis); segs.drawTo(axis)
                helper = root.attachNewNode(segs.create()); self._isolate_editor_helper(helper); helper.setDepthTest(False); helper.setBin('fixed', 25)
            self._configure_light_shadow(light, light_type, light_component, ent.name)
            self.base.render.setLight(light_np)
            self.entity_lights[ent.id] = light_np
            self.runtime_light_enabled[ent.id] = True

        # Camera component helper roughly reflects the authored projection/FOV.
        if camera_component:
            projection = str(camera_component.get('projection', 'perspective')).lower()
            depth = 1.5
            if projection == 'orthographic':
                half_h = 0.52
                half_w = 0.78
            else:
                fov = max(1.0, min(150.0, float(camera_component.get('fov', 60.0))))
                half_h = max(.18, min(.85, math.tan(math.radians(fov) * .5) * depth * .42))
                half_w = half_h * 1.45
            segs = LineSegs(ent.name + '-camera-helper'); segs.setThickness(2.0); segs.setColor(0.40, 0.78, 1.0, 1)
            origin = Vec3(0, 0, 0)
            corners = [Vec3(-half_w,depth,-half_h),Vec3(half_w,depth,-half_h),Vec3(half_w,depth,half_h),Vec3(-half_w,depth,half_h)]
            for c in corners:
                segs.moveTo(origin); segs.drawTo(c)
            for a,b in ((0,1),(1,2),(2,3),(3,0)):
                segs.moveTo(corners[a]); segs.drawTo(corners[b])
            helper = root.attachNewNode(segs.create()); self._isolate_editor_helper(helper); helper.setDepthTest(False); helper.setBin('fixed', 25)


        navigation_surface = ent.components.get('navigation_surface', {})
        if navigation_surface and not self.play_mode:
            self._build_navigation_surface_helper(root, ent.name, navigation_surface, bool(terrain_component))
        navigation_obstacle = ent.components.get('navigation_obstacle', {})
        if navigation_obstacle and not self.play_mode:
            self._build_navigation_obstacle_helper(root, ent.name, navigation_obstacle)

        render_attributes = ent.components.get('render_attributes', {})
        if render_attributes:
            self._apply_render_attributes(root, render_attributes)

        # Render Attributes/custom shaders belong to the game entity only. Reassert
        # editor-helper isolation after authored render state has been applied.
        for helper in root.findAllMatches('**/*helper*'):
            self._isolate_editor_helper(helper)

        return root


    # ------------------------------------------------------------------
    # Navigation / AI foundation (0.4.16)
    # ------------------------------------------------------------------
    def _build_navigation_surface_helper(self, root: NodePath, name: str, comp: dict, terrain_backed: bool=False) -> None:
        if comp.get('enabled', True) is False: return
        size=list(comp.get('size',[20.0,20.0]))+[20.0,20.0]
        sx=max(.1,float(size[0])); sy=max(.1,float(size[1])); cell=max(.1,float(comp.get('cell_size',1.0)))
        terrain_backed=bool(terrain_backed)
        x0=0.0 if terrain_backed else -sx*.5; y0=0.0 if terrain_backed else -sy*.5
        seg=LineSegs(name+'-nav-surface-helper'); seg.setThickness(1.0); seg.setColor(.18,.88,.66,.7)
        # Keep authoring helpers bounded even for very fine grids.
        nx=max(1,min(32,int(math.ceil(sx/cell)))); ny=max(1,min(32,int(math.ceil(sy/cell))))
        for i in range(nx+1):
            x=x0+sx*(i/nx); seg.moveTo(x,y0,.04); seg.drawTo(x,y0+sy,.04)
        for j in range(ny+1):
            y=y0+sy*(j/ny); seg.moveTo(x0,y,.04); seg.drawTo(x0+sx,y,.04)
        h=root.attachNewNode(seg.create()); self._isolate_editor_helper(h); h.setName(name+'-navigation-helper'); h.setDepthWrite(False); h.setBin('fixed',24)

    def _build_navigation_obstacle_helper(self, root: NodePath, name: str, comp: dict) -> None:
        if comp.get('enabled', True) is False: return
        radius=max(.05,float(comp.get('radius',1.0))); seg=LineSegs(name+'-nav-obstacle-helper'); seg.setThickness(2.0); seg.setColor(1.0,.35,.18,.9)
        steps=24
        for i in range(steps+1):
            a=math.tau*(i/steps); p=Vec3(math.cos(a)*radius,math.sin(a)*radius,.08)
            if i==0: seg.moveTo(p)
            else: seg.drawTo(p)
        h=root.attachNewNode(seg.create()); self._isolate_editor_helper(h); h.setName(name+'-navigation-obstacle-helper'); h.setDepthWrite(False); h.setBin('fixed',25)

    def _clear_navigation_runtime(self) -> None:
        self.nav_surfaces.clear(); self.nav_agents.clear(); self.nav_obstacles.clear()
        if self._nav_debug_root:
            try: self._nav_debug_root.removeNode()
            except Exception: pass
        self._nav_debug_root=None

    def _initialize_navigation(self) -> None:
        self._clear_navigation_runtime()
        if not self.base: return
        for eid,raw in self.entity_data.items():
            comps=raw.get('components') or {}; root=self.nodes.get(eid)
            surf=comps.get('navigation_surface') or {}
            if root and surf and surf.get('enabled',True) is not False:
                size=list(surf.get('size',[20,20]))+[20,20]
                if comps.get('terrain'):
                    ts=list((comps.get('terrain') or {}).get('size',[64,64]))+[64,64]
                    if not surf.get('override_size',False): size=ts
                self.nav_surfaces[eid]={'id':eid,'name':raw.get('name',eid),'root':root,'component':copy.deepcopy(surf),'size':[max(.1,float(size[0])),max(.1,float(size[1]))],'terrain':bool(comps.get('terrain')),'terrain_id':eid if comps.get('terrain') else None}
            obs=comps.get('navigation_obstacle') or {}
            if root and obs and obs.get('enabled',True) is not False:
                try: pos=root.getPos(self.base.render)
                except Exception: pos=Vec3(0,0,0)
                self.nav_obstacles[eid]={'id':eid,'name':raw.get('name',eid),'position':[float(pos.x),float(pos.y),float(pos.z)],'radius':max(.05,float(obs.get('radius',1.0))),'height':max(.05,float(obs.get('height',2.0))),'carve':bool(obs.get('carve',True))}
        for eid,raw in self.entity_data.items():
            comp=(raw.get('components') or {}).get('navigation_agent') or {}
            if comp and comp.get('enabled',True) is not False and eid in self.nodes:
                self.nav_agents[eid]={'component':copy.deepcopy(comp),'surface':str(comp.get('surface') or ''),'speed':max(0.0,float(comp.get('speed',3.5))),'acceleration':max(0.0,float(comp.get('acceleration',12.0))),'stopping_distance':max(0.0,float(comp.get('stopping_distance',.25))),'repath_interval':max(.05,float(comp.get('repath_interval',.5))),'face_movement':bool(comp.get('face_movement',True)),'movement_mode':str(comp.get('movement_mode','auto')),'behavior':str(comp.get('behavior','none')),'target':str(comp.get('target') or ''),'path':[],'finished':True,'repath_clock':0.0,'patrol_index':0,'patrol_points':copy.deepcopy(comp.get('patrol_points') or []),'patrol_loop':bool(comp.get('patrol_loop',True)),'flee_distance':max(.5,float(comp.get('flee_distance',8.0))),'velocity':[0.0,0.0,0.0]}
        # Start authored behaviors only after all agents/surfaces exist.
        for eid,state in list(self.nav_agents.items()):
            beh=state.get('behavior','none')
            if beh=='patrol' and state.get('patrol_points'): self._navigation_agent_patrol(eid,state['patrol_points'],state.get('patrol_loop',True))
            elif beh=='chase' and state.get('target'): self._navigation_agent_chase(eid,state['target'],state.get('repath_interval'))
            elif beh=='flee' and state.get('target'): self._navigation_agent_flee(eid,state['target'],state.get('flee_distance',8),state.get('repath_interval'))
        self.log(f'Navigation: {len(self.nav_surfaces)} surface(s), {len(self.nav_agents)} agent(s), {len(self.nav_obstacles)} obstacle(s).')

    def _navigation_resolve_surface(self, surface=None):
        if not self.nav_surfaces: return None
        if isinstance(surface,RuntimeEntity): surface=surface.id
        key=str(surface or '')
        if key in self.nav_surfaces: return self.nav_surfaces[key]
        if key:
            low=key.lower()
            for st in self.nav_surfaces.values():
                if str(st.get('name','')).lower()==low: return st
        return next(iter(self.nav_surfaces.values()))

    def _navigation_surface_info(self, surface=None) -> dict | None:
        st=self._navigation_resolve_surface(surface)
        if not st: return None
        comp=st.get('component') or {}
        return {'id':st['id'],'name':st['name'],'size':list(st['size']),'cell_size':max(.1,float(comp.get('cell_size',1.0))),'diagonal':bool(comp.get('diagonal',True)),'terrain':bool(st.get('terrain')),'obstacles':len(self.nav_obstacles)}

    def _navigation_point(self, value) -> Point3 | None:
        if isinstance(value,RuntimeEntity):
            n=value.node
            if n and self.base:
                p=n.getPos(self.base.render); return Point3(p)
        if isinstance(value,str):
            ent=self.runtime_world.get_entity(value)
            if ent and ent.node and self.base:
                p=ent.node.getPos(self.base.render); return Point3(p)
        try:
            v=list(value); return Point3(float(v[0]),float(v[1]),float(v[2] if len(v)>2 else 0.0))
        except Exception: return None

    def _navigation_surface_local_bounds(self, st):
        sx,sy=st['size']; return (0.0,sx,0.0,sy) if st.get('terrain') else (-sx*.5,sx*.5,-sy*.5,sy*.5)

    def _navigation_world_to_cell(self, st, point: Point3):
        root=st['root']; comp=st.get('component') or {}; cell=max(.1,float(comp.get('cell_size',1.0)))
        try: local=root.getRelativePoint(self.base.render,point)
        except Exception: return None
        x0,x1,y0,y1=self._navigation_surface_local_bounds(st)
        if local.x<x0 or local.x>x1 or local.y<y0 or local.y>y1: return None
        nx=max(1,int(math.ceil((x1-x0)/cell))); ny=max(1,int(math.ceil((y1-y0)/cell)))
        ix=max(0,min(nx-1,int((local.x-x0)/cell))); iy=max(0,min(ny-1,int((local.y-y0)/cell)))
        return ix,iy,nx,ny,x0,y0,cell

    def _navigation_cell_world(self, st, cell_data, ix, iy):
        _,_,_,_,x0,y0,cell=cell_data; root=st['root']
        local=Point3(x0+(ix+.5)*cell,y0+(iy+.5)*cell,0)
        wp=self.base.render.getRelativePoint(root,local)
        if st.get('terrain_id'):
            z=self._terrain_height(st['terrain_id'],wp.x,wp.y,True)
            if z is not None: wp.z=float(z)
        return [float(wp.x),float(wp.y),float(wp.z)]

    def _navigation_cell_blocked(self, st, world_point, agent_radius=0.0) -> bool:
        px,py=float(world_point[0]),float(world_point[1]); pad=max(0.0,float(agent_radius))
        for ob in self.nav_obstacles.values():
            if not ob.get('carve',True): continue
            n=self.nodes.get(str(ob.get('id') or '')); op=ob.get('position',[0,0,0])
            if n and self.base:
                try:
                    p=n.getPos(self.base.render); op=[float(p.x),float(p.y),float(p.z)]; ob['position']=op
                except Exception: pass
            r=float(ob.get('radius',1.0))+pad
            if (px-float(op[0]))**2+(py-float(op[1]))**2 <= r*r: return True
        return False

    def _navigation_find_path(self, start, end, surface=None, agent_radius: float=0.0) -> list[list[float]]:
        if not self.base: return []
        st=self._navigation_resolve_surface(surface); a=self._navigation_point(start); b=self._navigation_point(end)
        if not st or a is None or b is None: return []
        ca=self._navigation_world_to_cell(st,a); cb=self._navigation_world_to_cell(st,b)
        if not ca or not cb: return []
        sx,sy=ca[0],ca[1]; gx,gy=cb[0],cb[1]; nx,ny=ca[2],ca[3]
        diagonal=bool((st.get('component') or {}).get('diagonal',True)); dirs=[(1,0,1),(-1,0,1),(0,1,1),(0,-1,1)]
        if diagonal: dirs += [(1,1,1.41421356),(1,-1,1.41421356),(-1,1,1.41421356),(-1,-1,1.41421356)]
        start_key=(sx,sy); goal=(gx,gy); openq=[(0.0,start_key)]; came={}; gscore={start_key:0.0}; seen=set()
        while openq:
            _,cur=heapq.heappop(openq)
            if cur in seen: continue
            seen.add(cur)
            if cur==goal: break
            for dx,dy,cost in dirs:
                q=(cur[0]+dx,cur[1]+dy)
                if q[0]<0 or q[1]<0 or q[0]>=nx or q[1]>=ny: continue
                wp=self._navigation_cell_world(st,ca,q[0],q[1])
                if q!=goal and self._navigation_cell_blocked(st,wp,agent_radius): continue
                ng=gscore[cur]+cost
                if ng<gscore.get(q,1e30):
                    gscore[q]=ng; came[q]=cur; h=math.hypot(goal[0]-q[0],goal[1]-q[1]); heapq.heappush(openq,(ng+h,q))
        if goal not in came and goal!=start_key: return []
        cells=[goal]
        while cells[-1]!=start_key: cells.append(came[cells[-1]])
        cells.reverse(); path=[self._navigation_cell_world(st,ca,x,y) for x,y in cells]
        if path: path[-1]=[float(b.x),float(b.y),float(self._terrain_height(st['terrain_id'],b.x,b.y,True) if st.get('terrain_id') and self._terrain_height(st['terrain_id'],b.x,b.y,True) is not None else b.z)]
        # simple line-of-sight-like reduction by direction changes
        reduced=[]; last_dir=None
        for i,p in enumerate(path):
            if i==0 or i==len(path)-1: reduced.append(p); continue
            prev=path[i-1]; nxt=path[i+1]; d=(round(nxt[0]-p[0],4),round(nxt[1]-p[1],4)); pd=(round(p[0]-prev[0],4),round(p[1]-prev[1],4))
            if d!=pd: reduced.append(p)
        if path and (not reduced or reduced[-1]!=path[-1]): reduced.append(path[-1])
        result=reduced or path
        # The start cell represents the agent's current occupancy, not a waypoint it
        # should walk back to the centre of.  Skip it when a route has more points.
        return result[1:] if len(result)>1 else result

    def _navigation_nearest_point(self, point, surface=None):
        st=self._navigation_resolve_surface(surface); p=self._navigation_point(point)
        if not st or p is None or not self.base: return None
        root=st['root']; local=root.getRelativePoint(self.base.render,p); x0,x1,y0,y1=self._navigation_surface_local_bounds(st)
        local.x=max(x0,min(x1,local.x)); local.y=max(y0,min(y1,local.y)); wp=self.base.render.getRelativePoint(root,local)
        if st.get('terrain_id'):
            z=self._terrain_height(st['terrain_id'],wp.x,wp.y,True)
            if z is not None: wp.z=z
        return [float(wp.x),float(wp.y),float(wp.z)]

    def _navigation_agent_position(self, eid):
        n=self.nodes.get(str(eid));
        if not n or not self.base: return None
        p=n.getPos(self.base.render); return Point3(p)

    def _navigation_agent_set_target(self, eid, target, surface=None) -> bool:
        state=self.nav_agents.get(str(eid)); pos=self._navigation_agent_position(eid); dest=self._navigation_point(target)
        if not state or pos is None or dest is None: return False
        surf=surface if surface is not None else state.get('surface')
        path=self._navigation_find_path(pos,dest,surf,float((state.get('component') or {}).get('radius',.35)))
        state['path']=path; state['target']=target.id if isinstance(target,RuntimeEntity) else copy.deepcopy(target); state['finished']=not bool(path); state['repath_clock']=0.0
        return bool(path)

    def _navigation_agent_stop(self, eid) -> bool:
        state=self.nav_agents.get(str(eid))
        if not state: return False
        state['path']=[]; state['finished']=True; state['behavior']='none'; state['target']=''
        char=self.physics_characters.get(str(eid))
        if char:
            try: char.node().setLinearMovement(Vec3(0,0,0),False)
            except Exception: pass
        return True

    def _navigation_agent_repath(self, eid) -> bool:
        state=self.nav_agents.get(str(eid));
        if not state or not state.get('target'): return False
        return self._navigation_agent_set_target(eid,state['target'],state.get('surface'))

    def _navigation_agent_patrol(self, eid, points, loop=True) -> bool:
        state=self.nav_agents.get(str(eid));
        if not state: return False
        pts=list(points or []); state['behavior']='patrol'; state['patrol_points']=copy.deepcopy(pts); state['patrol_loop']=bool(loop); state['patrol_index']=0
        if not pts: return False
        return self._navigation_agent_set_target(eid,pts[0],state.get('surface'))

    def _navigation_agent_chase(self, eid, target, repath_interval=None) -> bool:
        state=self.nav_agents.get(str(eid));
        if not state: return False
        state['behavior']='chase'; state['target']=target.id if isinstance(target,RuntimeEntity) else copy.deepcopy(target)
        if repath_interval is not None: state['repath_interval']=max(.05,float(repath_interval))
        return self._navigation_agent_repath(eid)

    def _navigation_agent_flee(self, eid, target, distance=8.0, repath_interval=None) -> bool:
        state=self.nav_agents.get(str(eid)); pos=self._navigation_agent_position(eid); threat=self._navigation_point(target)
        if not state or pos is None or threat is None: return False
        state['behavior']='flee'; state['target']=target.id if isinstance(target,RuntimeEntity) else copy.deepcopy(target); state['flee_distance']=max(.5,float(distance))
        if repath_interval is not None: state['repath_interval']=max(.05,float(repath_interval))
        dx=pos.x-threat.x; dy=pos.y-threat.y; l=max(1e-6,math.hypot(dx,dy)); dest=[pos.x+dx/l*state['flee_distance'],pos.y+dy/l*state['flee_distance'],pos.z]
        ok=self._navigation_agent_set_target(eid,dest,state.get('surface')); state['behavior']='flee'; state['target']=target.id if isinstance(target,RuntimeEntity) else copy.deepcopy(target); return ok

    def _navigation_finish_or_advance(self, eid, state) -> None:
        beh=state.get('behavior','none')
        # Chase/flee are continuous steering behaviors. Repath cadence may place the
        # agent at the temporary endpoint repeatedly; that is not a completed authored
        # navigation command and must not spam navigation_finished every repath.
        if beh in {'chase','flee'}:
            state['finished']=True
            return
        if beh=='patrol':
            pts=state.get('patrol_points') or []; idx=int(state.get('patrol_index',0))+1
            if idx>=len(pts):
                if state.get('patrol_loop',True): idx=0
                else: state['finished']=True; state['behavior']='none'; return
            state['patrol_index']=idx; self._navigation_agent_set_target(eid,pts[idx],state.get('surface'))
        else:
            state['finished']=True
            raw=self.entity_data.get(str(eid),{}); comp=(raw.get('components') or {}).get('navigation_agent') or {}
            ev=str(comp.get('finished_event') or '').strip(); sig=str(comp.get('finished_signal') or '').strip()
            if ev: self._dispatch_script_event(ev,{'agent':eid},str(eid),str(eid))
            if sig: self._emit_entity_signal(str(eid),sig,{'agent':eid})

    def _update_navigation_agents(self, dt: float) -> None:
        if dt<=0: return
        for eid,state in list(self.nav_agents.items()):
            if eid not in self.nodes: continue
            state['repath_clock']=float(state.get('repath_clock',0.0))+dt
            beh=state.get('behavior','none'); interval=max(.05,float(state.get('repath_interval',.5)))
            if beh in {'chase','flee'} and state.get('target') and state['repath_clock']>=interval:
                state['repath_clock']=0.0
                if beh=='chase': self._navigation_agent_repath(eid)
                else:
                    target=state.get('target'); pos=self._navigation_agent_position(eid); threat=self._navigation_point(target)
                    if pos is not None and threat is not None:
                        dx=pos.x-threat.x; dy=pos.y-threat.y; l=max(1e-6,math.hypot(dx,dy)); d=float(state.get('flee_distance',8)); dest=[pos.x+dx/l*d,pos.y+dy/l*d,pos.z]; self._navigation_agent_set_target(eid,dest,state.get('surface')); state['behavior']='flee'; state['target']=target
            path=state.get('path') or []
            if not path: continue
            root=self.nodes.get(eid); pos=self._navigation_agent_position(eid)
            if not root or pos is None: continue
            stop=max(.02,float(state.get('stopping_distance',.25))); wp=path[0]; dx=float(wp[0])-pos.x; dy=float(wp[1])-pos.y; dz=float(wp[2])-pos.z; dist=math.sqrt(dx*dx+dy*dy+dz*dz)
            if dist<=stop:
                path.pop(0); state['path']=path
                if not path: self._navigation_finish_or_advance(eid,state)
                continue
            speed=max(0.0,float(state.get('speed',3.5))); desired=[dx/max(dist,1e-6)*speed,dy/max(dist,1e-6)*speed,dz/max(dist,1e-6)*speed]
            vel=list(state.get('velocity') or [0,0,0])+[0,0,0]; accel=max(0.0,float(state.get('acceleration',12.0))); max_delta=accel*dt
            for i in range(3):
                delta=desired[i]-float(vel[i]); vel[i]=float(vel[i])+max(-max_delta,min(max_delta,delta)) if accel>0 else desired[i]
            state['velocity']=vel[:3]; vx,vy,vz=vel[:3]
            if state.get('face_movement',True) and abs(vx)+abs(vy)>1e-6:
                heading=math.degrees(math.atan2(vx,vy))
                try: root.setH(self.base.render,heading)
                except Exception: pass
            mode=str(state.get('movement_mode','auto')).lower(); char=self.physics_characters.get(eid)
            if char and mode in {'auto','character'}:
                try: char.node().setLinearMovement(Vec3(vx,vy,vz),False); self._character_move_written.add(eid)
                except Exception: pass
            else:
                try:
                    step=min(dist,math.sqrt(vx*vx+vy*vy+vz*vz)*dt); root.setPos(self.base.render,pos+Vec3(dx,dy,dz)/max(dist,1e-6)*step)
                except Exception: pass

    def _clear_ai_behaviors(self) -> None:
        self.ai_behaviors.clear()

    def _initialize_ai_behaviors(self) -> None:
        self._clear_ai_behaviors()
        for eid,raw in self.entity_data.items():
            comp=(raw.get('components') or {}).get('ai_behavior') or {}
            if not comp or comp.get('enabled',True) is False or eid not in self.nodes:
                continue
            states=copy.deepcopy(comp.get('states') or {'idle':'Idle','patrol':'Patrol','chase':'Chase','attack':'Attack','flee':'Flee','search':'Search'})
            self.ai_behaviors[eid]={
                'component':copy.deepcopy(comp),'state':str(comp.get('initial_state','idle') or 'idle').lower(),
                'target':str(comp.get('target') or ''),'paused':False,'think_clock':0.0,
                'think_interval':max(.02,float(comp.get('think_interval',.2))),
                'disposition':str(comp.get('disposition','aggressive') or 'aggressive').lower(),
                'target_mode':str(comp.get('target_mode','explicit') or 'explicit').lower(),
                'target_tag':str(comp.get('target_tag','player') or 'player'),
                'sight_distance':max(0.0,float(comp.get('sight_distance',15.0))),
                'field_of_view':max(1.0,min(360.0,float(comp.get('field_of_view',120.0)))),
                'require_los':bool(comp.get('require_los',False)),
                'attack_distance':max(0.0,float(comp.get('attack_distance',1.75))),
                'attack_cooldown':max(.02,float(comp.get('attack_cooldown',1.0))),
                'attack_clock':0.0,'memory_time':max(0.0,float(comp.get('memory_time',2.0))),
                'memory_clock':0.0,'last_seen':None,'last_seen_time':-9999.0,
                'auto_navigation':bool(comp.get('auto_navigation',True)),
                'sync_fsm':bool(comp.get('sync_fsm',True)),'states':states,
                'patrol_points':copy.deepcopy(comp.get('patrol_points') or []),'patrol_loop':bool(comp.get('patrol_loop',True)),
                'flee_distance':max(.5,float(comp.get('flee_distance',8.0))),
                'blackboard':copy.deepcopy(comp.get('blackboard') or {}),
            }
        for eid in list(self.ai_behaviors):
            self._ai_set_state(eid,self.ai_behaviors[eid].get('state','idle'),'initial',force=True)
            self._ai_think(eid,force=True)
        self.log(f'AI Behavior: {len(self.ai_behaviors)} behavior controller(s).')

    def _ai_entity(self, value):
        if isinstance(value,RuntimeEntity): return value
        if value is None: return None
        return self.runtime_world.get_entity(str(value))

    def _ai_line_of_sight(self, source: RuntimeEntity, target: RuntimeEntity, distance: float) -> bool:
        if not self.physics_world: return True
        origin=source.world_position; dest=target.world_position
        # Slight eye lift reduces ground/self hits for characters standing on Terrain.
        origin=[origin[0],origin[1],origin[2]+.75]; dest=[dest[0],dest[1],dest[2]+.75]
        d=Vec3(dest[0]-origin[0],dest[1]-origin[1],dest[2]-origin[2]); length=float(d.length())
        if length<=1e-6: return True
        hit=self._runtime_raycast(origin,d/length,min(max(distance,length)+.05,length+.05),0xFFFFFFFF,ignore_entity=source.id)
        return hit is None or str(hit.get('id') or hit.get('entity_id') or '')==target.id

    def _ai_target_visible(self, owner: RuntimeEntity, target: RuntimeEntity, state: dict) -> bool:
        try: dist=owner.distance_to(target)
        except Exception: return False
        radius=max(0.0,float(state.get('sight_distance',15.0)))
        if radius>0 and dist>radius: return False
        fov=max(1.0,min(360.0,float(state.get('field_of_view',120.0))))
        if fov<359.9 and dist>1e-6:
            f=Vec3(*owner.forward); f.z=0
            d=Vec3(*owner.direction_to(target)); d.z=0
            if f.lengthSquared()>1e-8 and d.lengthSquared()>1e-8:
                f.normalize(); d.normalize()
                if float(f.dot(d)) < math.cos(math.radians(fov*.5)): return False
        if state.get('require_los',False) and not self._ai_line_of_sight(owner,target,dist): return False
        return True

    def _ai_find_targets(self, origin, tag: str='', radius: float=20.0, fov: float=360.0, line_of_sight: bool=False) -> list[RuntimeEntity]:
        owner=self._ai_entity(origin)
        if not owner: return []
        temp={'sight_distance':max(0.0,float(radius)),'field_of_view':float(fov),'require_los':bool(line_of_sight)}
        out=[]
        for ent in self.runtime_world.entities:
            if ent.id==owner.id: continue
            if tag and not ent.has_tag(tag): continue
            if self._ai_target_visible(owner,ent,temp): out.append(ent)
        out.sort(key=lambda e: owner.distance_to(e))
        return out

    def _ai_scan_entities(self, eid: str) -> list[RuntimeEntity]:
        state=self.ai_behaviors.get(str(eid)); owner=self._ai_entity(str(eid))
        if not state or not owner: return []
        tag=state.get('target_tag','') if state.get('target_mode') in {'tag','nearest_tag'} else ''
        return self._ai_find_targets(owner,tag,state.get('sight_distance',15),state.get('field_of_view',120),state.get('require_los',False))

    def _ai_emit(self, eid: str, kind: str, payload=None) -> None:
        state=self.ai_behaviors.get(str(eid)) or {}; comp=state.get('component') or {}
        key=str(kind).strip().lower(); event_name=str(comp.get(key+'_event') or '').strip(); signal_name=str(comp.get(key+'_signal') or '').strip()
        data={'ai':str(eid),'state':state.get('state'),'target':state.get('target'),'kind':key,'data':payload}
        if event_name: self._dispatch_script_event(event_name,data,target=str(eid),sender=str(eid))
        if signal_name: self._emit_entity_signal(str(eid),signal_name,data)

    def _ai_set_target(self, eid: str, target) -> bool:
        state=self.ai_behaviors.get(str(eid)); ent=self._ai_entity(target)
        if not state or not ent or ent.id==str(eid): return False
        old=str(state.get('target') or ''); state['target']=ent.id; state['last_seen']=ent.world_position; state['last_seen_time']=self.runtime_world.time; state['memory_clock']=0.0
        if old!=ent.id: self._ai_emit(str(eid),'target_acquired',{'previous':old,'target':ent.id})
        return True

    def _ai_clear_target(self, eid: str, reason: str='lost') -> bool:
        state=self.ai_behaviors.get(str(eid))
        if not state: return False
        old=str(state.get('target') or '')
        if not old: return True
        state['target']=''; self._ai_emit(str(eid),'target_lost',{'target':old,'reason':str(reason)})
        return True

    def _ai_set_state(self, eid: str, new_state: str, reason: str='decision', force: bool=False) -> bool:
        state=self.ai_behaviors.get(str(eid)); new=str(new_state or 'idle').lower().strip()
        if not state: return False
        if new not in {'idle','patrol','chase','attack','flee','search'}: return False
        old=str(state.get('state','idle'))
        if old==new and not force: return True
        state['state']=new; state['blackboard']['reason']=str(reason); state['blackboard']['previous_state']=old
        if state.get('auto_navigation',True) and str(eid) in self.nav_agents:
            if new=='patrol':
                pts=state.get('patrol_points') or (self.nav_agents[str(eid)].get('patrol_points') or [])
                if pts: self._navigation_agent_patrol(str(eid),pts,bool(state.get('patrol_loop',True)))
                else: self._navigation_agent_stop(str(eid))
            elif new=='chase' and state.get('target'): self._navigation_agent_chase(str(eid),state['target'])
            elif new=='flee' and state.get('target'): self._navigation_agent_flee(str(eid),state['target'],state.get('flee_distance',8.0))
            elif new=='search' and state.get('last_seen') is not None: self._navigation_agent_set_target(str(eid),state['last_seen'])
            else: self._navigation_agent_stop(str(eid))
        if state.get('sync_fsm',True) and str(eid) in self.fsm_states:
            mapped=str((state.get('states') or {}).get(new) or '').strip()
            if mapped and self._fsm_state_def(str(eid),mapped): self._fsm_request(str(eid),mapped,{'ai_state':new,'reason':reason})
        self._ai_emit(str(eid),'state_changed',{'from':old,'to':new,'reason':str(reason)})
        if new=='attack': state['attack_clock']=state.get('attack_cooldown',1.0)
        return True

    def _ai_choose_target(self, eid: str, state: dict):
        owner=self._ai_entity(eid)
        if not owner: return None
        current=self._ai_entity(state.get('target'))
        if current and self._ai_target_visible(owner,current,state): return current
        mode=str(state.get('target_mode','explicit')).lower()
        comp=state.get('component') or {}
        if mode=='explicit':
            explicit=self._ai_entity(comp.get('target') or state.get('target'))
            return explicit if explicit and self._ai_target_visible(owner,explicit,state) else None
        tag=str(state.get('target_tag') or '')
        found=self._ai_find_targets(owner,tag,state.get('sight_distance',15),state.get('field_of_view',120),state.get('require_los',False))
        return found[0] if found else None

    def _ai_think(self, eid: str, force: bool=False) -> bool:
        state=self.ai_behaviors.get(str(eid)); owner=self._ai_entity(str(eid))
        if not state or not owner or state.get('paused'): return False
        target=self._ai_choose_target(str(eid),state)
        if target:
            self._ai_set_target(str(eid),target)
            state['last_seen']=target.world_position; state['last_seen_time']=self.runtime_world.time; state['memory_clock']=0.0
            disposition=str(state.get('disposition','aggressive')).lower()
            if disposition=='scripted': return True
            if disposition=='avoid': return self._ai_set_state(str(eid),'flee','target_visible')
            dist=owner.distance_to(target)
            return self._ai_set_state(str(eid),'attack' if dist<=float(state.get('attack_distance',1.75)) else 'chase','target_visible')
        # Target is not currently visible. Retain memory briefly and search last position.
        had=bool(state.get('target')); memory=max(0.0,float(state.get('memory_time',2.0)))
        if had and self.runtime_world.time-float(state.get('last_seen_time',-9999)) <= memory:
            if str(state.get('disposition'))!='scripted': self._ai_set_state(str(eid),'search','target_memory')
            return True
        if had: self._ai_clear_target(str(eid),'memory_expired')
        if str(state.get('disposition'))!='scripted':
            fallback='patrol' if (state.get('patrol_points') or ((self.nav_agents.get(str(eid)) or {}).get('patrol_points'))) else 'idle'
            self._ai_set_state(str(eid),fallback,'no_target')
        return True

    def _update_ai_behaviors(self, dt: float) -> None:
        if dt<=0: return
        for eid,state in list(self.ai_behaviors.items()):
            if state.get('paused') or eid not in self.nodes: continue
            state['think_clock']=float(state.get('think_clock',0.0))+dt
            state['attack_clock']=max(0.0,float(state.get('attack_clock',0.0))-dt)
            if state['think_clock']>=max(.02,float(state.get('think_interval',.2))):
                state['think_clock']=0.0; self._ai_think(eid)
            if state.get('state')=='attack' and state.get('target') and state['attack_clock']<=0.0:
                target=self._ai_entity(state.get('target')); owner=self._ai_entity(eid)
                if target and owner and owner.distance_to(target)<=float(state.get('attack_distance',1.75))*1.1:
                    self._ai_emit(eid,'attack_ready',{'target':target.id,'distance':owner.distance_to(target)})
                    state['attack_clock']=max(.02,float(state.get('attack_cooldown',1.0)))

    def _apply_render_attributes(self, root: NodePath, comp: dict) -> None:
        if not root or root.isEmpty():
            return
        try:
            if comp.get('enabled', True) is False:
                self._clear_render_attributes(root)
                return
            root.setDepthTest(bool(comp.get('depth_test', True)))
            root.setDepthWrite(bool(comp.get('depth_write', True)))
            cull=str(comp.get('cull','back')).lower()
            if cull=='none': root.setAttrib(CullFaceAttrib.make(CullFaceAttrib.MCullNone), 30)
            elif cull=='front': root.setAttrib(CullFaceAttrib.make(CullFaceAttrib.MCullCounterClockwise), 30)
            elif cull=='back': root.setAttrib(CullFaceAttrib.make(CullFaceAttrib.MCullClockwise), 30)
            else: root.clearAttrib(CullFaceAttrib.getClassType())
            trans=str(comp.get('transparency','inherit')).lower()
            if trans=='alpha': root.setTransparency(TransparencyAttrib.MAlpha, 30)
            elif trans=='binary': root.setTransparency(TransparencyAttrib.MBinary, 30)
            elif trans=='multisample': root.setTransparency(TransparencyAttrib.MMultisample, 30)
            elif trans=='none': root.setTransparency(TransparencyAttrib.MNone, 30)
            else: root.clearTransparency()
            cs=list(comp.get('color_scale',[1,1,1,1]))+[1,1,1,1]
            root.setColorScale(float(cs[0]),float(cs[1]),float(cs[2]),float(cs[3]),30)
            bin_name=str(comp.get('bin','inherit')).strip()
            if bin_name and bin_name!='inherit': root.setBin(bin_name, int(comp.get('sort',0) or 0),30)
            else: root.clearBin()
            try: root.setDepthOffset(int(comp.get('depth_offset',0) or 0),30)
            except Exception: pass
            billboard=str(comp.get('billboard','none')).lower()
            try:
                root.clearBillboard()
                if billboard=='point_eye': root.setBillboardPointEye(0.0, False, 30)
            except Exception: pass
            if bool(comp.get('light_off',False)): root.setLightOff(30)
            else: root.clearLight()
            if bool(comp.get('shader_off',False)): root.setShaderOff(30)
            else: root.clearShader()
        except Exception as exc:
            self.log(f'Render Attributes apply failed on {root.getName()}: {exc}')

    def _clear_render_attributes(self, root: NodePath) -> None:
        try: root.clearDepthTest(); root.clearDepthWrite(); root.clearTransparency(); root.clearColorScale(); root.clearBin(); root.clearAttrib(CullFaceAttrib.getClassType()); root.clearLight(); root.clearShader(); root.clearBillboard()
        except Exception: pass

    def _render_attribute_set(self, entity_id: str, name: str, value) -> bool:
        raw=self.entity_data.get(str(entity_id)); root=self.nodes.get(str(entity_id))
        if not raw or not root: return False
        comp=(raw.setdefault('components',{})).get('render_attributes')
        if not comp: return False
        allowed={'enabled','depth_test','depth_write','cull','transparency','color_scale','bin','sort','depth_offset','billboard','light_off','shader_off'}
        if name not in allowed: return False
        comp[name]=copy.deepcopy(value); self._apply_render_attributes(root,comp); return True

    def _render_attributes_reset(self, entity_id: str) -> bool:
        raw=self.entity_data.get(str(entity_id)); root=self.nodes.get(str(entity_id))
        if not raw or not root: return False
        comp=(raw.get('components') or {}).get('render_attributes')
        if not comp: return False
        # render_set() mutates only the Play-mode mirror. Reset means restore the
        # authored component snapshot, not erase the component's intended state.
        authored=None
        for src in self._authoring_entities:
            if str(src.get('id'))==str(entity_id):
                authored=copy.deepcopy((src.get('components') or {}).get('render_attributes'))
                break
        if authored:
            raw.setdefault('components',{})['render_attributes']=authored
            self._apply_render_attributes(root,authored)
        else:
            self._clear_render_attributes(root)
        return True

    def _shader_path(self, value: str) -> str:
        raw=str(value or '').strip()
        if not raw: return ''
        path=Path(raw)
        if not path.is_absolute(): path=(PROJECT_ROOT/path).resolve()
        return str(path)

    def _shader_input_value(self, value):
        if isinstance(value, dict):
            typ=str(value.get('type','auto')).lower(); v=value.get('value')
            if typ=='texture':
                path=self._shader_path(str(v or ''))
                if path and Path(path).exists():
                    try: return self.base.loader.loadTexture(self._panda_filename(Path(path)))
                    except Exception: return None
            if typ=='entity':
                ent=self.runtime_world.get_entity(str(v or '')); return ent.node if ent else None
            value=v
        if isinstance(value,(list,tuple)):
            vals=[float(x) for x in value]
            if len(vals)==2:return Vec2(*vals)
            if len(vals)==3:return Vec3(*vals)
            if len(vals)>=4:return Vec4(*vals[:4])
        if isinstance(value,(bool,int,float,str)): return value
        return value

    def _load_glsl_shader(self, vertex: str, fragment: str, geometry: str=''):
        vp=self._shader_path(vertex); fp=self._shader_path(fragment); gp=self._shader_path(geometry)
        if not vp or not fp or not Path(vp).exists() or not Path(fp).exists(): return None
        key=(vp,fp,gp if gp and Path(gp).exists() else '')
        shader=self.shader_cache.get(key)
        if shader: return shader
        try:
            kwargs={'vertex':Filename.fromOsSpecific(vp),'fragment':Filename.fromOsSpecific(fp)}
            if key[2]: kwargs['geometry']=Filename.fromOsSpecific(key[2])
            shader=Shader.load(Shader.SL_GLSL,**kwargs)
            if shader: self.shader_cache[key]=shader
            return shader
        except Exception as exc:
            self.log(f'GLSL shader load failed: {Path(vp).name} / {Path(fp).name}: {exc}')
            return None

    def _apply_shader_component(self, entity_id: str, root: NodePath, comp: dict) -> bool:
        if not root or root.isEmpty(): return False
        if comp.get('enabled',True) is False:
            try: root.clearShader()
            except Exception: pass
            return True
        shader=self._load_glsl_shader(str(comp.get('vertex') or ''),str(comp.get('fragment') or ''),str(comp.get('geometry') or ''))
        if not shader: return False
        try:
            root.setShader(shader,int(comp.get('priority',20) or 20))
            for name,value in (comp.get('inputs') or {}).items():
                resolved=self._shader_input_value(value)
                if resolved is not None: root.setShaderInput(str(name),resolved,int(comp.get('input_priority',0) or 0))
            return True
        except Exception as exc:
            self.log(f'Shader apply failed [{entity_id}]: {exc}'); return False

    def _shader_reload_entity(self, entity_id: str) -> bool:
        raw=self.entity_data.get(str(entity_id)); root=self.nodes.get(str(entity_id))
        if not raw or not root: return False
        comp=(raw.get('components') or {}).get('shader') or {}
        vp=self._shader_path(comp.get('vertex','')); fp=self._shader_path(comp.get('fragment','')); gp=self._shader_path(comp.get('geometry',''))
        self.shader_cache.pop((vp,fp,gp if gp and Path(gp).exists() else ''),None)
        return self._apply_shader_component(str(entity_id),root,comp)

    def _shader_set_input(self, entity_id: str, name: str, value) -> bool:
        root=self.nodes.get(str(entity_id)); raw=self.entity_data.get(str(entity_id))
        if not root or not raw: return False
        comp=(raw.setdefault('components',{})).get('shader')
        if not comp: return False
        comp.setdefault('inputs',{})[str(name)]=copy.deepcopy(value)
        resolved=self._shader_input_value(value)
        try:
            if resolved is None:return False
            root.setShaderInput(str(name),resolved,int(comp.get('input_priority',0) or 0)); return True
        except Exception:return False

    def _shader_clear_input(self, entity_id: str, name: str) -> bool:
        root=self.nodes.get(str(entity_id)); raw=self.entity_data.get(str(entity_id))
        if not root:return False
        try: root.clearShaderInput(str(name))
        except Exception:return False
        if raw:
            comp=(raw.get('components') or {}).get('shader') or {}; (comp.get('inputs') or {}).pop(str(name),None)
        return True

    def _shader_clear_entity(self, entity_id: str) -> bool:
        root=self.nodes.get(str(entity_id))
        if not root:return False
        try: root.clearShader(); root.clearShaderInputs(); return True
        except Exception:return False

    def _apply_material_component(self, root: NodePath, comp: dict) -> None:
        """Apply authoring material overrides to an entity visual subtree."""
        assert self.base
        visuals = []
        if root.hasTag('editor_geometry_source'):
            visuals.append(root)
        visuals.extend(root.findAllMatches('**/=editor_geometry_source=1'))
        if not visuals:
            visuals = [root]
        base = list(comp.get('base_color', [1.0, 1.0, 1.0, 1.0])) + [1,1,1,1]
        emission = list(comp.get('emission', [0.0, 0.0, 0.0])) + [0,0,0]
        specular = list(comp.get('specular', [0.15, 0.15, 0.15])) + [0,0,0]
        shininess = max(0.0, float(comp.get('shininess', 16.0)))
        alpha = max(0.0, min(1.0, float(comp.get('alpha', base[3] if len(base)>3 else 1.0))))
        mat = Material()
        mat.setDiffuse(Vec4(float(base[0]), float(base[1]), float(base[2]), alpha))
        mat.setAmbient(Vec4(float(base[0])*0.45, float(base[1])*0.45, float(base[2])*0.45, alpha))
        mat.setEmission(Vec4(float(emission[0]), float(emission[1]), float(emission[2]), 1.0))
        mat.setSpecular(Vec4(float(specular[0]), float(specular[1]), float(specular[2]), 1.0))
        mat.setShininess(shininess)
        # Panda's material object carries PBR values used by glTF-aware/PBR pipelines.
        # Guard these calls so the built-in 1.10 material path remains compatible.
        try:
            if hasattr(mat, 'setBaseColor'): mat.setBaseColor(Vec4(float(base[0]), float(base[1]), float(base[2]), alpha))
            if hasattr(mat, 'setMetallic'): mat.setMetallic(max(0.0, min(1.0, float(comp.get('metallic', 0.0)))))
            if hasattr(mat, 'setRoughness'): mat.setRoughness(max(0.0, min(1.0, float(comp.get('roughness', 0.5)))))
        except Exception:
            pass
        def load_material_texture(key: str):
            rel = str(comp.get(key) or '').strip()
            if not rel:
                return None
            try:
                path = (PROJECT_ROOT / rel).resolve() if not Path(rel).is_absolute() else Path(rel)
                tex = self.base.loader.loadTexture(self._panda_filename(path))
                if not tex: self.log(f'Material: texture failed to load: {rel}')
                return tex
            except Exception as exc:
                self.log(f'Material: texture failed to load {rel}: {exc}')
                return None
        texture = load_material_texture('base_texture')
        normal_texture = load_material_texture('normal_texture')
        emission_texture = load_material_texture('emission_texture')
        metal_rough_texture = load_material_texture('metal_rough_texture')
        uv_scale = list(comp.get('uv_scale') or [1.0,1.0]) + [1.0,1.0]
        uv_offset = list(comp.get('uv_offset') or [0.0,0.0]) + [0.0,0.0]
        uv_rotation = float(comp.get('uv_rotation', 0.0) or 0.0)
        wrap_u = str(comp.get('wrap_u','repeat') or 'repeat').lower()
        wrap_v = str(comp.get('wrap_v','repeat') or 'repeat').lower()
        min_filter = str(comp.get('min_filter','trilinear') or 'trilinear').lower()
        mag_filter = str(comp.get('mag_filter','linear') or 'linear').lower()
        anisotropic = max(1, int(comp.get('anisotropic_degree',1) or 1))
        def configure_texture(tex):
            if not tex: return
            wraps={'repeat':('WM_repeat','WMRepeat'),'clamp':('WM_clamp','WMClamp'),'mirror':('WM_mirror','WMMirror'),'border':('WM_border_color','WMBorderColor')}
            mins={'nearest':('FT_nearest','FTNearest'),'linear':('FT_linear','FTLinear'),'trilinear':('FT_linear_mipmap_linear','FTLinearMipmapLinear')}
            mags={'nearest':('FT_nearest','FTNearest'),'linear':('FT_linear','FTLinear')}
            def enum_value(names):
                for name in names:
                    value=getattr(Texture,name,None)
                    if value is not None: return value
                return None
            try:
                wu=enum_value(wraps.get(wrap_u,wraps['repeat'])); wv=enum_value(wraps.get(wrap_v,wraps['repeat']))
                if wu is not None: tex.setWrapU(wu)
                if wv is not None: tex.setWrapV(wv)
                mf=enum_value(mins.get(min_filter,mins['trilinear'])); gf=enum_value(mags.get(mag_filter,mags['linear']))
                if mf is not None: tex.setMinfilter(mf)
                if gf is not None: tex.setMagfilter(gf)
                if hasattr(tex,'setAnisotropicDegree'): tex.setAnisotropicDegree(anisotropic)
            except Exception:
                pass
        for _tex in (texture, normal_texture, emission_texture, metal_rough_texture): configure_texture(_tex)
        for visual in visuals:
            try:
                visual.setMaterial(mat, 1)
                # Base colour belongs to Panda's Material / PBR material state.
                # Applying the same RGB again as ColorScale double-tints textured
                # materials and can make lighting appear flat/dark. Keep ColorScale
                # neutral so Built-in, simplepbr and complexpbr see the same material.
                visual.setColorScale(1.0, 1.0, 1.0, 1.0)
                # Use Panda semantic TextureStage modes. simplepbr consumes these same semantics:
                # Modulate=BaseColor, Selector=MetalRoughness, Normal=Normals, Emission=Emission.
                def apply_stage(stage, tex, mode):
                    stage.setMode(mode); visual.setTexture(stage, tex, 20)
                    try:
                        visual.setTexScale(stage, float(uv_scale[0]), float(uv_scale[1]))
                        visual.setTexOffset(stage, float(uv_offset[0]), float(uv_offset[1]))
                        visual.setTexRotate(stage, float(uv_rotation))
                    except Exception:
                        pass
                if texture:
                    apply_stage(TextureStage('BaseColor'), texture, TextureStage.MModulate)
                if metal_rough_texture:
                    apply_stage(TextureStage('MetalRoughness'), metal_rough_texture, TextureStage.MSelector)
                if normal_texture:
                    apply_stage(TextureStage('Normals'), normal_texture, TextureStage.MNormal)
                if emission_texture:
                    apply_stage(TextureStage('Emission'), emission_texture, TextureStage.MEmission)
                if bool(comp.get('two_sided', False)):
                    visual.setTwoSided(True)
                else:
                    visual.setTwoSided(False)
                if alpha < 0.999 or bool(comp.get('transparent', False)):
                    visual.setTransparency(TransparencyAttrib.MAlpha)
                else:
                    visual.clearTransparency()
                # Shader policy is explicit now. 'inherit' is the normal/default
                # path: the object inherits Panda Built-in auto-shader state or the
                # selected PBR pipeline from render. Legacy shader_auto is still read
                # for old scenes, but no longer ambiguously toggles PBR on/off.
                policy = str(comp.get('shader_policy') or ('inherit' if bool(comp.get('shader_auto', True)) else 'off')).lower()
                if bool(comp.get('unlit', False)):
                    visual.setLightOff(20)
                    visual.setShaderOff(20)
                else:
                    visual.clearLight()
                    if policy == 'panda_auto':
                        visual.setShaderAuto(10)
                    elif policy == 'off':
                        visual.setShaderOff(10)
                    else:
                        visual.clearShader()
            except Exception as exc:
                self.log(f'Material apply failed on {root.getName()}: {exc}')

    def _ui_reference_metrics(self) -> tuple[float, float, float, float]:
        """Return reference width/height, reference aspect and contain scale.

        UI is authored in the project's game-window pixel space (1280x720 by default),
        not in the temporary editor viewport size.  The reference canvas is fitted inside
        the real aspect2d area using a contain scale.  A wide editor viewport therefore
        gets harmless side margins instead of stretching/re-anchoring the HUD.
        """
        rw = max(1.0, float(self.project_settings.get('game_window_width', 1280) or 1280))
        rh = max(1.0, float(self.project_settings.get('game_window_height', 720) or 720))
        ref_aspect = max(0.1, rw / rh)
        actual_aspect = max(0.1, float(self.base.getAspectRatio())) if self.base else ref_aspect
        contain = min(1.0, actual_aspect / ref_aspect)
        return rw, rh, ref_aspect, max(0.01, contain)

    def _ensure_ui_root(self) -> NodePath | None:
        if not self.base:
            return None
        if self.ui_root is None or self.ui_root.isEmpty():
            self.ui_root = self.base.aspect2d.attachNewNode('uiReferenceRoot')
        _rw, _rh, _ra, scale = self._ui_reference_metrics()
        self.ui_root.setScale(scale, 1.0, scale)
        return self.ui_root

    def _refresh_ui_reference_layout(self, rebuild: bool = False) -> None:
        root = self._ensure_ui_root()
        if root is None:
            return
        if rebuild:
            for eid, raw in list(self.entity_data.items()):
                ui = (raw.get('components') or {}).get('ui') or {}
                if ui:
                    self._build_ui_component(eid, str(raw.get('name', eid)), ui)

    def _ui_anchor_pos(self, anchor: str, offset, half_w: float = 0.0, half_h: float = 0.0) -> tuple[float, float, float]:
        """Convert reference-resolution pixels into stable aspect2d coordinates.

        Anchors are resolved against the authored game-window aspect, so the HUD designer,
        embedded Play Mode and standalone/exported windows share one canonical layout.
        """
        _rw, rh, ref_aspect, _scale = self._ui_reference_metrics()
        anchors = {
            'center': (0.0, 0.0), 'top': (0.0, 1.0-half_h), 'bottom': (0.0, -1.0+half_h),
            'left': (-ref_aspect+half_w, 0.0), 'right': (ref_aspect-half_w, 0.0),
            'top_left': (-ref_aspect+half_w, 1.0-half_h), 'top_right': (ref_aspect-half_w, 1.0-half_h),
            'bottom_left': (-ref_aspect+half_w, -1.0+half_h), 'bottom_right': (ref_aspect-half_w, -1.0+half_h),
        }
        x, z = anchors.get(str(anchor or 'center'), (0.0, 0.0))
        vals = list(offset or [0, 0]) + [0, 0]
        # aspect2d has a vertical span of 2 units; reference pixels are therefore
        # converted using reference height for both axes.
        x += (2.0 * float(vals[0])) / rh
        z -= (2.0 * float(vals[1])) / rh
        return (x, 0.0, z)

    def _ui_half_size(self, size) -> tuple[float, float]:
        _rw, rh, _ref_aspect, _scale = self._ui_reference_metrics()
        vals = list(size or [240, 80]) + [240, 80]
        return (float(vals[0]) / rh, float(vals[1]) / rh)

    @staticmethod
    def _rgba(value, default=(1,1,1,1)):
        vals = list(value or default) + list(default)
        return tuple(max(0.0, min(1.0, float(vals[i]))) for i in range(4))

    def _terrain_path(self, raw: object) -> Path | None:
        text = str(raw or '').strip()
        if not text:
            return None
        p = Path(text)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        try:
            return p.resolve()
        except Exception:
            return p

    def _destroy_terrain(self, entity_id: str) -> None:
        self._terrain_paint_live.pop(str(entity_id), None)
        state = self.terrains.pop(str(entity_id), None)
        if not state:
            return
        np = state.get('root')
        if np is not None:
            try: np.removeNode()
            except Exception: pass

    def _load_live_texture(self, path: Path, *, refresh: bool = False):
        """Load an authoring texture, optionally bypassing Panda's filename texture cache.

        Splat maps are edited in-place while the editor is running. TexturePool intentionally
        returns the previously loaded texture for the same filename, so a normal loadTexture()
        call makes a successful paint stroke appear to do nothing.  A directly-read Texture
        gives authoring data a fresh GPU image without flushing unrelated project textures.
        """
        if not refresh:
            return self.base.loader.loadTexture(self._panda_filename(path))
        tex = Texture(path.stem + '-live')
        if not tex.read(Filename.fromOsSpecific(str(path))):
            raise RuntimeError(f'could not read texture: {path}')
        return tex

    def _terrain_layer_sample(self, image: PNMImage, u: float, v: float) -> tuple[float, float, float, float]:
        """Nearest wrapped sampling used by the editor's deterministic terrain paint compositor."""
        w=max(1,int(image.getXSize())); h=max(1,int(image.getYSize()))
        # u/v are allowed to tile beyond 0..1.  PNM rows are top-to-bottom, so v is
        # converted explicitly instead of depending on backend texture orientation.
        uu=float(u)-math.floor(float(u)); vv=float(v)-math.floor(float(v))
        x=max(0,min(w-1,int(uu*w)))
        y=max(0,min(h-1,int((1.0-vv)*h)))
        try:
            c=image.getXelA(x,y); return float(c[0]),float(c[1]),float(c[2]),float(c[3])
        except Exception:
            c=image.getXel(x,y); return float(c[0]),float(c[1]),float(c[2]),1.0

    def _terrain_recompose_region(self, live: dict, xmin: int=0, ymin: int=0, xmax: int|None=None, ymax: int|None=None) -> None:
        """Rebuild only the changed part of the CPU-composited painted terrain albedo."""
        splat=live.get('image'); baked=live.get('baked_image'); layers=live.get('layer_images') or []
        if splat is None or baked is None or len(layers)<4: return
        w=max(1,int(splat.getXSize())); h=max(1,int(splat.getYSize()))
        xmax=w-1 if xmax is None else max(0,min(w-1,int(xmax))); ymax=h-1 if ymax is None else max(0,min(h-1,int(ymax)))
        xmin=max(0,min(w-1,int(xmin))); ymin=max(0,min(h-1,int(ymin)))
        scale=max(.1,float(live.get('texture_scale',8.0)))
        tints=live.get('tints') or [(1,1,1,1)]*4
        for y in range(ymin,ymax+1):
            # This mirrors the authoring PNG row into Terrain-local V, matching the
            # sculpt/paint brush conversion already verified in 0.4.5.
            terrain_v=1.0-(y/max(1,h-1))
            for x in range(xmin,xmax+1):
                terrain_u=x/max(1,w-1)
                sw=splat.getXelA(x,y); weights=[max(0.0,float(sw[i])) for i in range(4)]
                total=sum(weights)
                if total<=1e-8: weights=[1.0,0.0,0.0,0.0]
                else: weights=[q/total for q in weights]
                rgb=[0.0,0.0,0.0]
                for i in range(4):
                    c=self._terrain_layer_sample(layers[i],terrain_u*scale,terrain_v*scale)
                    tint=tints[i]
                    rgb[0]+=c[0]*float(tint[0])*weights[i]; rgb[1]+=c[1]*float(tint[1])*weights[i]; rgb[2]+=c[2]*float(tint[2])*weights[i]
                baked.setXelA(x,y,max(0,min(1,rgb[0])),max(0,min(1,rgb[1])),max(0,min(1,rgb[2])),1.0)

    def _apply_terrain_material_paint(self, entity_id: str, terrain_np: NodePath, comp: dict, name: str, width: int, height: int) -> bool:
        """Apply editable four-layer terrain painting without a fragile custom terrain shader.

        The RGBA splat map remains the authored source of truth.  For the editor/runtime
        baseline we composite the four tiled layer albedos into one live Panda Texture.
        This uses the same texture path already proven to render correctly on GeoMipTerrain,
        and means a paint stroke only updates splat weights + the changed composite region.
        A later PBR terrain shader can consume the same splat/layer source data directly.
        """
        mp=comp.get('material_paint') or {}
        if not mp.get('enabled',False): return False
        splat_path=self._terrain_path(mp.get('splatmap')); layers=list(mp.get('layers') or [])[:4]
        if not splat_path or not splat_path.exists() or not layers:
            self.log(f'Terrain [{name}]: material paint enabled but splat map/layers are incomplete.'); return False
        while len(layers)<4: layers.append(copy.deepcopy(layers[-1]))
        try:
            splat=PNMImage()
            if not splat.read(Filename.fromOsSpecific(str(splat_path))): raise RuntimeError('could not read splat map')
            layer_images=[]; tints=[]
            for i,layer in enumerate(layers):
                path=self._terrain_path(layer.get('albedo'))
                if not path or not path.exists(): path=self._terrain_path('assets/textures/material_checker.png')
                img=PNMImage()
                if not path or not img.read(Filename.fromOsSpecific(str(path))): raise RuntimeError(f'could not read terrain layer {i+1}')
                layer_images.append(img)
                tint=list(layer.get('tint') or [1,1,1,1])+[1,1,1,1]; tints.append(tuple(float(v) for v in tint[:4]))
            sw,sh=max(1,int(splat.getXSize())),max(1,int(splat.getYSize()))
            baked=PNMImage(sw,sh,4)
            baked_rel=str(mp.get('baked_albedo') or '').strip()
            if baked_rel:
                baked_path=self._terrain_path(baked_rel)
            else:
                baked_path=splat_path.with_name(splat_path.stem + '_painted.png')
            live={'image':splat,'baked_image':baked,'layer_images':layer_images,'tints':tints,'texture_scale':max(.1,float(mp.get('texture_scale',8.0))),'path':str(splat_path),'baked_path':str(baked_path),'component':copy.deepcopy(comp),'root':terrain_np}
            self._terrain_recompose_region(live)
            # Keep a real generated albedo asset on disk.  The RGBA splat map is data,
            # not a surface texture; the generated albedo is the visible terrain result.
            try:
                baked_path.parent.mkdir(parents=True,exist_ok=True)
                baked.write(Filename.fromOsSpecific(str(baked_path)))
            except Exception as exc:
                self.log(f'Terrain [{name}]: could not persist painted albedo: {exc}')
            # Reuse the exact ordinary Material path already proven to render correctly
            # on GeoMipTerrain.  Force a neutral base colour so authored layer colours are
            # not multiplied by an unrelated entity Material tint.
            authored_material=copy.deepcopy(((self.entity_data.get(str(entity_id),{}).get('components') or {}).get('material') or {}))
            display_material=authored_material if authored_material else {}
            display_material.update({'base_color':[1.0,1.0,1.0,1.0],'base_texture':str(baked_path),'alpha':1.0})
            display_material.setdefault('metallic',0.0); display_material.setdefault('roughness',0.9)
            display_material.setdefault('shader_auto',True); display_material.setdefault('two_sided',False); display_material.setdefault('unlit',False)
            terrain_np.clearTexture()
            self._apply_material_component(terrain_np,display_material)
            # Keep the Material state from the standard path, but replace its file-backed
            # texture stage with exactly one mutable live BaseColor stage.  Leaving both
            # stages active would multiply the painted texture by itself.
            terrain_np.clearTexture()
            tex=Texture('terrain-painted-live-'+str(entity_id)); tex.load(baked)
            try: tex.setMinfilter(Texture.FT_linear_mipmap_linear); tex.setMagfilter(Texture.FT_linear)
            except Exception: pass
            stage=TextureStage('BaseColor'); stage.setMode(TextureStage.MModulate)
            terrain_np.setTexture(stage,tex,50)
            live['texture']=tex; live['stage']=stage; self._terrain_paint_live[str(entity_id)]=live
            self.log(f'Terrain [{name}]: 4-layer material paint active ({splat_path.name} -> {baked_path.name}).')
            return True
        except Exception as exc:
            self.log(f'Terrain [{name}]: material paint failed: {exc}'); return False

    def _build_terrain_component(self, entity_id: str, root: NodePath, name: str, comp: dict) -> None:
        self._destroy_terrain(entity_id)
        if comp.get('enabled', True) is False:
            return
        path = self._terrain_path(comp.get('heightfield'))
        if not path or not path.exists():
            self.log(f'Terrain [{name}]: heightfield not found: {comp.get("heightfield", "")}')
            return
        try:
            image = PNMImage()
            if not image.read(Filename.fromOsSpecific(str(path))):
                raise RuntimeError('PNMImage could not read heightfield')
            width, height = int(image.getXSize()), int(image.getYSize())
            if width < 2 or height < 2:
                raise RuntimeError('heightfield must be at least 2x2 pixels')
            terrain = GeoMipTerrain('terrain-' + str(entity_id))
            terrain.setHeightfield(image)
            try: terrain.setBlockSize(max(2, int(comp.get('block_size', 32))))
            except Exception: pass
            sxsy = list(comp.get('size', [64.0,64.0])) + [64.0,64.0]
            cell_x = max(0.001, float(sxsy[0])) / max(1, width - 1)
            cell_y = max(0.001, float(sxsy[1])) / max(1, height - 1)
            lod_world_to_terrain = 1.0 / max(0.001, (cell_x + cell_y) * 0.5)
            try: terrain.setNear(max(0.0, float(comp.get('near', 24.0))) * lod_world_to_terrain)
            except Exception: pass
            try: terrain.setFar(max(0.01, float(comp.get('far', 120.0))) * lod_world_to_terrain)
            except Exception: pass
            try: terrain.setMinLevel(max(0, int(comp.get('min_level', 0))))
            except Exception: pass
            try: terrain.setBruteforce(bool(comp.get('bruteforce', False)))
            except Exception: pass
            try: terrain.setBorderStitching(bool(comp.get('border_stitching', True)))
            except Exception: pass
            try:
                mode = str(comp.get('auto_flatten', 'off')).lower()
                mapping = {'off':0, 'none':0, 'light':1, 'medium':2, 'strong':3}
                terrain.setAutoFlatten(mapping.get(mode, 0))
            except Exception: pass
            terrain.generate()
            terrain_np = terrain.getRoot()
            terrain_np.reparentTo(root)
            terrain_np.setName(name + '-terrain')
            terrain_np.setTag('editor_geometry_source', '1')
            sx = cell_x
            sy = cell_y
            sz = max(0.0, float(comp.get('height_scale', 12.0)))
            terrain_np.setScale(sx, sy, sz)
            if comp.get('visible', True) is False:
                terrain_np.hide()
            try:
                terrain.setFocalPoint(self.base.camera)
            except Exception:
                pass
            self._apply_visual_render_mode(terrain_np)
            terrain_material_applied = self._apply_terrain_material_paint(str(entity_id), terrain_np, comp, name, width, height)
            material_comp = ((self.entity_data.get(str(entity_id), {}).get('components') or {}).get('material') or {})
            if material_comp and not terrain_material_applied:
                self._apply_material_component(terrain_np, material_comp)
            self.terrains[str(entity_id)] = {
                'terrain': terrain, 'root': terrain_np, 'image': image,
                'component': copy.deepcopy(comp), 'width': width, 'height': height,
            }
            self.log(f'Terrain [{name}]: generated {width}x{height} heightfield, world size {float(sxsy[0]):g} x {float(sxsy[1]):g}.')
        except Exception as exc:
            self.log(f'Terrain [{name}]: failed to generate: {exc}')

    def _update_entity_lod(self) -> None:
        """Cull entities carrying the lightweight LOD component by camera distance."""
        if not self.base:
            return
        cam = self.base.camera.getPos(self.base.render)
        for eid, raw in self.entity_data.items():
            lod = ((raw.get('components') or {}).get('lod') or {})
            if not lod or lod.get('enabled', True) is False:
                continue
            root = self.nodes.get(str(eid))
            if not root:
                continue
            dist = (root.getPos(self.base.render) - cam).length()
            near = max(0.0, float(lod.get('near', 0.0)))
            far = max(near, float(lod.get('far', 250.0)))
            if raw.get('visible', True) is not False and near <= dist <= far:
                root.show()
            else:
                root.hide()

    def _update_terrains(self) -> None:
        for state in list(self.terrains.values()):
            terrain = state.get('terrain')
            if terrain is not None:
                try: terrain.update()
                except Exception: pass

    def _terrain_regenerate(self, entity_id: str) -> bool:
        eid = str(entity_id)
        root = self.nodes.get(eid)
        raw = self.entity_data.get(eid, {})
        comp = (raw.get('components') or {}).get('terrain') or {}
        if not root or not comp:
            return False
        self._build_terrain_component(eid, root, str(raw.get('name', eid)), comp)
        return eid in self.terrains

    def _terrain_configure(self, entity_id: str, settings: dict) -> bool:
        eid = str(entity_id)
        raw = self.entity_data.get(eid)
        if not raw:
            return False
        comps = raw.get('components') or {}
        comp = comps.get('terrain')
        if not isinstance(comp, dict):
            return False
        allowed = {'enabled','heightfield','size','height_scale','block_size','near','far','min_level','bruteforce','auto_flatten','border_stitching','collision_enabled','visible','material_paint'}
        changed = False
        for key, value in (settings or {}).items():
            key = str(key)
            if key not in allowed:
                continue
            if key == 'size':
                vals = list(value)[:2]; value = [max(.001,float(vals[0])), max(.001,float(vals[1]))]
            elif key in {'height_scale','near','far'}: value = float(value)
            elif key in {'block_size','min_level'}: value = int(value)
            elif key in {'enabled','bruteforce','border_stitching','collision_enabled','visible','material_paint'}: value = bool(value)
            else: value = str(value)
            comp[key] = copy.deepcopy(value); changed = True
        if not changed:
            return False
        # Runtime configuration is intentionally isolated to the Play copy of entity_data.
        ok = self._terrain_regenerate(eid)
        if self.play_mode and self.physics_world is not None and 'collision_enabled' in settings:
            # Physics is rebuilt only when explicitly toggling collision; other terrain
            # runtime changes remain visual/query changes to avoid disrupting actors.
            self._build_play_physics()
        return ok

    def _terrain_sample_local(self, entity_id: str, x: float, y: float) -> float | None:
        state = self.terrains.get(str(entity_id))
        if not state:
            return None
        image = state.get('image'); comp = state.get('component') or {}
        if image is None:
            return None
        size = list(comp.get('size', [64.0,64.0])) + [64.0,64.0]
        wx, wy = max(.001,float(size[0])), max(.001,float(size[1]))
        u = max(0.0, min(1.0, float(x) / wx)); v = max(0.0, min(1.0, float(y) / wy))
        width, height = int(state.get('width',2)), int(state.get('height',2))
        px = u * (width - 1); py = v * (height - 1)
        x0,y0=int(math.floor(px)),int(math.floor(py)); x1,y1=min(width-1,x0+1),min(height-1,y0+1)
        tx,ty=px-x0,py-y0
        def g(ix,iy):
            try: return float(image.getGray(ix,iy))
            except Exception: return 0.0
        a=g(x0,y0)*(1-tx)+g(x1,y0)*tx; b=g(x0,y1)*(1-tx)+g(x1,y1)*tx
        return (a*(1-ty)+b*ty) * max(0.0,float(comp.get('height_scale',12.0)))

    def _terrain_height(self, entity_id: str, x: float, y: float, world_space: bool = True) -> float | None:
        eid = str(entity_id); root = self.nodes.get(eid)
        if not root:
            return None
        if world_space:
            try:
                local = root.getRelativePoint(self.base.render, Point3(float(x),float(y),0.0))
                h = self._terrain_sample_local(eid, local.x, local.y)
                if h is None: return None
                wp = self.base.render.getRelativePoint(root, Point3(local.x, local.y, h))
                return float(wp.z)
            except Exception:
                return None
        return self._terrain_sample_local(eid, float(x), float(y))

    def _terrain_normal(self, entity_id: str, x: float, y: float, world_space: bool = True) -> list[float] | None:
        eid=str(entity_id); state=self.terrains.get(eid); root=self.nodes.get(eid)
        if not state or not root: return None
        comp=state.get('component') or {}; size=list(comp.get('size',[64,64]))+[64,64]
        eps=max(.01,min(float(size[0]),float(size[1]))/max(2,int(max(state.get('width',2),state.get('height',2)))-1))
        if world_space:
            try:
                local=root.getRelativePoint(self.base.render,Point3(float(x),float(y),0))
                lx,ly=local.x,local.y
            except Exception: return None
        else: lx,ly=float(x),float(y)
        hl=self._terrain_sample_local(eid,lx-eps,ly); hr=self._terrain_sample_local(eid,lx+eps,ly)
        hd=self._terrain_sample_local(eid,lx,ly-eps); hu=self._terrain_sample_local(eid,lx,ly+eps)
        if None in {hl,hr,hd,hu}: return None
        n=Vec3(-(hr-hl)/(2*eps),-(hu-hd)/(2*eps),1.0); n.normalize()
        if world_space:
            try:
                n=self.base.render.getRelativeVector(root,n); n.normalize()
            except Exception: pass
        return [float(n.x),float(n.y),float(n.z)]

    def _build_particle_emitter(self, entity_id: str, root: NodePath, name: str, comp: dict) -> None:
        self._destroy_particle_emitter(entity_id)
        state = {'component': copy.deepcopy(comp), 'particles': [], 'accumulator': 0.0, 'elapsed':0.0, 'finished_sent':False, 'running': bool((not self.play_mode) and self.particle_preview_entity == entity_id), 'root': root}
        self.particle_emitters[entity_id] = state
        # Authoring helper: emission origin and forward/up direction.
        if not self.play_mode:
            segs = LineSegs(name + '-particle-helper'); segs.setThickness(2.0); segs.setColor(1.0,0.45,0.10,1.0)
            segs.moveTo(-.18,0,0); segs.drawTo(.18,0,0); segs.moveTo(0,-.18,0); segs.drawTo(0,.18,0)
            segs.moveTo(0,0,-.18); segs.drawTo(0,0,.42)
            helper = root.attachNewNode(segs.create()); self._isolate_editor_helper(helper); helper.setName(name+'-particle-helper'); helper.setDepthTest(False); helper.setBin('fixed',24)

    def _destroy_particle_emitter(self, entity_id: str) -> None:
        state = self.particle_emitters.pop(entity_id, None)
        if not state: return
        for item in list(state.get('particles') or []):
            try: item['node'].removeNode()
            except Exception: pass

    def _start_play_particles(self) -> None:
        for eid, state in self.particle_emitters.items():
            comp = state.get('component') or {}
            state['running'] = bool(comp.get('enabled', True) and comp.get('autoplay', True))
            state['accumulator'] = 0.0

    def _stop_all_particles(self, clear: bool = False) -> None:
        for eid in list(self.particle_emitters):
            self._particle_set_running(eid, False)
            if clear: self._particle_clear(eid)

    def _particle_set_running(self, entity_id: str, running: bool) -> bool:
        state = self.particle_emitters.get(entity_id)
        if not state: return False
        state['running'] = bool(running); state['elapsed']=0.0; state['finished_sent']=False; return True

    def _particle_clear(self, entity_id: str) -> None:
        state = self.particle_emitters.get(entity_id)
        if not state: return
        for item in list(state.get('particles') or []):
            try: item['node'].removeNode()
            except Exception: pass
        state['particles'] = []

    def _particle_spawn_one(self, entity_id: str) -> bool:
        """Spawn one authored particle using the editor's Factory / Emitter / Renderer contract."""
        if not self.base:
            return False
        state = self.particle_emitters.get(entity_id)
        root = (state or {}).get('root') or self.nodes.get(entity_id)
        if not state or not root:
            return False
        comp = state.get('component') or {}
        particles = state.setdefault('particles', [])
        if len(particles) >= max(1, int(comp.get('max_particles', 256) or 256)):
            return False

        local_space = bool(comp.get('local_space', True))
        parent = root if local_space else self.base.render
        renderer = str(comp.get('renderer_type', 'sprite') or 'sprite').lower()
        node = None

        # Renderer: sprite/card, point-card, line, sparkle-cross, or reusable geometry.
        if renderer == 'geom':
            model = str(comp.get('renderer_model') or '').strip()
            if model:
                try:
                    path = (PROJECT_ROOT/model).resolve() if not Path(model).is_absolute() else Path(model)
                    loaded = self.base.loader.loadModel(self._panda_filename(path))
                    if loaded and not loaded.isEmpty():
                        node = parent.attachNewNode(f'particle-{entity_id[:6]}-geom')
                        loaded.instanceTo(node)
                except Exception:
                    node = None
        elif renderer in {'line', 'sparkle'}:
            segs = LineSegs(f'particle-{entity_id[:6]}-{renderer}')
            segs.setThickness(max(.5, float(comp.get('line_thickness', 2.0) or 2.0)))
            if renderer == 'line':
                ll = max(.01, float(comp.get('line_length', .35) or .35))
                segs.moveTo(0,0,0); segs.drawTo(0,0,-ll)
            else:
                ss = max(.01, float(comp.get('sparkle_scale', 1.0) or 1.0)) * .15
                for a,b in [((-ss,0,0),(ss,0,0)),((0,-ss,0),(0,ss,0)),((0,0,-ss),(0,0,ss))]:
                    segs.moveTo(*a); segs.drawTo(*b)
            node = parent.attachNewNode(segs.create())
        else:
            cm = CardMaker(f'particle-{entity_id[:6]}')
            cm.setFrame(-.5,.5,-.5,.5); cm.setHasNormals(False)
            node = parent.attachNewNode(cm.generate())
            node.setBillboardPointEye(); node.setTwoSided(True)

        if node is None:
            return False
        node.setTransparency(TransparencyAttrib.MAlpha)
        if str(comp.get('blend_mode','alpha')).lower() == 'additive':
            try: node.setAttrib(ColorBlendAttrib.make(ColorBlendAttrib.MAdd, ColorBlendAttrib.OIncomingAlpha, ColorBlendAttrib.OOne))
            except Exception: pass

        # Emitter position. Shapes mirror the useful Panda3D emitter families while
        # preserving legacy sphere/cone names for old scenes.
        shape = str(comp.get('shape','point') or 'point').lower()
        radius = max(0.0, float(comp.get('radius', .25) or .25))
        inner = max(0.0, min(radius, float(comp.get('inner_radius', 0.0) or 0.0)))
        bs = list(comp.get('box_size',[.5,.5,.5])) + [.5,.5,.5]
        pos = Vec3(0,0,0)
        radial = Vec3(0,0,1)
        if shape in {'sphere','sphere_volume'}:
            radial=Vec3(random.uniform(-1,1),random.uniform(-1,1),random.uniform(-1,1))
            if radial.lengthSquared()<1e-6: radial=Vec3(0,0,1)
            radial.normalize(); pos=radial*(inner+(radius-inner)*(random.random()**(1/3)))
        elif shape == 'sphere_surface':
            radial=Vec3(random.uniform(-1,1),random.uniform(-1,1),random.uniform(-1,1))
            if radial.lengthSquared()<1e-6: radial=Vec3(0,0,1)
            radial.normalize(); pos=radial*radius
        elif shape in {'box','rectangle'}:
            z = random.uniform(-abs(float(bs[2]))*.5, abs(float(bs[2]))*.5) if shape=='box' else 0.0
            pos=Vec3(random.uniform(-abs(float(bs[0]))*.5,abs(float(bs[0]))*.5), random.uniform(-abs(float(bs[1]))*.5,abs(float(bs[1]))*.5), z)
        elif shape in {'disc','ring','tangent_ring'}:
            angle=math.radians(random.uniform(0.0,max(0.1,float(comp.get('emission_angle',360.0) or 360.0))))
            rr = radius if shape in {'ring','tangent_ring'} else math.sqrt(random.random())*radius
            rr = max(inner, rr); pos=Vec3(math.cos(angle)*rr, math.sin(angle)*rr, 0)
            radial=Vec3(math.cos(angle),math.sin(angle),0)
        elif shape == 'cone':
            a=random.uniform(0,math.tau); rr=math.sqrt(random.random())*radius; pos=Vec3(math.cos(a)*rr,math.sin(a)*rr,0)

        if local_space:
            node.setPos(pos)
        else:
            try: node.setPos(self.base.render, root.getPos(self.base.render) + root.getQuat(self.base.render).xform(pos))
            except Exception: node.setPos(pos)

        tex=str(comp.get('texture') or '').strip()
        if tex and renderer in {'sprite','point'}:
            try:
                path=(PROJECT_ROOT/tex).resolve() if not Path(tex).is_absolute() else Path(tex)
                t=self.base.loader.loadTexture(self._panda_filename(path))
                if t: node.setTexture(t,1)
            except Exception: pass

        speed=max(0.0,float(comp.get('speed',2.5) or 0.0)); sv=max(0.0,float(comp.get('speed_variation',0.0) or 0.0)); speed=max(0.0,speed+random.uniform(-sv,sv))
        spread=math.radians(max(0.0,min(180.0,float(comp.get('spread',35.0) or 0.0))))
        mode=str(comp.get('velocity_mode','outward') or 'outward').lower()
        if mode=='outward' and shape in {'sphere','sphere_volume','sphere_surface','disc','ring','tangent_ring'}:
            direction=Vec3(radial)
            if shape=='tangent_ring': direction=Vec3(-radial.y, radial.x, 0)
            if direction.lengthSquared()<1e-6: direction=Vec3(0,0,1)
            direction.normalize()
            if spread>0:
                direction += Vec3(random.uniform(-1,1),random.uniform(-1,1),random.uniform(-1,1))*math.sin(spread)*.5
                if direction.lengthSquared()>1e-6: direction.normalize()
        else:
            theta=random.uniform(0,spread); phi=random.uniform(0,math.tau)
            direction=Vec3(math.sin(theta)*math.cos(phi), math.sin(theta)*math.sin(phi), math.cos(theta))
        if not local_space:
            try: direction=root.getQuat(self.base.render).xform(direction)
            except Exception: pass
        vel=direction*speed

        life=max(.02,float(comp.get('lifetime',1.4) or 1.4)); lv=max(0.0,float(comp.get('lifetime_variation',0.0) or 0.0)); life=max(.02,life+random.uniform(-lv,lv))
        start=float(comp.get('point_size' if renderer=='point' else 'size_start', .08 if renderer=='point' else .16) or .01)
        end=float(comp.get('size_end',start) or start)
        c0=self._rgba(comp.get('color_start'),(1,.55,.12,1)); c1=self._rgba(comp.get('color_end'),(.2,.05,.02,0))
        node.setScale(start); node.setColor(*c0)
        factory=str(comp.get('factory_type','point') or 'point').lower()
        initial=float(comp.get('rotation_start',0.0) or 0.0)
        spin=float(comp.get('rotation_speed',0.0) or 0.0) if factory=='zspin' else 0.0
        node.setR(initial)
        mass=max(.001,float(comp.get('mass',1.0) or 1.0)+random.uniform(-max(0.0,float(comp.get('mass_variation',0.0) or 0.0)),max(0.0,float(comp.get('mass_variation',0.0) or 0.0))))
        particles.append({'node':node,'age':0.0,'life':life,'vel':vel,'start':start,'end':end,'c0':c0,'c1':c1,'spin':spin,'mass':mass,'renderer':renderer})
        return True

    def _particle_configure(self, entity_id: str, settings: dict) -> bool:
        state = self.particle_emitters.get(str(entity_id))
        if not state:
            return False
        comp = state.get('component') or {}
        allowed = {'enabled','autoplay','loop','rate','burst_count','lifetime','speed','spread','gravity','shape','radius','inner_radius','box_size','size_start','size_end','color_start','color_end','texture','max_particles','speed_variation','lifetime_variation','drag','duration','local_space','rotation_start','rotation_speed','blend_mode','emit_signal_finished','factory_type','mass','mass_variation','terminal_velocity','renderer_type','renderer_model','line_length','line_thickness','sparkle_scale','point_size','emission_angle','velocity_mode'}
        clear_existing = False
        for key, value in dict(settings or {}).items():
            if key not in allowed:
                continue
            try:
                if key in {'gravity','box_size'}:
                    vals=list(value)[:3]; value=[float(vals[i]) if i < len(vals) else 0.0 for i in range(3)]
                elif key in {'color_start','color_end'}:
                    vals=list(value)[:4]; value=[float(vals[i]) if i < len(vals) else (1.0 if i==3 else 0.0) for i in range(4)]
                elif key in {'rate','lifetime','speed','spread','radius','inner_radius','size_start','size_end','speed_variation','lifetime_variation','drag','duration','rotation_start','rotation_speed','mass','mass_variation','terminal_velocity','line_length','line_thickness','sparkle_scale','point_size','emission_angle'}:
                    value=float(value)
                elif key in {'burst_count','max_particles'}:
                    value=int(value)
                elif key in {'enabled','autoplay','loop','local_space','emit_signal_finished'}:
                    value=bool(value)
                else:
                    value=str(value)
            except Exception:
                continue
            if key in {'texture','blend_mode','local_space','shape','factory_type','renderer_type','renderer_model'} and comp.get(key) != value:
                clear_existing=True
            comp[key]=value
        state['component']=comp
        raw=self.entity_data.get(str(entity_id))
        if raw is not None:
            raw.setdefault('components',{})['particle_emitter']=copy.deepcopy(comp)
        if clear_existing:
            self._particle_clear(str(entity_id))
        return True

    def _particle_burst(self, entity_id: str, count: int | None = None) -> bool:
        state=self.particle_emitters.get(entity_id)
        if not state: return False
        comp=state.get('component') or {}; n=max(1,int(count if count is not None else comp.get('burst_count',24) or 24))
        for _ in range(n): self._particle_spawn_one(entity_id)
        return True

    def _update_particle_emitters(self, dt: float, authoring_preview: bool = False) -> None:
        if self.play_mode and self.play_paused: return
        if not self.play_mode and not authoring_preview: return
        for eid,state in list(self.particle_emitters.items()):
            if authoring_preview and eid != self.particle_preview_entity: continue
            comp=state.get('component') or {}
            if state.get('running') and comp.get('enabled',True):
                state['elapsed']=float(state.get('elapsed',0.0))+dt; duration=max(0.0,float(comp.get('duration',0.0) or 0.0))
                if duration>0 and state['elapsed']>=duration:
                    if bool(comp.get('loop',True)): state['elapsed']=0.0
                    else: state['running']=False
                rate=max(0.0,float(comp.get('rate',18.0) or 0.0)); state['accumulator']=float(state.get('accumulator',0.0))+dt*rate
                while state['accumulator']>=1.0:
                    state['accumulator']-=1.0; self._particle_spawn_one(eid)
            g=list(comp.get('gravity',[0,0,-1.5]))+[0,0,-1.5]; gravity=Vec3(float(g[0]),float(g[1]),float(g[2]))
            alive=[]
            for p in list(state.get('particles') or []):
                p['age']+=dt
                if p['age']>=p['life']:
                    try:p['node'].removeNode()
                    except Exception:pass
                    continue
                p['vel']+=(gravity/max(.001,float(p.get('mass',1.0))))*dt; terminal=max(0.0,float(comp.get('terminal_velocity',0.0) or 0.0));
                if terminal>0 and p['vel'].length()>terminal: p['vel'].normalize(); p['vel']*=terminal
                drag=max(0.0,float(comp.get('drag',0.0) or 0.0));
                if drag>0:p['vel']*=max(0.0,1.0-drag*dt)
                p['node'].setPos(p['node'].getPos()+p['vel']*dt); p['node'].setR(p['node'].getR()+float(p.get('spin',0.0))*dt); t=max(0.0,min(1.0,p['age']/p['life']))
                p['node'].setScale(p['start']+(p['end']-p['start'])*t)
                c=tuple(p['c0'][i]+(p['c1'][i]-p['c0'][i])*t for i in range(4)); p['node'].setColor(*c); alive.append(p)
            state['particles']=alive
            if (not state.get('running')) and (not alive) and bool(comp.get('emit_signal_finished',True)) and not state.get('finished_sent'):
                state['finished_sent']=True
                if self.play_mode:self._emit_entity_signal(eid,'finished',{'particle_entity_id':eid})

    def _ensure_vfx_preview_scene(self, source_id: str | None = None) -> None:
        if not self.base: return
        if self.vfx_preview_root is None or self.vfx_preview_root.isEmpty():
            self.vfx_preview_root = self.base.render.attachNewNode('__vfx_preview_scene__')
            self._isolate_editor_helper(self.vfx_preview_root)
            segs=LineSegs('vfx-preview-grid'); segs.setThickness(1.0); segs.setColor(.20,.30,.38,.65)
            for i in range(-5,6):
                segs.moveTo(i,-5,0); segs.drawTo(i,5,0); segs.moveTo(-5,i,0); segs.drawTo(5,i,0)
            grid=self.vfx_preview_root.attachNewNode(segs.create()); self._isolate_editor_helper(grid); grid.setName('vfx-preview-grid'); grid.setBin('background',0)
            axes=LineSegs('vfx-preview-axes'); axes.setThickness(2.0)
            axes.setColor(1,.25,.25,1); axes.moveTo(0,0,0); axes.drawTo(1,0,0)
            axes.setColor(.25,1,.35,1); axes.moveTo(0,0,0); axes.drawTo(0,1,0)
            axes.setColor(.25,.55,1,1); axes.moveTo(0,0,0); axes.drawTo(0,0,1)
            axes_np=self.vfx_preview_root.attachNewNode(axes.create()); self._isolate_editor_helper(axes_np); axes_np.setName('vfx-preview-axes')
            self.vfx_preview_emitter_root=self.vfx_preview_root.attachNewNode('__vfx_preview_emitter__')
        self._vfx_preview_options(self.vfx_preview_show_grid, self.vfx_preview_show_axes)
        if source_id: self._rebuild_vfx_preview_emitter(source_id)

    def _vfx_preview_options(self, grid: bool = True, axes: bool = True) -> None:
        self.vfx_preview_show_grid=bool(grid); self.vfx_preview_show_axes=bool(axes)
        root=self.vfx_preview_root
        if not root or root.isEmpty(): return
        for name,show in (('vfx-preview-grid',self.vfx_preview_show_grid),('vfx-preview-axes',self.vfx_preview_show_axes)):
            np=root.find('**/'+name)
            if np and not np.isEmpty():
                try: np.show() if show else np.hide()
                except Exception: pass

    def _rebuild_vfx_preview_emitter(self, source_id: str) -> None:
        raw=self.entity_data.get(str(source_id),{}); comp=copy.deepcopy((raw.get('components') or {}).get('particle_emitter') or {})
        if not comp or not self.vfx_preview_emitter_root: return
        preview_id='__vfx_preview__'
        self._destroy_particle_emitter(preview_id)
        try:
            for child in list(self.vfx_preview_emitter_root.getChildren()): child.removeNode()
        except Exception: pass
        self.particle_emitters[preview_id]={'component':comp,'particles':[],'accumulator':0.0,'running':self.vfx_preview_mode,'root':self.vfx_preview_emitter_root}
        helper=LineSegs('vfx-preview-emitter-helper'); helper.setThickness(2.0); helper.setColor(1.0,.48,.10,1)
        helper.moveTo(-.2,0,0); helper.drawTo(.2,0,0); helper.moveTo(0,-.2,0); helper.drawTo(0,.2,0); helper.moveTo(0,0,0); helper.drawTo(0,0,.55)
        helper_np=self.vfx_preview_emitter_root.attachNewNode(helper.create()); self._isolate_editor_helper(helper_np)
        self.particle_preview_entity=preview_id; self.vfx_preview_source=str(source_id); self._particle_preview_last_time=time.perf_counter()

    def _terrain_live_paint(self, entity_id: str, local_x: float, local_y: float, mode: str, radius: float, strength: float, falloff: float, phase: str) -> None:
        """Paint splat weights and refresh only the affected composite-albedo region."""
        eid=str(entity_id); live=self._terrain_paint_live.get(eid); state=self.terrains.get(eid)
        if not live or not state or not str(mode).startswith('paint'): return
        img=live.get('image'); tex=live.get('texture'); baked=live.get('baked_image'); comp=state.get('component') or {}
        if img is None or tex is None or baked is None: return
        try: layer=max(0,min(3,int(str(mode)[5:] or 0)))
        except Exception: layer=0
        try:
            w,h=int(img.getXSize()),int(img.getYSize()); size=list(comp.get('size') or [64,64])+[64,64]; sx=max(.001,float(size[0])); sy=max(.001,float(size[1]))
            cx=max(0.0,min(w-1,(float(local_x)/sx)*(w-1))); cy=max(0.0,min(h-1,(1.0-float(local_y)/sy)*(h-1)))
            rr=max(1.0,float(radius)*.5*((w-1)/sx+(h-1)/sy)); st=max(0.0,min(1.0,float(strength))); fo=max(.05,min(1.0,float(falloff)))
            xmin=max(0,int(math.floor(cx-rr))); xmax=min(w-1,int(math.ceil(cx+rr))); ymin=max(0,int(math.floor(cy-rr))); ymax=min(h-1,int(math.ceil(cy+rr)))
            changed=False
            for y in range(ymin,ymax+1):
                for x in range(xmin,xmax+1):
                    d=math.hypot(x-cx,y-cy)
                    if d>rr: continue
                    wt=(max(0.0,1.0-d/rr)**(1.0/fo))*st*.34
                    c=img.getXelA(x,y); vals=[float(c[0]),float(c[1]),float(c[2]),float(c[3])]
                    old=vals[layer]; vals[layer]+= (1.0-vals[layer])*wt
                    other=sum(vals[i] for i in range(4) if i!=layer); target=max(0.0,1.0-vals[layer])
                    if other>1e-8:
                        factor=target/other
                        for i in range(4):
                            if i!=layer: vals[i]*=factor
                    else:
                        for i in range(4):
                            if i!=layer: vals[i]=target/3.0
                    img.setXelA(x,y,vals[0],vals[1],vals[2],vals[3]); changed=changed or abs(vals[layer]-old)>1e-6
            if changed:
                self._terrain_recompose_region(live,xmin,ymin,xmax,ymax)
                tex.load(baked)
                if str(phase).lower()=='end' and live.get('baked_path'):
                    try: baked.write(Filename.fromOsSpecific(str(live.get('baked_path'))))
                    except Exception as exc: self.log(f'Terrain painted albedo save failed: {exc}')
        except Exception as exc: self.log(f'Terrain live paint failed: {exc}')

    def _destroy_material_preview(self) -> None:
        """Destroy the dedicated render-to-texture material preview."""
        if self.material_preview_display_np:
            try: self.material_preview_display_np.removeNode()
            except Exception: pass
        self.material_preview_display_np = None
        if self.material_preview_scene_root:
            try: self.material_preview_scene_root.removeNode()
            except Exception: pass
        self.material_preview_scene_root = None
        self.material_preview_root = None
        self.material_preview_mesh_np = None
        self.material_preview_camera_np = None
        if self.material_preview_buffer is not None and self.base:
            try: self.base.graphicsEngine.removeWindow(self.material_preview_buffer)
            except Exception: pass
        self.material_preview_buffer = None
        self.material_preview_texture = None

    def _ensure_material_preview_buffer(self) -> bool:
        """Create Panda's hidden RTT buffer with an independent scene graph."""
        if not self.base:
            return False
        if self.material_preview_buffer is not None and self.material_preview_scene_root is not None:
            return True
        try:
            buf = self.base.win.makeTextureBuffer('MaterialPreviewBuffer', 512, 512)
            if not buf:
                self.log('Material preview: could not create offscreen buffer.')
                return False
            buf.setSort(-100)
            try:
                buf.setClearColor(Vec4(.018,.024,.032,1)); buf.setClearColorActive(True)
            except Exception: pass
            tex = buf.getTexture()
            scene = NodePath('__material_preview_scene__')
            cam = self.base.makeCamera(buf)
            cam.reparentTo(scene)
            lens = PerspectiveLens(); lens.setFov(42); lens.setNearFar(.05, 200)
            cam.node().setLens(lens)
            self.material_preview_buffer = buf
            self.material_preview_texture = tex
            self.material_preview_scene_root = scene
            self.material_preview_root = scene.attachNewNode('__material_preview_content__')
            self.material_preview_camera_np = cam
            cm = CardMaker('material-preview-rtt-card'); cm.setFrameFullscreenQuad()
            card = self.base.render2d.attachNewNode(cm.generate())
            card.setTexture(tex, 1); card.setLightOff(1); card.setDepthTest(False); card.setDepthWrite(False); card.setBin('fixed',100)
            try:
                aspect=max(0.001,float(self.rect[2])/max(1.0,float(self.rect[3])))
                card.setScale(1.0/aspect if aspect>1.0 else 1.0,1.0,aspect if aspect<1.0 else 1.0)
            except Exception: pass
            self.material_preview_display_np = card
            return True
        except Exception as exc:
            self.log(f'Material preview offscreen buffer failed: {exc}')
            self._destroy_material_preview()
            return False

    def _build_material_preview(self, component: dict | None = None) -> None:
        """Build only the chosen preview mesh in the dedicated RTT scene."""
        if not self._ensure_material_preview_buffer(): return
        root = self.material_preview_root
        if root is None: return
        try:
            for child in list(root.getChildren()): child.removeNode()
            mesh=str(self.material_preview_mesh or 'sphere').lower()
            if mesh=='plane':
                cm=CardMaker('material-preview-plane'); cm.setFrame(-1.55,1.55,-1.55,1.55); cm.setHasNormals(True)
                visual=root.attachNewNode(cm.generate()); visual.setP(-90); visual.setTwoSided(True)
            else:
                visual=self.base.loader.loadModel('models/box' if mesh=='cube' else 'models/misc/sphere')
                visual.reparentTo(root); visual.setScale(1.25 if mesh=='sphere' else 1.05)
            visual.setTag('editor_geometry_source','1'); self.material_preview_mesh_np=visual
            mat=component
            if mat is None and self.material_preview_entity:
                mat=(((self.entity_data.get(self.material_preview_entity,{}) or {}).get('components') or {}).get('material') or {})
            self._apply_material_component(visual,copy.deepcopy(mat or {}))
            self._apply_material_preview_lighting(); self._position_material_preview_camera()
        except Exception as exc: self.log(f'Material preview build failed: {exc}')

    def _apply_material_preview_lighting(self) -> None:
        root=self.material_preview_root
        if not root:return
        try: root.clearLight()
        except Exception: pass
        for child in list(root.getChildren()):
            try:
                if child.getName().startswith('__mat_preview_'): child.removeNode()
            except Exception: pass
        mode=str(self.material_preview_light or 'studio').lower()
        amb=AmbientLight('__mat_preview_ambient__'); amb.setColor(Vec4(.07,.08,.10,1) if mode=='dark' else Vec4(.25,.27,.30,1)); anp=root.attachNewNode(amb)
        key=DirectionalLight('__mat_preview_key__'); key.setColor(Vec4(.78,.81,.84,1) if mode=='neutral' else Vec4(1.0,.90,.78,1)); knp=root.attachNewNode(key); knp.setHpr(-35,-50,0)
        root.setLight(anp); root.setLight(knp)
        if mode=='studio':
            fill=DirectionalLight('__mat_preview_fill__'); fill.setColor(Vec4(.22,.35,.58,1)); fnp=root.attachNewNode(fill); fnp.setHpr(135,-18,0); root.setLight(fnp)
            rim=DirectionalLight('__mat_preview_rim__'); rim.setColor(Vec4(.20,.42,.54,1)); rnp=root.attachNewNode(rim); rnp.setHpr(205,-5,0); root.setLight(rnp)

    def _position_material_preview_camera(self) -> None:
        cam=self.material_preview_camera_np
        if not cam:return
        h=math.radians(float(self.camera_heading)); p=math.radians(float(self.camera_pitch)); d=max(.5,float(self.camera_distance))
        target=Point3(float(self.camera_target.x),float(self.camera_target.y),float(self.camera_target.z))
        pos=Point3(target.x+math.sin(h)*math.cos(p)*d,target.y-math.cos(h)*math.cos(p)*d,target.z+math.sin(p)*d)
        cam.setPos(pos); cam.lookAt(target)

    def _clear_material_preview_lights(self) -> None:
        return

    def _set_material_preview_scene(self, enabled: bool, entity_id: str | None=None, mesh: str='sphere', light: str='studio') -> None:
        if self.play_mode:return
        self.material_preview_mode=bool(enabled); self.material_preview_entity=str(entity_id or '') or None; self.material_preview_mesh=str(mesh or 'sphere'); self.material_preview_light=str(light or 'studio')
        if enabled:
            if self.vfx_preview_mode:self._set_vfx_preview_scene(False,None)
            self._set_editor_view_context('material')
            try:
                self._material_preview_previous_camera_mask=self.base.cam.node().getCameraMask(); self.base.cam.node().setCameraMask(BitMask32.allOff())
            except Exception: pass
            self.camera_target.set(0,0,0); self.camera_distance=4.6; self.camera_heading=-28; self.camera_pitch=12
            self._build_material_preview()
        else:
            self._destroy_material_preview()
            try:
                if self._material_preview_previous_camera_mask is not None:self.base.cam.node().setCameraMask(self._material_preview_previous_camera_mask)
            except Exception:pass
            self._material_preview_previous_camera_mask=None
            self._sync_entities(copy.deepcopy(self._authoring_entities)); self._apply_world_settings(); self._rebuild_gizmo(); self._apply_editor_camera(); self._set_editor_view_context('level')

    def _update_material_preview(self, entity_id: str | None=None) -> None:
        if entity_id:self.material_preview_entity=str(entity_id)
        if self.material_preview_mode:self._build_material_preview()

    def _apply_material_preview_component(self, component: dict) -> None:
        if self.material_preview_mode:self._build_material_preview(copy.deepcopy(component or {}))

    def _material_preview_settings(self, mesh: str='sphere', light: str='studio') -> None:
        self.material_preview_mesh=str(mesh or 'sphere'); self.material_preview_light=str(light or 'studio')
        if self.material_preview_mode:self._build_material_preview()

    def _material_preview_camera(self, action: str='focus') -> None:
        if not self.material_preview_mode:return
        a=str(action or 'focus').lower()
        if a=='orbit_left':self.camera_heading-=15
        elif a=='orbit_right':self.camera_heading+=15
        elif a=='zoom_in':self.camera_distance=max(1.7,self.camera_distance*.82)
        elif a=='zoom_out':self.camera_distance=min(14.0,self.camera_distance*1.22)
        else:self.camera_target.set(0,0,0);self.camera_distance=4.6;self.camera_heading=-28;self.camera_pitch=12
        self._position_material_preview_camera()

    def _set_vfx_preview_scene(self, enabled: bool, source_id: str | None = None) -> None:
        if self.play_mode: return
        self.vfx_preview_mode=bool(enabled)
        if self.vfx_preview_mode:
            if self.material_preview_mode:
                self._set_material_preview_scene(False, None)
            self._set_editor_view_context('vfx')
            for root in self.nodes.values():
                try: root.hide()
                except Exception: pass
            self._ensure_vfx_preview_scene(str(source_id or self.vfx_preview_source or '') or None)
            if self.vfx_preview_root:
                self.vfx_preview_root.show(); self.vfx_preview_root.setLightOff(1)
            if self.world_skybox_np:
                try:self.world_skybox_np.hide()
                except Exception:pass
            try:self.base.render.clearFog(); self.base.setBackgroundColor(.025,.035,.045,1)
            except Exception:pass
            self.camera_target.set(0,0,.8); self.camera_distance=7.5; self.camera_heading=-35; self.camera_pitch=22; self._apply_editor_camera()
        else:
            self._destroy_particle_emitter('__vfx_preview__'); self.particle_preview_entity=None; self.vfx_preview_source=None
            if self.vfx_preview_root:
                try:self.vfx_preview_root.removeNode()
                except Exception:pass
            self.vfx_preview_root=None; self.vfx_preview_emitter_root=None
            self._sync_entities(copy.deepcopy(self._authoring_entities))
            self._rebuild_gizmo(); self._apply_world_settings(); self._apply_editor_camera(); self._set_editor_view_context('level')

    def _vfx_preview_camera(self, action: str) -> None:
        if not self.vfx_preview_mode: return
        a=str(action or 'focus').lower()
        if a=='orbit_left': self.camera_heading-=15
        elif a=='orbit_right': self.camera_heading+=15
        elif a=='pan_left': self.camera_target.x-=.5
        elif a=='pan_right': self.camera_target.x+=.5
        elif a=='zoom_in': self.camera_distance=max(.5,self.camera_distance*.8)
        elif a=='zoom_out': self.camera_distance=min(100,self.camera_distance*1.25)
        else: self.camera_target.set(0,0,.8); self.camera_distance=7.5; self.camera_heading=-35; self.camera_pitch=22
        self._apply_editor_camera()

    def _preview_particles(self, entity_id: str | None, mode: str = 'start', count=None, clear: bool = False) -> None:
        if self.play_mode: return
        source=str(entity_id or '') or None
        eid=source
        if self.vfx_preview_mode:
            if source and source != self.vfx_preview_source: self._rebuild_vfx_preview_emitter(source)
            elif source and '__vfx_preview__' not in self.particle_emitters: self._rebuild_vfx_preview_emitter(source)
            eid='__vfx_preview__' if '__vfx_preview__' in self.particle_emitters else None
        if self.particle_preview_entity and self.particle_preview_entity != eid:
            self._particle_set_running(self.particle_preview_entity, False); self._particle_clear(self.particle_preview_entity)
        if not eid or eid not in self.particle_emitters:
            self.particle_preview_entity = None; return
        self.particle_preview_entity=eid; self._particle_preview_last_time=time.perf_counter(); mode=str(mode or 'start').lower()
        if mode=='start': self._particle_set_running(eid,True)
        elif mode=='burst': self._particle_burst(eid,count)
        elif mode=='clear': self._particle_clear(eid)
        elif mode=='stop':
            self._particle_set_running(eid,False)
            if clear:self._particle_clear(eid)

    def _apply_world_settings(self) -> None:
        if not self.base: return
        ps=self.project_settings or {}
        bg=list(ps.get('world_background_color',[.028,.036,.048,1]))+[1,1,1,1]
        try:self.base.setBackgroundColor(float(bg[0]),float(bg[1]),float(bg[2]),float(bg[3]))
        except Exception:pass
        requested_pipeline=str(ps.get('world_render_pipeline','builtin') or 'builtin').lower()
        if requested_pipeline=='simplepbr' and self.simplepbr_pipeline is None:
            try:
                import simplepbr
                try:
                    self.simplepbr_pipeline=simplepbr.init(use_normal_maps=True, use_emission_maps=True, use_occlusion_maps=True)
                except TypeError:
                    self.simplepbr_pipeline=simplepbr.init()
                self.log('Rendering: panda3d-simplepbr pipeline enabled (normal/emission/occlusion maps requested where supported).')
            except Exception as exc:
                self.log(f'Rendering: simplepbr unavailable, using Panda built-in shader path: {exc}'); requested_pipeline='builtin'
        elif requested_pipeline=='complexpbr' and not self.complexpbr_enabled:
            try:
                import complexpbr
                self.complexpbr_module=complexpbr
                intensity=max(0.0,float(ps.get('world_complexpbr_intensity',1.0) or 1.0))
                env_res=max(32,min(2048,int(ps.get('world_complexpbr_env_res',256) or 256)))
                try:
                    complexpbr.apply_shader(self.base.render, intensity=intensity, env_res=env_res, default_lighting=False)
                except TypeError:
                    complexpbr.apply_shader(self.base.render, intensity=intensity, env_res=env_res)
                self.complexpbr_enabled=True
                if bool(ps.get('world_complexpbr_screenspace',False)):
                    complexpbr.screenspace_init(); self.complexpbr_screenspace_enabled=True
                if bool(ps.get('world_complexpbr_static_reflections',False)):
                    try: complexpbr.set_cubebuff_inactive()
                    except Exception: pass
                self.log(f'Rendering: panda3d-complexpbr enabled (IBL/reflections, env_res={env_res}, GLSL 4.30+ required).')
            except Exception as exc:
                self.complexpbr_enabled=False; self.complexpbr_module=None
                self.log(f'Rendering: complexpbr unavailable/unsupported, using Panda built-in shader path: {exc}'); requested_pipeline='builtin'
        shader_auto=bool(ps.get('world_shader_auto',True))
        if requested_pipeline=='builtin':
            try:self.base.render.setShaderAuto() if shader_auto else self.base.render.clearShader()
            except Exception:pass
        ac=list(ps.get('world_ambient_color',[.38,.41,.46,1]))+[1,1,1,1]; ai=max(0,float(ps.get('world_ambient_intensity',1) or 0))
        if self.editor_ambient_np:
            try:self.editor_ambient_np.node().setColor(Vec4(float(ac[0])*ai,float(ac[1])*ai,float(ac[2])*ai,float(ac[3])))
            except Exception:pass
        sc=list(ps.get('world_sun_color',[.94,.92,.86,1]))+[1,1,1,1]; si=max(0,float(ps.get('world_sun_intensity',1) or 0)); hpr=list(ps.get('world_sun_hpr',[-35,-55,0]))+[0,0,0]
        if self.editor_sun_np:
            try:
                self.editor_sun_np.node().setColor(Vec4(float(sc[0])*si,float(sc[1])*si,float(sc[2])*si,float(sc[3]))); self.editor_sun_np.setHpr(float(hpr[0]),float(hpr[1]),float(hpr[2]))
                self.base.render.setLight(self.editor_sun_np) if bool(ps.get('world_sun_enabled',True)) else self.base.render.clearLight(self.editor_sun_np)
            except Exception:pass
        try:self.base.render.clearFog()
        except Exception:pass
        self.world_fog=None
        if bool(ps.get('world_fog_enabled',False)):
            try:
                fog=Fog('worldFog'); fc=list(ps.get('world_fog_color',[.1,.13,.17,1]))+[1,1,1,1]; fog.setColor(float(fc[0]),float(fc[1]),float(fc[2]))
                if str(ps.get('world_fog_mode','exponential')).lower()=='linear': fog.setLinearRange(float(ps.get('world_fog_start',25)),float(ps.get('world_fog_end',180)))
                else: fog.setExpDensity(max(0.0,float(ps.get('world_fog_density',.015))))
                self.base.render.setFog(fog); self.world_fog=fog
            except Exception as exc:self.log(f'World fog setup failed: {exc}')
        if self.world_skybox_np:
            try:self.world_skybox_np.removeNode()
            except Exception:pass
            self.world_skybox_np=None
        sky=str(ps.get('world_skybox_model') or '').strip()
        if sky:
            try:
                path=(PROJECT_ROOT/sky).resolve() if not Path(sky).is_absolute() else Path(sky)
                model=self.base.loader.loadModel(self._panda_filename(path))
                if model and not model.isEmpty():
                    model.reparentTo(self.base.camera); model.setPos(0,0,0); model.setScale(1000); model.setLightOff(1); model.setDepthWrite(False); model.setBin('background',-100); self.world_skybox_np=model
            except Exception as exc:self.log(f'Skybox load failed: {exc}')
        self._apply_post_processing()


    def _active_render_pipeline_name(self) -> str:
        """Return the renderer that is actually active in this Panda process."""
        if self.complexpbr_enabled:
            return 'complexpbr'
        if self.simplepbr_pipeline is not None:
            return 'simplepbr'
        return 'builtin'

    def _light_shadow_supported(self, light_type: str) -> tuple[bool, str]:
        """Report shadow support for the active renderer/light combination.

        simplepbr intentionally supports shadow mapping for DirectionalLight and
        Spotlight only.  PointLight shadow maps are cubemap-based in Panda and
        do not match simplepbr's 2D shadow sampler, which is the source of the
        repeated shadowMap sampler errors seen when Point shadows are enabled.
        """
        lt=str(light_type or 'point').lower()
        pipeline=self._active_render_pipeline_name()
        if pipeline == 'simplepbr' and lt == 'point':
            return False, 'simplepbr supports shadow casting for Directional and Spot lights, not Point lights.'
        return True, ''

    def _configure_light_shadow(self, light, light_type: str, comp: dict, light_name: str = 'Light') -> bool:
        """Configure a light shadow map with renderer-aware capability checks."""
        requested=bool(comp.get('cast_shadows',False))
        if not hasattr(light,'setShadowCaster'):
            return False
        supported,reason=self._light_shadow_supported(light_type)
        if not requested or not supported:
            try: light.setShadowCaster(False)
            except Exception: pass
            if requested and not supported:
                key=f'{self._active_render_pipeline_name()}:{str(light_type).lower()}'
                if key not in self._shadow_warning_keys:
                    self._shadow_warning_keys.add(key)
                    self.log(f'Lighting: {reason} {light_name} shadow request was disabled safely.')
            return False

        resolution=max(128,min(4096,int(comp.get('shadow_resolution',1024) or 1024)))
        lt=str(light_type or 'point').lower()
        try:
            if lt == 'directional':
                # Directional shadows need an orthographic shadow volume.  Panda
                # specifically requires a sensible film size/near/far range for
                # usable directional shadow-map precision.
                lens=light.getLens() if hasattr(light,'getLens') else None
                if not isinstance(lens,OrthographicLens):
                    lens=OrthographicLens()
                    if hasattr(light,'setLens'): light.setLens(lens)
                area=max(1.0,float(comp.get('shadow_area',40.0) or 40.0))
                near=float(comp.get('shadow_near',0.1) or 0.1)
                far=max(near+0.1,float(comp.get('shadow_far',120.0) or 120.0))
                lens.setFilmSize(area,area)
                lens.setNearFar(near,far)
            elif lt == 'spot':
                lens=light.getLens() if hasattr(light,'getLens') else None
                if lens is not None:
                    rng=max(.5,float(comp.get('range',30.0) or 30.0))
                    lens.setNearFar(max(.02,float(comp.get('shadow_near',.05) or .05)),rng)
            light.setShadowCaster(True,resolution,resolution)
            return True
        except Exception as exc:
            self.log(f'Light shadow setup failed for {light_name}: {exc}')
            try: light.setShadowCaster(False)
            except Exception: pass
            return False

    def _post_process_config(self) -> dict:
        ps=self.project_settings or {}
        keys=('world_post_bloom','world_post_bloom_intensity','world_post_bloom_size','world_post_ambient_occlusion','world_post_ao_samples','world_post_gamma','world_post_exposure','world_post_srgb')
        return {k:copy.deepcopy(ps.get(k)) for k in keys}

    def _ensure_common_filters(self):
        if CommonFilters is None or not self.base or not self.base.win:return None
        if self.common_filters is None:
            try:self.common_filters=CommonFilters(self.base.win,self.base.cam)
            except Exception as exc:self.log(f'Post-processing unavailable: {exc}'); self.common_filters=False
        return self.common_filters if self.common_filters is not False else None

    def _apply_post_processing(self) -> None:
        ps=self.project_settings or {}
        if str(ps.get('world_render_pipeline','builtin')).lower()=='complexpbr' and bool(ps.get('world_complexpbr_screenspace',False)):
            # complexpbr screenspace_init owns the screen-space chain; do not stack CommonFilters over it.
            return
        filters=self._ensure_common_filters()
        if not filters:return
        try:
            filters.delBloom(); filters.delAmbientOcclusion(); filters.delGammaAdjust(); filters.delExposureAdjust(); filters.delSrgbEncode()
        except Exception:pass
        try:
            if bool(ps.get('world_post_bloom',False)):
                filters.setBloom(intensity=max(0.0,float(ps.get('world_post_bloom_intensity',1.0) or 1.0)),size=str(ps.get('world_post_bloom_size','medium') or 'medium'))
            if bool(ps.get('world_post_ambient_occlusion',False)):
                filters.setAmbientOcclusion(numsamples=max(1,int(ps.get('world_post_ao_samples',16) or 16)))
            gamma=float(ps.get('world_post_gamma',1.0) or 1.0)
            if abs(gamma-1.0)>1e-6: filters.setGammaAdjust(gamma)
            exposure=float(ps.get('world_post_exposure',0.0) or 0.0)
            if abs(exposure)>1e-6 and hasattr(filters,'setExposureAdjust'): filters.setExposureAdjust(exposure)
            if bool(ps.get('world_post_srgb',False)) and hasattr(filters,'setSrgbEncode'): filters.setSrgbEncode()
        except Exception as exc:self.log(f'Post-processing setup failed: {exc}')

    def _post_process_set(self, name: str, enabled: bool=True, **settings) -> bool:
        name=str(name).lower().strip(); ps=self.project_settings
        if name=='bloom':
            ps['world_post_bloom']=bool(enabled)
            if 'intensity' in settings: ps['world_post_bloom_intensity']=float(settings['intensity'])
            if 'size' in settings: ps['world_post_bloom_size']=str(settings['size'])
        elif name in {'ao','ambient_occlusion','ssao'}:
            ps['world_post_ambient_occlusion']=bool(enabled)
            if 'samples' in settings: ps['world_post_ao_samples']=int(settings['samples'])
        elif name=='gamma':
            ps['world_post_gamma']=float(settings.get('value',settings.get('gamma',1.0))) if enabled else 1.0
        elif name=='exposure':
            ps['world_post_exposure']=float(settings.get('value',settings.get('stops',0.0))) if enabled else 0.0
        elif name=='srgb': ps['world_post_srgb']=bool(enabled)
        else:return False
        self._apply_post_processing(); return True

    def _post_process_clear(self) -> bool:
        self.project_settings.update({'world_post_bloom':False,'world_post_ambient_occlusion':False,'world_post_gamma':1.0,'world_post_exposure':0.0,'world_post_srgb':False})
        self._apply_post_processing(); return True

    def _set_runtime_light_enabled(self, entity_id: str, enabled: bool) -> bool:
        light_np=self.entity_lights.get(entity_id)
        if not (self.base and light_np): return False
        enabled=bool(enabled); self.runtime_light_enabled[entity_id]=enabled
        try:
            self.base.render.setLight(light_np) if enabled else self.base.render.clearLight(light_np); return True
        except Exception: return False

    def _set_runtime_light_intensity(self, entity_id: str, intensity: float) -> bool:
        light_np=self.entity_lights.get(entity_id); raw=self.entity_data.get(entity_id,{})
        if not light_np: return False
        comp=(raw.get('components') or {}).get('light') or {}; color=list(comp.get('color',[1,1,1]))+[1,1,1]
        try: light_np.node().setColor(Vec4(float(color[0])*intensity,float(color[1])*intensity,float(color[2])*intensity,1)); return True
        except Exception: return False

    def _configure_runtime_light(self, entity_id: str, settings: dict) -> bool:
        light_np=self.entity_lights.get(entity_id)
        if not light_np: return False
        node=light_np.node(); authored=((self.entity_data.get(entity_id,{}) or {}).get('components') or {}).get('light') or {}
        try:
            if 'enabled' in settings: self._set_runtime_light_enabled(entity_id,bool(settings['enabled']))
            intensity=max(0.0,float(settings.get('intensity', authored.get('intensity',1.0))))
            color=list(settings.get('color', authored.get('color',[1,1,1])))+[1,1,1]
            node.setColor(Vec4(float(color[0])*intensity,float(color[1])*intensity,float(color[2])*intensity,1))
            if isinstance(node,(PointLight,Spotlight)):
                default_range=30.0 if isinstance(node,Spotlight) else 25.0
                rng=max(.1,float(settings.get('range', authored.get('range',default_range))))
                node.setAttenuation(Vec3(1.0,0.0,16.0/(rng*rng)))
                if hasattr(node,'setMaxDistance'): node.setMaxDistance(rng)
            if isinstance(node,Spotlight):
                fov=max(1.0,min(175.0,float(settings.get('fov',authored.get('fov',45.0)))))
                exponent=max(0.0,float(settings.get('exponent',authored.get('exponent',8.0))))
                lens=node.getLens() if hasattr(node,'getLens') else None
                if lens is None: lens=PerspectiveLens(); node.setLens(lens)
                lens.setFov(fov)
                rng=max(.1,float(settings.get('range',authored.get('range',30.0))))
                lens.setNearFar(.05,rng); node.setExponent(exponent)
            if any(k in settings for k in ('cast_shadows','shadow_resolution','shadow_area','shadow_near','shadow_far')):
                merged=dict(authored); merged.update(settings)
                light_type=str(merged.get('type','spot' if isinstance(node,Spotlight) else ('point' if isinstance(node,PointLight) else 'directional'))).lower()
                self._configure_light_shadow(node,light_type,merged,str((self.entity_data.get(entity_id,{}) or {}).get('name') or entity_id))
            return True
        except Exception as exc:
            self.log(f'Runtime light configure failed for {entity_id}: {exc}'); return False

    def _preview_light_action(self, entity_id: str | None, action: str = 'toggle') -> None:
        if self.play_mode: return
        eid=str(entity_id or '')
        if eid not in self.entity_lights: return
        action=str(action or 'toggle').lower()
        if action == 'toggle': self._set_runtime_light_enabled(eid, not self.runtime_light_enabled.get(eid, True))
        elif action == 'on': self._set_runtime_light_enabled(eid, True)
        elif action == 'off': self._set_runtime_light_enabled(eid, False)

    def _destroy_ui_node(self, entity_id: str) -> None:
        widget = self.ui_nodes.pop(entity_id, None)
        if widget is not None:
            try: widget.destroy()
            except Exception:
                try: widget.removeNode()
                except Exception: pass

    def _build_ui_component(self, entity_id: str, name: str, comp: dict) -> None:
        if not self.base:
            return
        self._destroy_ui_node(entity_id)
        kind = str(comp.get('type', 'label')).lower()
        half_w, half_h = self._ui_half_size(comp.get('size', [240, 80]))
        pos = self._ui_anchor_pos(str(comp.get('anchor', 'center')), comp.get('offset', [0, 0]), half_w, half_h)
        color = self._rgba(comp.get('color'), (0.08, 0.12, 0.17, 0.88))
        text_color = self._rgba(comp.get('text_color'), (0.95, 0.97, 1.0, 1.0))
        text = str(comp.get('text', name if kind in {'label','button'} else ''))
        font_px = max(6.0, float(comp.get('font_size', 22)))
        _rw, ref_h, _ra, _rs = self._ui_reference_metrics()
        text_scale = (2.0 * font_px) / ref_h
        # DirectGUI text uses its baseline rather than the visual glyph centre.
        # Keep one baseline offset across authored controls so the browser HUD
        # designer and runtime widgets line up much more predictably.
        text_y = -text_scale * 0.34
        text_pad = max(0.008, text_scale * 0.35)
        common = dict(parent=self._ensure_ui_root() or self.base.aspect2d, pos=pos)
        widget = None
        if kind == 'canvas':
            widget = DirectFrame(frameColor=(0,0,0,0), frameSize=(-.001,.001,-.001,.001), **common)
        elif kind == 'panel':
            widget = DirectFrame(frameColor=color, frameSize=(-half_w, half_w, -half_h, half_h), **common)
        elif kind == 'image':
            image = str(comp.get('image') or '').strip()
            image_path = None
            if image:
                try: image_path = str(self._panda_filename((PROJECT_ROOT / image).resolve()))
                except Exception: image_path = image
            kwargs = dict(frameColor=color, frameSize=(-half_w, half_w, -half_h, half_h), **common)
            if image_path: kwargs['image'] = image_path; kwargs['image_scale'] = (half_w, 1, half_h)
            widget = DirectFrame(**kwargs)
        elif kind == 'button':
            def clicked(eid=entity_id):
                if not self.play_mode or self.play_paused: return
                self._emit_ui_signal(eid, 'clicked')
            widget = DirectButton(text=text, text_fg=text_color, text_scale=text_scale, text_pos=(0, text_y), frameColor=color,
                                  frameSize=(-half_w, half_w, -half_h, half_h), command=clicked, relief=DGG.FLAT, **common)
        elif kind == 'checkbox':
            def toggled(eid=entity_id):
                if not self.play_mode or self.play_paused: return
                raw=self.entity_data.get(eid,{}) ; ui=(raw.get('components') or {}).get('ui') or {}
                ui['checked']=not bool(ui.get('checked',False))
                w=self.ui_nodes.get(eid)
                if w is not None:
                    try:w['text']=('[✓] ' if ui['checked'] else '[ ] ')+str(ui.get('text','Checkbox'))
                    except Exception:pass
                self._emit_ui_signal(eid, 'changed', {'checked':ui['checked']})
            label=('[✓] ' if bool(comp.get('checked',False)) else '[ ] ')+text
            widget = DirectButton(text=label, text_fg=text_color, text_scale=text_scale, text_pos=(0, text_y), frameColor=color,
                                  frameSize=(-half_w, half_w, -half_h, half_h), command=toggled, relief=DGG.FLAT, **common)
        elif kind == 'progress':
            rng=max(.001,float(comp.get('range',100.0) or 100.0)); val=max(0.0,min(rng,float(comp.get('value',0.0) or 0.0)))
            bg=self._rgba(comp.get('background_color'),(.04,.07,.10,.92))
            widget=DirectWaitBar(range=rng,value=val,barColor=color,frameColor=bg,frameSize=(-half_w,half_w,-half_h,half_h),**common)
        elif kind == 'slider':
            mn=float(comp.get('min_value',0.0)); mx=float(comp.get('max_value',100.0)); val=max(mn,min(mx,float(comp.get('value',mn))))
            bg=self._rgba(comp.get('background_color'),(.04,.07,.10,.92))
            slider_ref={'widget':None}
            # DirectSlider.command is invoked with no value argument.
            def changed(eid=entity_id,ref=slider_ref):
                w=ref.get('widget')
                if w is None:return
                try:value=float(w['value'])
                except Exception:return
                raw=self.entity_data.get(eid,{}) ; ui=(raw.get('components') or {}).get('ui') or {}; ui['value']=value
                if self.play_mode and not self.play_paused:self._emit_ui_signal(eid,'changed',{'value':value})
            thumb_w=max(.012,min(half_w*.12,half_h*.72)); thumb_h=max(.012,half_h*.76)
            widget=DirectSlider(range=(mn,mx),value=val,pageSize=max(.001,float(comp.get('page_size',1.0) or 1.0)),command=changed,orientation=DGG.HORIZONTAL,
                frameColor=bg,frameSize=(-half_w,half_w,-half_h,half_h),relief=DGG.FLAT,
                thumb_frameColor=color,thumb_frameSize=(-thumb_w,thumb_w,-thumb_h,thumb_h),thumb_relief=DGG.FLAT,**common)
            slider_ref['widget']=widget
        elif kind == 'input':
            bg=self._rgba(comp.get('color'),(.05,.08,.12,.96))
            def submitted(text_value,eid=entity_id):
                raw=self.entity_data.get(eid,{}) ; ui=(raw.get('components') or {}).get('ui') or {}; ui['text']=str(text_value)
                if self.play_mode and not self.play_paused:self._emit_ui_signal(eid,'submitted',{'text':str(text_value)})
            widget=DirectEntry(initialText=str(comp.get('text','')),text_fg=text_color,text_scale=text_scale,text_align=TextNode.ALeft,
                text_pos=(-half_w+text_pad,text_y),frameColor=bg,frameSize=(-half_w,half_w,-half_h,half_h),
                width=max(1.0,half_w*2/max(text_scale,.001)),numLines=1,focus=0,cursorKeys=1,command=submitted,**common)
        elif kind == 'dropdown':
            opts=[str(x) for x in (comp.get('options') or ['Option A'])] or ['Option A']; idx=max(0,min(len(opts)-1,int(comp.get('selected_index',0) or 0)))
            def selected_option(value,eid=entity_id,options=opts):
                raw=self.entity_data.get(eid,{}) ; ui=(raw.get('components') or {}).get('ui') or {}
                try:ui['selected_index']=options.index(str(value))
                except Exception:ui['selected_index']=0
                if self.play_mode and not self.play_paused:self._emit_ui_signal(eid,'changed',{'value':str(value),'index':ui['selected_index']})
            pad=max(.008,text_scale*.35); marker_x=max(-half_w+pad,half_w-half_h*.70)
            widget=DirectOptionMenu(items=opts,initialitem=idx,textMayChange=1,text_fg=text_color,text_scale=text_scale,
                text_align=TextNode.ALeft,text_pos=(-half_w+pad,text_y),frameColor=color,frameSize=(-half_w,half_w,-half_h,half_h),
                relief=DGG.FLAT,highlightColor=(.16,.32,.44,1),popupMarker_pos=(marker_x,0,0),popupMarker_scale=max(.015,half_h*.55),
                item_text_scale=text_scale,item_text_fg=text_color,item_frameColor=(.055,.085,.115,.98),command=selected_option,**common)
        elif kind == 'radio':
            def choose_radio(eid=entity_id):
                if not self.play_mode or self.play_paused:return
                raw=self.entity_data.get(eid,{}) ; ui=(raw.get('components') or {}).get('ui') or {}; group=str(ui.get('group') or 'default')
                for oid,oraw in self.entity_data.items():
                    oui=(oraw.get('components') or {}).get('ui') or {}
                    if str(oui.get('type','')).lower()=='radio' and str(oui.get('group') or 'default')==group:
                        oui['selected']=(oid==eid); w=self.ui_nodes.get(oid)
                        if w is not None:
                            try:w['text']=('(*) ' if oui['selected'] else '( ) ')+str(oui.get('text','Radio Option'))
                            except Exception:pass
                self._emit_ui_signal(eid,'changed',{'selected':True,'group':group})
            label=('(*) ' if bool(comp.get('selected',False)) else '( ) ')+text
            widget=DirectButton(text=label,text_fg=text_color,text_scale=text_scale,text_pos=(0,text_y),frameColor=color,frameSize=(-half_w,half_w,-half_h,half_h),command=choose_radio,relief=DGG.FLAT,**common)
        else:
            align_name = str(comp.get('align', 'center')).lower()
            align = {'left': TextNode.ALeft, 'right': TextNode.ARight}.get(align_name, TextNode.ACenter)
            text_pos_x = (-half_w + (font_px / ref_h)) if align_name == 'left' else ((half_w - (font_px / ref_h)) if align_name == 'right' else 0.0)
            widget = DirectLabel(text=text, text_fg=text_color, text_scale=text_scale, text_align=align, text_pos=(text_pos_x, text_y), frameColor=(0,0,0,0),
                                 frameSize=(-half_w, half_w, -half_h, half_h), **common)
        if widget is None:
            return
        widget.setTag('ui_entity_id', entity_id)
        if not bool(comp.get('visible', True)):
            widget.hide()
        self.ui_nodes[entity_id] = widget
        self._refresh_ui_interaction_state(entity_id)

    def _emit_ui_signal(self, entity_id: str, fallback: str = 'clicked', extra: dict | None = None) -> None:
        raw=self.entity_data.get(entity_id,{})
        ui=(raw.get('components') or {}).get('ui') or {}
        signal_name=str(ui.get('signal_name') or fallback)
        payload={'ui_entity_id':entity_id,'ui_entity_name':raw.get('name',entity_id),'signal':signal_name}
        if extra: payload.update(extra)
        connections=list(ui.get('connections') or [])
        if connections:
            for c in connections:
                self._execute_signal_connection(entity_id, signal_name, payload, c)
        else:
            event_name=str(ui.get('event_name') or signal_name or fallback)
            self._dispatch_script_event(event_name,payload,sender=entity_id)

    def _refresh_ui_interaction_state(self, entity_id: str | None = None) -> None:
        ids = [entity_id] if entity_id else list(self.ui_nodes)
        for eid in ids:
            widget = self.ui_nodes.get(eid)
            raw = self.entity_data.get(eid, {})
            comp = (raw.get('components') or {}).get('ui') or {}
            if widget is None or str(comp.get('type','')).lower() not in {'button','checkbox','slider','input','dropdown','radio'}:
                continue
            try:
                widget['state'] = DGG.NORMAL if (self.play_mode and not self.play_paused and comp.get('enabled', True) is not False) else DGG.DISABLED
            except Exception:
                pass

    def _ui_set_text(self, entity_id: str, text: str) -> None:
        raw = self.entity_data.get(entity_id, {})
        comp = (raw.get('components') or {}).get('ui')
        if not isinstance(comp, dict):
            return
        comp['text'] = str(text)
        widget = self.ui_nodes.get(entity_id)
        if widget is None:
            return
        kind = str(comp.get('type', '')).lower()
        try:
            if kind == 'input':
                # DirectEntry owns its text through PGEntry; changing the
                # generic DirectGUI text option does not update the field.
                widget.enterText(str(text))
            elif kind == 'checkbox':
                widget['text'] = ('[✓] ' if bool(comp.get('checked', False)) else '[ ] ') + str(text)
            elif kind == 'radio':
                widget['text'] = ('(*) ' if bool(comp.get('selected', False)) else '( ) ') + str(text)
            else:
                widget['text'] = str(text)
        except Exception:
            pass

    def _ui_set_value(self, entity_id: str, value: float) -> None:
        raw=self.entity_data.get(entity_id,{})
        comp=(raw.get('components') or {}).get('ui')
        if not isinstance(comp,dict): return
        kind=str(comp.get('type','')).lower()
        if kind=='slider':
            mn=float(comp.get('min_value',0.0)); mx=float(comp.get('max_value',100.0)); val=max(mn,min(mx,float(value)))
        else:
            rng=max(.001,float(comp.get('range',100.0) or 100.0)); val=max(0.0,min(rng,float(value)))
        comp['value']=val
        widget=self.ui_nodes.get(entity_id)
        if widget is not None:
            try: widget['value']=val
            except Exception: pass

    def _ui_set_visible(self, entity_id: str, visible: bool) -> None:
        widget = self.ui_nodes.get(entity_id)
        if widget is not None:
            try: widget.show() if visible else widget.hide()
            except Exception: pass

    def _ui_set_color(self, entity_id: str, color) -> None:
        widget = self.ui_nodes.get(entity_id)
        raw = self.entity_data.get(entity_id, {})
        comp = (raw.get('components') or {}).get('ui')
        rgba = self._rgba(color)
        if isinstance(comp, dict): comp['color'] = list(rgba)
        if widget is not None:
            try: widget['frameColor'] = rgba
            except Exception: pass

    def _build_collider_helper(self, root: NodePath, name: str, collider: dict) -> None:
        shape = str(collider.get('shape', 'box')).lower()
        offset = list(collider.get('offset', [0, 0, 0])) + [0, 0, 0]
        ox, oy, oz = [float(v) for v in offset[:3]]
        segs = LineSegs(name + '-collider-helper')
        segs.setThickness(1.6)
        segs.setColor(0.28, 0.92, 0.78, 1)
        if shape == 'sphere':
            radius = max(0.01, float(collider.get('radius', 0.5)))
            for plane in range(3):
                points = []
                for i in range(33):
                    a = math.tau * i / 32.0
                    c, d = math.cos(a) * radius, math.sin(a) * radius
                    if plane == 0: points.append(Vec3(ox + c, oy + d, oz))
                    elif plane == 1: points.append(Vec3(ox + c, oy, oz + d))
                    else: points.append(Vec3(ox, oy + c, oz + d))
                for a, b in zip(points, points[1:]): segs.moveTo(a); segs.drawTo(b)
        elif shape in {'capsule','cylinder','cone'}:
            radius = max(0.01, float(collider.get('radius', 0.5)))
            height = max(0.01, float(collider.get('height', 1.0)))
            half = height * 0.5
            rings=(-half,half) if shape!='cone' else (-half,)
            for z in rings:
                pts=[]
                for i in range(33):
                    a=math.tau*i/32.0; pts.append(Vec3(ox+math.cos(a)*radius, oy+math.sin(a)*radius, oz+z))
                for a,b in zip(pts,pts[1:]): segs.moveTo(a); segs.drawTo(b)
            if shape=='cone':
                apex=Vec3(ox,oy,oz+half)
                for x,y in ((radius,0),(-radius,0),(0,radius),(0,-radius)):
                    segs.moveTo(ox+x,oy+y,oz-half); segs.drawTo(apex)
            else:
                for x,y in ((radius,0),(-radius,0),(0,radius),(0,-radius)):
                    segs.moveTo(ox+x,oy+y,oz-half); segs.drawTo(ox+x,oy+y,oz+half)
        elif shape == 'plane':
            extent=3.0
            for i in range(-3,4):
                segs.moveTo(ox-extent,oy+i,oz);segs.drawTo(ox+extent,oy+i,oz)
                segs.moveTo(ox+i,oy-extent,oz);segs.drawTo(ox+i,oy+extent,oz)
        elif shape in {'convex_hull','triangle_mesh'}:
            # Complex colliders are authored directly from the render Geoms.  Mirror
            # those same Geoms as a teal wire overlay instead of showing a misleading
            # bounding box helper.  Bullet's runtime debug renderer remains the final
            # authority during Play Mode.
            helper_root = root.attachNewNode(name + '-collider-helper-mesh')
            self._isolate_editor_helper(helper_root)
            copied = 0
            for source in self._geometry_sources(root):
                try:
                    clone = source.copyTo(helper_root)
                    clone.clearTag('editor_geometry_source')
                    clone.setRenderModeWireframe(45)
                    clone.setColor(0.28, 0.92, 0.78, 1, 100)
                    clone.setTextureOff(100); clone.setLightOff(100)
                    clone.setDepthWrite(False); clone.setBin('fixed', 26)
                    for gnp in clone.findAllMatches('**/+GeomNode'):
                        gnp.setCollideMask(BitMask32.allOff())
                    copied += 1
                except Exception:
                    pass
            if not self.collider_helpers_visible or self.play_mode:
                helper_root.hide()
            if copied:
                return
            # Geometry-less entities retain a small fallback hint.
            try:
                lo,hi=root.getTightBounds(root)
            except Exception:
                lo=hi=None
            if lo is not None and hi is not None:
                hx,hy,hz=(hi.x-lo.x)*.5,(hi.y-lo.y)*.5,(hi.z-lo.z)*.5;cx,cy,cz=(hi.x+lo.x)*.5,(hi.y+lo.y)*.5,(hi.z+lo.z)*.5
                pts=[Vec3(cx-hx,cy-hy,cz-hz),Vec3(cx+hx,cy-hy,cz-hz),Vec3(cx+hx,cy+hy,cz-hz),Vec3(cx-hx,cy+hy,cz-hz),Vec3(cx-hx,cy-hy,cz+hz),Vec3(cx+hx,cy-hy,cz+hz),Vec3(cx+hx,cy+hy,cz+hz),Vec3(cx-hx,cy+hy,cz+hz)]
                for a,b in ((0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)):
                    segs.moveTo(pts[a]); segs.drawTo(pts[b])
        else:
            size = list(collider.get('size', [1,1,1])) + [1,1,1]
            hx,hy,hz = [max(0.005, abs(float(v))*0.5) for v in size[:3]]
            pts=[Vec3(ox-hx,oy-hy,oz-hz),Vec3(ox+hx,oy-hy,oz-hz),Vec3(ox+hx,oy+hy,oz-hz),Vec3(ox-hx,oy+hy,oz-hz),Vec3(ox-hx,oy-hy,oz+hz),Vec3(ox+hx,oy-hy,oz+hz),Vec3(ox+hx,oy+hy,oz+hz),Vec3(ox-hx,oy+hy,oz+hz)]
            for a,b in ((0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)):
                segs.moveTo(pts[a]); segs.drawTo(pts[b])
        helper = root.attachNewNode(segs.create())
        self._isolate_editor_helper(helper)
        helper.setName(name + '-collider-helper')
        helper.setTag('editor_helper', '1')
        helper.setDepthTest(False); helper.setBin('fixed', 26)
        if not self.collider_helpers_visible or self.play_mode: helper.hide()

    def _physics_body_node(self, entity_id: str):
        np = self.physics_nodes.get(entity_id)
        if not np or np.isEmpty():
            return None
        try:
            return np.node()
        except Exception:
            return None

    def _geometry_sources(self, root: NodePath) -> list[NodePath]:
        """Return visual roots intended to provide rendered/collision geometry.

        Editor helpers, gizmos, selection boxes and collider helpers are deliberately
        excluded.  Imported models and generated primitives tag their visual root
        with ``editor_geometry_source`` when they are created.
        """
        sources: list[NodePath] = []
        try:
            for child in root.getChildren():
                if child.hasTag('editor_geometry_source'):
                    sources.append(child)
        except Exception:
            pass
        return sources

    def _iter_collision_geoms(self, root: NodePath):
        """Yield every render Geom plus its transform relative to the entity root.

        Bullet's convex-hull and triangle-mesh helpers accept a TransformState.
        Passing each Geom with its actual local transform preserves multi-part GLB
        assemblies instead of collapsing them into one bounds proxy or only using
        the first GeomNode.
        """
        for source in self._geometry_sources(root):
            try:
                matches = source.findAllMatches('**/+GeomNode')
                # A source may itself be a GeomNode; include it if the pattern did not.
                paths = [matches.getPath(i) for i in range(matches.getNumPaths())]
                if hasattr(source.node(), 'getNumGeoms') and source.node().getNumGeoms() > 0 and not paths:
                    paths = [source]
                for geom_np in paths:
                    node = geom_np.node()
                    if not hasattr(node, 'getNumGeoms'):
                        continue
                    ts = geom_np.getTransform(root)
                    for gi in range(node.getNumGeoms()):
                        yield node.getGeom(gi), ts
            except Exception as exc:
                self.log(f'Physics: could not inspect render geometry under {root.getName()}: {exc}')

    def _make_bullet_shape(self, collider: dict, root: NodePath):
        shape_name = str(collider.get('shape', 'box')).lower()
        scale = root.getScale(self.base.render)
        sx, sy, sz = max(.001, abs(scale.x)), max(.001, abs(scale.y)), max(.001, abs(scale.z))
        offset = list(collider.get('offset', [0,0,0])) + [0,0,0]
        offset_vec = Vec3(float(offset[0])*sx, float(offset[1])*sy, float(offset[2])*sz)
        radius=max(.005,float(collider.get('radius',.5))*max(sx,sy))
        height=max(.005,float(collider.get('height',1.0))*sz)
        if shape_name == 'sphere':
            return BulletSphereShape(max(radius, .005)), offset_vec, False
        if shape_name == 'capsule':
            return BulletCapsuleShape(radius, height, ZUp), offset_vec, False
        if shape_name == 'cylinder':
            return BulletCylinderShape(radius, height, ZUp), offset_vec, False
        if shape_name == 'cone':
            return BulletConeShape(radius, height, ZUp), offset_vec, False
        if shape_name == 'plane':
            return BulletPlaneShape(Vec3(0,0,1), float(collider.get('plane_constant',0.0))), offset_vec, False
        if shape_name in {'convex_hull','triangle_mesh'}:
            geoms = list(self._iter_collision_geoms(root))
            if not geoms:
                self.log(f'Physics: {shape_name} collider requires visible model/primitive geometry.')
                return None, Vec3(0), False
            # Geom transforms are relative to the entity root.  Keep entity scale on
            # the Bullet body so all authored GLB child transforms are preserved.
            raw_offset = Vec3(float(offset[0]), float(offset[1]), float(offset[2]))
            if shape_name == 'convex_hull':
                shape = BulletConvexHullShape()
                for geom, ts in geoms:
                    shape.addGeom(geom, ts)
                self.log(f'Physics: convex hull built from {len(geoms)} render Geom(s) for {root.getName()}.')
                return shape, raw_offset, True
            mesh = BulletTriangleMesh()
            for geom, ts in geoms:
                mesh.addGeom(geom, False, ts)
            dynamic=bool(collider.get('mesh_dynamic',False))
            shape = BulletTriangleMeshShape(mesh, dynamic)
            try:
                tri_count = mesh.getNumTriangles()
            except Exception:
                tri_count = '?'
            self.log(f'Physics: triangle mesh built from {len(geoms)} render Geom(s), {tri_count} triangle(s) for {root.getName()}.')
            return shape, raw_offset, True
        size = list(collider.get('size', [1,1,1])) + [1,1,1]
        half = Vec3(max(.005, abs(float(size[0]))*sx*.5), max(.005, abs(float(size[1]))*sy*.5), max(.005, abs(float(size[2]))*sz*.5))
        return BulletBoxShape(half), offset_vec, False

    def _build_play_physics(self) -> None:
        self._destroy_play_physics()
        candidates = [(eid, raw) for eid, raw in self.entity_data.items() if (raw.get('components') or {}).get('collider') or bool(((raw.get('components') or {}).get('terrain') or {}).get('collision_enabled', False))]
        if not candidates:
            return
        if not PHYSICS_AVAILABLE:
            self.log('Physics: Panda3D Bullet module is unavailable; Collider components will be ignored in Play Mode.')
            return
        self.physics_world = BulletWorld()
        g = list(self.project_settings.get('gravity', [0,0,-9.81])) + [0,0,-9.81]
        self.physics_world.setGravity(Vec3(float(g[0]), float(g[1]), float(g[2])))
        self._contact_pairs.clear()
        self._trigger_pairs.clear()
        built = 0
        for eid, raw in candidates:
            components = raw.get('components') or {}
            collider = components.get('collider') or {}
            terrain_comp = components.get('terrain') or {}
            if terrain_comp and terrain_comp.get('collision_enabled', False) and not collider:
                collider = {'shape':'triangle_mesh','offset':[0,0,0],'enabled':True,'trigger':False,'mesh_dynamic':False,'layer':0,'mask':4294967295}
            if collider.get('enabled', True) is False:
                continue
            root = self.nodes.get(eid)
            if not root:
                continue
            character = components.get('character_controller') or {}
            if character:
                radius = max(0.05, float(character.get('radius', collider.get('radius', 0.45))))
                height = max(0.05, float(character.get('height', collider.get('height', 1.2))))
                step_height = max(0.01, float(character.get('step_height', 0.35)))
                cylinder_height = max(0.01, height - (2.0 * radius))
                shape = BulletCapsuleShape(radius, cylinder_height, ZUp)
                controller = BulletCharacterControllerNode(shape, step_height, 'physics-character-' + eid)
                try:
                    _g = list(self.project_settings.get('gravity', [0,0,-9.81])) + [0,0,-9.81]
                    controller.setGravity(abs(float(_g[2])))
                except Exception: pass
                try: controller.setJumpSpeed(max(0.0, float(character.get('jump_speed', 6.0))))
                except Exception: pass
                try: controller.setFallSpeed(max(0.0, float(character.get('fall_speed', 35.0))))
                except Exception: pass
                try: controller.setMaxJumpHeight(max(0.0, float(character.get('max_jump_height', 1.5))))
                except Exception: pass
                try: controller.setMaxSlope(max(0.0, float(character.get('max_slope', 45.0))))
                except Exception: pass
                try: controller.setUseGhostSweepTest(bool(character.get('ghost_sweep', True)))
                except Exception: pass
                np = self.base.render.attachNewNode(controller)
                np.setTag('physics_entity_id', eid)
                np.setCollideMask(BitMask32.allOn())
                np.setPos(root.getPos(self.base.render)); np.setQuat(root.getQuat(self.base.render))
                self.physics_world.attachCharacter(controller)
                self.physics_characters[eid] = np
                built += 1
                continue
            shape, offset, scale_with_entity = self._make_bullet_shape(collider, root)
            if shape is None:
                continue
            shape_transform = TransformState.makePos(offset)
            if collider.get('trigger', False):
                ghost = BulletGhostNode('physics-trigger-' + eid)
                ghost.addShape(shape, shape_transform)
                np = self.base.render.attachNewNode(ghost)
                np.setTag('physics_entity_id', eid)
                np.setPos(root.getPos(self.base.render)); np.setQuat(root.getQuat(self.base.render))
                if scale_with_entity: np.setScale(root.getScale(self.base.render))
                self.physics_world.attachGhost(ghost)
                self.physics_ghost_nodes[eid] = np
                built += 1
                continue
            rb = components.get('rigid_body') or {}
            body_type = str(rb.get('body_type', 'static' if not rb else 'dynamic')).lower()
            if body_type not in {'dynamic','static','kinematic'}: body_type = 'dynamic'
            shape_name=str(collider.get('shape','box')).lower()
            if shape_name == 'plane': body_type='static'
            if shape_name == 'triangle_mesh' and not collider.get('mesh_dynamic',False): body_type='static'
            body = BulletRigidBodyNode('physics-body-' + eid)
            body.addShape(shape, shape_transform)
            body.setFriction(max(0.0, float(rb.get('friction', .5))))
            body.setRestitution(max(0.0, min(1.0, float(rb.get('restitution', 0.0)))))
            if body_type == 'dynamic':
                body.setMass(max(.001, float(rb.get('mass', 1.0))))
                try:
                    body.setLinearDamping(max(0.0, min(1.0, float(rb.get('linear_damping', .05)))))
                    body.setAngularDamping(max(0.0, min(1.0, float(rb.get('angular_damping', .05)))))
                except Exception:
                    pass
            else:
                body.setMass(0.0)
            if body_type == 'kinematic':
                body.setKinematic(True)
            np = self.base.render.attachNewNode(body)
            np.setTag('physics_entity_id', eid)
            np.setPos(root.getPos(self.base.render)); np.setQuat(root.getQuat(self.base.render))
            if scale_with_entity: np.setScale(root.getScale(self.base.render))
            self.physics_world.attachRigidBody(body)
            self.physics_nodes[eid] = np
            self.physics_body_types[eid] = body_type
            built += 1
        self.log(f'Physics: Bullet world initialized with {built} collider bodies/triggers.')
        self._set_bullet_debug(self.bullet_debug_enabled)

    def _destroy_play_physics(self) -> None:
        if self.physics_world is not None:
            for np in list(self.physics_nodes.values()):
                try: self.physics_world.removeRigidBody(np.node())
                except Exception: pass
                try: np.removeNode()
                except Exception: pass
            for np in list(self.physics_ghost_nodes.values()):
                try: self.physics_world.removeGhost(np.node())
                except Exception: pass
                try: np.removeNode()
                except Exception: pass
            for np in list(self.physics_characters.values()):
                try: self.physics_world.removeCharacter(np.node())
                except Exception: pass
                try: np.removeNode()
                except Exception: pass
        else:
            for np in list(self.physics_nodes.values()) + list(self.physics_ghost_nodes.values()) + list(self.physics_characters.values()):
                try: np.removeNode()
                except Exception: pass
        if self.bullet_debug_np:
            try: self.bullet_debug_np.removeNode()
            except Exception: pass
            self.bullet_debug_np=None
        self.physics_nodes.clear(); self.physics_body_types.clear(); self.physics_ghost_nodes.clear(); self.physics_characters.clear()
        self._contact_pairs.clear(); self._trigger_pairs.clear()
        self.physics_world = None

    def _sync_characters_from_physics(self) -> None:
        if not self.base:
            return
        for eid, np in list(self.physics_characters.items()):
            root = self.nodes.get(eid)
            if not root or not np:
                continue
            try:
                root.setPos(self.base.render, np.getPos(self.base.render))
                root.setQuat(self.base.render, np.getQuat(self.base.render))
            except Exception:
                pass

    def _collider_layer_mask(self, entity_id: str) -> tuple[int, int]:
        raw = self.entity_data.get(entity_id, {})
        c = (raw.get('components') or {}).get('collider') or {}
        try: layer = max(0, min(31, int(c.get('layer', 0))))
        except Exception: layer = 0
        try: mask = int(c.get('mask', 0xFFFFFFFF)) & 0xFFFFFFFF
        except Exception: mask = 0xFFFFFFFF
        return layer, mask

    def _interaction_allowed(self, a: str, b: str) -> bool:
        la, ma = self._collider_layer_mask(a); lb, mb = self._collider_layer_mask(b)
        return bool((ma & (1 << lb)) and (mb & (1 << la)))

    def _physics_entity_from_node(self, node) -> str | None:
        if node is None:
            return None
        try: name = str(node.getName())
        except Exception: name = ''
        for prefix in ('physics-body-', 'physics-trigger-', 'physics-character-'):
            if name.startswith(prefix):
                eid = name[len(prefix):]
                if eid in self.entity_data:
                    return eid
        return None

    def _physics_payload(self, self_id: str, other_id: str, trigger: bool) -> dict:
        other = self.entity_data.get(other_id, {})
        return {
            'other_id': other_id, 'other_name': str(other.get('name', other_id)),
            'trigger': bool(trigger),
            'self_layer': self._collider_layer_mask(self_id)[0],
            'other_layer': self._collider_layer_mask(other_id)[0],
        }

    def _emit_pair_event(self, event_name: str, a: str, b: str, trigger: bool = False) -> None:
        if not self._interaction_allowed(a, b):
            return
        self._dispatch_script_event(event_name, self._physics_payload(a, b, trigger), target=a, sender=b)
        self._dispatch_script_event(event_name, self._physics_payload(b, a, trigger), target=b, sender=a)

    def _process_physics_interactions(self) -> None:
        if not self.physics_world:
            return
        # Rigid-body contact pairs.  Manifolds are the authoritative post-step
        # Bullet contact state, allowing clean enter/stay/exit events.
        current_contacts: set[tuple[str, str]] = set()
        try:
            for manifold in self.physics_world.getManifolds():
                if manifold.getNumManifoldPoints() <= 0:
                    continue
                a = self._physics_entity_from_node(manifold.getNode0())
                b = self._physics_entity_from_node(manifold.getNode1())
                if not a or not b or a == b:
                    continue
                pair = tuple(sorted((a, b)))
                if self._interaction_allowed(*pair):
                    current_contacts.add(pair)
        except Exception as exc:
            self.log(f'Physics contact query failed: {exc}')
        for pair in current_contacts - self._contact_pairs:
            self._emit_pair_event('collision_enter', pair[0], pair[1], False)
        for pair in current_contacts & self._contact_pairs:
            self._emit_pair_event('collision_stay', pair[0], pair[1], False)
        for pair in self._contact_pairs - current_contacts:
            self._emit_pair_event('collision_exit', pair[0], pair[1], False)
        self._contact_pairs = current_contacts

        # Trigger/ghost overlap pairs.
        current_triggers: set[tuple[str, str]] = set()
        for trigger_id, np in list(self.physics_ghost_nodes.items()):
            try: overlaps = np.node().getOverlappingNodes()
            except Exception: overlaps = []
            for other_node in overlaps:
                other_id = self._physics_entity_from_node(other_node)
                if not other_id or other_id == trigger_id:
                    continue
                pair = (trigger_id, other_id)
                if self._interaction_allowed(trigger_id, other_id):
                    current_triggers.add(pair)
        for trigger_id, other_id in current_triggers - self._trigger_pairs:
            self._emit_pair_event('trigger_enter', trigger_id, other_id, True)
        for trigger_id, other_id in current_triggers & self._trigger_pairs:
            self._emit_pair_event('trigger_stay', trigger_id, other_id, True)
        for trigger_id, other_id in self._trigger_pairs - current_triggers:
            self._emit_pair_event('trigger_exit', trigger_id, other_id, True)
        self._trigger_pairs = current_triggers

    def _runtime_raycast(self, origin, direction, distance: float = 100.0, mask: int = 0xFFFFFFFF, ignore_entity: str | None = None):
        if not self.physics_world or not self.base:
            return None
        try:
            start = origin if isinstance(origin, Vec3) else Vec3(*[float(v) for v in list(origin)[:3]])
            d = direction if isinstance(direction, Vec3) else Vec3(*[float(v) for v in list(direction)[:3]])
            if d.lengthSquared() <= 1e-12:
                return None
            d.normalize()
            length = max(0.0, float(distance))
            end = start + d * length
            query_mask = int(mask) & 0xFFFFFFFF
            hits = self.physics_world.rayTestAll(start, end)
            candidates = []
            try: raw_hits = list(hits.getHits())
            except Exception: raw_hits = []
            for hit in raw_hits:
                eid = self._physics_entity_from_node(hit.getNode())
                if not eid or eid == ignore_entity:
                    continue
                layer, _ = self._collider_layer_mask(eid)
                if not (query_mask & (1 << layer)):
                    continue
                candidates.append((float(hit.getHitFraction()), hit, eid))
            if not candidates:
                return None
            fraction, hit, eid = min(candidates, key=lambda row: row[0])
            pos = hit.getHitPos(); normal = hit.getHitNormal()
            raw = self.entity_data.get(eid, {})
            return {
                'entity': RuntimeEntity(self, eid), 'id': eid, 'name': str(raw.get('name', eid)),
                'position': [float(pos.x), float(pos.y), float(pos.z)],
                'normal': [float(normal.x), float(normal.y), float(normal.z)],
                'fraction': fraction, 'distance': fraction * length,
                'layer': self._collider_layer_mask(eid)[0],
            }
        except Exception as exc:
            self.log(f'Physics raycast failed: {exc}')
            return None

    def _sync_physics_body_from_entity(self, entity_id: str) -> None:
        if not self.play_mode or not self.base:
            return
        root = self.nodes.get(entity_id)
        np = self.physics_nodes.get(entity_id) or self.physics_ghost_nodes.get(entity_id) or self.physics_characters.get(entity_id)
        if not root or not np:
            return
        try:
            np.setPos(root.getPos(self.base.render)); np.setQuat(root.getQuat(self.base.render))
            if entity_id in self.physics_nodes:
                np.node().setActive(True, True)
        except Exception:
            pass

    def _sync_non_dynamic_physics(self) -> None:
        if not self.base:
            return
        for eid, np in self.physics_nodes.items():
            if self.physics_body_types.get(eid) == 'dynamic':
                continue
            root = self.nodes.get(eid)
            if root:
                np.setPos(root.getPos(self.base.render)); np.setQuat(root.getQuat(self.base.render))
        for eid, np in self.physics_ghost_nodes.items():
            root = self.nodes.get(eid)
            if root:
                np.setPos(root.getPos(self.base.render)); np.setQuat(root.getQuat(self.base.render))

    def _sync_dynamic_from_physics(self) -> None:
        if not self.base:
            return
        for eid, np in self.physics_nodes.items():
            if self.physics_body_types.get(eid) != 'dynamic':
                continue
            root = self.nodes.get(eid)
            if not root:
                continue
            try:
                root.setPos(self.base.render, np.getPos(self.base.render))
                root.setQuat(self.base.render, np.getQuat(self.base.render))
            except Exception:
                pass


    def _enable_terrain_geometry_picking(self, entity_id: str, root: NodePath) -> None:
        """Make only generated terrain triangles pickable; never use the terrain AABB.

        A terrain-sized CollisionBox masks small scene objects resting on or above the
        terrain. Direct GeomNode picking lets the closest visible triangle win instead.
        """
        try:
            count = 0
            terrain_state = self.terrains.get(str(entity_id)) or {}
            terrain_root = terrain_state.get('root')
            search_root = terrain_root if terrain_root and not terrain_root.isEmpty() else root
            for geom_np in search_root.findAllMatches('**/+GeomNode'):
                geom_np.setCollideMask(self.PICK_MASK)
                geom_np.setTag('entity_id', str(entity_id))
                geom_np.setTag('terrain_pick_surface', '1')
                count += 1
            if count == 0:
                self.log(f'Viewport: terrain geometry for {root.getName()} has no pickable GeomNodes yet.')
            else:
                self.log(f'Viewport: terrain triangle picking enabled for {root.getName()} ({count} GeomNode(s)).')
        except Exception as exc:
            self.log(f'Viewport: terrain geometry picking failed for {root.getName()}: {exc}')

    def _refresh_authoring_terrain(self, entity_id: str | None) -> None:
        if self.play_mode or not entity_id:
            return
        eid=str(entity_id); raw=self.entity_data.get(eid)
        if not raw: return
        root=self.nodes.get(eid); comp=(raw.get('components') or {}).get('terrain') or {}
        if not root or not comp: return
        self._build_terrain_component(eid, root, str(raw.get('name', eid)), comp)
        self._enable_terrain_geometry_picking(eid, root)
        if self.selected == eid:
            self._build_selection_helper()

    def _set_terrain_edit(self, enabled: bool, entity_id: str | None, mode: str, radius: float, strength: float, falloff: float) -> None:
        self.terrain_edit_enabled=bool(enabled) and bool(entity_id)
        self.terrain_edit_entity=str(entity_id) if self.terrain_edit_enabled else None
        self.terrain_edit_mode=str(mode or 'raise').lower()
        self.terrain_edit_radius=max(.1,float(radius or 4.0))
        self.terrain_edit_strength=max(.01,min(1.0,float(strength or .5)))
        self.terrain_edit_falloff=max(.05,min(1.0,float(falloff or .65)))
        self._terrain_brush_down=False
        self._terrain_brush_last_point=None
        if not self.terrain_edit_enabled and self._terrain_brush_cursor:
            self._terrain_brush_cursor.removeNode(); self._terrain_brush_cursor=None
        self._rebuild_gizmo()

    def _terrain_hit_at_mouse(self) -> tuple[str, Point3, Point3] | None:
        """Ray-test the active heightfield directly instead of relying on GeoMip collision entries.

        GeoMipTerrain rebuilds/adapts its render geometry for LOD.  Using those GeomNodes
        as the *authoring brush* collision target proved unreliable: on some Panda builds the
        collision traverser returns no surface entry even though the terrain renders correctly.
        Sculpting therefore performs an analytic ray/heightfield intersection against the
        authored terrain data.  Normal scene picking can still use render geometry separately.
        """
        if not (self.base and self.base.mouseWatcherNode.hasMouse() and self.terrain_edit_entity):
            return None
        eid=str(self.terrain_edit_entity); root=self.nodes.get(eid); state=self.terrains.get(eid)
        if not root or not state:
            return None
        try:
            m=self.base.mouseWatcherNode.getMouse()
            near_cam=Point3(); far_cam=Point3()
            if not self.base.camNode.getLens().extrude(m, near_cam, far_cam):
                return None
            near_world=self.base.render.getRelativePoint(self.base.camera, near_cam)
            far_world=self.base.render.getRelativePoint(self.base.camera, far_cam)
            a=root.getRelativePoint(self.base.render, near_world)
            b=root.getRelativePoint(self.base.render, far_world)
            d=b-a
            comp=state.get('component') or {}; size=list(comp.get('size',[64.0,64.0]))+[64.0,64.0]
            sx=max(.001,float(size[0])); sy=max(.001,float(size[1]))

            # Clip the ray segment to the terrain XY footprint.
            t0,t1=0.0,1.0
            for origin,delta,lo,hi in ((a.x,d.x,0.0,sx),(a.y,d.y,0.0,sy)):
                if abs(delta) < 1e-10:
                    if origin < lo or origin > hi: return None
                    continue
                ta=(lo-origin)/delta; tb=(hi-origin)/delta
                if ta>tb: ta,tb=tb,ta
                t0=max(t0,ta); t1=min(t1,tb)
                if t0>t1: return None
            t0=max(0.0,t0); t1=min(1.0,t1)
            if t0>t1: return None

            # Find the first ray crossing of z - terrain_height.  Step density scales
            # with heightfield resolution, then binary-refine for a stable brush point.
            samples=max(48,min(320,int(max(state.get('width',129),state.get('height',129)))*2))
            prev_t=t0; prev_p=a+d*prev_t
            prev_h=self._terrain_sample_local(eid,prev_p.x,prev_p.y)
            if prev_h is None: return None
            prev_f=float(prev_p.z)-float(prev_h)
            best=(abs(prev_f),prev_t)
            hit_pair=None
            for i in range(1,samples+1):
                t=t0+(t1-t0)*(i/samples); p=a+d*t
                h=self._terrain_sample_local(eid,p.x,p.y)
                if h is None: continue
                f=float(p.z)-float(h)
                if abs(f)<best[0]: best=(abs(f),t)
                if (prev_f>=0.0 and f<=0.0) or (prev_f<=0.0 and f>=0.0):
                    hit_pair=(prev_t,t); break
                prev_t,prev_f=t,f
            if hit_pair:
                lo,hi=hit_pair
                for _ in range(14):
                    mid=(lo+hi)*.5; p=a+d*mid; h=self._terrain_sample_local(eid,p.x,p.y)
                    if h is None: break
                    f=float(p.z)-float(h)
                    plo=a+d*lo; hlo=self._terrain_sample_local(eid,plo.x,plo.y)
                    flo=float(plo.z)-float(hlo if hlo is not None else plo.z)
                    if (flo>=0.0 and f<=0.0) or (flo<=0.0 and f>=0.0): hi=mid
                    else: lo=mid
                t=(lo+hi)*.5
            else:
                # A nearly tangent ray may not change sign.  Accept a close sample only.
                tolerance=max(.05,float(comp.get('height_scale',12.0))*.01)
                if best[0] > tolerance: return None
                t=best[1]
            local=a+d*t
            h=self._terrain_sample_local(eid,local.x,local.y)
            if h is None: return None
            local=Point3(float(local.x),float(local.y),float(h))
            world=self.base.render.getRelativePoint(root,local)
            return eid,local,Point3(world)
        except Exception as exc:
            self.log(f'Terrain sculpt ray test failed: {exc}')
            return None

    def _update_terrain_brush_cursor(self) -> None:
        if not self.base or not self.terrain_edit_enabled:
            return
        hit=self._terrain_hit_at_mouse()
        if not hit:
            if self._terrain_brush_cursor: self._terrain_brush_cursor.hide()
            return
        _eid,_local,world=hit
        if self._terrain_brush_cursor:
            self._terrain_brush_cursor.removeNode()
        segs=LineSegs('terrain-brush-cursor'); segs.setThickness(2.0); segs.setColor(0.16,0.78,1.0,1.0)
        steps=48; r=self.terrain_edit_radius
        for i in range(steps+1):
            a=(i/steps)*math.tau; p=Point3(world.x+math.cos(a)*r, world.y+math.sin(a)*r, world.z+.04)
            if i==0: segs.moveTo(p)
            else: segs.drawTo(p)
        self._terrain_brush_cursor=self.base.render.attachNewNode(segs.create())
        self._isolate_editor_helper(self._terrain_brush_cursor)
        self._terrain_brush_cursor.setDepthTest(False); self._terrain_brush_cursor.setBin('fixed',35); self._terrain_brush_cursor.setTag('editor_helper','1')

    def _emit_terrain_brush_point(self, phase: str) -> bool:
        hit=self._terrain_hit_at_mouse()
        if hit:
            eid,local,_world=hit
            lx,ly=float(local.x),float(local.y)
            self._terrain_brush_last_point=(eid,lx,ly)
        elif phase == 'end' and self._terrain_brush_last_point:
            eid,lx,ly=self._terrain_brush_last_point
        else:
            return False
        if str(self.terrain_edit_mode).startswith('paint'):
            self._terrain_live_paint(eid,lx,ly,self.terrain_edit_mode,self.terrain_edit_radius,self.terrain_edit_strength,self.terrain_edit_falloff,phase)
        self.event('terrain_brush', entity_id=eid, phase=phase, local_x=lx, local_y=ly, mode=self.terrain_edit_mode, radius=self.terrain_edit_radius, strength=self.terrain_edit_strength, falloff=self.terrain_edit_falloff)
        if phase == 'end':
            self._terrain_brush_last_point=None
        return True

    def _enable_model_geometry_picking(self, entity_id: str, root: NodePath) -> None:
        """Use imported model geometry for editor picking instead of one giant AABB.

        A tight bounding box is useful for selection visualization, but it is a poor
        hit proxy for sparse/large assemblies because empty space inside the box
        blocks objects behind it.  Panda's collision traverser can ray-test GeomNode
        triangles directly when the GeomNodes carry the pick mask.
        """
        try:
            count = 0
            for geom_np in root.findAllMatches('**/+GeomNode'):
                name = geom_np.getName().lower()
                # Editor helpers are GeomNodes too; never make those pickable, even
                # when a copied GLB child keeps its original node name.
                cur = geom_np
                helper_ancestor = False
                while cur and cur != root:
                    if cur.hasTag('editor_helper'):
                        helper_ancestor = True
                        break
                    cur = cur.getParent()
                if helper_ancestor or any(token in name for token in ('helper', 'gizmo', 'collider')):
                    continue
                geom_np.setCollideMask(self.PICK_MASK)
                geom_np.setTag('entity_id', entity_id)
                count += 1
            if count == 0:
                # Models without usable GeomNodes still get the legacy fallback.
                self._build_pick_bounds(entity_id, root)
            else:
                self.log(f'Viewport: geometry picking enabled for {root.getName()} ({count} GeomNode(s)).')
        except Exception as exc:
            self.log(f'Viewport: geometry picking failed for {root.getName()}: {exc}; using bounds fallback.')
            self._build_pick_bounds(entity_id, root)

    def _build_pick_bounds(self, entity_id: str, root: NodePath) -> None:
        try:
            bounds = root.getTightBounds()
            if not bounds or bounds[0] is None or bounds[1] is None:
                lo, hi = Point3(-0.35, -0.35, -0.35), Point3(0.35, 0.35, 0.35)
            else:
                lo, hi = bounds
            center = (lo + hi) * 0.5
            half = (hi - lo) * 0.5
            cnode = CollisionNode('pick-' + entity_id)
            cnode.setIntoCollideMask(self.PICK_MASK)
            cnode.setFromCollideMask(BitMask32.allOff())
            cnode.addSolid(CollisionBox(center, max(.08, half.x), max(.08, half.y), max(.08, half.z)))
            np = root.attachNewNode(cnode)
            np.setTag('entity_id', entity_id)
            self.pick_nodes[entity_id] = np
        except Exception as exc:
            self.log(f'Viewport: could not build pick bounds for {root.getName()}: {exc}')

    def _select(self, entity_id: str | None) -> None:
        self.selected = entity_id
        if not self.base:
            return
        if self.selection_helper:
            self.selection_helper.removeNode()
            self.selection_helper = None
        if self.gizmo:
            self.gizmo.removeNode()
            self.gizmo = None
        root = self.nodes.get(entity_id or '')
        if not root:
            return

        # A depth-independent wire box avoids z-fighting with the grid/floor.
        try:
            lo, hi = root.getTightBounds(root)
            if lo is None or hi is None:
                return
            pts = [
                (lo.x, lo.y, lo.z), (hi.x, lo.y, lo.z), (hi.x, hi.y, lo.z), (lo.x, hi.y, lo.z),
                (lo.x, lo.y, hi.z), (hi.x, lo.y, hi.z), (hi.x, hi.y, hi.z), (lo.x, hi.y, hi.z),
            ]
            edges = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
            segs = LineSegs('selection-helper')
            segs.setThickness(2.2)
            segs.setColor(1.0, 0.58, 0.06, 1)
            for a, b in edges:
                segs.moveTo(*pts[a]); segs.drawTo(*pts[b])
            helper = root.attachNewNode(segs.create())
            self._isolate_editor_helper(helper)
            helper.setDepthTest(False)
            helper.setDepthWrite(False)
            helper.setBin('fixed', 50)
            self.selection_helper = helper
        except Exception:
            pass
        self._rebuild_gizmo()

    def _rebuild_gizmo(self) -> None:
        if not self.base:
            return
        if self.gizmo:
            self.gizmo.removeNode(); self.gizmo = None
        for np in self.gizmo_hit_nodes:
            try: np.removeNode()
            except Exception: pass
        self.gizmo_hit_nodes.clear()
        root = self.nodes.get(self.selected or '')
        if not root or self.tool_mode == 'select':
            return
        if root.hasTag('editor_locked') and root.getTag('editor_locked') == '1':
            return
        segs = LineSegs('transform-gizmo')
        segs.setThickness(3.0)
        colors = {'x': (0.95,0.22,0.22,1), 'y': (0.25,0.90,0.38,1), 'z': (0.28,0.55,1.0,1)}
        active = self._axis_constraint
        if self.tool_mode in {'move', 'scale'}:
            axes = {'x': Vec3(1,0,0), 'y': Vec3(0,1,0), 'z': Vec3(0,0,1)}
            for name, vec in axes.items():
                c = (1.0,0.78,0.15,1) if active == name else colors[name]
                segs.setColor(*c); segs.moveTo(0,0,0); segs.drawTo(vec * 1.65)
                end = vec * 1.65
                # Small cross-cap distinguishes scale from move without geometry-heavy handles.
                if self.tool_mode == 'scale':
                    segs.moveTo(end + Vec3(-.08,-.08,-.08)); segs.drawTo(end + Vec3(.08,.08,.08))
        else:
            # Three lightweight rotation rings.
            radius = 1.15; steps = 48
            for name in ('x','y','z'):
                c = (1.0,0.78,0.15,1) if active == name else colors[name]
                segs.setColor(*c)
                for i in range(steps+1):
                    a = (i/steps) * math.tau
                    if name == 'x': pt = Vec3(0, math.cos(a)*radius, math.sin(a)*radius)
                    elif name == 'y': pt = Vec3(math.cos(a)*radius, 0, math.sin(a)*radius)
                    else: pt = Vec3(math.cos(a)*radius, math.sin(a)*radius, 0)
                    if i == 0: segs.moveTo(pt)
                    else: segs.drawTo(pt)
        self.gizmo = self.base.render.attachNewNode(segs.create())
        self._isolate_editor_helper(self.gizmo)
        self.gizmo.setPos(root.getPos(self.base.render))
        self.gizmo.setDepthTest(False); self.gizmo.setDepthWrite(False); self.gizmo.setBin('fixed', 60)

        # Dedicated editor hit geometry makes handles clickable without making the
        # visible gizmo itself part of normal scene picking.
        axes = {'x': Vec3(1,0,0), 'y': Vec3(0,1,0), 'z': Vec3(0,0,1)}
        if self.tool_mode in {'move', 'scale'}:
            for name, vec in axes.items():
                cn = CollisionNode('gizmo-' + name)
                cn.setIntoCollideMask(self.GIZMO_MASK); cn.setFromCollideMask(BitMask32.allOff())
                cn.addSolid(CollisionCapsule(Point3(0,0,0), Point3(*(vec * 1.72)), 0.13))
                np = self.gizmo.attachNewNode(cn); np.setTag('gizmo_axis', name)
                self.gizmo_hit_nodes.append(np)
        else:
            radius = 1.15
            for name in ('x','y','z'):
                cn = CollisionNode('gizmo-ring-' + name)
                cn.setIntoCollideMask(self.GIZMO_MASK); cn.setFromCollideMask(BitMask32.allOff())
                for i in range(20):
                    a = (i/20.0) * math.tau
                    if name == 'x': pt = Vec3(0, math.cos(a)*radius, math.sin(a)*radius)
                    elif name == 'y': pt = Vec3(math.cos(a)*radius, 0, math.sin(a)*radius)
                    else: pt = Vec3(math.cos(a)*radius, math.sin(a)*radius, 0)
                    cn.addSolid(CollisionSphere(Point3(pt), 0.10))
                np = self.gizmo.attachNewNode(cn); np.setTag('gizmo_axis', name)
                self.gizmo_hit_nodes.append(np)
        self._update_gizmo_scale()

    def _update_gizmo_scale(self) -> None:
        if not self.gizmo:
            return
        root = self.nodes.get(self.selected or '')
        if root:
            self.gizmo.setPos(root.getPos(self.base.render))
        scale = max(0.15, self.camera_distance * 0.055)
        self.gizmo.setScale(scale)

    def _frame_selected(self) -> None:
        if not self.base or not self.selected:
            return
        root = self.nodes.get(self.selected)
        if not root:
            return
        lo, hi = root.getTightBounds(self.base.render)
        if lo is None or hi is None:
            p = root.getPos(self.base.render)
            radius = 1.0
        else:
            p = (lo + hi) * 0.5
            radius = max(0.5, (hi - lo).length() * 0.5)
        self.camera_target = Vec3(p)
        self.camera_distance = max(2.5, radius * 3.2)
        self._apply_editor_camera()


    def _frame_all(self) -> None:
        if not self.base or not self.nodes:
            return
        lows = []
        highs = []
        for root in self.nodes.values():
            if not root or root.isEmpty() or root.isHidden():
                continue
            try:
                lo, hi = root.getTightBounds(self.base.render)
            except Exception:
                lo = hi = None
            if lo is not None and hi is not None:
                lows.append(lo); highs.append(hi)
        if not lows:
            return
        lo = Point3(min(p.x for p in lows), min(p.y for p in lows), min(p.z for p in lows))
        hi = Point3(max(p.x for p in highs), max(p.y for p in highs), max(p.z for p in highs))
        center = (lo + hi) * 0.5
        radius = max(0.5, (hi - lo).length() * 0.5)
        self.camera_target = Vec3(center)
        self.camera_distance = max(3.0, radius * 2.8)
        self._apply_editor_camera()
        self._update_lens_geometry()

    def _restore_editor_lens(self) -> None:
        if not self.base:
            return
        aspect = max(0.1, self.rect[2] / max(1, self.rect[3]))
        if self.perspective:
            lens = PerspectiveLens()
            lens.setFov(48)
            lens.setAspectRatio(aspect)
            lens.setNearFar(0.10, 5000)
        else:
            lens = OrthographicLens()
            height = max(0.5, self.camera_distance * 0.90)
            lens.setFilmSize(height * aspect, height)
            lens.setNearFar(0.10, 5000)
        self.base.cam.node().setLens(lens)

    def _preview_camera(self, entity_id: str | None) -> None:
        if self.play_mode:
            return
        entity_id = str(entity_id) if entity_id else None
        if entity_id and entity_id not in self.nodes:
            return
        self.preview_camera_id = entity_id
        if entity_id:
            self._apply_preview_camera()
        else:
            self._restore_editor_lens()
            self._apply_editor_camera()
        self.event('camera_preview_changed', entity_id=self.preview_camera_id)

    def _apply_preview_camera(self) -> None:
        if not (self.base and self.preview_camera_id):
            return
        root = self.nodes.get(self.preview_camera_id)
        raw = self.entity_data.get(self.preview_camera_id, {})
        component = (raw.get('components') or {}).get('camera') or {}
        if not root or not component:
            self.preview_camera_id = None
            self._restore_editor_lens()
            self._apply_editor_camera()
            self.event('camera_preview_changed', entity_id=None)
            return
        self.base.camera.setPos(root.getPos(self.base.render))
        self.base.camera.setHpr(root.getHpr(self.base.render))
        aspect = max(0.1, self.rect[2] / max(1, self.rect[3]))
        near = max(0.001, float(component.get('near', 0.1)))
        far = max(near + 0.01, float(component.get('far', 2000.0)))
        if str(component.get('projection', 'perspective')).lower() == 'orthographic':
            lens = OrthographicLens()
            size = max(0.1, float(component.get('ortho_size', 10.0)))
            lens.setFilmSize(size * aspect, size)
            lens.setNearFar(near, far)
        else:
            lens = PerspectiveLens()
            lens.setFov(max(1.0, min(179.0, float(component.get('fov', 60.0)))))
            lens.setAspectRatio(aspect)
            lens.setNearFar(near, far)
        self.base.cam.node().setLens(lens)

    def _apply_visual_render_mode(self, visual: NodePath) -> None:
        try:
            if self.wireframe:
                visual.setRenderModeWireframe(30)
            else:
                visual.setRenderModeFilled(30)
        except Exception:
            pass

    def _set_wireframe(self, enabled: bool) -> None:
        self.wireframe = bool(enabled)
        for root in list(self.nodes.values()):
            if root and not root.isEmpty():
                for source in self._geometry_sources(root):
                    self._apply_visual_render_mode(source)
        self.event('wireframe_changed', enabled=self.wireframe)

    def _apply_grid_for_preset(self, preset: str) -> None:
        if not self.grid_np or self.grid_np.isEmpty():
            return
        p = str(preset or '').lower()
        try:
            self.grid_np.setHpr(0, 0, 0)
            if p in {'front', 'back'}:
                # XY ground grid -> XZ front/back construction plane.
                self.grid_np.setP(90)
            elif p in {'left', 'right'}:
                # XY ground grid -> YZ side construction plane.
                self.grid_np.setR(90)
        except Exception:
            pass

    def _set_camera_preset(self, preset: str) -> None:
        if not self.base or self.play_mode or self.preview_camera_id:
            return
        p = str(preset or '').strip().lower()
        presets = {
            'front': (0.0, 0.0),
            'back': (180.0, 0.0),
            'right': (90.0, 0.0),
            'left': (-90.0, 0.0),
            'top': (0.0, 89.9),
            'bottom': (0.0, -89.9),
            'perspective': (-32.0, 27.0),
        }
        if p not in presets:
            return
        self.camera_preset = p
        self.camera_heading, self.camera_pitch = presets[p]
        self._apply_grid_for_preset(p)
        if p != 'perspective':
            if self.perspective:
                self.perspective = False
                self._restore_editor_lens()
                self.event('projection_changed', perspective=False)
        else:
            if not self.perspective:
                self.perspective = True
                self._restore_editor_lens()
                self.event('projection_changed', perspective=True)
        self._apply_editor_camera()
        self.event('camera_preset_changed', preset=p)

    def _ensure_arrow_cursor(self) -> None:
        """Reset the Win32 cursor when crossing WebView scrollbars into Panda.

        WebView2 can leave a scrollbar/resize cursor active when the pointer crosses
        directly into the native Panda child HWND.  Reasserting IDC_ARROW while the
        Panda mouse watcher owns the pointer prevents the stale cursor state without
        interfering with Play Mode mouse capture.
        """
        if os.name != 'nt' or self._mouse_captured:
            return
        try:
            import ctypes
            IDC_ARROW = 32512
            cur = ctypes.windll.user32.LoadCursorW(None, IDC_ARROW)
            if cur:
                ctypes.windll.user32.SetCursor(cur)
        except Exception:
            pass

    def _toggle_projection(self) -> None:
        if self.play_mode:
            return
        if not self.base or self.preview_camera_id:
            return
        self.perspective = not self.perspective
        self._restore_editor_lens()
        self.event('projection_changed', perspective=self.perspective)


def panda_viewport_process(parent_hwnd: int, commands, messages) -> None:
    try:
        PandaProcessRuntime(parent_hwnd, commands, messages).run()
    except BaseException:
        try:
            messages.put({'type': 'log', 'message': 'Viewport process fatal error:\n' + traceback.format_exc()})
        except Exception:
            pass
        raise
    finally:
        try:
            messages.put(None)
        except Exception:
            pass
