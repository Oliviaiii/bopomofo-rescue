"""Generate the README demo animation.

Run from the repository root:
    python scripts/generate_demo_gif.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "demo.gif"

WIDTH, HEIGHT = 960, 420
SCALE = 1

BG = "#11111b"
WINDOW = "#1e1e2e"
WINDOW_TOP = "#181825"
BORDER = "#313244"
TEXT = "#cdd6f4"
MUTED = "#7f849c"
LAVENDER = "#b4befe"
YELLOW = "#f9e2af"
YELLOW_BG = (249, 226, 175)
GREEN = "#a6e3a1"
GREEN_BG = (166, 227, 161)

LATIN_FONT_PATH = Path(r"C:\Windows\Fonts\consola.ttf")
CJK_FONT_PATH = Path(r"C:\Windows\Fonts\NotoSansTC-VF.ttf")

SOURCE = "這個 PR dk3u3 merge 了嗎"
PREFIX = "這個 PR "
MISTYPE = "dk3u3"
REPLACEMENT = "可以"
SUFFIX = " merge 了嗎"

assert SOURCE == PREFIX + MISTYPE + SUFFIX
assert PREFIX + REPLACEMENT + SUFFIX == "這個 PR 可以 merge 了嗎"


def load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise FileNotFoundError(f"Required font not found: {path}")
    return ImageFont.truetype(str(path), size)


LATIN = load_font(LATIN_FONT_PATH, 43)
CJK = load_font(CJK_FONT_PATH, 42)
LATIN_SMALL = load_font(LATIN_FONT_PATH, 19)
CJK_SMALL = load_font(CJK_FONT_PATH, 22)
CJK_STATUS = load_font(CJK_FONT_PATH, 20)


def font_for(char: str, *, small: bool = False) -> ImageFont.FreeTypeFont:
    if ord(char) < 128:
        return LATIN_SMALL if small else LATIN
    return CJK_SMALL if small else CJK


def text_width(text: str, *, small: bool = False) -> float:
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    return sum(scratch.textlength(char, font=font_for(char, small=small)) for char in text)


def draw_mixed(
    image: Image.Image,
    position: tuple[float, float],
    text: str,
    *,
    color: str | tuple[int, int, int, int] = TEXT,
    small: bool = False,
    alpha: int = 255,
) -> float:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x, baseline = position
    rgba = ImageColor_getrgb(color, alpha)
    for char in text:
        font = font_for(char, small=small)
        draw.text((x, baseline), char, font=font, fill=rgba, anchor="ls")
        x += draw.textlength(char, font=font)
    image.alpha_composite(layer)
    return x


def ImageColor_getrgb(
    color: str | tuple[int, int, int, int], alpha: int
) -> tuple[int, int, int, int]:
    if isinstance(color, tuple):
        return color
    value = color.lstrip("#")
    red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    return red, green, blue, alpha


def rounded_highlight(
    image: Image.Image,
    box: tuple[float, float, float, float],
    color: tuple[int, int, int],
    alpha: int,
) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.rounded_rectangle(box, radius=9, fill=(*color, alpha))
    image.alpha_composite(layer)


def ease(value: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * value)


def base_frame() -> Image.Image:
    image = Image.new("RGBA", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)

    # Window shadow and terminal shell.
    draw.rounded_rectangle((25, 29, 935, 401), radius=23, fill="#090910")
    draw.rounded_rectangle(
        (18, 18, 928, 390), radius=23, fill=WINDOW, outline=BORDER, width=2
    )
    draw.rounded_rectangle((19, 19, 927, 78), radius=22, fill=WINDOW_TOP)
    draw.rectangle((19, 57, 927, 78), fill=WINDOW_TOP)
    draw.line((19, 78, 927, 78), fill=BORDER, width=2)

    # Familiar terminal chrome.
    for x, color in ((50, "#f38ba8"), (78, "#f9e2af"), (106, "#a6e3a1")):
        draw.ellipse((x - 7, 42 - 7, x + 7, 42 + 7), fill=color)

    title = "bopomofo-rescue — 精準還原預覽"
    title_w = text_width(title, small=True)
    draw_mixed(image, ((WIDTH - title_w) / 2, 50), title, color=MUTED, small=True)

    # Prompt and context labels.
    draw.text((60, 154), ">", font=LATIN, fill=LAVENDER, anchor="ls")
    draw_mixed(image, (91, 116), "輸入內容", color=MUTED, small=True)
    draw_mixed(image, (91, 346), "中文、英文與檔名保持原樣", color=MUTED, small=True)

    return image


def render(
    *,
    typed: int | None = None,
    detect_alpha: float = 0,
    transition: float = 0,
    success_alpha: float = 0,
    final_status: float = 0,
    cursor_on: bool = True,
) -> Image.Image:
    image = base_frame()
    draw = ImageDraw.Draw(image)
    line_x = 91.0
    baseline = 226.0

    if typed is not None:
        shown = SOURCE[:typed]
        cursor_x = draw_mixed(image, (line_x, baseline), shown)
    else:
        prefix_end = draw_mixed(image, (line_x, baseline), PREFIX)
        old_width = text_width(MISTYPE)
        new_width = text_width(REPLACEMENT)
        progress = ease(transition)
        active_width = old_width + (new_width - old_width) * progress
        suffix_x = prefix_end + active_width

        if detect_alpha > 0:
            rounded_highlight(
                image,
                (prefix_end - 7, baseline - 44, prefix_end + old_width + 7, baseline + 10),
                YELLOW_BG,
                int(72 * detect_alpha),
            )

        if success_alpha > 0:
            rounded_highlight(
                image,
                (prefix_end - 7, baseline - 44, prefix_end + active_width + 7, baseline + 10),
                GREEN_BG,
                int(92 * success_alpha),
            )

        old_alpha = int(255 * (1 - progress))
        new_alpha = int(255 * progress)
        if old_alpha:
            draw_mixed(
                image,
                (prefix_end, baseline),
                MISTYPE,
                color=YELLOW if detect_alpha else TEXT,
                alpha=old_alpha,
            )
        if new_alpha:
            draw_mixed(
                image,
                (prefix_end, baseline),
                REPLACEMENT,
                color=GREEN if success_alpha > 0 else TEXT,
                alpha=new_alpha,
            )

        cursor_x = draw_mixed(image, (suffix_x, baseline), SUFFIX)

        if detect_alpha > 0 and transition == 0:
            draw_mixed(
                image,
                (prefix_end, 292),
                "↓ 偵測到注音誤打",
                color=YELLOW,
                small=True,
                alpha=int(255 * detect_alpha),
            )

        if transition > 0 or final_status > 0:
            draw_mixed(
                image,
                (91, 292),
                "✓ 只修復誤打片段，其餘內容保持原樣",
                color=GREEN,
                small=True,
                alpha=int(255 * max(progress, final_status)),
            )

    if cursor_on:
        draw.rounded_rectangle(
            (cursor_x + 5, baseline - 39, cursor_x + 9, baseline + 5),
            radius=2,
            fill=LAVENDER,
        )

    return image


def add_frame(
    frames: list[Image.Image],
    durations: list[int],
    frame: Image.Image,
    duration: int,
) -> None:
    frames.append(frame.convert("RGB"))
    durations.append(duration)


def generate() -> None:
    frames: list[Image.Image] = []
    durations: list[int] = []

    add_frame(frames, durations, render(typed=0), 450)

    for index in range(1, len(SOURCE) + 1):
        add_frame(
            frames,
            durations,
            render(typed=index, cursor_on=index % 6 < 4),
            85,
        )

    add_frame(frames, durations, render(typed=len(SOURCE), cursor_on=False), 550)

    for index in range(9):
        amount = ease(index / 8)
        add_frame(
            frames,
            durations,
            render(detect_alpha=amount, cursor_on=index % 5 < 3),
            65,
        )

    for index in range(8):
        pulse = 0.88 + 0.12 * math.sin(index / 7 * math.pi)
        add_frame(
            frames,
            durations,
            render(detect_alpha=pulse, cursor_on=index % 5 < 3),
            80,
        )

    for index in range(1, 13):
        amount = index / 12
        add_frame(
            frames,
            durations,
            render(
                detect_alpha=1 - amount,
                transition=amount,
                success_alpha=amount,
                final_status=amount,
                cursor_on=index % 6 < 4,
            ),
            60,
        )

    for index in range(10):
        fade = 1 - index / 9
        add_frame(
            frames,
            durations,
            render(
                transition=1,
                success_alpha=fade,
                final_status=1,
                cursor_on=index % 6 < 4,
            ),
            70,
        )

    add_frame(
        frames,
        durations,
        render(transition=1, final_status=1, cursor_on=False),
        2200,
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(
        f"Wrote {OUTPUT.relative_to(ROOT)} "
        f"({len(frames)} frames, {sum(durations) / 1000:.2f}s)"
    )


if __name__ == "__main__":
    generate()
