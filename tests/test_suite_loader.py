import tempfile
import unittest
from pathlib import Path

from relaylens.suite_loader import load_suite
from relaylens.tasks import suite as builtin_suite


class SuiteLoaderTests(unittest.TestCase):
    def test_builtin_suite_has_commitment(self):
        fn, version, source, commitment = load_suite()
        self.assertIs(fn, builtin_suite)
        self.assertEqual(source, "builtin")
        self.assertTrue(version)
        self.assertRegex(commitment or "", r"^[0-9a-f]{64}$")

    def test_external_suite_is_loaded_and_committed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private_suite.py"
            path.write_text(
                "from relaylens.tasks import suite\n"
                "SUITE_VERSION = 'private-test-1'\n",
                encoding="utf-8",
            )
            fn, version, source, commitment = load_suite(str(path))
            self.assertEqual(source, "external")
            self.assertEqual(version, "private-test-1")
            self.assertRegex(commitment or "", r"^[0-9a-f]{64}$")
            self.assertEqual(len(fn(11, 1)), len(builtin_suite(11, 1)))


if __name__ == "__main__":
    unittest.main()
