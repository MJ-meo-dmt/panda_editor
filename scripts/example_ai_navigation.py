"""Panda Editor 0.4.16 AI / Navigation example."""

class EntityScript:
    def on_start(self, entity, world):
        self.player = world.find("Player")
        if self.player and entity.has_navigation_agent:
            entity.navigation_chase(self.player, repath_interval=0.25)
            world.log("Navigation chase started")

    def on_update(self, entity, world, dt):
        if world.action_pressed("interact") and self.player:
            # Switch to flee for a quick behavior test.
            entity.navigation_flee(self.player, distance=10.0, repath_interval=0.25)

    def on_event(self, entity, world, event_name, payload):
        if event_name == "navigation_finished":
            world.log(f"{entity.name} reached its navigation target")

    def on_stop(self, entity, world):
        pass
