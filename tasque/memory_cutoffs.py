import json
from pathlib import Path


class MemoryCutoffs:
    """Per-channel message id before which the character ignores history. Persisted so a wipe survives restarts."""

    def __init__(self, path: Path):
        self.path = path
        self.message_id_by_channel: dict[int, int] = {}
        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.message_id_by_channel = {int(channel_id): message_id for channel_id, message_id in stored.items()}

    def get(self, channel_id: int) -> int | None:
        return self.message_id_by_channel.get(channel_id)

    def set(self, channel_id: int, message_id: int) -> None:
        self.message_id_by_channel[channel_id] = message_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {str(channel_id): message_id for channel_id, message_id in self.message_id_by_channel.items()}
        self.path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
