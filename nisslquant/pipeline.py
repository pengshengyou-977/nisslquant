# -*- coding: utf-8 -*-
"""单张图像的完整分析流水线。

顺序：读图 → 通道 → 双参考标定 → 标准化密度场 → 多尺度分解
     → 零分布与检出限 → 分割 → 连通域伪影剔除 → 指标 → 不确定度 → 质控
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .calibration import (Calibration, NullModel, estimate_calibration,
                          estimate_null, focal_component, reference_mask,
                          standardized_field, bimodality_coefficient, normal_ppf)
from .config import Params
from .imageio import LoadedImage, read_image
from .metrics import (Metrics, area_metrics, bootstrap_ci_objects, bootstrap_ci_pixels,
                      continuous_metrics, object_stats)
from .quality import QCResult, evaluate
from .segmentation import analyze_objects, polygon_mask, saturation_fraction


@dataclass
class AnalysisResult:
    code: str
    path: str
    params: Params
    metrics: Metrics
    qc: QCResult
    calibration: Calibration
    null: NullModel
    null_focal: Optional[NullModel]
    polygon: List[Tuple[float, float]]
    light_pts: List[Tuple[float, float]]
    dark_pts: List[Tuple[float, float]]
    roi_mask: np.ndarray
    dark_mask: np.ndarray
    focal_mask: np.ndarray
    u: np.ndarray
    u_smooth: np.ndarray
    u_focal: np.ndarray
    objects: List = field(default_factory=list)
    elapsed_s: float = 0.0

    def as_row(self) -> Dict:
        row = {"code": self.code, "file": os.path.basename(self.path)}
        row.update(self.metrics.to_row())
        row.update({
            "light_R": round(self.calibration.light_value, 2),
            "dark_R": round(self.calibration.dark_value, 2),
            "od_span": round(self.calibration.span, 4),
            "ref_contrast": round(self.calibration.contrast, 3),
            "null_mu": round(self.null.mu, 4),
            "null_sd": round(self.null.sigma, 4),
            "threshold_u": round(self.null.threshold, 4),
            "alpha": self.params.alpha,
            "qc_grade": self.qc.grade,
            "qc_score": self.qc.score,
            "qc_flags": self.qc.summary(),
            "elapsed_s": round(self.elapsed_s, 2),
        })
        return row


def analyze(path: str,
            polygon: Sequence[Tuple[float, float]],
            light_pts: Sequence[Tuple[float, float]],
            dark_pts: Sequence[Tuple[float, float]],
            params: Params,
            code: Optional[str] = None,
            image: Optional[LoadedImage] = None) -> AnalysisResult:
    t0 = time.time()
    img = image if image is not None else read_image(path)
    ch = img.rgb[:, :, params.channel].astype(np.float32)

    roi = polygon_mask(ch.shape, polygon)
    if roi.sum() < 1000:
        raise ValueError("ROI 面积过小，请重新勾画")

    cal = estimate_calibration(ch, light_pts, dark_pts, params)
    u = standardized_field(ch, cal, params)

    if params.decompose:
        u_f, u_s = focal_component(u, roi, params.sigma_px)
    else:
        u_f = u.copy()
        u_s = np.zeros_like(u)

    refmask = reference_mask(ch.shape, light_pts, params.ref_patch_radius * 1.4)
    null = estimate_null(u, roi, refmask, params.alpha)

    dark_raw = roi & (u > null.threshold)
    dark, feats = analyze_objects(dark_raw, u, roi, ch, params, apply_filter=True)

    if params.decompose:
        null_f = estimate_null(u_f, roi, refmask, params.alpha)
        focal_raw = roi & (u_f > null_f.threshold)
        focal, _ = analyze_objects(focal_raw, u_f, roi, ch, params, apply_filter=True)
    else:
        null_f = None
        focal = np.zeros_like(roi)

    area = area_metrics(roi, dark, dark_raw, focal, params)
    cont = continuous_metrics(u, roi, u_s, null.threshold)
    objs = object_stats(feats, params)

    # 参数敏感性：每个 alpha 都走同样的伪影剔除流程，保证口径一致
    dafs = {}
    for a in params.alpha_sensitivity:
        thr = null.mu + normal_ppf(1 - a) * null.sigma
        cand = roi & (u > thr)
        masked, _ = analyze_objects(cand, u, roi, ch, params, apply_filter=True)
        dafs[a] = float(masked.sum() / roi.sum() * 100)

    kept_areas = np.array([f.area_um2 for f in feats if not f.reject], dtype=np.float64)
    if kept_areas.size >= 30:
        ci = bootstrap_ci_objects(kept_areas, area["roi_um2"], params)
    else:
        ci = bootstrap_ci_pixels(dark, roi, params)
    metrics = Metrics(**area, **cont, **objs, **ci,
                      daf_alpha_low=dafs.get(min(params.alpha_sensitivity), 0.0),
                      daf_alpha_mid=dafs.get(params.alpha, 0.0),
                      daf_alpha_high=dafs.get(max(params.alpha_sensitivity), 0.0))

    bc = bimodality_coefficient(u[roi])
    sat = saturation_fraction(ch, roi, params.saturation_level)
    artifact_frac = area.get("artifact_pct", 0.0) / 100.0
    qc = evaluate(cal, null, metrics, bc, sat, artifact_frac, params)

    return AnalysisResult(
        code=code or os.path.splitext(os.path.basename(path))[0],
        path=path, params=params, metrics=metrics, qc=qc, calibration=cal,
        null=null, null_focal=null_f, polygon=list(polygon),
        light_pts=list(light_pts), dark_pts=list(dark_pts),
        roi_mask=roi, dark_mask=dark, focal_mask=focal,
        u=u, u_smooth=u_s, u_focal=u_f, objects=feats,
        elapsed_s=time.time() - t0)


def preview_threshold(u: np.ndarray, roi: np.ndarray, refmask: np.ndarray,
                      alpha: float, params: Params) -> Tuple[float, np.ndarray]:
    """仅计算阈值与候选掩膜，用于界面实时预览。"""
    null = estimate_null(u, roi, refmask, alpha)
    return null.threshold, roi & (u > null.threshold)
