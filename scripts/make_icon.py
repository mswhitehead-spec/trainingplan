"""Generate a simple 256x256 PNG icon for the Strava API app.

Pure stdlib — no Pillow needed. Writes the PNG by hand using `zlib` for
the IDAT chunk and `struct` for the headers. Design is geometric so we
don't need a font lib: a dark background plus three horizontal "HR zone"
bars (Z2 olive, Z3 amber, Z4 red).

Usage:
    venv\\Scripts\\python scripts\\make_icon.py [out.png]

Output defaults to docs/app-icon.png.
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

W = H = 256
ROOT = Path(__file__).resolve().parent.parent


# ----- the actual drawing --------------------------------------------------

# Background and three HR-zone-coloured stripes.
BG       = (15, 23, 42)      # slate-900-ish
CARD     = (30, 41, 59)      # slate-800 — a slightly lighter inset
Z2       = (132, 204, 22)    # lime — easy / aerobic
Z3       = (234, 179, 8)     # amber — tempo
Z4       = (220, 38, 38)     # red — threshold


def render() -> list[tuple[int, int, int]]:
    """Return a flat row-major list of (r, g, b) tuples, length W*H."""
    px = [BG] * (W * H)

    def fill_rect(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        for y in range(max(0, y0), min(H, y1)):
            row = y * W
            for x in range(max(0, x0), min(W, x1)):
                px[row + x] = color

    # Inset card so the icon doesn't look like it bleeds to the edges.
    fill_rect(20, 20, W - 20, H - 20, CARD)

    # Three bars, each 28 px tall with 12 px gap, centered vertically.
    bar_h = 28
    gap = 12
    total = bar_h * 3 + gap * 2
    top = (H - total) // 2

    # Bar widths suggest "easier = wider base, harder = narrower spike".
    bars = [
        (Z2, 60),    # widest — Z2 base
        (Z3, 110),   # medium — Z3 tempo
        (Z4, 165),   # narrowest left edge → longest bar — Z4 spike
    ]
    bar_left = 50
    bar_right = W - 50
    for i, (color, _left_inset) in enumerate(bars):
        y = top + i * (bar_h + gap)
        # Each bar grows from a shared left edge.
        fill_rect(bar_left, y, bar_right, y + bar_h, color)

    return px


# ----- PNG writer (stdlib only) -------------------------------------------

def _chunk(kind: bytes, body: bytes) -> bytes:
    """Build one PNG chunk: length + type + body + CRC32(type+body)."""
    payload = kind + body
    return (struct.pack(">I", len(body))
            + payload
            + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF))


def write_png(path: Path, pixels: list[tuple[int, int, int]], width: int, height: int) -> None:
    sig = b"\x89PNG\r\n\x1a\n"

    # IHDR: 8-bit depth, color type 2 (RGB), no interlace.
    ihdr_body = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

    # IDAT: each scanline prefixed with a filter byte (0 = None).
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            r, g, b = pixels[y * width + x]
            raw.append(r); raw.append(g); raw.append(b)
    idat_body = zlib.compress(bytes(raw), level=9)

    with path.open("wb") as f:
        f.write(sig)
        f.write(_chunk(b"IHDR", ihdr_body))
        f.write(_chunk(b"IDAT", idat_body))
        f.write(_chunk(b"IEND", b""))


# ----- entrypoint ----------------------------------------------------------

def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "app-icon.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    pixels = render()
    write_png(out, pixels, W, H)
    print(f"wrote {out}  ({W}x{H}, {out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
