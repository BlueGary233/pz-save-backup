#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 app_icon.ico（无需外部素材，纯代码绘制）
运行：python create_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "app_icon.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]
BG_TOP = (255, 137, 153)      # 主色 #FF8999
BG_BOTTOM = (201, 69, 90)     # 深一点的同色系
DISK = (255, 255, 255)


def _rounded(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = max(2, int(size * 0.22))
    # 竖向渐变背景
    grad = Image.new("RGBA", (size, size))
    gd = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / max(1, size - 1)
        gd.line(
            [(0, y), (size, y)],
            fill=tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)) + (255,),
        )
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    img.paste(grad, (0, 0), mask)

    # 白色“存档磁盘”：圆角方块 + 顶部标签槽 + 底部小孔
    m = int(size * 0.20)
    box = [m, m, size - 1 - m, size - 1 - m]
    d.rounded_rectangle(box, radius=max(1, int(size * 0.06)), fill=DISK)
    w = box[2] - box[0]
    h = box[3] - box[1]
    # 标签槽（上）：用背景色挖出
    d.rectangle(
        [box[0] + int(w * 0.30), box[1], box[2] - int(w * 0.30), box[1] + int(h * 0.36)],
        fill=BG_BOTTOM,
    )
    # 内芯（下）
    d.rectangle(
        [box[0] + int(w * 0.16), box[1] + int(h * 0.56), box[2] - int(w * 0.16), box[3] - int(h * 0.10)],
        fill=BG_TOP,
    )
    return img


def main():
    frames = [_rounded(s) for s in SIZES]
    base = frames[-1]
    base.save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"✅ 已生成图标：{OUT}")


if __name__ == "__main__":
    main()
