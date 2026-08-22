#!/usr/bin/env python3
"""Pack the Sooz frames gen.py animates into one strip for SVG embedding.

The frames are shaded rather than flat pixel art (~2000 colours each), so an
aggressive shared palette is not safe: colours drift between frames and she
visibly shimmers as she runs. This picks the smallest encoding whose sampled
mean colour error stays under ERR_LIMIT, falling back to full RGBA rather than
shipping wrong-looking art to save a few KB.

Usage:  python3 prep_sprites.py [--assets DIR]
"""
import argparse
import base64
import io
import json
import os
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required: pip install Pillow")

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ASSETS = os.path.normpath(
    os.path.join(HERE, os.pardir, "slayrat", "assets", "processed"))
ERR_LIMIT = 1.5   # sampled mean per-channel error, 0-255, over opaque pixels

# Only frames gen.py actually selects. `apex` is deliberately absent: the apex
# of every hop coincides with a hit, so the slash combo always wins there and
# the frame would ship as ~15 KB of dead weight.
WANTED = [
    ("sooz", [f"run{i}" for i in range(8)]),            # ground run cycle
    # Three combat frames, not one: hits land every ~0.18s, and a single held
    # arcslash sat on screen ~40% of the loop and read as a freeze.
    ("soozcombat", ["thrust", "arcslash", "riposte", "flourish"]),
    ("soozair", ["rise", "fall1", "fall2"]),            # jump arc
    ("sooz", ["land"]),                                 # touchdown
]


def load_frames(assets):
    path = os.path.join(assets, "manifest.json")
    try:
        with open(path, encoding="utf-8") as f:
            man = json.load(f)
    except FileNotFoundError:
        sys.exit(f"no sprite manifest at {path}\n"
                 f"point --assets at the slayrat repo's assets/processed directory")

    picked = []
    for key, names in WANTED:
        if key not in man:
            sys.exit(f"{path} has no sheet {key!r}")
        m = man[key]
        sheet_path = os.path.join(assets, m["file"])
        try:
            sheet = Image.open(sheet_path).convert("RGBA")
        except FileNotFoundError:
            sys.exit(f"missing sprite sheet {sheet_path}")
        cw, ch = m["cw"], m["ch"]
        for n in names:
            try:
                i = m["names"].index(n)
            except ValueError:
                sys.exit(f"sheet {key!r} ({m['file']}) has no frame {n!r}")
            picked.append((n, sheet.crop((i * cw, 0, (i + 1) * cw, ch))))
    if not picked:
        sys.exit("WANTED selected no frames")
    return picked


def pack(picked):
    """Crop every frame to one shared alpha box so they stay registered."""
    box = None
    for _, im in picked:
        b = im.getbbox()
        if b is None:
            continue
        box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]),
                                     max(box[2], b[2]), max(box[3], b[3]))
    if box is None:
        sys.exit("every frame is fully transparent")

    cropped = [(n, im.crop(box)) for n, im in picked]
    fw, fh = cropped[0][1].size
    strip = Image.new("RGBA", (fw * len(cropped), fh), (0, 0, 0, 0))
    for i, (_, im) in enumerate(cropped):
        strip.paste(im, (i * fw, 0))
    return strip, cropped, fw, fh, box


def encode_rgba(strip):
    buf = io.BytesIO()
    strip.save(buf, "PNG", optimize=True)
    return buf.getvalue(), 0.0


def encode_quantised(strip, colors, step=2):
    """Quantise to a shared palette and measure the damage.

    Error is sampled on a `step` grid, not every pixel, which is plenty to tell
    a safe palette from a drifting one and keeps this fast.
    """
    alpha = strip.getchannel("A")
    quant = strip.convert("RGB").quantize(colors=colors,
                                          method=Image.MEDIANCUT).convert("RGBA")
    quant.putalpha(alpha)

    orig_px, quant_px = strip.load(), quant.load()
    total = count = 0
    for y in range(0, strip.height, step):
        for x in range(0, strip.width, step):
            if orig_px[x, y][3] > 128:
                total += sum(abs(orig_px[x, y][c] - quant_px[x, y][c]) for c in range(3))
                count += 3
    buf = io.BytesIO()
    quant.save(buf, "PNG", optimize=True)
    return buf.getvalue(), (total / count if count else 0.0)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--assets", default=os.environ.get("SLAYRAT_ASSETS", DEFAULT_ASSETS),
                    help="slayrat assets/processed directory (default: ../slayrat/...)")
    args = ap.parse_args(argv)

    picked = load_frames(args.assets)
    strip, cropped, fw, fh, box = pack(picked)
    print(f"union bbox {box} -> frame {fw}x{fh}, {len(cropped)} frames")

    candidates = [("rgba", *encode_rgba(strip))]
    for c in (256, 192, 128):
        candidates.append((f"quant{c}", *encode_quantised(strip, c)))

    print("\n  encoding    bytes    sampled colour error")
    for name, data, err in candidates:
        verdict = "ok" if err <= ERR_LIMIT else "rejected, drifts"
        print(f"  {name:10s} {len(data):7d}    {err:5.2f}  {verdict}")

    # The rgba candidate always has err 0.0, so this can never be empty.
    name, data, err = min((c for c in candidates if c[2] <= ERR_LIMIT),
                          key=lambda c: len(c[1]))
    print(f"\nusing {name} ({len(data)} bytes, error {err:.2f})")

    payload = {"frameW": fw, "frameH": fh,
               "names": [n for n, _ in cropped],
               "b64": base64.b64encode(data).decode()}
    out = os.path.join(HERE, "sooz-strip.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    print(f"wrote {out} ({len(payload['b64'])} base64 chars)")


if __name__ == "__main__":
    main()
