#!/usr/bin/env python3
"""Report the PE subsystem of a Windows executable: 2 = GUI (no console window), 3 = console.

    python pe_subsystem.py <exe> [gui|console]     exit code 1 if it is not the expected kind
"""
from __future__ import annotations

import struct
import sys

NAMES = {2: "gui", 3: "console"}


def subsystem(path: str) -> int:
    with open(path, "rb") as f:
        d = f.read(4096)
    if d[:2] != b"MZ":
        raise SystemExit(f"not a PE file: {path}")
    e = struct.unpack_from("<I", d, 0x3C)[0]               # e_lfanew
    if d[e:e + 4] != b"PE\0\0":
        raise SystemExit(f"PE signature not found: {path}")
    return struct.unpack_from("<H", d, e + 24 + 68)[0]      # optional header: Subsystem (same offset for PE32 and PE32+)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sub = subsystem(sys.argv[1])
    kind = NAMES.get(sub, f"other({sub})")
    print(f"{sys.argv[1]}: subsystem {sub} = {kind}")
    if len(sys.argv) > 2 and kind != sys.argv[2]:
        raise SystemExit(f"expected {sys.argv[2]}, got {kind}")
