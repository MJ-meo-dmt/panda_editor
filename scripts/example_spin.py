"""Example Panda Editor Play Mode script.

Attach this file as a Script component to an entity, or copy its logic into the
script created by the Inspector. Runtime changes are discarded when Play stops.
"""


class EntityScript:
    def on_start(self, entity, world):
        self.speed = 35.0
        world.log(f"Started {entity.name}")

    def on_update(self, entity, world, dt):
        # Panda H/P/R rotation in degrees.
        entity.rotate(h=self.speed * dt)

    def on_event(self, entity, world, event_name, payload):
        pass

    def on_stop(self, entity, world):
        world.log(f"Stopped {entity.name}")
