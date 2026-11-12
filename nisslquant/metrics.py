# -*- coding: utf-8 -*-
"""定量指标计算与不确定度估计。

口径约定
--------
daf_pct        伪影剔除后的深染面积比，作为主报告指标
daf_raw_pct    剔除前的阈值面积比，用于说明伪影占比
artifact_pct   被剔除的候选深染面积占候选总面积的比例
置信区间       对深染连通域做有放回重采样（对象级 bootstrap），
               反映"深染斑块分布不均"带来的不确定度，
               而非仅由像素计数造成的二项误差。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

import numpy as np

from .config import Params


@dataclass
class Metrics:
    # 面积
    roi_px: int = 0
    roi_um2: float = 0.0
    roi_mm2: float = 0.0
    dark_px: int = 0
    dark_um2: float = 0.0
    dark_mm2: float = 0.0
    daf_pct: float = 0.0
    daf_raw_pct: float = 0.0
    artifact_pct: float = 0.0

    # 局灶分量
    focal_px: int = 0
    focal_um2: float = 0.0
    focal_pct: float = 0.0

    # 连续指标
    mean_u: float = 0.0
    median_u: float = 0.0
    diffuse_u: float = 0.0
    excess_load: float = 0.0

    # 对象
    n_objects: int = 0
    n_rejected: int = 0
    obj_mean_um2: float = 0.0
    obj_median_um2: float = 0.0

    # 不确定度
    ci_low: float = 0.0
    ci_high: float = 0.0
    ci_width: float = 0.0

    # 灵敏度
    daf_alpha_low: float = 0.0
    daf_alpha_mid: float = 0.0
    daf_alpha_high: float = 0.0

    def to_row(self) -> Dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def area_metrics(roi: np.ndarray, dark: np.ndarray, dark_raw: np.ndarray,
                 focal: np.ndarray, params: Params) -> Dict[str, float]:
    px_um2 = params.um_per_px ** 2
    roi_px = int(roi.sum())
    dark_px = int(dark.sum())
    raw_px = int(dark_raw.sum())
    focal_px = int(focal.sum())
    return dict(
        roi_px=roi_px,
        roi_um2=roi_px * px_um2,
        roi_mm2=roi_px * px_um2 / 1e6,
        dark_px=dark_px,
        dark_um2=dark_px * px_um2,
        dark_mm2=dark_px * px_um2 / 1e6,
        daf_pct=dark_px / roi_px * 100 if roi_px else 0.0,
        daf_raw_pct=raw_px / roi_px * 100 if roi_px else 0.0,
        artifact_pct=(raw_px - dark_px) / raw_px * 100 if raw_px else 0.0,
        focal_px=focal_px,
        focal_um2=focal_px * px_um2,
        focal_pct=focal_px / roi_px * 100 if roi_px else 0.0,
    )


def continuous_metrics(u: np.ndarray, roi: np.ndarray, us: np.ndarray,
                       threshold: float) -> Dict[str, float]:
    vals = u[roi.astype(bool)]
    if vals.size == 0:
        return dict(mean_u=0.0, median_u=0.0, diffuse_u=0.0, excess_load=0.0)
    diff = us[roi.astype(bool)]
    return dict(
        mean_u=float(vals.mean()),
        median_u=float(np.median(vals)),
        diffuse_u=float(np.median(diff)),
        excess_load=float(np.clip(vals - threshold, 0, None).mean()),
    )


def object_stats(feats: List, params: Params) -> Dict[str, float]:
    kept = [f for f in feats if not f.reject]
    areas = np.array([f.area_um2 for f in kept], dtype=np.float64)
    return dict(
        n_objects=len(kept),
        n_rejected=len(feats) - len(kept),
        obj_mean_um2=float(areas.mean()) if areas.size else 0.0,
        obj_median_um2=float(np.median(areas)) if areas.size else 0.0,
    )


def bootstrap_ci_objects(areas_um2: np.ndarray, roi_um2: float, params: Params,
                         seed: int = 20261112) -> Dict[str, float]:
    """对象级 bootstrap：对深染连通域面积作有放回重采样。

    当对象数少于 5 时退化为零宽区间，并在质控中提示对象过少。
    """
    a = np.asarray(areas_um2, dtype=np.float64)
    if a.size < 2 or roi_um2 <= 0:
        p = (a.sum() / roi_um2 * 100) if roi_um2 > 0 else 0.0
        return dict(ci_low=p, ci_high=p, ci_width=0.0)
    rng = np.random.default_rng(seed)
    n = a.size
    draws = np.empty(params.bootstrap_n, dtype=np.float64)
    for i in range(params.bootstrap_n):
        s = rng.choice(a, n, replace=True)
        draws[i] = s.sum() / roi_um2 * 100
    lo = float(np.percentile(draws, (1 - params.ci_level) / 2 * 100))
    hi = float(np.percentile(draws, (1 + params.ci_level) / 2 * 100))
    # 分母固定为 ROI 面积，重采样和可能超过 100%，按物理上限截断
    lo = max(0.0, min(lo, 100.0))
    hi = max(0.0, min(hi, 100.0))
    return dict(ci_low=lo, ci_high=hi, ci_width=hi - lo)


def bootstrap_ci_pixels(mask: np.ndarray, roi: np.ndarray, params: Params,
                        seed: int = 20261112) -> Dict[str, float]:
    """像素级 bootstrap，作为对象过少时的替代方案。"""
    vals = mask[roi.astype(bool)].astype(np.float64)
    if vals.size == 0:
        return dict(ci_low=0.0, ci_high=0.0, ci_width=0.0)
    rng = np.random.default_rng(seed)
    if vals.size > params.bootstrap_pixels:
        vals = rng.choice(vals, params.bootstrap_pixels, replace=False)
    n = vals.size
    draws = np.empty(params.bootstrap_n, dtype=np.float64)
    for i in range(params.bootstrap_n):
        s = rng.choice(vals, n, replace=True)
        draws[i] = s.mean() * 100
    lo = float(np.percentile(draws, (1 - params.ci_level) / 2 * 100))
    hi = float(np.percentile(draws, (1 + params.ci_level) / 2 * 100))
    return dict(ci_low=lo, ci_high=hi, ci_width=hi - lo)
