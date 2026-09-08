"""Panda Editor 0.4.2 example: terrain sampling and runtime LOD API."""

class EntityScript:
    def on_start(self, entity, world):
        self.terrain = world.find("Landscape")
        if self.terrain and self.terrain.has_terrain:
            world.log(f"Terrain config: {self.terrain.terrain_config}")

    def on_update(self, entity, world, dt):
        if not self.terrain or not self.terrain.has_terrain:
            return
        x, y, z = entity.position
        ground = self.terrain.terrain_height(x, y)
        if ground is not None:
            entity.position = [x, y, ground + 1.0]

        # Toggle full-detail terrain at runtime with the existing interact action.
        if world.action_pressed("interact"):
            current = bool(self.terrain.terrain_get("bruteforce", False))
            self.terrain.terrain_set("bruteforce", not current)
            world.log(f"Terrain bruteforce: {not current}")
