from collections import defaultdict
from typing import Any
from uuid import uuid4


class MemoryStore:
    """Demo için kullanıcıya göre ayrılmış küçük bellek içi veri deposu."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, dict[str, Any]]]] = defaultdict(
            lambda: defaultdict(dict)
        )

    def list(self, collection: str, user_id: str) -> list[dict[str, Any]]:
        return list(self._data[collection][user_id].values())

    def get(self, collection: str, user_id: str, item_id: str) -> dict[str, Any] | None:
        return self._data[collection][user_id].get(item_id)

    def create(
        self, collection: str, user_id: str, value: dict[str, Any]
    ) -> dict[str, Any]:
        item = {"id": str(uuid4()), **value}
        self._data[collection][user_id][item["id"]] = item
        return item

    def delete(self, collection: str, user_id: str, item_id: str) -> bool:
        return self._data[collection][user_id].pop(item_id, None) is not None
