"""Panda Editor 0.4.14 example: enriched runtime API.

Attach to an entity with a Character Controller to exercise the new facing API.
The script also demonstrates generic entity discovery and component inspection.
"""


class EntityScript:
    def on_start(self, entity, world):
        self.turn_speed = 120.0
        self.move_speed = 5.0
        world.log(f"Enhanced API ready: {entity.name}")
        world.log(f"Components: {entity.component_names}")
        world.log(f"World position: {entity.world_position}")

        # Discover scene content without hard-coded IDs.
        lights = world.entities_with_component("light")
        world.log(f"Discovered {len(lights)} light(s)")

        if entity.has_character_controller:
            entity.character_configure(jump_speed=7.0, max_jump_height=2.0)
            world.log(f"Character heading: {entity.character_heading:.1f}")

    def on_update(self, entity, world, dt):
        if entity.has_character_controller:
            x = world.action_axis("move_left", "move_right")
            y = world.action_axis("move_backward", "move_forward")
            entity.character_move(x=x * self.move_speed, y=y * self.move_speed, local=True)

            # Physics Character Controller angular movement. Panda Bullet expects deg/sec directly.
            turn = world.action_axis("turn_left", "turn_right")
            if turn:
                entity.character_turn(turn * self.turn_speed)

            if world.action_pressed("jump") and entity.grounded:
                entity.character_jump()

        # Generic facing/query example for any RuntimeEntity.
        target = world.find("Target")
        if target and entity.distance_to(target) < 10.0 and world.action_pressed("interact"):
            entity.look_at(target, keep_upright=True)
            world.log(f"Facing Target; direction={entity.direction_to(target)}")

    def on_event(self, entity, world, event_name, payload):
        if event_name == "low_gravity":
            world.set_gravity(z=-3.0)
        elif event_name == "normal_gravity":
            world.set_gravity(z=-9.81)
