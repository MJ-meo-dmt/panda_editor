class EntityScript:
    def __init__(self):
        self._space_was_down = False

    def on_start(self, entity, world):
        world.log(f"Physics event demo started on {entity.name}")

    def on_update(self, entity, world, dt):
        down = world.key_down("space")
        if down and not self._space_was_down:
            hit = entity.raycast(y=1, distance=25.0)
            if hit:
                world.log(f"Ray: {entity.name} -> {hit['name']} ({hit['distance']:.2f}m)")
            else:
                world.log("Ray: no hit")
        self._space_was_down = down

    def on_event(self, entity, world, event_name, payload):
        data = payload.get("data") or {}
        if event_name in {"collision_enter", "collision_exit", "trigger_enter", "trigger_exit"}:
            world.log(f"{event_name}: {entity.name} <-> {data.get('other_name', '?')}")
