"""Panda Editor 0.4.14: verified Bullet Character Controller turning example.

Default bindings added in 0.4.14:
  Q = turn left
  R = turn right
  W/S = forward/back
  A/D = strafe
"""

class EntityScript:
    def on_start(self, entity, world):
        self.move_speed = 5.0
        self.turn_speed = 120.0
        if entity.has_character_controller:
            world.log("Character turning ready: Q/R = 120 degrees/sec")

    def on_update(self, entity, world, dt):
        if not entity.has_character_controller:
            return

        x = world.action_axis("move_left", "move_right")
        y = world.action_axis("move_backward", "move_forward")
        turn = world.action_axis("turn_left", "turn_right")

        entity.character_move(x=x * self.move_speed, y=y * self.move_speed, local=True)
        entity.character_turn(turn * self.turn_speed)

        if world.action_pressed("jump") and entity.grounded:
            entity.character_jump()
