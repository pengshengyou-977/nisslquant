# -*- coding: utf-8 -*-
"""核心流水线的最小测试：在合成演示图上跑通并检查指标范围。"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nisslquant.calibration import normal_ppf, robust_sigma
from nisslquant.config import Params
from nisslquant.pipeline import analyze


HERE = os.path.dirname(os.path.abspath(__file__))
EX = os.path.join(os.path.dirname(HERE), "examples")


def ensure_demo():
    img = os.path.join(EX, "demo_nissl.png")
    meta = os.path.join(EX, "demo_points.json")
    if not (os.path.exists(img) and os.path.exists(meta)):
        sys.path.insert(0, EX)
        from make_demo import make
        make(EX)
    with open(meta, encoding="utf-8") as fh:
        return img, json.load(fh)


class TestMath(unittest.TestCase):
    def test_normal_ppf(self):
        self.assertAlmostEqual(normal_ppf(0.975), 1.959964, places=5)
        self.assertAlmostEqual(normal_ppf(0.99), 2.326348, places=5)

    def test_robust_sigma(self):
        import numpy as np
        x = np.array([1, 2, 3, 4, 5, 100], dtype=float)
        med, sd = robust_sigma(x)
        self.assertEqual(med, 3.5)
        self.assertLess(sd, 5.0)  # 离群点不应把 MAD 拉大


class TestPipeline(unittest.TestCase):
    def test_demo_runs(self):
        img, meta = ensure_demo()
        res = analyze(img, meta["polygon"], meta["light_pts"], meta["dark_pts"],
                      Params(um_per_px=meta["um_per_px"]), code="DEMO")
        m = res.metrics
        self.assertGreater(m.roi_px, 10000)
        self.assertGreater(m.daf_pct, 0.0)
        self.assertLess(m.daf_pct, 60.0)
        self.assertGreaterEqual(m.ci_low, 0.0)
        self.assertLessEqual(m.ci_high, 100.0)
        self.assertIn(res.qc.grade, {"优", "良", "可疑", "不合格"})
        self.assertGreater(res.calibration.span, 0.0)


if __name__ == "__main__":
    unittest.main()
