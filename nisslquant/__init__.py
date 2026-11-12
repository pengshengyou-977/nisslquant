# -*- coding: utf-8 -*-
"""NisslQuant：尼氏染色深染面积半自动化定量系统。"""

from .config import APP_NAME, APP_NAME_CN, VERSION, Params
from .pipeline import analyze, AnalysisResult

__all__ = ["APP_NAME", "APP_NAME_CN", "VERSION", "Params", "analyze", "AnalysisResult"]
