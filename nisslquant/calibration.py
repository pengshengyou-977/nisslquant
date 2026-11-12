# -*- coding: utf-8 -*-
"""光密度变换、双参考两点标定与稳健零分布估计。

核心记号
--------
OD     光密度，OD = -lg((I - b) / (I0 - b))，I0 为浅参考的稳健代表强度
u      标准化染色密度，u = (OD - OD_L) / (OD_D - OD_L)
       由构造，u=0 对应浅参考，u=1 对应深参考
u_f    局灶分量，u_f = u - G_sigma * u
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np

from .config import Params


# ----------------------------------------------------------------------------
# 数学工具
# ----------------------------------------------------------------------------

def normal_ppf(p: float) -> float:
    """标准正态分位数，Acklam 有理逼近，最大相对误差 < 1.2e-9。"""
    if not 0.0 < p < 1.0:
        raise ValueError("p 必须在 (0,1) 内")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = np.sqrt(-2 * np.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = np.sqrt(-2 * np.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def robust_sigma(x: np.ndarray) -> Tuple[float, float]:
    """中位数与 MAD 稳健标准差，抗离群点。"""
    x = np.asarray(x, dtype=np.float64).ravel()
    if x.size == 0:
        return float("nan"), float("nan")
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med)))
    return med, 1.4826 * mad + 1e-6


def bimodality_coefficient(x: np.ndarray, max_n: int = 200000) -> float:
    """Sarle 双峰系数 BC=(g^2+1)/k，均匀分布约 0.555，双峰分布趋近 1。"""
    x = np.asarray(x, dtype=np.float64).ravel()
    if x.size > max_n:
        x = x[:: max(1, x.size // max_n)]
    n = x.size
    if n < 50:
        return float("nan")
    m = x.mean(); s = x.std()
    if s < 1e-9:
        return float("nan")
    g = np.mean(((x - m) / s) ** 3)
    k = np.mean(((x - m) / s) ** 4) - 3.0
    denom = k + 3.0 * (n - 1) ** 2 / ((n - 2) * (n - 3))
    if abs(denom) < 1e-9:
        return float("nan")
    return float((g ** 2 + 1.0) / denom)


# ----------------------------------------------------------------------------
# 光密度与标定
# ----------------------------------------------------------------------------

def optical_density(intensity: np.ndarray, i0: float, black: float = 0.0) -> np.ndarray:
    """由透射强度计算光密度，结果对 I0 归一化到浅参考处为 0。"""
    i = np.asarray(intensity, dtype=np.float32)
    denom = max(i0 - black, 1e-3)
    ratio = np.clip((i - black) / denom, 1e-3, None)
    return -np.log10(ratio)


@dataclass
class Calibration:
    light_value: float          # 浅参考中位强度
    dark_value: float           # 深参考中位强度
    od_light: float             # 浅参考光密度（≈0）
    od_dark: float              # 深参考光密度
    light_spread: float         # 浅参考内部离散度（强度）
    dark_spread: float          # 深参考内部离散度（强度）
    n_light: int
    n_dark: int

    @property
    def span(self) -> float:
        """标定跨度（OD 差），用于 QC 与批间归一化。"""
        return self.od_dark - self.od_light

    @property
    def light_od_noise(self) -> float:
        """浅参考区的光密度噪声（由强度离散度换算）。"""
        return self.light_spread / max(self.light_value * 2.302585, 1e-6)

    @property
    def contrast(self) -> float:
        """标定对比度 = 标定跨度 / 浅参考光密度噪声，即双参考的信噪比。"""
        return self.span / max(self.light_od_noise, 1e-6)


def patch_values(channel: np.ndarray, points, radius: int) -> np.ndarray:
    """取若干圆形/方形参考块的像素值（方窗近似，半径以像素计）。"""
    h, w = channel.shape
    vals = []
    for x, y in points:
        xi, yi = int(round(x)), int(round(y))
        y0, y1 = max(0, yi - radius), min(h, yi + radius + 1)
        x0, x1 = max(0, xi - radius), min(w, xi + radius + 1)
        if y1 > y0 and x1 > x0:
            vals.append(channel[y0:y1, x0:x1].ravel())
    if not vals:
        return np.array([], dtype=np.float32)
    return np.concatenate(vals).astype(np.float32)


def estimate_calibration(channel: np.ndarray, light_pts, dark_pts,
                         params: Params) -> Calibration:
    lv = patch_values(channel, light_pts, params.ref_patch_radius)
    dv = patch_values(channel, dark_pts, params.ref_patch_radius)
    if lv.size == 0 or dv.size == 0:
        raise ValueError("参考区为空：请至少各点选一处浅染与深染参考区")
    L = float(np.median(lv))
    D = float(np.median(dv))
    if not D < L:
        raise ValueError("深参考应比浅参考更暗：请检查点选位置或通道设置")
    od_l = float(optical_density(np.array([L]), L)[0])
    od_d = float(optical_density(np.array([D]), L)[0])
    _, ls = robust_sigma(lv)
    _, ds = robust_sigma(dv)
    return Calibration(light_value=L, dark_value=D, od_light=od_l, od_dark=od_d,
                       light_spread=ls, dark_spread=ds, n_light=len(light_pts), n_dark=len(dark_pts))


def standardized_field(channel: np.ndarray, cal: Calibration, params: Params) -> np.ndarray:
    """计算标准化染色密度场 u。"""
    od = optical_density(channel, cal.light_value, params.black_level)
    span = cal.od_dark - cal.od_light
    if abs(span) < 1e-6:
        raise ValueError("标定跨度近似为零：浅参考与深参考过近")
    return (od - cal.od_light) / span


def low_frequency(u: np.ndarray, roi: np.ndarray, sigma: float) -> np.ndarray:
    """在 ROI 内估计低频分量。

    ROI 外用最近邻中位值填充，避免边界处被背景拉低。
    """
    vals = u[roi.astype(bool)]
    fill = float(np.median(vals)) if vals.size else 0.0
    filled = np.where(roi.astype(bool), u, fill).astype(np.float32)
    if sigma <= 0:
        return filled
    return cv2.GaussianBlur(filled, (0, 0), sigma)


def focal_component(u: np.ndarray, roi: np.ndarray, sigma: float) -> Tuple[np.ndarray, np.ndarray]:
    us = low_frequency(u, roi, sigma)
    return u - us, us


# ----------------------------------------------------------------------------
# 零分布与阈值
# ----------------------------------------------------------------------------

@dataclass
class NullModel:
    mu: float
    sigma: float
    threshold: float
    alpha: float
    z: float
    n_ref: int
    n_refined: int


def estimate_null(values: np.ndarray, roi: np.ndarray, ref_mask: np.ndarray,
                  alpha: float, refine: bool = True,
                  inflation_cap: float = 1.5) -> NullModel:
    """由浅参考区估计零分布，并按单侧错误率 α 给出检出限。

    精化步骤只纳入零分布浅色侧的像素，且标准差放大不超过 inflation_cap 倍，
    防止深染区渗入导致零分布发散。
    """
    ref_vals = values[ref_mask.astype(bool) & roi.astype(bool)]
    if ref_vals.size < 30:
        raise ValueError("浅参考区像素过少，请扩大参考区或增加采样点")
    mu, sd = robust_sigma(ref_vals)
    n_ref = int(ref_vals.size)
    n_refined = 0
    if refine:
        arr = values[roi.astype(bool)]
        near = arr[(arr < mu + 1.5 * sd) & (arr > mu - 2.5 * sd)]
        if near.size > 2000:
            mu2, sd2 = robust_sigma(near)
            sd = min(sd2, inflation_cap * sd)
            mu = mu2
            n_refined = int(near.size)
    z = normal_ppf(1.0 - alpha)
    return NullModel(mu=mu, sigma=sd, threshold=mu + z * sd, alpha=alpha, z=z,
                     n_ref=n_ref, n_refined=n_refined)


def reference_mask(shape: Tuple[int, int], points, radius: int) -> np.ndarray:
    m = np.zeros(shape, dtype=np.uint8)
    for x, y in points:
        cv2.circle(m, (int(round(x)), int(round(y))), int(radius), 1, -1)
    return m.astype(bool)
