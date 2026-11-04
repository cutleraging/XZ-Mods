"""Read-only check that a rekordbox USB exports the four expected PCM WAVs.

This checks media and database references for the first four-track bench. It
does not qualify playback, beat grids, routing, controls or hardware timing.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import struct
import sys
import wave

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "source/xdj-xz-toolkit"))
from builder.cache import _safe_path
from builder import rekordbox_pdb


def sha(path):
    with path.open("rb") as source:
        value = hashlib.sha256()
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def pcm_identity(path, pins):
    path = _safe_path(path)
    raw = path.read_bytes()
    pins[path] = hashlib.sha256(raw).hexdigest()
    with wave.open(io.BytesIO(raw), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (2, 2, 44100, "NONE"):
            raise ValueError("First-bench WAV must be stereo 16-bit PCM at 44100 Hz")
        count = audio.getnframes()
        if not count:
            raise ValueError("Empty WAV")
        hashed = hashlib.sha256(struct.pack("<IIIQ", 2, 2, 44100, count))
        actual = 0
        while True:
            block = audio.readframes(65536)
            if not block:
                break
            hashed.update(block)
            actual += len(block)
        if actual != count * 4:
            raise ValueError("Truncated WAV audio")
    return {"pcm_sha256": hashed.hexdigest(), "frames": count, "seconds": count / 44100}


def exported_path(root, name):
    parts = PurePosixPath(name).parts
    if (len(parts) < 3 or parts[0] != "/" or parts[1].casefold() != "contents"
            or any(part in (".", "..") or "\\" in part or ":" in part for part in parts[1:])):
        raise ValueError("Invalid exported track path: " + name)
    return _safe_path(root.joinpath(*parts[1:]))


def check_music(volume, expected_wavs):
    report = {"schema": "xz-four-deck-music-check/1", "music_ready": False,
              "hardware_tested": False, "scope": "Four expected PCM WAVs referenced by export.pdb",
              "issues": [], "matched": [], "unsupported_tracks": [], "inputs": {}}
    pins = {}
    try:
        root = _safe_path(volume)
        expected = _safe_path(expected_wavs)
        files = sorted(p for p in expected.iterdir() if p.suffix.lower() == ".wav")
        if len(files) != 4:
            raise ValueError("Supply exactly four expected WAV files")
        wanted = {}
        for path in files:
            identity = pcm_identity(path, pins)
            key = identity["pcm_sha256"]
            if key in wanted:
                raise ValueError("Expected tracks must contain four distinct audio streams")
            wanted[key] = {"expected_file": path.name, **identity}
        database = _safe_path(root.joinpath(*rekordbox_pdb.EXPORT_PDB))
        report["database"] = str(database)
        if not database.is_file():
            raise ValueError("No export.pdb: import, analyse and export the WAVs through rekordbox; copying files alone is insufficient")
        pins[database] = sha(database)
        tracks = rekordbox_pdb.track_paths(database)
        matches = {key: [] for key in wanted}
        for track_id, name in tracks.items():
            path = exported_path(root, name)
            if path.suffix.lower() != ".wav":
                report["unsupported_tracks"].append({"id": track_id, "path": name,
                    "note": "Not a WAV bench input; AAC/M4A cannot play on software decks"})
                continue
            if not path.is_file():
                report["issues"].append("Exported audio file is missing: " + name)
                continue
            identity = pcm_identity(path, pins)
            if identity["pcm_sha256"] in matches:
                matches[identity["pcm_sha256"]].append({"id": track_id, "path": name, **identity})
        for key, reference in wanted.items():
            found = matches[key]
            if len(found) != 1:
                report["issues"].append(reference["expected_file"] + ": expected one exported match, found " + str(len(found)))
            else:
                report["matched"].append({**reference, **found[0]})
        for path, pin in pins.items():
            if sha(path) != pin:
                raise ValueError("Input changed during inspection: " + str(path))
        report["music_ready"] = not report["issues"] and len(report["matched"]) == 4
    except (OSError, ValueError, wave.Error, EOFError) as error:
        report["issues"].append(str(error))
    report["inputs"] = {str(path): pin for path, pin in pins.items()}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--volume", required=True, type=Path)
    parser.add_argument("--expected-wavs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New report outside the USB")
    args = parser.parse_args()
    root = _safe_path(args.volume)
    out = _safe_path(args.output)
    if out == root or root in out.parents:
        parser.error("The report must be outside the inspected USB")
    if out.exists():
        parser.error("Choose a new report path")
    report = check_music(root, args.expected_wavs)
    with out.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print("Music export verified" if report["music_ready"] else "Music export incomplete: " + "; ".join(report["issues"]))
    return 0 if report["music_ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
