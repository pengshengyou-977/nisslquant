# -*- coding: utf-8 -*-
"""生成一张合成的"尼氏染色样"演示图像与标注点。

合成图像不含任何真实动物数据，可随代码一起公开。
"""
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def make(out_dir: str = ".") -> tuple:
    rng = np.random.default_rng(20261112)
    W, H = 1200, 800
    # 浅蓝色背景（模拟神经毡）
    img = np.zeros((H, W, 3), dtype=np.float32)
    img[:, :] = (205, 218, 238)

    # 弯曲的颗粒层带
    yy, xx = np.mgrid[0:H, 0:W]
    def band_y(x):
        return 430 + 90 * np.sin(x / 260.0) - 0.10 * x
    top = band_y(xx) - 70
    bot = band_y(xx) + 70
    band = (yy > top) & (yy < bot)
    img[band] = (186, 199, 226)

    # 颗粒细胞：密集小椭圆
    for _ in range(2600):
        x = rng.uniform(60, W - 60)
        y0 = band_y(np.array([x]))[0]
        y = y0 + rng.normal(0, 42)
        if not (0 < y < H):
            continue
        rx, ry = rng.uniform(3.5, 6.5), rng.uniform(5, 8)
        x0, x1 = int(x - rx), int(x + rx)
        y0i, y1i = int(y - ry), int(y + ry)
        sub = (xx[y0i:y1i, x0:x1] - x) ** 2 / rx ** 2 + (yy[y0i:y1i, x0:x1] - y) ** 2 / ry ** 2
        m = sub <= 1
        lum = rng.normal(0, 10)
        img[y0i:y1i, x0:x1][m] = np.clip(
            np.array([150, 162, 202]) + lum, 0, 255)

    # 深染斑块（焦油紫深色）
    for _ in range(55):
        x = rng.uniform(80, W - 80)
        y0 = band_y(np.array([x]))[0]
        y = y0 + rng.normal(0, 45)
        r = rng.uniform(6, 14)
        m = ((xx - x) ** 2 + (yy - y) ** 2) <= r ** 2
        lum = rng.normal(0, 7)
        img[m] = np.clip(np.array([52, 38, 92]) + lum, 0, 255)

    # 轻微模糊与噪声，模拟显微成像
    im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(1.1))
    arr = np.asarray(im).astype(np.float32) + rng.normal(0, 3.0, (H, W, 3))
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    # 比例尺（100 µm = 201 px，与正文一致）
    dr = ImageDraw.Draw(im)
    x0, y0 = W - 260, H - 40
    dr.rectangle([x0, y0, x0 + 201, y0 + 6], fill=(20, 20, 20))
    dr.text((x0, y0 - 18), "100 µm", fill=(20, 20, 20))

    img_path = os.path.join(out_dir, "demo_nissl.png")
    im.save(img_path)

    # 标注：ROI 多边形与两类参考点
    xs = np.arange(70, W - 70, 60)
    poly = []
    for x in xs:
        poly.append([float(x), float(band_y(np.array([x]))[0] - 78)])
    for x in xs[::-1]:
        poly.append([float(x), float(band_y(np.array([x]))[0] + 78)])

    # 从图像本身挑选最亮与最暗的参考窗口，保证标定有效
    arr_r = np.asarray(im)[:, :, 0].astype(np.float32)
    cand = []
    for x in range(120, W - 120, 30):
        for dy in (-55, -35, -15, 0, 15, 35, 55):
            y = int(band_y(np.array([x]))[0] + dy)
            if 20 <= y < H - 20:
                patch = arr_r[y - 7:y + 8, x - 7:x + 8]
                cand.append((float(np.median(patch)), float(x), float(y)))
    cand.sort(key=lambda t: t[0])
    vals = np.array([c[0] for c in cand])
    light_target = float(np.percentile(vals, 40))
    dark_target = float(np.percentile(vals, 2))

    def pick(target, n=3, sep=120.0):
        order = sorted(cand, key=lambda t: abs(t[0] - target))
        out = []
        for v, x, y in order:
            if all((x - px) ** 2 + (y - py) ** 2 > sep ** 2 for _, px, py in out):
                out.append((v, x, y))
            if len(out) == n:
                break
        return out

    dark_pts = pick(dark_target)
    light_pts = pick(light_target)
    light_pts = [[x, y] for _, x, y in light_pts]
    dark_pts = [[x, y] for _, x, y in dark_pts]
    meta = {"um_per_px": 0.4975, "polygon": poly,
            "light_pts": light_pts, "dark_pts": dark_pts}
    with open(os.path.join(out_dir, "demo_points.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    return img_path, meta


if __name__ == "__main__":
    p, m = make(os.path.dirname(os.path.abspath(__file__)))
    print("demo image:", p)
    print("ROI vertices:", len(m["polygon"]))
