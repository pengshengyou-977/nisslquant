# -*- coding: utf-8 -*-
"""图像读取、缩放与叠加图输出。

Windows 下路径可能含中文，统一用 PIL 读取，避免 OpenCV 的 imread 编码问题。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .config import IMAGE_EXTS, COLOR_ROI, COLOR_MASK, COLOR_LIGHT, COLOR_DARK, COLOR_FOCAL


@dataclass
class LoadedImage:
    path: str
    rgb: np.ndarray          # H×W×3 uint8
    width: int
    height: int

    @property
    def gray(self) -> np.ndarray:
        return self.rgb[:, :, 0]


def read_image(path: str) -> LoadedImage:
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with Image.open(path) as im:
        im = im.convert("RGB")
        arr = np.asarray(im, dtype=np.uint8)
    return LoadedImage(path=path, rgb=arr, width=arr.shape[1], height=arr.shape[0])


def list_images(folder: str) -> list:
    out = []
    for name in sorted(os.listdir(folder)):
        if name.lower().endswith(IMAGE_EXTS):
            out.append(os.path.join(folder, name))
    return out


def make_thumbnail(rgb: np.ndarray, max_side: int = 1400) -> Tuple[np.ndarray, float]:
    """返回缩放后的图像与缩放倍率（原图/缩略图）。"""
    h, w = rgb.shape[:2]
    scale = max(1.0, max(h, w) / float(max_side))
    if scale <= 1.0:
        return rgb, 1.0
    new_w = max(1, int(round(w / scale)))
    new_h = max(1, int(round(h / scale)))
    im = Image.fromarray(rgb).resize((new_w, new_h), Image.LANCZOS)
    return np.asarray(im, dtype=np.uint8), scale


def _font(size: int = 20):
    for name in ("msyh.ttc", "simhei.ttf", "simsun.ttc", "arial.ttf"):
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def save_overlay(path: str,
                 rgb: np.ndarray,
                 roi_mask: Optional[np.ndarray] = None,
                 dark_mask: Optional[np.ndarray] = None,
                 focal_mask: Optional[np.ndarray] = None,
                 light_pts: Optional[list] = None,
                 dark_pts: Optional[list] = None,
                 roi_poly: Optional[list] = None,
                 caption: str = "",
                 patch_radius: int = 7) -> None:
    """把 ROI、深染区、局灶区与参考点叠加到原图上保存。

    叠加顺序：ROI 蓝色半透明 → 深染红色半透明 → 局灶橙色描边 → 参考圈 → 轮廓 → 标题条。
    """
    base = Image.fromarray(rgb).convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    px = layer.load()

    if roi_mask is not None:
        arr = np.zeros((rgb.shape[0], rgb.shape[1], 4), dtype=np.uint8)
        arr[roi_mask.astype(bool)] = (*COLOR_ROI, 40)
        layer = Image.alpha_composite(layer, Image.fromarray(arr, "RGBA"))
    if dark_mask is not None:
        arr = np.zeros((rgb.shape[0], rgb.shape[1], 4), dtype=np.uint8)
        arr[dark_mask.astype(bool)] = (*COLOR_MASK, 120)
        layer = Image.alpha_composite(layer, Image.fromarray(arr, "RGBA"))
    if focal_mask is not None:
        arr = np.zeros((rgb.shape[0], rgb.shape[1], 4), dtype=np.uint8)
        arr[focal_mask.astype(bool)] = (*COLOR_FOCAL, 110)
        layer = Image.alpha_composite(layer, Image.fromarray(arr, "RGBA"))

    out = Image.alpha_composite(base, layer).convert("RGB")
    dr = ImageDraw.Draw(out)

    if roi_poly and len(roi_poly) > 2:
        pts = [(float(x), float(y)) for x, y in roi_poly]
        dr.line(pts + [pts[0]], fill=COLOR_ROI, width=5)
    for pts, color in ((light_pts or [], COLOR_LIGHT), (dark_pts or [], COLOR_DARK)):
        r = patch_radius * 1.6
        for x, y in pts:
            dr.ellipse([x - r, y - r, x + r, y + r], outline=color, width=4)

    if caption:
        f = _font(30)
        box = dr.textbbox((0, 0), caption, font=f)
        w = min(out.size[0], box[2] - box[0] + 24)
        dr.rectangle([0, 0, w, 46], fill=(255, 255, 255))
        dr.text((10, 6), caption, fill=(20, 20, 20), font=f)

    out.save(path, quality=92)


def save_mask_png(path: str, mask: np.ndarray) -> None:
    Image.fromarray((mask.astype(bool) * 255).astype(np.uint8), "L").save(path)


def format_caption(code: str, daf: float, abs_mm2: float, thr: float,
                   quality: str = "") -> str:
    s = f"{code}   深染面积比 {daf:.2f}%   绝对面积 {abs_mm2:.4f} mm²   阈值 u>{thr:.3f}"
    if quality:
        s += f"   [{quality}]"
    return s
