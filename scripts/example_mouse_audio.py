"""0.2.4 mouse + audio example."""

class EntityScript:
    def on_start(self, entity, world):
        world.capture_mouse(True)
        world.log("Mouse captured. Move the mouse; left click plays the attached sound.")

    def on_update(self, entity, world, dt):
        dx, dy = world.mouse_delta
        if abs(dx) + abs(dy) > 0.0001:
            entity.rotate(h=-dx * 85.0, p=dy * 60.0)
        if world.mouse_down("mouse1"):
            if not getattr(self, "held", False):
                entity.audio_play()
            self.held = True
        else:
            self.held = False

    def on_stop(self, entity, world):
        world.capture_mouse(False)
