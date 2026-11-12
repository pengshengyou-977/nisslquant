# -*- coding: utf-8 -*-
"""全局配置与参数默认值。

所有可调参数集中在此，便于版本追溯与软著说明书逐项说明。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field
from typing import Dict, Any

APP_NAME = "NisslQuant"
APP_NAME_CN = "尼氏深染面积定量分析系统"
VERSION = "1.0.0"
BUILD_DATE = "2026-11-12"
AUTHOR = "ClawsGO Science Agent"


@dataclass
class Params:
    """一次分析所使用的全部参数。

    长度单位统一为像素（px），面积单位统一为平方微米（µm²）或平方毫米（mm²）。
    """

    # ---- 图像与尺度 ----
    um_per_px: float = 0.4975          # 20 倍物镜下 100 µm = 201 px
    channel: int = 0                   # 0=R 1=G 2=B；尼氏染色取 R 通道
    black_level: float = 0.0           # 相机黑电平，一般取 0

    # ---- 参考区采样 ----
    ref_patch_radius: int = 7          # 参考区采样圆片半径（px）
    ref_min_points: int = 1            # 每类参考区最少点数
    ref_contrast_min: float = 3.0     # 浅/深参考的标准化间距下限（QC 用）

    # ---- 多尺度分解 ----
    sigma_px: float = 35.0             # 低频分量高斯核尺度（px），约一个胞体直径
    decompose: bool = True             # 是否启用局灶/弥漫分解

    # ---- 阈值 ----
    threshold_frac: float = 0.5        # 阈值在浅→深参考之间的位置：0=浅参考，1=深参考
    threshold_frac_sensitivity: tuple = (0.4, 0.5, 0.6)
    alpha: float = 0.01                # 局灶分量与质控用的单侧错误率
    alpha_sensitivity: tuple = (0.005, 0.01, 0.02)

    # ---- 伪影剔除 ----
    min_area_um2: float = 12.0         # 连通域面积下限
    border_frac_max: float = 0.60      # 贴边像素占比上限
    border_area_um2: float = 200.0     # 仅对大于此面积的连通域执行贴边规则
    saturation_level: float = 2.0      # 低于此灰度视为过饱和/染料沉淀

    # ---- 不确定度 ----
    bootstrap_n: int = 120             # bootstrap 次数
    bootstrap_pixels: int = 40000      # 每次重采样的像素上限
    ci_level: float = 0.95

    # ---- 质控阈值 ----
    qc_ci_width_max: float = 5.0       # 95%CI 宽度上限（百分点）
    qc_bimodality_min: float = 0.555   # 双峰系数下限
    qc_sat_frac_max: float = 0.05      # 饱和像素比例上限
    qc_artifact_frac_max: float = 0.60 # 伪影剔除比例上限

    # ---- 输出 ----
    save_overlay: bool = True
    save_masks: bool = True
    overlay_scale: float = 1.0
    decimals: int = 3

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["alpha_sensitivity"] = list(self.alpha_sensitivity)
        d["threshold_frac_sensitivity"] = list(self.threshold_frac_sensitivity)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Params":
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in d.items() if k in known}
        if "alpha_sensitivity" in clean:
            clean["alpha_sensitivity"] = tuple(clean["alpha_sensitivity"])
        if "threshold_frac_sensitivity" in clean:
            clean["threshold_frac_sensitivity"] = tuple(clean["threshold_frac_sensitivity"])
        return cls(**clean)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "Params":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


DEFAULT_PARAMS = Params()

# 允许的图像扩展名
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp")

# 参考区颜色（界面与叠加图共用）
COLOR_LIGHT = (46, 139, 87)
COLOR_DARK = (192, 57, 43)
COLOR_ROI = (31, 78, 121)
COLOR_MASK = (230, 40, 40)
COLOR_FOCAL = (243, 156, 18)

# 应用数据目录
def app_dir() -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return base
