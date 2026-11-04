"""Real PDB fixtures exercise the observed file-copy/export failure boundary."""
import hashlib
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_four_deck_music import check_music
from builder.tests.pdb_fixture import write_export


class MusicExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.expected = self.root / "expected"
        self.expected.mkdir()
        self.usb = self.root / "usb"
        self.usb.mkdir()
        self.paths = {}
        for n in range(1, 5):
            name = "Track " + str(n) + ".wav"
            with wave.open(str(self.expected / name), "wb") as audio:
                audio.setnchannels(2)
                audio.setsampwidth(2)
                audio.setframerate(44100)
                audio.writeframes(struct.pack("<hh", n * 100, -n * 100) * 4410)
            self.paths[n] = "/Contents/Test/" + name
        self.db = self.usb / "PIONEER/rekordbox/export.pdb"

    def exported(self):
        for name in self.paths.values():
            dest = self.usb / name.lstrip("/")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.expected / dest.name, dest)
        write_export(self.db, self.paths)

    def check(self):
        return check_music(self.usb, self.expected)

    def test_root_file_copies_do_not_count_as_export(self):
        for path in self.expected.glob("*.wav"):
            shutil.copyfile(path, self.usb / path.name)
        result = self.check()
        self.assertFalse(result["music_ready"])
        self.assertIn("No export.pdb", result["issues"][0])

    def test_four_real_references_pass_without_writes(self):
        self.exported()
        before = {p.relative_to(self.root): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.root.rglob("*") if p.is_file()}
        result = self.check()
        self.assertTrue(result["music_ready"], result)
        self.assertEqual(len(result["matched"]), 4)
        self.assertFalse(result["hardware_tested"])
        self.assertEqual(before, {p.relative_to(self.root): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in self.root.rglob("*") if p.is_file()})

    def test_missing_referenced_audio_fails(self):
        self.exported()
        (self.usb / self.paths[2].lstrip("/")).unlink()
        self.assertFalse(self.check()["music_ready"])

    def test_m4a_export_does_not_count_as_matching_wav(self):
        self.exported()
        self.paths[2] = "/Contents/Test/Track 2.m4a"
        write_export(self.db, self.paths)
        result = self.check()
        self.assertFalse(result["music_ready"])
        self.assertEqual(result["unsupported_tracks"][0]["id"], 2)

    def test_duplicate_reference_is_ambiguous(self):
        self.exported()
        write_export(self.db, {**self.paths, 5: self.paths[2]})
        self.assertFalse(self.check()["music_ready"])

    def test_changed_audio_fails_even_when_filename_matches(self):
        self.exported()
        shutil.copyfile(self.expected / "Track 1.wav", self.usb / self.paths[2].lstrip("/"))
        self.assertFalse(self.check()["music_ready"])

    def test_truncated_audio_fails(self):
        self.exported()
        path = self.usb / self.paths[1].lstrip("/")
        path.write_bytes(path.read_bytes()[:-40])
        self.assertFalse(self.check()["music_ready"])

    def test_path_traversal_and_symlinks_fail(self):
        self.exported()
        write_export(self.db, {**self.paths, 1: "/Contents/../../escape.wav"})
        self.assertFalse(self.check()["music_ready"])
        write_export(self.db, self.paths)
        path = self.usb / self.paths[1].lstrip("/")
        path.unlink()
        path.symlink_to(self.expected / path.name)
        self.assertFalse(self.check()["music_ready"])

    def test_corrupt_database_fails(self):
        self.exported()
        self.db.write_bytes(b"invalid")
        self.assertFalse(self.check()["music_ready"])


if __name__ == "__main__":
    unittest.main()
