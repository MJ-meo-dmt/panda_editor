"""Panda Editor 0.4.4 example: managed tasks and custom runtime events."""

class EntityScript:
    def on_start(self, entity, world):
        world.log("Tasks / Events demo started")
        # Dynamic one-shot task. Authored tasks on the component run independently.
        world.call_later(2.5, "demo_once", {"source": "script"}, target=entity.id, name="script_once")

    def on_event(self, entity, world, event_name, payload):
        if event_name == "heartbeat":
            data = payload.get("data", {})
            world.log(f"heartbeat -> {data}")
        elif event_name == "demo_once":
            world.log("call_later() fired")
            entity.task_stop("Heartbeat")
            world.call_later(1.5, "restart_heartbeat", target=entity.id, name="restart")
        elif event_name == "restart_heartbeat":
            world.log("Restarting authored Heartbeat task")
            entity.task_start("Heartbeat")
