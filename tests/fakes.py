"""多处测试共用的替身。"""

from dehydrater.credentials import KeychainUnavailableError


class FakeKeychain:
    def __init__(self, entries: dict[str, str] | None = None, *, available: bool = True) -> None:
        self.entries = dict(entries or {})
        self._available = available

    def get(self, name: str) -> str | None:
        return self.entries.get(name)

    def set(self, name: str, value: str) -> None:
        if not self._available:
            raise KeychainUnavailableError("没有可用的钥匙串")
        self.entries[name] = value

    def delete(self, name: str) -> bool:
        return self.entries.pop(name, None) is not None
