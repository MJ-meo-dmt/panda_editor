"""Panda Editor 0.4.12 example: Tasks/Events + Intervals + Render Attributes."""


class EntityScript:
    def on_start(self, entity, world):
        world.log("0.4.12 systems demo started")
        world.log(f"Authored intervals: {entity.interval_names}")
        if entity.has_render_attributes:
            world.log(f"Render attributes: {entity.render_attributes}")

        # Inspect/pause/resume a repeating authored task without resetting cadence.
        info = world.task_info("Pulse")
        if info:
            world.log(f"Pulse task: {info}")

        # A runtime-created Sequence uses the same Panda Interval layer as authored clips.
        world.interval_sequence(
            "Runtime Nudge",
            [
                {"type": "move", "target": entity.id, "duration": 0.45, "to": [0, 1.5, 0], "blend": "easeInOut"},
                {"type": "wait", "duration": 0.15},
                {"type": "move", "target": entity.id, "duration": 0.45, "to": [0, 0, 0], "blend": "easeInOut"},
            ],
            owner=entity.id,
        )

    def on_event(self, entity, world, event_name, payload):
        if event_name == "pulse":
            # Runtime-only render-state changes. Stop restores authored values.
            alpha = 0.55 if entity.render_attributes.get("color_scale", [1, 1, 1, 1])[3] > 0.8 else 1.0
            entity.render_set("color_scale", [1.0, 1.0, 1.0, alpha])
            entity.render_set("transparency", "alpha" if alpha < 1.0 else "inherit")

        elif event_name == "pulse_finished":
            world.log("Finite Pulse task completed")
            entity.interval_start("Move + Turn")

        elif event_name == "interval_done":
            world.log("Authored Move + Turn interval completed")
            entity.render_reset()
