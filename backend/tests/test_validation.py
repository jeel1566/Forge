import sys
import tempfile
import unittest
from pathlib import Path

from backend.app.store import Store
from backend.app.validation import run_validation


class ValidationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary_directory.name) / "repository"
        self.repository.mkdir()
        self.store = Store(self.repository / ".forge" / "forge.sqlite3")
        self.store.register_repository("default", str(self.repository))

    def tearDown(self):
        self.store.close()
        self.temporary_directory.cleanup()

    def test_runs_a_real_command_and_keeps_output_out_of_evidence(self):
        result = run_validation(self.store, "default", "python check", [sys.executable, "-c", "print('private command output')"])
        self.assertEqual("passed", result["status"])
        evidence_id = self.store.db.execute("SELECT evidence_id FROM evidence_spans WHERE id=?", (result["span_id"],)).fetchone()["evidence_id"]
        evidence = self.store.get_evidence(evidence_id)
        self.assertEqual("local_validation", evidence["kind"])
        self.assertNotIn("private command output", evidence["content"])
        self.assertEqual("forge", evidence["metadata"]["captured_by"])
