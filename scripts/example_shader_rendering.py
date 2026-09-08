"""Panda Editor 0.4.14: GLSL shader + post-processing runtime API example."""
import math

class EntityScript:
    def on_start(self, entity, world):
        self.elapsed = 0.0
        if entity.has_shader:
            entity.shader_set_input("tint", [0.15, 0.7, 1.0, 1.0])
        world.log(f"Render pipeline: {world.render_pipeline}")

    def on_update(self, entity, world, dt):
        self.elapsed += dt
        if entity.has_shader:
            pulse = 0.5 + 0.5 * math.sin(self.elapsed * 3.0)
            entity.shader_set_input("pulse", pulse)

    def on_event(self, entity, world, event_name, payload):
        if event_name == "bloom_on":
            world.post_process_set("bloom", True, intensity=1.2, size="medium")
        elif event_name == "bloom_off":
            world.post_process_set("bloom", False)
        elif event_name == "reload_shader":
            entity.shader_reload()
