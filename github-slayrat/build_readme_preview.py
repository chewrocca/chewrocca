#!/usr/bin/env python3
"""Preview the profile README, with Sooz swapped in, exactly as GitHub renders it.

The markdown goes through GitHub's own /markdown API, so the preview passes the
same sanitizer the live profile page uses. That is what makes it proof rather
than a mockup: if the graphic would be stripped, it is stripped here too.

Writes into out/:
  readme-dark.html    the README on GitHub dark, pinned to the dark SVG
  readme-light.html   the same on GitHub light
  preview.html        just the graphic, both themes
  readme-preview.html a hub linking to the three

Each is a standalone page on purpose. Chrome throttles SMIL animation inside an
iframe, so a framed side-by-side view shows a frozen first frame and makes
working artwork look broken.

Usage:  python3 build_readme_preview.py [--repo owner/name] [--check]
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
CDN = "https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.5.1"
PICTURE = """<picture>
  <source media="(prefers-color-scheme: dark)" srcset="slayrat-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="slayrat-light.svg">
  <img alt="My GitHub contribution graph, slashed by Slay Rat" src="slayrat-dark.svg">
</picture>"""


def gh(*args, **kw):
    """Run gh, failing with a readable message instead of a traceback."""
    try:
        p = subprocess.run(("gh",) + args, capture_output=True, text=True, **kw)
    except FileNotFoundError:
        sys.exit("the GitHub CLI (gh) is required: https://cli.github.com")
    if p.returncode:
        sys.exit(f"gh {' '.join(args)} failed:\n{p.stderr.strip()}")
    return p.stdout


def fetch_readme(repo, path):
    """Cache the profile README locally; patch_readme.py edits this copy."""
    if not os.path.exists(path):
        raw = gh("api", f"/repos/{repo}/contents/README.md", "--jq", ".content")
        with open(path, "w", encoding="utf-8") as f:
            f.write(base64.b64decode(raw).decode("utf-8"))
    with open(path, encoding="utf-8") as f:
        return f.read()


def swap(md, mode):
    """Point the <picture> block at the locally generated SVGs.

    mode "picture" keeps the markup we would actually ship, for the sanitizer
    check. "dark"/"light" pin one file so a preview pane cannot drift with the
    viewer's OS theme and silently show only one of the two.
    """
    new = PICTURE if mode == "picture" else (
        f'<img alt="My GitHub contribution graph, slashed by Slay Rat" '
        f'src="slayrat-{mode}.svg">')
    # A lambda replacement sidesteps backreference escaping in the payload.
    out, n = re.subn(r"<picture>.*?</picture>", lambda _: new, md, count=1, flags=re.S)
    if not n:
        sys.exit("could not find the <picture> block to replace")
    return out


def render(md):
    """GitHub's markdown API: same pipeline and sanitizer as the real page."""
    return gh("api", "--method", "POST", "/markdown", "--input", "-",
              input=json.dumps({"mode": "gfm", "text": md}))


def css(theme):
    """Vendor the GitHub markdown stylesheet once, atomically."""
    name = f"github-markdown-{theme}.css"
    path = os.path.join(OUT, name)
    if not os.path.exists(path):
        try:
            with urllib.request.urlopen(f"{CDN}/{name.replace('.css', '.min.css')}",
                                        timeout=15) as r:
                data = r.read()
        except (urllib.error.URLError, TimeoutError) as e:
            sys.exit(f"could not download {name}: {e}")
        # Write to a temp file and move, so an interrupted download never
        # leaves a truncated stylesheet that the exists() check then trusts.
        fd, tmp = tempfile.mkstemp(dir=OUT)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    return name


def page(theme, body):
    bg = "#0d1117" if theme == "dark" else "#ffffff"
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Profile README ({theme})</title>
<link rel="stylesheet" href="{css(theme)}">
<style>
  body {{ margin:0; background:{bg}; }}
  .markdown-body {{ max-width:1012px; margin:0 auto; padding:32px 16px 48px;
                    background:{bg}; }}
</style>
<article class="markdown-body">
{body}
</article>
"""


def graphic_only():
    return """<!doctype html>
