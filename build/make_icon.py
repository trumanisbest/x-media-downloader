"""生成应用图标 app.ico（macOS 风格：蓝色圆角方块 + 白色下载箭头）"""
import os
from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")
SIZE = 512
R = 112          # 圆角半径
BG_TOP = (10, 132, 255)
BG_BOT = (0, 99, 214)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def rounded(size):
    scale = size / SIZE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(R * scale)
    # 垂直渐变底
    for y in range(size):
        d.line([(0, y), (size, y)], fill=lerp(BG_TOP, BG_BOT, y / max(1, size - 1)))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    img.putalpha(mask)
    return img


def arrow(size):
    """白色下载箭头：向下的粗箭头 + 底部横线"""
    s = size / SIZE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = size / 2
    w = int(70 * s)          # 箭杆宽度
    top = int(150 * s)
    bot = int(352 * s)       # 箭头尖
    head = int(118 * s)      # 箭头头部半宽
    head_top = int(258 * s)

    # 箭杆
    d.rounded_rectangle([cx - w / 2, top, cx + w / 2, head_top + 2],
                        radius=int(6 * s), fill=(255, 255, 255, 255))
    # 箭头三角
    d.polygon([(cx - head, head_top), (cx + head, head_top), (cx, bot)],
              fill=(255, 255, 255, 255))
    # 底部托盘横线
    bar_h = int(34 * s)
    bar_w = int(250 * s)
    bar_y = int(392 * s)
    d.rounded_rectangle([cx - bar_w / 2, bar_y, cx + bar_w / 2, bar_y + bar_h],
                        radius=int(bar_h / 2), fill=(255, 255, 255, 255))
    return img


def main():
    sizes = [256, 128, 64, 48, 32, 16]
    frames = []
    for sz in sizes:
        base = rounded(sz)
        base.alpha_composite(arrow(sz))
        frames.append(base)
    frames[0].save(OUT, format="ICO", sizes=[(f.width, f.height) for f in frames])
    print("icon saved:", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
