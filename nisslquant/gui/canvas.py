# -*- coding: utf-8 -*-
"""可缩放、可平移的图像画布，支持多边形勾画与参考点标注。"""
from __future__ import annotations

import math
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np
import tkinter as tk
from PIL import Image, ImageTk

from ..config import COLOR_ROI, COLOR_LIGHT, COLOR_DARK, COLOR_MASK, COLOR_FOCAL


class ImageView(tk.Frame):
    """图像视图。

    坐标约定：所有对外接口使用原图像素坐标；内部维护画布坐标。
    """

    def __init__(self, master, on_change: Optional[Callable] = None, **kw):
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, bg="#2B2B2B", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)

        self.rgb: Optional[np.ndarray] = None
        self.mask_dark: Optional[np.ndarray] = None
        self.mask_focal: Optional[np.ndarray] = None
        self.mask_roi: Optional[np.ndarray] = None
        self._photo = None

        self.scale = 1.0          # 画布像素 / 图像像素
        self.cx = 0.0             # 视口中心（图像坐标）
        self.cy = 0.0
        self.min_scale = 0.02
        self.max_scale = 12.0

        self.polygon: List[Tuple[float, float]] = []
        self.light_pts: List[Tuple[float, float]] = []
        self.dark_pts: List[Tuple[float, float]] = []
        self.preview_point: Optional[Tuple[float, float]] = None
        self.mode = "roi"
        self.closed = False

        self.on_change = on_change
        self._drag = None
        self._auto_fit = True
        self._fit_job = None

        self.canvas.bind("<ButtonPress-1>", self._left_down)
        self.canvas.bind("<B1-Motion>", self._left_drag)
        self.canvas.bind("<ButtonRelease-1>", self._left_up)
        self.canvas.bind("<ButtonPress-3>", self._right_click)
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Configure>", self._on_configure)

    # ------------------------------------------------------------------
    # 图像与视口
    # ------------------------------------------------------------------
    def _on_configure(self, ev) -> None:
        if self._auto_fit:
            if self._fit_job:
                try:
                    self.after_cancel(self._fit_job)
                except Exception:
                    pass
            self._fit_job = self.after(80, self.fit)
        else:
            self.redraw()

    def set_image(self, rgb: np.ndarray) -> None:
        self._auto_fit = True
        self.rgb = rgb
        self.polygon = []
        self.light_pts = []
        self.dark_pts = []
        self.mask_dark = None
        self.mask_focal = None
        self.mask_roi = None
        self.closed = False
        self.fit()

    def set_overlays(self, dark=None, focal=None, roi=None) -> None:
        self.mask_dark = dark
        self.mask_focal = focal
        self.mask_roi = roi
        self.redraw()

    def fit(self) -> None:
        self._auto_fit = True
        if self.rgb is None:
            return
        h, w = self.rgb.shape[:2]
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        if cw < 10:
            cw, ch = 900, 650
        self.scale = min(cw / w, ch / h) * 0.98
        self.min_scale = self.scale * 0.2
        self.cx, self.cy = w / 2, h / 2
        self.redraw()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.canvas.config(cursor="crosshair" if mode != "pan" else "fleur")

    def zoom_at(self, factor: float, sx: float, sy: float) -> None:
        if self.rgb is None:
            return
        ix, iy = self.to_image(sx, sy)
        self._auto_fit = False
        new = min(self.max_scale, max(self.min_scale, self.scale * factor))
        f = new / self.scale
        self.scale = new
        # 保持鼠标下的图像点不动
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        self.cx = ix - (sx - cw / 2) / self.scale
        self.cy = iy - (sy - ch / 2) / self.scale
        self.redraw()

    def to_image(self, sx: float, sy: float) -> Tuple[float, float]:
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        return (self.cx + (sx - cw / 2) / self.scale,
                self.cy + (sy - ch / 2) / self.scale)

    def to_canvas(self, ix: float, iy: float) -> Tuple[float, float]:
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        return (cw / 2 + (ix - self.cx) * self.scale,
                ch / 2 + (iy - self.cy) * self.scale)

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def redraw(self) -> None:
        self.canvas.delete("all")
        if self.rgb is None:
            self.canvas.create_text(self.canvas.winfo_width() // 2,
                                    self.canvas.winfo_height() // 2,
                                    text="请打开尼氏染色图像", fill="#888", font=("Microsoft YaHei", 16))
            return
        img = self._compose_crop()
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.create_image(self.canvas.winfo_width() // 2,
                                 self.canvas.winfo_height() // 2,
                                 image=self._photo, anchor="center")
        self._draw_vectors()

    def _compose_crop(self) -> Image.Image:
        h, w = self.rgb.shape[:2]
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        half_w = cw / (2 * self.scale)
        half_h = ch / (2 * self.scale)
        x0 = int(max(0, math.floor(self.cx - half_w)))
        x1 = int(min(w, math.ceil(self.cx + half_w)))
        y0 = int(max(0, math.floor(self.cy - half_h)))
        y1 = int(min(h, math.ceil(self.cy + half_h)))
        if x1 <= x0 or y1 <= y0:
            return Image.new("RGB", (cw, ch))
        crop = self.rgb[y0:y1, x0:x1]
        img = Image.fromarray(crop).convert("RGBA")

        def blend(mask, color, alpha):
            if mask is None:
                return img
            m = mask[y0:y1, x0:x1]
            arr = np.zeros((m.shape[0], m.shape[1], 4), dtype=np.uint8)
            arr[m.astype(bool)] = (*color, alpha)
            return Image.alpha_composite(img, Image.fromarray(arr, "RGBA"))

        img = blend(self.mask_roi, COLOR_ROI, 40)
        img = blend(self.mask_dark, COLOR_MASK, 110)
        img = blend(self.mask_focal, COLOR_FOCAL, 90)
        out_w = max(1, int(round((x1 - x0) * self.scale)))
        out_h = max(1, int(round((y1 - y0) * self.scale)))
        img = img.convert("RGB").resize((out_w, out_h), Image.BILINEAR)
        canvas_img = Image.new("RGB", (cw, ch), (43, 43, 43))
        px, py = self.to_canvas(x0, y0)
        canvas_img.paste(img, (int(px), int(py)))
        return canvas_img

    def _draw_vectors(self) -> None:
        if self.polygon:
            pts = [self.to_canvas(x, y) for x, y in self.polygon]
            if len(pts) > 1:
                self.canvas.create_line(*[c for p in pts for c in p],
                                        fill=self._hex(COLOR_ROI), width=2)
            if self.closed and len(pts) > 2:
                self.canvas.create_line(pts[-1][0], pts[-1][1], pts[0][0], pts[0][1],
                                        fill=self._hex(COLOR_ROI), width=2)
            for p in pts:
                self.canvas.create_oval(p[0] - 3, p[1] - 3, p[0] + 3, p[1] + 3,
                                        fill="#FFFFFF", outline=self._hex(COLOR_ROI))
            if self.preview_point and not self.closed:
                p = self.to_canvas(*self.preview_point)
                self.canvas.create_line(pts[-1][0], pts[-1][1], p[0], p[1],
                                        fill="#7F9DB9", dash=(4, 3))
        r = max(6, 7 * 1.6 * self.scale)
        for pts, color in ((self.light_pts, COLOR_LIGHT), (self.dark_pts, COLOR_DARK)):
            for x, y in pts:
                cx, cy = self.to_canvas(x, y)
                self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                        outline=self._hex(color), width=2)

    @staticmethod
    def _hex(c) -> str:
        return "#%02X%02X%02X" % tuple(int(v) for v in c)

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _left_down(self, ev) -> None:
        if self.rgb is None:
            return
        if self.mode == "pan":
            self._drag = ("pan", ev.x, ev.y, self.cx, self.cy)
            return
        ix, iy = self.to_image(ev.x, ev.y)
        h, w = self.rgb.shape[:2]
        if not (0 <= ix < w and 0 <= iy < h):
            return
        if self.mode == "roi":
            if self.closed:
                return
            if len(self.polygon) >= 3:
                # 点回起点附近则闭合
                sx, sy = self.to_canvas(*self.polygon[0])
                if math.hypot(ev.x - sx, ev.y - sy) < 10:
                    self.close_polygon()
                    return
            self.polygon.append((ix, iy))
        elif self.mode == "light":
            self.light_pts.append((ix, iy))
        elif self.mode == "dark":
            self.dark_pts.append((ix, iy))
        self._changed()

    def _left_drag(self, ev) -> None:
        if self._drag and self._drag[0] == "pan":
            _, ex, ey, cx0, cy0 = self._drag
            self.cx = cx0 - (ev.x - ex) / self.scale
            self.cy = cy0 - (ev.y - ey) / self.scale
            self.redraw()

    def _left_up(self, ev) -> None:
        self._drag = None

    def _right_click(self, ev) -> None:
        if self.rgb is None:
            return
        if self.mode == "roi" and self.polygon and not self.closed:
            self.polygon.pop()
            self._changed()
        elif self.mode == "light" and self.light_pts:
            self.light_pts.pop()
            self._changed()
        elif self.mode == "dark" and self.dark_pts:
            self.dark_pts.pop()
            self._changed()

    def _motion(self, ev) -> None:
        if self.mode == "roi" and self.polygon and not self.closed:
            self.preview_point = self.to_image(ev.x, ev.y)
            self.redraw()

    def _wheel(self, ev) -> None:
        factor = 1.15 if ev.delta > 0 else 1 / 1.15
        self.zoom_at(factor, ev.x, ev.y)

    def close_polygon(self) -> None:
        if len(self.polygon) >= 3:
            self.closed = True
            self._changed()

    def undo_all(self) -> None:
        self.polygon = []
        self.light_pts = []
        self.dark_pts = []
        self.closed = False
        self._changed()

    def _changed(self) -> None:
        self.redraw()
        if self.on_change:
            self.on_change()
