import time


class Cache[T]:
    """Small, bounded TTL cache for provider metadata; nothing is cached indefinitely."""

    def __init__(self, capacity: int, ttl: float):
        self.capacity = capacity
        self.ttl = ttl
        self.entries: dict[str, tuple[float, T]] = {}

    def get(self, key: str) -> T | None:
        entry = self.entries.get(key)
        if entry is None:
            return None
        expires, value = entry
        if expires <= time.monotonic():
            self.entries.pop(key, None)
            return None
        return value

    def put(self, key: str, value: T) -> None:
        self.entries.pop(key, None)
        while len(self.entries) >= self.capacity:
            self.entries.pop(next(iter(self.entries)))
        self.entries[key] = (time.monotonic() + self.ttl, value)
