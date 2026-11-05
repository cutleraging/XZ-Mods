"""Build the exact timing-trial bridge from the retained kernel contract, offline."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

APP = Path(__file__).resolve().parents[1]
TOOLKIT = APP / "source/xdj-xz-toolkit"
QUAD = TOOLKIT / "vendor/tools/xz_quad"
PINS_PATH = Path(__file__).with_name("timing_trial_pins.json")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pins():
    return json.loads(PINS_PATH.read_text())


def trial_contract(original, expected):
    if sha(original) != expected["base_contract_sha256"]:
        raise ValueError("Unexpected baseline bridge contract")
    before = ('#define RUNTIME_SHA "' + expected["base_runtime_sha256"] + '"').encode()
    after = ('#define RUNTIME_SHA "' + expected["runtime_sha256"] + '"').encode()
    if original.count(before) != 1:
        raise ValueError("Expected exactly one retained runtime pin")
    # All firmware, receiver, module, release and CRC checks remain byte-identical.
    return original.replace(before, after)


def inspect_bridge(path, expected):
    from elftools.elf.elffile import ELFFile
    with path.open("rb") as stream:
        elf = ELFFile(stream)
        if elf.elfclass != 32 or not elf.little_endian or elf["e_machine"] != "EM_ARM" or elf["e_flags"] & 0x400:
            raise ValueError("Expected ARM32 base calling convention")
        if elf["e_type"] != "ET_EXEC":
            raise ValueError("Expected a non-PIE bridge executable")
        versions = {s.name for _, aux in elf.get_section_by_name(".gnu.version_r").iter_versions() for s in aux}
        for version in versions:
            if version.startswith("GLIBC_") and tuple(map(int, version[6:].split("."))) > (2, 4):
                raise ValueError("Bridge exceeds retained GLIBC_2.4 imports")
    data = path.read_bytes()
    for field in ("application_sha256", "runtime_sha256", "receiver_sha256", "module_sha256"):
        if expected[field].encode() not in data:
            raise ValueError("Compiled bridge lost pin: " + field)
    return {"sha256": sha(data), "bytes": len(data), "symbol_versions": sorted(versions)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--zig", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--qemu", default="qemu-arm")
    parser.add_argument("--sysroot", type=Path, default=Path("/usr/arm-linux-gnueabi"))
    args = parser.parse_args()
    expected = pins()
    if sha(args.runtime.read_bytes()) != expected["runtime_sha256"]:
        parser.error("Runtime differs from the reviewed timing build")
    runner = shutil.which(args.qemu)
    if not runner:
        parser.error("ARM user-mode QEMU is required for the bridge self-test")
    contract = trial_contract((QUAD / "contract.h").read_bytes(), expected)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "contract.h").write_bytes(contract)
    for name in ("bridge.c", "port_layout.h"):
        (out / name).write_bytes((QUAD / name).read_bytes())
    binary = out / "xz-auto-bridge"
    source = TOOLKIT / "mods/audio/vendor/sha256"
    command = [str(args.zig.resolve()), "cc", "-target", "arm-linux-gnueabi.2.13", "-mcpu=cortex_a9",
               "-O2", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fno-pie", "-no-pie", "-s",
               "-I" + str(out), "-I" + str(source), str(out / "bridge.c"), str(source / "sha256.c"),
               "-o", str(binary)]
    build = subprocess.run(command, capture_output=True, text=True, timeout=180)
    (out / "compile.log").write_text(build.stdout + build.stderr)
    if build.returncode:
        raise RuntimeError("Bridge build failed; see compile.log")
    identity = inspect_bridge(binary, expected)
    # --self-test enters the bridge's pure lifecycle tests before all device paths.
    test_command = [runner, "-cpu", "cortex-a9", "-L", str(args.sysroot.resolve()), str(binary), "--self-test"]
    result = subprocess.run(test_command, capture_output=True, text=True, timeout=60)
    (out / "self-test.log").write_text(result.stdout + result.stderr)
    if result.returncode or "PASS event validation" not in result.stdout:
        raise RuntimeError("ARM bridge self-test failed")
    receipt = {"schema": "xz-timing-trial-bridge/1", "pins": expected,
               "contract_sha256": sha(contract), "binary": identity,
               "compile_command": command, "self_test_command": test_command,
               "arm_self_test_passed": True, "hardware_contacted": False,
               "kernel_module_rebuilt": False, "kernel_contract_changed": False,
               "inputs": {str(p.relative_to(APP)): sha(p.read_bytes()) for p in
                          (Path(__file__), PINS_PATH, QUAD / "bridge.c", QUAD / "port_layout.h",
                           QUAD / "contract.h", source / "sha256.c", source / "sha256.h")}}
    (out / "build.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("Paired ARM bridge built and self-tested: " + identity["sha256"])


if __name__ == "__main__":
    main()
