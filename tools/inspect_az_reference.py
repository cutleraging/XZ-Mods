"""Inspect the official AZ reference files offline; never run or decrypt firmware."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import tarfile
import zipfile

ZIP_SHA256 = "f56b84c034fec86f319451153ac24e0b7f1ba32cdf5c7366e9f7a75d57e07f6f"
UPD_SHA256 = "ac799829427ee0483cc8ba219684cb341b7ecf1efd0a771390508fefae077ef8"
BSP_MD5 = "143d9eacf4b5830c1d00b76d0d878e75"
BSP_MEMBERS = (
    "XDJ-AZ/manifest_35_rk3399_linux_TVI2326A_20200820.xml",
    "XDJ-AZ/device/rockchip/rk3399/BoardConfig.mk",
    "XDJ-AZ/device/rockchip/rk3399/BoardConfig_debian.mk",
    "XDJ-AZ/device/rockchip/rk3399/parameter.txt",
)


def hashes(path: Path) -> dict:
    sha = hashlib.sha256()
    md5 = hashlib.md5()  # Publisher uses MD5 for this public BSP's file identity.
    size = 0
    with path.open("rb") as source:
        while block := source.read(4 * 1024 * 1024):
            sha.update(block)
            md5.update(block)
            size += len(block)
    return {"bytes": size, "sha256": sha.hexdigest(), "md5": md5.hexdigest()}


def inspect_update(path: Path) -> dict:
    identity = hashes(path)
    if identity["sha256"] != ZIP_SHA256:
        raise ValueError("Not the pinned official AZ 2.00 ZIP")
    with zipfile.ZipFile(path) as archive:
        rows = archive.infolist()
        if len(rows) != 1 or rows[0].filename != "XDJAZv200.UPD":
            raise ValueError("Unexpected ZIP members")
        sha = hashlib.sha256()
        header = b""
        with archive.open(rows[0]) as source:
            while block := source.read(4 * 1024 * 1024):
                if not header:
                    header = block[:592]
                sha.update(block)
        if sha.hexdigest() != UPD_SHA256:
            raise ValueError("Unexpected UPD identity")
        if len(header) != 592 or header[:6] != b"LUKS\xba\xbe":
            raise ValueError("Not a complete LUKS1 header")
        version = struct.unpack_from(">H", header, 6)[0]
        if version != 1:
            raise ValueError("Unsupported LUKS version")
        string = lambda offset: header[offset:offset + 32].split(b"\0", 1)[0].decode("ascii")
        sector = struct.unpack_from(">I", header, 104)[0]
        return {
            "zip": identity,
            "member": {"name": rows[0].filename, "bytes": rows[0].file_size,
                       "sha256": sha.hexdigest(), "zip_crc_verified": True},
            "container": {"format": "LUKS", "version": version,
                          "cipher": string(8), "mode": string(40), "hash": string(72),
                          "payload_offset_bytes": sector * 512,
                          "volume_key_bytes": struct.unpack_from(">I", header, 108)[0]},
            "decrypted": False, "internal_application_inspected": False,
        }


def inspect_bsp(path: Path) -> dict:
    identity = hashes(path)
    if identity["md5"] != BSP_MD5:
        raise ValueError("BSP does not match the manufacturer's published MD5")
    selected = {}
    with tarfile.open(path, "r|gz") as archive:
        for member in archive:
            if member.name not in BSP_MEMBERS:
                continue
            if not member.isfile() or member.size > 1024 * 1024 or member.name in selected:
                raise ValueError("Unexpected BSP member")
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("Unreadable BSP member")
            data = source.read()
            selected[member.name] = {"bytes": len(data),
                                     "sha256": hashlib.sha256(data).hexdigest(),
                                     "text": data.decode("utf-8")}
            if len(selected) == len(BSP_MEMBERS):
                break
    if set(selected) != set(BSP_MEMBERS):
        raise ValueError("Missing selected BSP members")
    return {"archive": identity, "publisher_md5_match": True, "members": selected,
            "scope": "Selected build configuration only; no BSP script executed"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware-zip", required=True, type=Path)
    parser.add_argument("--bsp", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = {"firmware": inspect_update(args.firmware_zip), "bsp": inspect_bsp(args.bsp),
              "hardware_executed": False, "xz_modified": False}
    # Exclusive create preserves earlier receipts; inputs and devices remain read-only.
    with args.output.open("x", encoding="utf-8") as destination:
        json.dump(report, destination, indent=2)
        destination.write("\n")
    print("Verified AZ 2.00 ZIP, encrypted UPD header and published BSP identity.")


if __name__ == "__main__":
    main()
