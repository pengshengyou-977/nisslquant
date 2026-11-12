# -*- coding: utf-8 -*-
"""命令行批处理：按工程文件中保存的 ROI 与参考点重算全部图像。

用法：
    NisslQuant.exe --cli --project D:\data\batch.nqproj --out D:\data\results.csv
可选：
    --alpha 0.01  --sigma 35  --um 0.4975  --report
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from .config import Params, VERSION
from .pipeline import analyze
from .report import export_html, export_methods_md, export_objects, export_results
from .session import Session


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="NisslQuant", description="尼氏深染面积定量（命令行）")
    p.add_argument("--cli", action="store_true", help="进入命令行模式")
    p.add_argument("--project", required=True, help="工程文件 .nqproj")
    p.add_argument("--out", default="", help="结果 CSV 输出路径")
    p.add_argument("--alpha", type=float, default=None, help="单侧错误率")
    p.add_argument("--sigma", type=float, default=None, help="分解尺度（px）")
    p.add_argument("--um", type=float, default=None, help="比例尺 µm/px")
    p.add_argument("--report", action="store_true", help="同时输出 HTML 报告")
    p.add_argument("--version", action="store_true", help="输出版本号")
    return p


def _log(msg: str, logpath: str = "") -> None:
    print(msg)
    if logpath:
        try:
            with open(logpath, "a", encoding="utf-8") as fh:
                fh.write(msg + "\n")
        except Exception:
            pass


def run_cli(argv) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(VERSION)
        return 0
    if not os.path.isfile(args.project):
        _log(f"找不到工程文件：{args.project}")
        return 2
    session = Session.load(args.project)
    params = session.params
    if args.alpha is not None:
        params.alpha = args.alpha
    if args.sigma is not None:
        params.sigma_px = args.sigma
    if args.um is not None:
        params.um_per_px = args.um

    rows = []
    objects = {}
    overlays = {}
    outdir = os.path.dirname(os.path.abspath(args.out)) if args.out else os.getcwd()
    os.makedirs(outdir, exist_ok=True)

    logpath = os.path.join(outdir, "nisslquant_cli.log")
    t0 = time.time()
    for i, e in enumerate(session.entries):
        if len(e.polygon) < 3 or not e.light_pts or not e.dark_pts:
            _log(f"[跳过] {e.code}：标注不完整", logpath)
            continue
        try:
            res = analyze(e.path, e.polygon, e.light_pts, e.dark_pts, params, code=e.code)
        except Exception as ex:
            _log(f"[失败] {e.code}：{ex}", logpath)
            continue
        rows.append(res.as_row())
        objects[e.code] = [o.as_row() for o in res.objects]
        _log(f"[{i + 1}/{len(session.entries)}] {e.code}  DAF={res.metrics.daf_pct:.2f}%  "
             f"QC={res.qc.grade}", logpath)
        if args.report:
            from .imageio import read_image, save_overlay, format_caption
            img = read_image(e.path)
            p = os.path.join(outdir, "overlays", e.code + ".jpg")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            save_overlay(p, img.rgb, res.roi_mask, res.dark_mask, res.focal_mask,
                         res.light_pts, res.dark_pts, res.polygon,
                         format_caption(e.code, res.metrics.daf_pct, res.metrics.dark_mm2, res.tau_u))
            overlays[e.code] = p

    if not rows:
        _log("没有可导出的结果", logpath)
        return 1

    out = args.out or os.path.join(outdir, "nisslquant_results.csv")
    export_results(out, rows)
    export_methods_md(os.path.splitext(out)[0] + "_方法说明.md", params)
    export_objects(os.path.splitext(out)[0] + "_逐对象.csv", objects)
    if args.report:
        export_html(os.path.splitext(out)[0] + ".html", rows, params, overlays,
                    project=session.project, operator=session.operator)
    _log(f"完成 {len(rows)} 张，用时 {time.time() - t0:.1f} s → {out}", logpath)
    return 0
