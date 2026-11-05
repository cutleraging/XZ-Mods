"""Run the four-deck host contracts without firmware, USB or mixer access."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys

APP = Path(__file__).resolve().parents[1]
MODS = APP / "source/xdj-xz-toolkit/mods"
PLAYER = [
    "extra_player.c", "key/keyshift.c", "key/music.c", "key/control.c",
    "deck_select.c", "anlz_extra.c", "shell_analysis.c",
    "ui/layered_wave_source.c", "ui/layered_wave.c",
    "audio/stem_media.c", "audio/stem_mp3.c", "audio/stem_decode.c",
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_closure(sources):
    """Retain quoted includes too, including tests which include a C file."""
    pending = [MODS / name for name in sources]
    found = set()
    while pending:
        path = pending.pop().resolve()
        if path in found:
            continue
        if not path.is_relative_to(MODS):
            raise ValueError("Source outside the toolkit: " + str(path))
        found.add(path)
        for name in re.findall(r'^\s*#\s*include\s+"([^"]+)"', path.read_text(), re.M):
            candidates = [path.parent / name, MODS / name]
            include = next((p for p in candidates if p.is_file()), None)
            if include is None:
                raise ValueError("Unresolved include: " + name + " in " + str(path))
            pending.append(include)
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    compiler = parser.add_mutually_exclusive_group()
    compiler.add_argument("--cc", default=None, help="Native C compiler (default: clang)")
    compiler.add_argument("--zig", help="Use Zig's native cc command")
    parser.add_argument("--output", required=True, type=Path, help="New evidence directory")
    parser.add_argument("--sanitizer", choices=("undefined", "address,undefined"), default="undefined")
    args = parser.parse_args()
    if sys.platform not in ("darwin", "linux"):
        parser.error("Use the upstream verify_extra_player.py on Windows")
    executable = shutil.which(args.zig or args.cc or "clang")
    if not executable:
        parser.error("C compiler not found")
    cc = [executable, "cc"] if args.zig else [executable]
    suites = {
        "clock": ["tests/test_clock_compat.c"],
        "deck-select": ["deck_select.c", "test_deck_select.c"],
        "deck-switch-idle": ["deck_select.c", "tests/test_idle_jog_shift.c"],
        "player": PLAYER + ["test_extra_player.c"],
        "sync-engine": PLAYER + ["tests/test_sync_engine.c"],
        "sync-clock-skew": PLAYER + ["tests/probe_sync_clock_skew.c"],
    }
    skipped = []
    if sys.platform == "linux":
        suites["connector"] = PLAYER + ["extra_decks.c", "extra_cue_store.c", "test_extra_decks.c"]
        suites["usb-transport-fake-io"] = ["audio/usb_transport/tests/test_usb_transport.c"]
    else:
        skipped.append("Linux-only route connector and fake usbfs transport; run on Linux")
    sources = {s for names in suites.values() for s in names}
    files = source_closure(sources) | {Path(__file__).resolve(), MODS / "extra_player_fixtures.py"}
    pins = {str(p.relative_to(APP)): digest(p) for p in sorted(files)}
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(MODS))
    from extra_player_fixtures import fixtures
    data = out / "fixtures"
    data.mkdir()
    fixtures(data)
    report = {
        "schema": "xz-four-deck-host-check/1", "platform": platform.platform(),
        "compiler": subprocess.check_output([*cc, "--version"], text=True).splitlines()[0],
        "inputs": pins, "checks": [], "skipped": skipped,
        "hardware_tested": False, "firmware_executed": False,
        "scope": "Actual software players and controls with synthetic media and fake transport",
        "passed": False,
    }
    common = [*cc, "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-UNDEBUG",
              "-pthread", "-DXZ_XP_TEST_RENDER_HOOK", "-I" + str(MODS),
              "-fsanitize=" + args.sanitizer, "-fno-sanitize-recover=all"]

    def run(name, command, expected_failure=None):
        result = subprocess.run(command, cwd=data, capture_output=True, text=True, timeout=180)
        (out / (name + ".log")).write_text(result.stdout + result.stderr)
        ok = (result.returncode == 0 if expected_failure is None else
              result.returncode != 0 and expected_failure in result.stderr)
        report["checks"].append({"name": name, "command": command, "returncode": result.returncode,
                                 "passed": ok, "expected_failure": expected_failure})
        if not ok:
            raise RuntimeError("Failed " + name + "; see " + str(out / (name + ".log")))
        print("PASS " + name, flush=True)

    try:
        for name, names in suites.items():
            binary = out / name
            flags = (["-DXZ_PLACEMENT_CONNECTOR_TEST", "-DUSB_MAJOR=1", "-DPOLL_DOWN_MS=50",
                      "-DROUTE_EVENT_SAFETY_MS=50", "-DPOLL_UP_MS=5"] if name == "connector" else [])
            if sys.platform == "darwin" and name in ("player", "sync-engine", "sync-clock-skew"):
                # Mach-O needs explicit allowance for absent optional ELF weak
                # hooks. Permit only the five diary hooks, never arbitrary symbols.
                flags += ["-Wl,-U,_xz_diary_" + hook for hook in
                          ("busy_begin", "busy_end", "audio", "notice", "notice_code")]
            run(name + "-build", common + flags + [str(MODS / s) for s in names] + ["-lm", "-o", str(binary)])
            run(name, [str(binary)] + ([str(data)] if name in ("player", "sync-engine", "sync-clock-skew") else []))
        # A passing suite must actually enforce back-cue pause, not just execute.
        before = "if (d->state == XZ_XP_PLAYING || d->state == XZ_XP_ENDED) { jump(d, d->cue, now); d->state = XZ_XP_CUED; }"
        after = "if (d->state == XZ_XP_PLAYING || d->state == XZ_XP_ENDED) { jump(d, d->cue, now); }"
        original = (MODS / "extra_player.c").read_text()
        if original.count(before) != 1:
            raise ValueError("Back-cue mutation no longer matches exactly once")
        mutant = out / "back-cue-mutant.c"
        mutant.write_text(original.replace(before, after))
        binary = out / "back-cue-mutant"
        optional = (["-Wl,-U,_xz_diary_" + hook for hook in
                     ("busy_begin", "busy_end", "audio", "notice", "notice_code")]
                    if sys.platform == "darwin" else [])
        run("back-cue-mutant-build", common + optional + [str(mutant)] +
            [str(MODS / s) for s in PLAYER[1:] + ["test_extra_player.c"]] + ["-lm", "-o", str(binary)])
        run("back-cue-mutant-rejected", [str(binary), str(data)], "Assertion")
        # Discarding the transport timestamp must reproduce the slow-clock drift.
        timed = "wire_origin_observe(p,route,position->wire_completed_frames,*at,position->wire_observed_us)"
        legacy = "wire_origin_observe(p,route,position->wire_completed_frames,*at,0)"
        if original.count(timed) != 1:
            raise ValueError("Clock timestamp mutation no longer matches exactly once")
        mutant = out / "clock-skew-mutant.c"
        mutant.write_text(original.replace(timed, legacy))
        binary = out / "clock-skew-mutant"
        run("clock-skew-mutant-build", common + optional + [str(mutant)] +
            [str(MODS / s) for s in PLAYER[1:] + ["tests/probe_sync_clock_skew.c"]] + ["-lm", "-o", str(binary)])
        run("clock-skew-mutant-rejected", [str(binary), str(data)], "Assertion")
        current = {str(p.relative_to(APP)): digest(p) for p in sorted(files)}
        if pins != current:
            raise RuntimeError("Inputs changed during verification")
        report["passed"] = True
    finally:
        (out / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Host checks pass; hardware remains untested. Evidence: " + str(out / "verification.json"))


if __name__ == "__main__":
    main()
