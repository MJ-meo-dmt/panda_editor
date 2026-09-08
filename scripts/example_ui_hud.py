"""POC 0.3.8 UI/HUD demo.

Attach this script to a normal controller entity.  The UI Button broadcasts
its configured event and this controller updates the shared Score Label.
"""


class EntityScript:
    def on_start(self, entity, world):
        self.score = 0
        label = world.find("Score Label")
        if label:
            label.ui_text = "Score: 0"
        world.log("UI/HUD demo ready. Click Add Point in Play Mode.")

    def on_event(self, entity, world, event_name, payload):
        if event_name != "add_point":
            return
        self.score += 1
        label = world.find("Score Label")
        if label:
            label.ui_text = f"Score: {self.score}"
        world.log(f"HUD score is now {self.score}")
