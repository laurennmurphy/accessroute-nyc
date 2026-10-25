"""Guards WCAG 2.1 AA text contrast for the colour tokens in static/style.css.

Parses the :root variable blocks (light, and the prefers-color-scheme: dark
override) and checks every foreground/background pairing the stylesheet uses.
"""
import re
from pathlib import Path

CSS = (Path(__file__).resolve().parent.parent / "static" / "style.css").read_text()


def luminance(hex_color):
    h = hex_color.lstrip("#")
    chans = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def tokens():
    """Return (light, dark) dicts of --name: #hex from the first two :root blocks."""
    blocks = re.findall(r":root\s*\{([^}]*)\}", CSS)
    parse = lambda b: dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", b))
    light, dark = parse(blocks[0]), parse(blocks[1])
    return light, {**light, **dark}  # dark only overrides some tokens


# (foreground, background, minimum ratio)
TEXT_PAIRS = [
    ("text", "bg", 4.5), ("text", "card", 4.5),
    ("muted", "bg", 4.5), ("muted", "card", 4.5),      # descriptions, hints, outage details
    ("accent", "bg", 4.5), ("accent", "card", 4.5),    # links, headings
    ("on-accent", "accent", 4.5),                      # buttons, user chat bubbles, line badges
]
PILL_BACKGROUNDS = ["ok", "warn", "bad"]               # verdict pills use white text


def test_text_contrast_meets_aa():
    for scheme, t in zip(("light", "dark"), tokens()):
        for fg, bg, need in TEXT_PAIRS:
            assert ratio(t[fg], t[bg]) >= need, f"{scheme}: {fg} on {bg} = {ratio(t[fg], t[bg]):.2f}"
        for bg in PILL_BACKGROUNDS:
            assert ratio("#ffffff", t[bg]) >= 4.5, f"{scheme}: white on {bg} = {ratio('#ffffff', t[bg]):.2f}"


def test_ui_component_contrast_meets_aa():
    """Borders and focus rings need 3:1 (WCAG 1.4.11)."""
    for scheme, t in zip(("light", "dark"), tokens()):
        for fg in ("border", "focus"):
            for bg in ("bg", "card"):
                assert ratio(t[fg], t[bg]) >= 3, f"{scheme}: {fg} on {bg}"


def test_no_text_smaller_than_16px():
    sizes = [float(v) for v in re.findall(r"font-size:\s*([\d.]+)rem", CSS)]
    assert sizes and min(sizes) >= 1.0
    assert not re.search(r"font-size:\s*[\d.]+px", CSS) or all(
        float(v) >= 16 for v in re.findall(r"font-size:\s*([\d.]+)px", CSS))
