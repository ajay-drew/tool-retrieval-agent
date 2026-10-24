import copy
import itertools
import json
import random
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

from atlas.backend.base import BackendResult, BackendTransientError
from atlas.jsonpath import dig
from atlas.tools.spec import ToolSpec

SEED_PATH = Path(__file__).with_name("seed.json")
LIST_LIMIT = 20


@dataclass(frozen=True)
class Route:
    collection: str
    item_id: str | None
    action: str | None


def parse_route(template: str, path_args: dict) -> Route:
    segments = template.strip("/").split("/")
    for i, segment in enumerate(segments):
        if segment.startswith("{"):
            item = path_args.get(segment[1:-1])
            rest = segments[i + 1 :]
            return Route(
                "/" + "/".join(segments[:i]), str(item) if item else None, rest[0] if rest else None
            )
    return Route("/" + "/".join(segments), None, None)


def _criterion_holds(value: object, text: str) -> bool:
    if isinstance(value, str):
        return value.lower() in text
    if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        return any(v.lower() in text for v in value)
    return True


def _matches(item: dict, criteria: dict) -> bool:
    text = json.dumps(item).lower()
    return all(_criterion_holds(value, text) for value in criteria.values())


def _apply_patch(item: dict, operations: list) -> None:
    for op in operations:
        if not isinstance(op, dict) or op.get("op") not in ("add", "replace"):
            continue
        keys = [k for k in str(op.get("path", "")).split("/") if k]
        target: object = item
        for key in keys[:-1]:
            if isinstance(target, dict):
                target = target.setdefault(key, {})
            elif isinstance(target, list) and key.isdigit() and int(key) < len(target):
                target = target[int(key)]
            else:
                target = None
                break
        if keys and isinstance(target, dict):
            target[keys[-1]] = op.get("value")


class MockPayPal:
    """In-memory PayPal: checks inputs against the full schema and keeps seeded state."""

    def __init__(
        self,
        full_schemas: dict[str, dict],
        seed_path: Path = SEED_PATH,
        fault_rate: float = 0.0,
        rng_seed: int = 7,
    ):
        self._full_schemas = full_schemas
        self._seed = json.loads(seed_path.read_text())
        self._actions: dict[str, dict] = self._seed["actions"]
        self._validators: dict[str, Draft202012Validator] = {}
        self._fault_rate = fault_rate
        self._rng = random.Random(rng_seed)
        self.reset()

    def reset(self) -> None:
        self._state: dict[str, dict] = copy.deepcopy(self._seed["collections"])
        self._ids = itertools.count(1)

    def _validator(self, name: str) -> Draft202012Validator:
        if name not in self._validators:
            self._validators[name] = Draft202012Validator(self._full_schemas.get(name, {}))
        return self._validators[name]

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}{next(self._ids):04d}"

    async def call(self, spec: ToolSpec, args: dict) -> BackendResult:
        if self._fault_rate and self._rng.random() < self._fault_rate:
            raise BackendTransientError(503, "service unavailable, try again")
        errors = sorted(self._validator(spec.name).iter_errors(args), key=lambda e: e.json_path)
        if errors:
            details = [{"field": e.json_path, "issue": e.message[:200]} for e in errors[:5]]
            return BackendResult(422, {"name": "UNPROCESSABLE_ENTITY", "details": details})
        route = parse_route(spec.path, args.get("path") or {})
        collection = self._state.get(route.collection)
        if collection is None:
            return self._placeholder(spec, route)
        if "search_of" in collection:
            return self._search(collection["search_of"], args.get("body") or {})
        if "singleton" in collection:
            return BackendResult(200, collection["singleton"])
        if route.item_id is None:
            return self._collection_call(spec, collection, args)
        item = next((i for i in collection["items"] if i.get("id") == route.item_id), None)
        if item is None:
            message = f"No resource with id {route.item_id} under {route.collection}"
            return BackendResult(404, {"name": "RESOURCE_NOT_FOUND", "message": message})
        if route.action:
            return self._action(route.action, item, args.get("body") or {})
        return self._item_call(spec, collection, item, args.get("body"))

    def _collection_call(self, spec: ToolSpec, collection: dict, args: dict) -> BackendResult:
        if spec.method == "GET":
            return self._list(collection, args.get("query") or {})
        if spec.method == "POST":
            body = args.get("body") or {}
            item = {**body, "id": self._new_id(collection.get("id_prefix", "NEW-"))}
            if collection.get("create_status"):
                item["status"] = collection["create_status"]
            collection.setdefault("items", []).append(item)
            return BackendResult(201, item)
        return self._placeholder(spec, Route("", None, None))

    def _list(self, collection: dict, query: dict) -> BackendResult:
        items = collection.get("items", [])
        date_field = collection.get("date_field")
        if date_field:
            start, end = query.get("start_date"), query.get("end_date")
            items = [
                i
                for i in items
                if (not start or str(dig(i, date_field)) >= str(start)[:19])
                and (not end or str(dig(i, date_field)) <= str(end))
            ]
        key = collection.get("list_key", "items")
        return BackendResult(200, {key: items[:LIST_LIMIT], "total_items": len(items)})

    def _search(self, target: str, criteria: dict) -> BackendResult:
        collection = self._state[target]
        items = [i for i in collection.get("items", []) if _matches(i, criteria)]
        return BackendResult(200, {"items": items[:LIST_LIMIT], "total_items": len(items)})

    def _item_call(
        self, spec: ToolSpec, collection: dict, item: dict, body: object
    ) -> BackendResult:
        if spec.method == "GET":
            return BackendResult(200, item)
        if spec.method == "DELETE":
            collection["items"].remove(item)
            return BackendResult(204, {})
        if isinstance(body, list):
            _apply_patch(item, body)
        elif isinstance(body, dict):
            item.update({k: v for k, v in body.items() if k != "id"})
        return BackendResult(200, item)

    def _action(self, action: str, item: dict, body: dict) -> BackendResult:
        effect = self._actions.get(action, {})
        if "status" in effect:
            item["status"] = effect["status"]
        if "returns" in effect:
            return BackendResult(200, effect["returns"])
        if "creates" in effect:
            target = self._state[effect["creates"]]
            created = {
                "id": self._new_id(target.get("id_prefix", "NEW-")),
                "status": "COMPLETED",
                "amount": body.get("amount") or item.get("amount"),
                "source_id": item["id"],
                **{k: v for k, v in body.items() if k not in ("id", "amount")},
            }
            target.setdefault("items", []).append(created)
            return BackendResult(201, created)
        return BackendResult(200, item)

    def _placeholder(self, spec: ToolSpec, route: Route) -> BackendResult:
        if spec.method == "GET":
            if route.item_id:
                return BackendResult(200, {"id": route.item_id, "status": "OK"})
            return BackendResult(200, {"items": [], "total_items": 0})
        if spec.method == "DELETE":
            return BackendResult(204, {})
        return BackendResult(200, {"id": self._new_id("MOCK-"), "status": "OK"})
