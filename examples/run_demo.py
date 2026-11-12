# -*- coding: utf-8 -*-
"""在合成演示图像上运行完整流水线，输出指标并保存叠加图。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nisslquant.config import Params
from nisslquant.imageio import read_image, save_overlay, format_caption
from nisslquant.pipeline import analyze


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    img_path = os.path.join(here, "demo_nissl.png")
    meta_path = os.path.join(here, "demo_points.json")
    if not os.path.exists(img_path):
        from make_demo import make
        make(here)
    with open(meta_path, encoding="utf-8") as fh:
        meta = json.load(fh)

    params = Params(um_per_px=meta.get("um_per_px", 0.4975))
    res = analyze(img_path, meta["polygon"], meta["light_pts"], meta["dark_pts"],
                  params, code="DEMO")
    m = res.metrics
    print(f"ROI 面积        {m.roi_mm2:.4f} mm²")
    print(f"深染面积比      {m.daf_pct:.2f} %  (95%CI {m.ci_low:.2f}–{m.ci_high:.2f})")
    print(f"绝对深染面积    {m.dark_mm2:.4f} mm²")
    print(f"局灶深染比      {m.focal_pct:.2f} %")
    print(f"参考对比度      {res.calibration.contrast:.2f}")
    print(f"质控            {res.qc.grade}（{res.qc.score} 分）")
    if res.qc.flags:
        for f in res.qc.flags:
            print(f"  - [{f.level}] {f.message}")

    img = read_image(img_path)
    out = os.path.join(here, "demo_overlay.jpg")
    save_overlay(out, img.rgb, res.roi_mask, res.dark_mask, res.focal_mask,
                 res.light_pts, res.dark_pts, res.polygon,
                 format_caption("DEMO", m.daf_pct, m.dark_mm2, res.null.threshold, res.qc.grade))
    print("叠加图已保存：", out)


if __name__ == "__main__":
    main()
