# -*- coding: utf-8 -*-
"""单张图像的质控规则与可信度分级。

质控不是"通过/不通过"的二元判断，而是给出可解释的告警清单与四级可信度，
便于作者在论文中如实披露，也便于批处理时快速定位问题切片。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from .config import Params


@dataclass
class QCFlag:
    code: str
    level: str      # info / warn / fail
    message: str
    value: Optional[float] = None
    limit: Optional[float] = None

    def as_row(self) -> Dict:
        return {"code": self.code, "level": self.level, "message": self.message,
                "value": self.value, "limit": self.limit}


@dataclass
class QCResult:
    flags: List[QCFlag] = field(default_factory=list)
    grade: str = "未评级"
    score: int = 100

    def add(self, code: str, level: str, message: str,
            value: Optional[float] = None, limit: Optional[float] = None) -> None:
        self.flags.append(QCFlag(code, level, message, value, limit))
        if level == "warn":
            self.score -= 12
        elif level == "fail":
            self.score -= 30

    def finalize(self) -> "QCResult":
        self.score = max(0, self.score)
        if self.score >= 85:
            self.grade = "优"
        elif self.score >= 70:
            self.grade = "良"
        elif self.score >= 50:
            self.grade = "可疑"
        else:
            self.grade = "不合格"
        return self

    def has_fail(self) -> bool:
        return any(f.level == "fail" for f in self.flags)

    def summary(self) -> str:
        if not self.flags:
            return "未见异常"
        return "；".join(f.message for f in self.flags)

    def as_rows(self) -> List[Dict]:
        return [f.as_row() for f in self.flags]


def evaluate(cal, null, metrics, bc: float, sat_frac: float,
             artifact_frac: float, params: Params) -> QCResult:
    q = QCResult()

    # 1) 参考标定
    if cal.n_light < params.ref_min_points or cal.n_dark < params.ref_min_points:
        q.add("REF_N", "warn", "参考区点数不足")
    if cal.contrast < params.ref_contrast_min:
        q.add("REF_CONTRAST", "fail", "浅/深参考对比不足，标定不可靠",
              cal.contrast, params.ref_contrast_min)
    elif cal.contrast < params.ref_contrast_min * 1.5:
        q.add("REF_CONTRAST", "warn", "参考对比偏低",
              cal.contrast, params.ref_contrast_min * 1.5)

    # 2) 直方图形态
    if np.isfinite(bc) and bc < params.qc_bimodality_min:
        q.add("UNIMODAL", "info",
              "ROI 内染色密度近似单峰，深染与浅染为连续过渡，面积比应结合连续指标解读", bc,
              params.qc_bimodality_min)

    # 3) 不确定度
    if metrics.ci_width > params.qc_ci_width_max:
        q.add("CI_WIDE", "warn", "深染面积比的 95% 置信区间过宽",
              metrics.ci_width, params.qc_ci_width_max)

    # 4) 图像质量
    if sat_frac > params.qc_sat_frac_max:
        q.add("SATURATION", "warn", "过饱和像素比例偏高，深染区可能被低估",
              sat_frac, params.qc_sat_frac_max)

    # 5) 伪影
    if artifact_frac > params.qc_artifact_frac_max:
        q.add("ARTIFACT", "warn", "候选深染面积剔除比例偏高，请检查切片折叠、染料沉淀或最小面积设置",
              artifact_frac, params.qc_artifact_frac_max)

    # 6) 结果合理性
    if metrics.daf_pct < 0.2:
        q.add("DAF_LOW", "warn", "深染面积比接近零，可能参考区选择不当或切片过淡",
              metrics.daf_pct, 0.2)
    elif metrics.daf_pct > 50:
        q.add("DAF_HIGH", "warn", "深染面积比过高，可能阈值偏低或整体过染",
              metrics.daf_pct, 50.0)

    # 7) 阈值位置敏感性
    if metrics.daf_tau_mid > 0:
        rel = abs(metrics.daf_tau_high - metrics.daf_tau_low) / metrics.daf_tau_mid * 100
        if rel > 80:
            q.add("TAU_SENS", "warn", "结果对阈值位置较敏感，应固定阈值位置并报告敏感性区间",
                  rel, 80.0)

    return q.finalize()
