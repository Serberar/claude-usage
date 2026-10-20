"""Genera claude_usage.ico (se usa al compilar el .exe)."""

from pathlib import Path

from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((8, 8, S - 8, S - 8), radius=56, fill="#1a1d24")
box = (52, 52, S - 52, S - 52)
d.ellipse(box, outline="#2a2f3a", width=26)
d.arc(box, start=-90, end=170, fill="#d97757", width=26)
d.ellipse((S / 2 - 16, S / 2 - 16, S / 2 + 16, S / 2 + 16), fill="#4ade80")

out = Path(__file__).with_name("claude_usage.ico")
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(out)
