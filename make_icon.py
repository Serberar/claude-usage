"""Genera claude_usage.ico (se usa al compilar el .exe): un medidor de consumo."""

import math
from pathlib import Path

from PIL import Image, ImageDraw

S = 1024                      # se dibuja grande y se reduce: bordes suaves
CX, CY, R, W = S / 2, S * 0.56, S * 0.33, S * 0.1
START, SWEEP, VALUE = 150, 240, 0.68    # arco abierto por abajo, lleno al 68 %


def point(angle, radius):
    rad = math.radians(angle)
    return CX + radius * math.cos(rad), CY + radius * math.sin(rad)


def arc(draw, start, end, color):
    box = (CX - R, CY - R, CX + R, CY + R)
    draw.arc(box, start, end, fill=color, width=int(W))
    for angle in (start, end):  # extremos redondeados
        x, y = point(angle, R - W / 2)
        draw.ellipse((x - W / 2, y - W / 2, x + W / 2, y + W / 2), fill=color)


img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((S * 0.03, S * 0.03, S * 0.97, S * 0.97), radius=S * 0.22, fill="#171a21")
arc(d, START, START + SWEEP, "#2c313c")
end = START + SWEEP * VALUE
arc(d, START, end, "#e07b56")
x, y = point(end, R * 0.78)
d.line((CX, CY, x, y), fill="#eef0f5", width=int(S * 0.05))
d.ellipse((CX - S * 0.065, CY - S * 0.065, CX + S * 0.065, CY + S * 0.065), fill="#eef0f5")

out = Path(__file__).with_name("claude_usage.ico")
img.resize((256, 256), Image.LANCZOS).save(
    out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(out)
