import json
import unittest

from strategies.python.common.strategy_state import StrategyStateStore


class FakeObjectStore:
    def __init__(self):
        self.values = {}

    def contains_key(self, key):
        return key in self.values

    def read(self, key):
        return self.values[key]

    def save(self, key, value):
        self.values[key] = value


class StrategyStateStoreTests(unittest.TestCase):
    def setUp(self):
        self.object_store = FakeObjectStore()
        self.store = StrategyStateStore(
            self.object_store,
            "example-strategy",
            "paper",
            1,
            lambda: {"trades": {}},
        )

    def test_missing_state_returns_default_payload(self):
        result = self.store.load()

        self.assertEqual("missing", result.status)
        self.assertEqual({"trades": {}}, result.payload)

    def test_save_and_load_round_trip(self):
        self.store.save({"trades": {"trade-1": {"status": "OPEN"}}}, "2026-08-21T00:00:00Z")

        result = self.store.load()

        self.assertTrue(result.is_valid)
        self.assertEqual("OPEN", result.payload["trades"]["trade-1"]["status"])
        saved = json.loads(self.object_store.values[self.store.key])
        self.assertEqual("example-strategy", saved["strategy_id"])
        self.assertEqual("2026-08-21T00:00:00Z", saved["updated_at"])

    def test_invalid_json_is_corrupt_without_deleting_state(self):
        self.object_store.values[self.store.key] = "not json"

        result = self.store.load()

        self.assertEqual("corrupt", result.status)
        self.assertIn(self.store.key, self.object_store.values)

    def test_identity_or_schema_mismatch_is_incompatible(self):
        self.object_store.values[self.store.key] = json.dumps({
            "schema_version": 2,
            "strategy_id": "another-strategy",
            "scope": "paper",
            "payload": {"trades": {}},
        })

        result = self.store.load()

        self.assertEqual("incompatible", result.status)


if __name__ == "__main__":
    unittest.main()