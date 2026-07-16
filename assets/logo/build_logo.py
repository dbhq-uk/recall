#!/usr/bin/env python3
"""Generate the recall logo asset set from one vector definition.

The mark (concept C4, "nested layers"): concentric slate diamonds closing in on
a single azure core. Retrieval as drilling through memory to the one result;
the azure core is the fused answer. Everything below derives from this, so the
mark, wordmark and favicon stay identical and rebuild with one command.
"""
from __future__ import annotations
from pathlib import Path

HERE = Path(__file__).parent
AZURE = "#2E9BFF"
GLINT = "#EAF4FF"

# variant : (slate for the rings, wordmark text colour, favicon glint)
THEMES = {
    "dark":  ("#8A99B0", "#EAF1F8", GLINT),
    "light": ("#46566E", "#161D28", GLINT),
}


def dia(cx: float, cy: float, r: float) -> str:
    return f"{cx:.1f},{cy-r:.1f} {cx+r:.1f},{cy:.1f} {cx:.1f},{cy+r:.1f} {cx-r:.1f},{cy:.1f}"


def mark_body(slate: str, stroke: float = 11.0) -> str:
    cx = cy = 128.0
    rings = (
        f'<g fill="none" stroke="{slate}" stroke-width="{stroke}" '
        f'stroke-linejoin="round">'
        f'<polygon points="{dia(cx, cy, 70)}"/>'
        f'<polygon points="{dia(cx, cy, 45)}"/>'
        "</g>"
    )
    core = (
        f'<polygon points="{dia(cx, cy, 21)}" fill="{AZURE}"/>'
        f'<polygon points="{dia(cx, cy, 9)}" fill="{GLINT}"/>'
    )
    return rings + core


def build_mark(slate: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" '
        'width="256" height="256" role="img" aria-label="recall">\n'
        f"{mark_body(slate)}\n</svg>\n"
    )


def build_wordmark(slate: str, text_col: str) -> str:
    W, H = 720, 256
    body = mark_body(slate)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}" role="img" aria-label="recall">\n'
        f'<g transform="translate(-8,0)">{body}</g>\n'
        f'<text x="258" y="170" font-family="Inter, ui-sans-serif, -apple-system, '
        f'Segoe UI, Helvetica, Arial, sans-serif" font-size="152" font-weight="640" '
        f'letter-spacing="-7" fill="{text_col}">recall</text>\n'
        f'<circle cx="690" cy="150" r="11" fill="{AZURE}"/>\n'
        "</svg>\n"
    )


def build_favicon() -> str:
    """Reduced for tiny sizes: one slate diamond + azure core on a rounded tile.
    The inner ring is dropped so 16px stays legible."""
    slate = "#AEBBD0"
    tile = "#0E141C"
    cx = cy = 128.0
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" '
        'width="256" height="256" role="img" aria-label="recall">\n'
        f'<rect width="256" height="256" rx="56" fill="{tile}"/>\n'
        f'<polygon points="{dia(cx, cy, 74)}" fill="none" stroke="{slate}" '
        f'stroke-width="16" stroke-linejoin="round"/>\n'
        f'<polygon points="{dia(cx, cy, 34)}" fill="{AZURE}"/>\n'
        f'<polygon points="{dia(cx, cy, 15)}" fill="{GLINT}"/>\n'
        "</svg>\n"
    )


def main() -> None:
    for name, (slate, text_col, _glint) in THEMES.items():
        (HERE / f"recall-mark-{name}.svg").write_text(build_mark(slate))
        (HERE / f"recall-wordmark-{name}.svg").write_text(build_wordmark(slate, text_col))
    (HERE / "recall-favicon.svg").write_text(build_favicon())
    names = sorted(p.name for p in HERE.glob("recall-*.svg"))
    print("wrote:", ", ".join(names))


if __name__ == "__main__":
    main()