<meta charset="utf-8">
<title>Slay Rat contribution graph</title>
<style>
  body { margin:0; background:#0d1117; color:#c9d1d9;
         font:14px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace; padding:24px 20px 60px; }
  h1 { font-size:15px; letter-spacing:2px; text-transform:uppercase; color:#e6edf3; margin:0 0 4px; }
  p.sub { color:#8b949e; margin:0 0 28px; }
  h2 { font-size:11px; text-transform:uppercase; letter-spacing:1.5px;
       color:#8b949e; margin:32px 0 8px; font-weight:600; }
  .frame { border:1px solid #21262d; border-radius:10px; overflow:hidden; display:inline-block; }
  .frame.light { background:#fff; border-color:#d0d7de; }
  img { display:block; max-width:100%; height:auto; }
  button { font:inherit; background:#21262d; color:#c9d1d9; border:1px solid #30363d;
           border-radius:6px; padding:5px 12px; cursor:pointer; margin-right:8px; }
  button:hover { background:#30363d; }
</style>
<h1>Slay Rat vs. the contribution graph</h1>
<p class="sub">She slashes every week that has commits; each contribution throws a coin.</p>
<h2>Dark</h2>
<div class="frame"><img id="d" src="slayrat-dark.svg" alt="Slay Rat, dark"></div>
<h2>Light</h2>
<div class="frame light"><img id="l" src="slayrat-light.svg" alt="Slay Rat, light"></div>
<p>
  <button onclick="replay('d')">replay dark</button>
  <button onclick="replay('l')">replay light</button>
  <span style="color:#6e7681">the loop restarts on its own too</span>
</p>
<script>
  // Re-request the image to restart its SMIL clock from zero.
  function replay(id) {
    const el = document.getElementById(id);
    el.src = el.src.split('?')[0] + '?' + Date.now();
  }
</script>
"""


def hub(kept, has_picture):
    ok = lambda good, yes, no: (  # noqa: E731
        f'<span style="color:{"#3fb950" if good else "#f85149"}">'
        f'{yes if good else no}</span>')
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Profile README preview</title>
<style>
  body {{ margin:0; background:#010409; color:#8b949e; padding:40px 24px;
          font:14px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace; }}
  h1 {{ color:#e6edf3; font-size:16px; letter-spacing:1px; margin:0 0 6px; }}
  ul {{ list-style:none; padding:0; margin:26px 0; }}
  li {{ margin:0 0 12px; }}
  a {{ display:inline-block; padding:12px 20px; border:1px solid #30363d;
       border-radius:8px; color:#58a6ff; text-decoration:none; background:#0d1117; }}
  a:hover {{ background:#161b22; }}
  .note {{ color:#6e7681; max-width:64ch; }}
</style>
<h1>Profile README preview</h1>
<p>Your real README, rendered by GitHub's own <code>/markdown</code> API, with
the local build swapped in.</p>
<p>{ok(kept, "&#10003; graphic survives the sanitizer", "&#10007; GRAPHIC STRIPPED")}
 &nbsp; {ok(has_picture, "&#10003; &lt;picture&gt; preserved", "&#10007; &lt;picture&gt; stripped")}</p>
<ul>
  <li><a href="readme-dark.html">Open on GitHub dark &rarr;</a></li>
  <li><a href="readme-light.html">Open on GitHub light &rarr;</a></li>
  <li><a href="preview.html">Just the graphic, both themes &rarr;</a></li>
</ul>
<p class="note">Each opens as its own page on purpose. Chrome throttles SMIL
animation inside an iframe, so a framed side-by-side view shows a frozen first
frame even though the artwork is fine. Reload a page to restart the loop.</p>
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default="chewrocca/chewrocca",
                    help="profile repo to pull the README from")
    ap.add_argument("--readme", default=os.path.join(HERE, "profile-README.md"))
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if GitHub's sanitizer strips the graphic")
    args = ap.parse_args(argv)

    os.makedirs(OUT, exist_ok=True)
    md = fetch_readme(args.repo, args.readme)

    shipped = render(swap(md, "picture"))
    kept = "slayrat-dark.svg" in shipped
    has_picture = "<picture" in shipped

    for theme in ("dark", "light"):
        with open(os.path.join(OUT, f"readme-{theme}.html"), "w", encoding="utf-8") as f:
            f.write(page(theme, render(swap(md, theme))))
    with open(os.path.join(OUT, "preview.html"), "w", encoding="utf-8") as f:
        f.write(graphic_only())
    with open(os.path.join(OUT, "readme-preview.html"), "w", encoding="utf-8") as f:
        f.write(hub(kept, has_picture))

    print(f"wrote {os.path.join(OUT, 'readme-preview.html')}")
    print(f"  graphic survives sanitizer : {kept}")
    print(f"  <picture> preserved        : {has_picture}")
    if args.check and not (kept and has_picture):
        sys.exit("sanitizer check FAILED")


if __name__ == "__main__":
    main()
