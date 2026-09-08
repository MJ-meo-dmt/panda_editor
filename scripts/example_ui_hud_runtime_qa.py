"""Runtime QA companion for project_templates/ui_hud_runtime_qa.pscene.

Every interactive DirectGUI control routes into this script so the Output panel
shows that the runtime callback and Signals 2.0 bridge are alive.
"""

class EntityScript:
    def on_start(self, entity, world):
        world.log("UI/HUD runtime QA ready")

    def on_event(self, entity, world, event_name, payload):
        if event_name.startswith("qa_"):
            world.log(f"UI QA: {event_name} -> {payload}")
