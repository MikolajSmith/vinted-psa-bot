import json
from pathlib import Path

MAX_SEEN_IDS = 3000


def load_seen_ids(state_file: Path) -> list[str]:
    """Oldest-first list of previously processed Vinted item ids."""
    if not state_file.exists():
        return []
    try:
        return list(json.loads(state_file.read_text()))
    except (json.JSONDecodeError, OSError):
        return []


def save_seen_ids(state_file: Path, seen_ids: list[str]):
    trimmed = seen_ids[-MAX_SEEN_IDS:]
    state_file.write_text(json.dumps(trimmed))
