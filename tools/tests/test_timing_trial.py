"""Fail closed if a private trial alters the retained firmware/kernel contract."""
import importlib.util
from pathlib import Path
import unittest

TOOLS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("trial_bridge", TOOLS / "build_timing_trial_bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class PairingTests(unittest.TestCase):
    def test_only_runtime_hash_changes(self):
        expected = bridge.pins()
        original = (bridge.QUAD / "contract.h").read_bytes()
        changed = bridge.trial_contract(original, expected)
        self.assertNotEqual(changed, original)
        self.assertEqual(changed.replace(expected["runtime_sha256"].encode(),
                                         expected["base_runtime_sha256"].encode()), original)
        self.assertIn(expected["receiver_sha256"].encode(), changed)
        self.assertIn(expected["module_sha256"].encode(), changed)
        self.assertIn(expected["application_sha256"].encode(), changed)

    def test_changed_kernel_or_application_contract_is_refused(self):
        expected = bridge.pins()
        original = (bridge.QUAD / "contract.h").read_bytes()
        for before in (b"3.0.101", expected["application_sha256"].encode(),
                       expected["module_sha256"].encode()):
            with self.subTest(before=before), self.assertRaises(ValueError):
                bridge.trial_contract(original.replace(before, b"unreviewed"), expected)

    def test_missing_or_duplicate_runtime_pin_is_refused(self):
        expected = bridge.pins()
        original = (bridge.QUAD / "contract.h").read_bytes()
        for changed in (original.replace(expected["base_runtime_sha256"].encode(), b"missing"),
                        original + b'\n#define RUNTIME_SHA "' + expected["base_runtime_sha256"].encode() + b'"\n'):
            # Even a caller that repins the outer contract must retain one exact declaration.
            with self.subTest(changed=bridge.sha(changed)), self.assertRaises(ValueError):
                bridge.trial_contract(changed, {**expected, "base_contract_sha256": bridge.sha(changed)})


if __name__ == "__main__":
    unittest.main()
