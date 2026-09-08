"""Panda Editor 0.4.15 Camera Systems example.
Attach to the Player entity in camera_systems_demo.pscene.
"""

class EntityScript:
    def on_start(self, entity, world):
        self.camera = world.find("Follow Camera")
        self.orbit = world.find("Orbit Camera")
        if self.camera:
            self.camera.camera_follow(entity, offset=[0, -7, 3], damping=10, look_at=True)
            self.camera.camera_activate()

    def on_update(self, entity, world, dt):
        if world.action_pressed("interact") and self.orbit:
            self.orbit.camera_orbit(entity, distance=8, pitch=24, damping=10)
            self.orbit.camera_activate(blend=0.6)
        if self.orbit and world.active_camera and world.active_camera.id == self.orbit.id:
            md = world.mouse_delta()
            if world.mouse_down("mouse3"):
                self.orbit.camera_orbit_input(heading_delta=-md[0]*120, pitch_delta=md[1]*90)
        if world.action_pressed("jump"):
            world.camera_shake(strength=0.18, duration=0.28, rotation=1.0)
