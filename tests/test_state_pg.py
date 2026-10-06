from __future__ import annotations

import json

from tf.state_pg import import_legacy_json_once


class _MemoryStateStore:
    def __init__(self) -> None:
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


def test_legacy_json_import_is_once_only(tmp_path):
    store = _MemoryStateStore()
    path = tmp_path / "cycle-state.json"
    path.write_text(json.dumps({"last_run": 42, "portfolio": ["s1"]}))

    assert import_legacy_json_once(store, "scheduler/cycle-state", path)
    assert store.get("scheduler/cycle-state") == {"last_run": 42, "portfolio": ["s1"]}

    path.write_text(json.dumps({"last_run": 99, "portfolio": []}))
    assert not import_legacy_json_once(store, "scheduler/cycle-state", path)
    assert store.get("scheduler/cycle-state")["last_run"] == 42


def test_missing_legacy_json_is_not_created_or_imported(tmp_path):
    store = _MemoryStateStore()

    assert not import_legacy_json_once(store, "g3/budget", tmp_path / "missing.json")
    assert store.get("g3/budget") is None
