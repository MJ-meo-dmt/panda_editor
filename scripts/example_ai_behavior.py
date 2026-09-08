"""Panda Editor 0.4.17 AI Behavior example.

Attach to an entity that also has AI Behavior + Navigation Agent.
The component can run on its own; this script demonstrates the high-level API/events.
"""

class EntityScript:
    def on_start(self, entity, world):
        world.log(f"AI ready: state={entity.ai_state}")
        entity.ai_blackboard_set("times_attacked", 0)

    def on_event(self, entity, world, event_name, payload):
        if event_name == "ai_target_acquired":
            world.log(f"{entity.name}: target acquired")
        elif event_name == "ai_target_lost":
            world.log(f"{entity.name}: target lost")
        elif event_name == "ai_state_changed":
            data=(payload or {}).get("data") if isinstance(payload,dict) else payload
            world.log(f"{entity.name}: AI state -> {entity.ai_state} ({data})")
        elif event_name == "ai_attack_ready":
            count=int(entity.ai_blackboard_get("times_attacked",0))+1
            entity.ai_blackboard_set("times_attacked",count)
            world.log(f"{entity.name}: attack opportunity #{count}")

    def on_update(self, entity, world, dt):
        # The authored AI component handles perception/decision/navigation itself.
        # Scripts are free to add game-specific policy without replacing the system.
        if world.action_pressed("jump"):
            entity.ai_think_now()
