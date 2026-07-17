import unittest
from backend.app.store import Store


class MemoryProjectionTests(unittest.TestCase):
    def test_pending_decisions_do_not_appear_in_memory(self):
        store = Store()
        self.assertEqual([], store.context("default")["memory"])
        store.review("demo-decision-1", "confirmed")
        self.assertEqual(1, len(store.context("default")["memory"]))


if __name__ == "__main__":
    unittest.main()
