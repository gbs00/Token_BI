"""Render a contact sheet from the Rust icon renderer's opt-in RGBA exports."""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def render(source: Path, destination: Path) -> None:
    states = ["100", "75", "50", "25", "1", "0", "unknown"]
    sheet = Image.new("RGB", (980, 420), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", 17)
    small = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", 13)
    destination.parent.mkdir(parents=True, exist_ok=True)
    for row, (background, foreground) in enumerate([
        ((239, 241, 243), (35, 37, 40)),
        ((35, 37, 40), (244, 245, 247)),
    ]):
        top = row * 210
        draw.rectangle((0, top, 980, top + 210), fill=background)
        draw.text((20, top + 14), "18pt / Retina 2x, plus enlarged detail", font=small, fill=foreground)
        for column, state in enumerate(states):
            image = Image.frombytes("RGBA", (36, 36), (source / f"{state}.rgba").read_bytes())
            tinted = Image.new("RGBA", image.size, (*foreground, 255))
            tinted.putalpha(image.getchannel("A"))
            left = column * 140
            sheet.paste(tinted, (left + 52, top + 48), tinted)
            detail = tinted.resize((90, 90), Image.Resampling.NEAREST)
            sheet.paste(detail, (left + 25, top + 92), detail)
            label = state + "%" if state.isdigit() else "Unknown"
            draw.text((left + 70, top + 193), label, font=font, fill=foreground, anchor="mm")
            if row == 0:
                image.save(destination.parent / f"quota-icon-{state}.png")
    sheet.save(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    render(args.source, args.destination)
