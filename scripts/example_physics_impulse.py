"""POC 0.1.9 physics example.

Attach this script to an entity that has both Collider and a Dynamic Rigid Body.
The body receives one upward/sideways impulse when Play Mode starts.
"""


class EntityScript:
    def on_start(self, entity, world):
        if not entity.has_physics:
            world.log(f"{entity.name}: no runtime physics body is attached")
            return
        entity.apply_impulse(x=1.5, y=0.0, z=4.0)
        world.log(f"Impulse applied to {entity.name}")

    def on_update(self, entity, world, dt):
        # Press Space to add another upward impulse.
        if world.key_down("space") and getattr(self, "_space_ready", True):
            entity.apply_impulse(z=3.0)
            self._space_ready = False
        elif not world.key_down("space"):
            self._space_ready = True
