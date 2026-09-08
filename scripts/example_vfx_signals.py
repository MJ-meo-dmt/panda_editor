class EntityScript:
    def on_start(self, entity, world):
        world.log("VFX signal demo ready")

    def on_event(self, entity, world, event_name, payload):
        if event_name == "burst_fx":
            fx = world.find("Impact FX")
            if fx:
                fx.particles_burst(36)
