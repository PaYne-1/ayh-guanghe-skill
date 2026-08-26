#!/usr/bin/env python3
"""Render an exact Chinese cover title onto an accepted 9:16 storyboard."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin


FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
)


def _font(font_path: Optional[Path], size: int) -> ImageFont.FreeTypeFont:
    candidates = ((font_path,) if font_path else ()) + FONT_CANDIDATES
    for candidate in candidates:
        if candidate and candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    raise RuntimeError("未找到支持中文的字体；请用 --font 指定中文 TTF/TTC")


def _style_from_reference(reference: Optional[Path]) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    if not reference:
        return (255, 238, 82), (20, 20, 20)
    image = Image.open(reference).convert("RGB").resize((1, 1))
    red, green, blue = image.getpixel((0, 0))
    luminance = 0.299 * red + 0.587 * green + 0.114 * blue
    if luminance < 128:
        return (255, 244, 120), (10, 10, 10)
    return (230, 40, 52), (255, 255, 255)


def render_cover(
    storyboard: Path,
    title: str,
    output: Path,
    *,
    reference: Optional[Path] = None,
    font_path: Optional[Path] = None,
) -> Path:
    if not 2 <= sum("\u4e00" <= char <= "\u9fff" for char in title) <= 8:
        raise ValueError("封面标题应为约 4–6 个汉字")
    image = Image.open(storyboard).convert("RGB")
    width, height = image.size
    if abs(width / height - 9 / 16) > 0.03:
        raise ValueError("分镜图必须接近 9:16")
    fill, stroke = _style_from_reference(reference)
    draw = ImageDraw.Draw(image)
    font = _font(font_path, max(42, width // 11))
    box = draw.textbbox((0, 0), title, font=font, stroke_width=max(2, width // 250))
    text_width = box[2] - box[0]
    x = max(24, (width - text_width) // 2)
    y = max(36, height // 11)
    padding = max(14, width // 50)
    background = (0, 0, 0, 120) if fill[0] > 200 and fill[1] > 200 else (255, 255, 255, 170)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle(
        (x - padding, y - padding, x + text_width + padding, y + (box[3] - box[1]) + padding),
        radius=padding,
        fill=background,
    )
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.text(
        (x, y),
        title,
        font=font,
        fill=fill,
        stroke_width=max(2, width // 250),
        stroke_fill=stroke,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("cover_title", title)
    metadata.add_text("style_reference", str(reference.resolve()) if reference else "default")
    image.save(output, pnginfo=metadata)
    return output


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="为已验收分镜图确定性绘制中文封面标题")
    parser.add_argument("--storyboard", type=Path, required=True)
    title_group = parser.add_mutually_exclusive_group(required=True)
    title_group.add_argument("--title")
    title_group.add_argument("--title-file", type=Path, help="UTF-8 文本文件；Windows 中文标题推荐")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--font", type=Path)
    args = parser.parse_args(argv)
    try:
        title = args.title_file.read_text(encoding="utf-8").strip() if args.title_file else args.title
        print(render_cover(args.storyboard, title, args.output, reference=args.reference, font_path=args.font))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"错误：{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
