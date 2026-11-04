"""Stage a private four-deck USB loader from verified paired runtime resources.

This only authors and reads files. It never runs firmware, writes a disk device,
formats a volume, starts the runtime or connects to the mixer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "source/xdj-xz-toolkit"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resources", required=True, type=Path, help="Complete paired quad resources")
    parser.add_argument("--firmware", required=True, type=Path, help="Local official 1.26 ZIP, UPD or extracted application")
    parser.add_argument("--key", required=True, type=Path, help="Local boot key from the manufacturer's source archive")
    parser.add_argument("--output", required=True, type=Path, help="New local staging folder, separate from the USB")
    parser.add_argument("--layout", choices=("mixer", "number"), default="mixer")
    args = parser.parse_args()
    from builder.cache import _safe_path
    from builder import firmware, usb_settings
    from builder.quad_payload import verified_files

    out = _safe_path(args.output)
    # Publishing to removable media is a separate step with a fresh volume identity.
    if sys.platform == "darwin" and Path("/Volumes") in out.parents:
        parser.error("Stage locally first; copy to the identified USB after verification")
    resources = _safe_path(args.resources)
    verified = verified_files(resources)
    if verified is None:
        parser.error("A complete pinned four-deck resource profile is required")
    profile, _ = verified
    manifest = json.loads((resources / "runtime/manifest.json").read_text())
    if "standalone-quad/1" not in manifest.get("capabilities", []):
        parser.error("The paired runtime does not declare standalone four-deck support")
    schema = usb_settings.contract(resources)
    settings = usb_settings.defaults(schema)
    settings["deck_view"] = 2 if args.layout == "mixer" else 1
    config = usb_settings.serialize(settings, schema)
    secret = firmware.effective_key(_safe_path(args.key))
    application, key_verified = firmware.import_application(_safe_path(args.firmware), secret)
    out.mkdir(parents=True, exist_ok=False)
    payload = out / "payload"
    expected = firmware.stage_payload(
        payload, application, resources / "runtime/libxz-mods.so",
        resources / "runtime/libxz-receiver.so", resources / "bootstrap.sh")
    # Carry the same license notices as the normal USB builder. Source archives
    # are supplied by the quad profile and kept locally with the complete package.
    for path in sorted((resources / "licenses").iterdir()):
        if path.is_file() and not path.name.lower().endswith((".zip", ".tar.gz", ".tar.xz", ".tar.bz2")):
            name = "licenses/" + path.name
            data = path.read_bytes()
            if name in expected and expected[name] != data:
                raise ValueError("Conflicting license in paired resources: " + name)
            target = payload / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            expected[name] = data
    image = firmware.author_image(payload, secret)
    structure = firmware.verify_image(image, secret, expected)
    public = out / "usb-root"
    (public / "VJ.Tools").mkdir(parents=True)
    (public / "autoexec.bin").write_bytes(image)
    (public / "VJ.Tools/XZ-Mods.cfg").write_bytes(config)
    # Independently read the published files, not just the in-memory authoring inputs.
    firmware.verify_image((public / "autoexec.bin").read_bytes(), secret, expected)
    if usb_settings.parse((public / "VJ.Tools/XZ-Mods.cfg").read_bytes(), schema) != settings:
        raise ValueError("Published preferences differ from the verified preset")
    receipt = {
        "schema": "xz-four-deck-staging/1", "firmware": "XDJ-XZ 1.26",
        "runtime_source_commit": profile["source_commit"],
        "runtime_sha256": manifest["runtime_sha256"],
        "receiver_sha256": manifest["receiver_sha256"],
        "quad_profile_sha256": hashlib.sha256((resources / "runtime/quad-package.json").read_bytes()).hexdigest(),
        "layout": args.layout, "deck_view": settings["deck_view"],
        "key_verified_against_input": key_verified, "structure": structure,
        "files": {str(p.relative_to(public)): {"bytes": p.stat().st_size,
                  "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                  for p in sorted(public.rglob("*")) if p.is_file()},
        "hardware_tested": False, "firmware_executed": False,
        "contains_local_firmware": True, "share_image": False,
        "note": "Matched upstream ARM runtime; fork host portability changes are not a new target build",
    }
    (out / "staging-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("Verified private USB-root files: " + str(public))
    print("No USB or mixer was changed. Receipt: " + str(out / "staging-receipt.json"))


if __name__ == "__main__":
    main()
