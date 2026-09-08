"""Panda Editor 0.4.31 example: repeating task callbacks with a flickering light.

This example intentionally uses the direct ``method=`` form of ``world.task_every``.
Runtime-created tasks start immediately; ``entity.task_start()`` is only needed when
starting/resetting a task authored in the entity's Tasks / Events component.
"""

import random


class EntityScript:
    def on_start(self, entity, world):
        world.log("Light flicker task started")

        # Direct method timer:
        #   every 0.12 seconds Panda Editor calls
        #   self.do_light_flicker(entity, world, payload)
        # on this entity's script.
        world.task_every(
            0.12,
            target=entity.id,
            name="light_flicker",
            method="do_light_flicker",
            payload={"source": "script"},
        )

        # No entity.task_start("light_flicker") is required here.
        # world.task_every() creates an already-running runtime task.

    def do_light_flicker(self, entity, world, payload):
        """Managed-task callback: self + entity + world + task payload."""
        if not entity.has_light:
            world.log("Flicker target has no Light component")
            return

        # Mostly bright, with occasional darker dips for a broken-lamp look.
        intensity = random.uniform(0.25, 1.1)
        if random.random() < 0.18:
            intensity = random.uniform(0.03, 0.18)

        entity.light_configure(
            intensity=intensity * 6.0,
            range=random.uniform(18.0, 28.0),
        )

    def on_update(self, entity, world, dt):
        pass

    def on_event(self, entity, world, event_name, payload):
        # Event-style timers arrive here instead. Example:
        # world.task_every(0.5, "flicker_event", target=entity.id)
        # if event_name == "flicker_event":
        #     self.do_light_flicker(entity, world, payload)
        pass

    def on_stop(self, entity, world):
        # Managed runtime tasks are cleared automatically when Play stops.
        pass
