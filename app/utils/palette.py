"""Emotion colors shared by native and browser views.

Colors are user preferences, not model predictions. Every indication also carries
a text label; readable foregrounds are calculated from the chosen background.
"""
import re

DEFAULT_EMOTION_COLORS = {
    "angry": "#dc4848", "disgust": "#679940", "fear": "#8c65cc",
    "happy": "#f4c542", "neutral": "#7596ad", "sad": "#5488cb",
    "uncertain": "#d0d7df",
}


def validate_palette(colors):
    if not isinstance(colors, dict) or set(colors) != set(DEFAULT_EMOTION_COLORS):
        raise ValueError("Assign one color to each emotion, including uncertain.")
    if any(not isinstance(c, str) or re.fullmatch(r"#[0-9a-fA-F]{6}", c) is None
           for c in colors.values()):
        raise ValueError("Emotion colors must use #RRGGBB notation.")
    return colors


def foreground(background):
    """Choose black or white to meet WCAG AA for any valid sRGB background."""
    channels = [int(background[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
    luminance = sum(c * w for c, w in zip(linear, (.2126, .7152, .0722)))
    return "#000000" if (luminance + .05) / .05 >= 1.05 / (luminance + .05) else "#ffffff"
