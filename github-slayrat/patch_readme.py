#!/usr/bin/env python3
"""Apply the two profile-README changes to the local working copy.

1. Wrap the contribution graph in a link out to slayrat.com. It has to go in the
   markdown, not inside the SVG: links within an SVG are inert when it is served
   through <img>, which is how GitHub serves it.
2. Unstack the footer badges. They sit as bare lines inside <div align="center">
   and GFM turns each newline there into a <br>, so every badge lands on its own
   row. Wrapping them in an explicit <p> makes markdown pass the block through as
   raw HTML untouched, which is exactly why the badges at the top of the README
   were always fine.

Idempotent: safe to run more than once.

Usage:  python3 patch_readme.py [--readme profile-README.md]
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LINK = "https://slayrat.com"

PICTURE_RE = re.compile(r"<picture>.*?</picture>", re.S)
# The footer is the mailto badge plus the &nbsp;-separated badges after it.
FOOTER_RE = re.compile(r'<a href="mailto:[^\n]*\n(?:&nbsp;\n<a href="[^\n]*\n?)+')
ANCHOR_OPEN = f'<a href="{LINK}">'


def patch(md):
    """Return (new_markdown, [descriptions of what changed])."""
    changed = []

    m = PICTURE_RE.search(md)
    if not m:
        sys.exit("could not find the <picture> block")
    if ANCHOR_OPEN not in md[:m.start()][-40:]:
        md = md[:m.start()] + f"{ANCHOR_OPEN}\n{m.group(0)}\n</a>" + md[m.end():]
        changed.append("linked the graph to slayrat.com")

    m = FOOTER_RE.search(md)
    if not m:
        sys.exit("could not find the footer badge block; has it been reflowed?")
    block = m.group(0)
    if not md[:m.start()].rstrip().endswith("<p>"):
        # Splice by span rather than str.replace, which would hit every match.
        md = md[:m.start()] + "<p>\n" + block.rstrip("\n") + "\n</p>\n" + md[m.end():]
        changed.append("wrapped the footer badges in <p>")

    return md, changed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--readme", default=os.path.join(HERE, "profile-README.md"))
    args = ap.parse_args(argv)

    try:
        with open(args.readme, encoding="utf-8") as f:
            md = f.read()
    except FileNotFoundError:
        sys.exit(f"no README at {args.readme}; run build_readme_preview.py first")

    md, changed = patch(md)
    if not changed:
        print("already patched, nothing to do")
        return
    with open(args.readme, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"patched {args.readme}")
    for c in changed:
        print(f"  - {c}")


if __name__ == "__main__":
    main()
