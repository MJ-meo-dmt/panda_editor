"""POC 0.2.1 character controller + Input Map example."""

class EntityScript:
    def on_start(self, entity, world):
        self.walk_speed = 5.0
        self.sprint_speed = 8.0
        world.log(f"Character ready: {entity.name}")

    def on_update(self, entity, world, dt):
        x = world.action_axis('move_left', 'move_right')
        y = world.action_axis('move_backward', 'move_forward')
        speed = self.sprint_speed if world.action_down('sprint') else self.walk_speed
        entity.character_move(x=x * speed, y=y * speed, local=True)

        if world.action_pressed('jump'):
            entity.character_jump()

        if world.action_pressed('interact'):
            hit = entity.raycast(y=1, z=0.15, distance=3.0)
            if hit:
                world.log(f"Interact ray hit: {hit['name']}")

    def on_stop(self, entity, world):
        world.log(f"Character stopped: {entity.name}")
