"""Panda Editor 0.4.1 example: FSM + animation + live VFX API."""

class EntityScript:
    def on_start(self, entity, world):
        if entity.has_fsm:
            world.log(f"FSM starts in {entity.fsm_state}")

    def on_update(self, entity, world, dt):
        if entity.has_fsm and world.action_pressed("interact"):
            entity.fsm_send("interact")

    def on_event(self, entity, world, event_name, payload):
        if event_name == "enter_attack":
            fx = world.find("Impact FX")
            if fx and fx.has_particles:
                fx.particles_configure(rate=60, speed=7.0, lifetime=0.7, drag=0.25, blend_mode="additive")
                fx.particles_burst(32)
