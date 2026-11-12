# -*- coding: utf-8 -*-
"""ROI 生成、阈值分割、连通域特征与伪影剔除。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .config import Params


# ----------------------------------------------------------------------------
# ROI
# ----------------------------------------------------------------------------

def polygon_mask(shape: Tuple[int, int], points: Sequence[Tuple[float, float]]) -> np.ndarray:
    """由多边形顶点生成 ROI 掩膜（含边界）。"""
    m = np.zeros(shape, dtype=np.uint8)
    if len(points) < 3:
        return m.astype(bool)
    pts = np.asarray([[int(round(x)), int(round(y))] for x, y in points], dtype=np.int32)
    cv2.fillPoly(m, [pts], 1)
    return m.astype(bool)


def polygon_area_px(points: Sequence[Tuple[float, float]]) -> float:
    """鞋带公式计算多边形面积（像素）。"""
    if len(points) < 3:
        return 0.0
    x = np.array([p[0] for p in points], dtype=np.float64)
    y = np.array([p[1] for p in points], dtype=np.float64)
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0)


def snap_polygon(points: Sequence[Tuple[float, float]], edge_map: np.ndarray,
                 max_shift: float = 6.0) -> List[Tuple[float, float]]:
    """把顶点吸附到最近的强边缘（可选功能，失败时原样返回）。"""
    if edge_map is None or not points:
        return list(points)
    h, w = edge_map.shape
    out = []
    r = int(max(1, max_shift))
    for x, y in points:
        xi, yi = int(round(x)), int(round(y))
        x0, x1 = max(0, xi - r), min(w, xi + r + 1)
        y0, y1 = max(0, yi - r), min(h, yi + r + 1)
        if x1 <= x0 or y1 <= y0:
            out.append((x, y)); continue
        win = edge_map[y0:y1, x0:x1]
        idx = np.unravel_index(int(np.argmax(win)), win.shape)
        if win[idx] > 0:
            out.append((float(x0 + idx[1]), float(y0 + idx[0])))
        else:
            out.append((x, y))
    return out


# ----------------------------------------------------------------------------
# 连通域
# ----------------------------------------------------------------------------

@dataclass
class ObjectFeature:
    label: int
    area_px: int
    area_um2: float
    bbox: Tuple[int, int, int, int]
    centroid: Tuple[float, float]
    mean_u: float
    max_u: float
    border_frac: float
    aspect: float
    solidity: float
    saturation_frac: float
    reject: str = ""

    def as_row(self) -> Dict:
        return {
            "label": self.label, "area_px": self.area_px, "area_um2": round(self.area_um2, 2),
            "x": int(self.centroid[0]), "y": int(self.centroid[1]),
            "mean_u": round(self.mean_u, 4), "max_u": round(self.max_u, 4),
            "border_frac": round(self.border_frac, 3), "aspect": round(self.aspect, 2),
            "solidity": round(self.solidity, 3), "reject": self.reject,
        }


def _solidity(component: np.ndarray) -> float:
    cnts, _ = cv2.findContours(component.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return 0.0
    c = max(cnts, key=cv2.contourArea)
    a = cv2.contourArea(c)
    if a <= 0:
        return 0.0
    hull = cv2.convexHull(c)
    ha = cv2.contourArea(hull)
    return float(min(1.0, a / ha)) if ha > 0 else 0.0


def analyze_objects(binary: np.ndarray, u: np.ndarray, roi: np.ndarray,
                    channel: np.ndarray, params: Params,
                    apply_filter: bool = True) -> Tuple[np.ndarray, List[ObjectFeature]]:
    """标记连通域、计算形态学特征并按规则剔除伪影。

    返回（保留的深染掩膜，全部连通域特征列表）。
    """
    n, labels, stats, cents = cv2.connectedComponentsWithStats(binary.astype(np.uint8), connectivity=8)
    px_um2 = params.um_per_px ** 2
    border = roi & ~cv2.erode(roi.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
    sat = channel <= params.saturation_level

    feats: List[ObjectFeature] = []
    keep = np.zeros(n, dtype=bool)
    for i in range(1, n):
        x, y, w, h, area = [int(v) for v in stats[i]]
        if area <= 0:
            continue
        comp = labels[y:y + h, x:x + w] == i
        area_um2 = area * px_um2
        border_frac = float((border[y:y + h, x:x + w] & comp).sum() / area)
        aspect = float(max(w, h) / max(1, min(w, h)))
        sol = _solidity(comp)
        sat_frac = float((sat[y:y + h, x:x + w] & comp).sum() / area)
        vals = u[y:y + h, x:x + w][comp]
        f = ObjectFeature(label=i, area_px=area, area_um2=area_um2, bbox=(x, y, w, h),
                          centroid=(float(cents[i][0]), float(cents[i][1])),
                          mean_u=float(vals.mean()) if vals.size else 0.0,
                          max_u=float(vals.max()) if vals.size else 0.0,
                          border_frac=border_frac, aspect=aspect, solidity=sol,
                          saturation_frac=sat_frac)
        if apply_filter:
            if area_um2 < params.min_area_um2:
                f.reject = "面积过小"
            elif border_frac > params.border_frac_max and area_um2 > params.border_area_um2:
                f.reject = "贴边（折叠/切片边缘）"
            elif sat_frac > 0.5:
                f.reject = "过饱和（染料沉淀/曝光）"
            elif aspect > 8.0 and sol < 0.5:
                f.reject = "狭长（刀痕/裂隙）"
        if not f.reject:
            keep[i] = True
        feats.append(f)

    out = keep[labels]
    return out.astype(bool), feats


# ----------------------------------------------------------------------------
# 前后景与质量
# ----------------------------------------------------------------------------

def saturation_fraction(channel: np.ndarray, roi: np.ndarray, level: float) -> float:
    m = roi.astype(bool)
    if m.sum() == 0:
        return 0.0
    return float((channel[m] <= level).mean())


def edge_map(channel: np.ndarray, sigma: float = 2.0) -> np.ndarray:
    blur = cv2.GaussianBlur(channel.astype(np.float32), (0, 0), sigma)
    gx = cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    if mag.max() > 0:
        mag = mag / mag.max()
    return mag
