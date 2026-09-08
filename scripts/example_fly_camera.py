"""Panda Editor beginner example: keyboard + mouse free-fly camera.

Attach this script to an ACTIVE Camera entity whose Camera Rig is ``Fixed``.
It is intentionally verbose and commented so it can double as a learning file
and as a development/showcase camera while testing scenes.

Controls
--------
W / S           fly forward / backward
A / D           strafe left / right
Space / C       move straight up / down in world space
Shift           speed boost
Mouse           look around while captured
Left Click      capture the mouse again after releasing it
Escape          release the mouse so the normal pointer can be used

The script demonstrates both Input Map actions (WASD/sprint) and direct
keyboard/mouse APIs (Space, C, Escape, mouse buttons and mouse delta).
"""

# Easy-to-find tuning values.  Beginners can change only these constants first.
MOVE_SPEED = 7.0
BOOST_MULTIPLIER = 3.0
LOOK_SENSITIVITY = 105.0
MAX_PITCH = 89.0
LOOK_DEADZONE = 0.001  # Ignores tiny driver/warp jitter around the captured centre.


class EntityScript:
    def on_start(self, entity, world):
        # This example belongs on a Camera component.  Keeping the check here
        # gives a useful error instead of silently doing nothing.
        if not entity.has_camera:
            world.log("Fly Camera: attach example_fly_camera.py to an entity with a Camera component.")
            return

        # A free camera should be a Fixed camera: the script owns its transform.
        entity.camera_configure(rig="fixed")
        entity.camera_activate()

        # FPS/free-look style mouse capture hides the pointer and keeps mouse
        # delta centered.  Play Mode automatically releases capture when stopped.
        self._skip_look_frames = 2
        world.capture_mouse(True)
        world.log(
            "Fly Camera controls: WASD move | Space/C up/down | Shift boost | "
            "Mouse look | Esc release mouse | Left Click recapture"
        )

    def on_update(self, entity, world, dt):
        # --- Mouse ownership -------------------------------------------------
        # key_pressed()/mouse_pressed() are one-frame edge events.  They are
        # better than key_down() for toggles because holding the key does not
        # repeat the action every frame.
        if world.key_pressed("escape"):
            self._skip_look_frames = 2
            world.capture_mouse(False)

        if not world.mouse_captured and world.mouse_pressed("mouse1"):
            self._skip_look_frames = 2
            world.capture_mouse(True)

        # --- Mouse look ------------------------------------------------------
        if world.mouse_captured:
            # The runtime already suppresses pointer-warp frames.  The small
            # script-side guard is intentionally defensive and useful to copy
            # into beginner camera scripts that may run on unusual mouse drivers.
            if self._skip_look_frames > 0:
                self._skip_look_frames -= 1
            else:
                dx, dy = world.mouse_delta
                if abs(dx) < LOOK_DEADZONE:
                    dx = 0.0
                if abs(dy) < LOOK_DEADZONE:
                    dy = 0.0

                # Panda uses H/P/R: Heading (yaw), Pitch, Roll.
                heading, pitch, _roll = entity.rotation
                heading -= dx * LOOK_SENSITIVITY
                pitch += dy * LOOK_SENSITIVITY
                pitch = max(-MAX_PITCH, min(MAX_PITCH, pitch))

                # Lock roll to zero for a conventional flying/FPS camera.
                entity.rotation = [heading, pitch, 0.0]

        # --- Keyboard movement ---------------------------------------------
        # These use the project's Input Map, so W/A/S/D can be rebound later
        # without changing this script.
        strafe = world.action_axis("move_left", "move_right")
        forward = world.action_axis("move_backward", "move_forward")

        speed = MOVE_SPEED
        if world.action_down("sprint"):
            speed *= BOOST_MULTIPLIER

        # Move relative to the camera orientation.  Looking up/down therefore
        # also changes the direction of forward flight.
        entity.translate(
            x=strafe * speed * dt,
            y=forward * speed * dt,
            local=True,
        )

        # Space/C demonstrate direct raw-key state.  Vertical movement is kept
        # in WORLD Z so it remains intuitive even when the camera is pitched.
        vertical = float(world.key_down("space")) - float(world.key_down("c"))
        if vertical:
            entity.translate(z=vertical * speed * dt, local=False)

    def on_stop(self, entity, world):
        # Explicit cleanup also documents ownership clearly for beginners.
        world.capture_mouse(False)
