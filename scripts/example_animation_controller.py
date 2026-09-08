"""Panda Editor Actor/Animation runtime example.

Attach this script to an entity that has both a Model and Animation component.
The model should contain one or more animation clips, such as an animated glTF/GLB.
"""


class EntityScript:
    def on_start(self, entity, world):
        clips = entity.animation_names
        world.log(f"{entity.name} animation clips: {clips}")
        if clips:
            entity.animation_loop(clips[0])

    def on_update(self, entity, world, dt):
        # Example: press interact to replay the authored/default clip once.
        if world.action_pressed("interact") and entity.has_animation:
            entity.animation_play()

    def on_stop(self, entity, world):
        entity.animation_stop()
