# -*- coding: utf-8 -*-
"""结果导出：CSV、逐对象明细、HTML 质控报告与方法学说明。"""
from __future__ import annotations

import base64
import csv
import io
import os
import time
from typing import Dict, List, Optional

import numpy as np

from .config import Params, VERSION, APP_NAME_CN


def _write_csv(path: str, rows: List[Dict], fieldnames: Optional[List[str]] = None) -> None:
    if not rows:
        return
    names = fieldnames or list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=names, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def export_results(path: str, rows: List[Dict]) -> None:
    _write_csv(path, rows)


def export_objects(path: str, objects_by_code: Dict[str, List[Dict]]) -> None:
    rows = []
    for code, objs in objects_by_code.items():
        for o in objs:
            r = {"code": code}
            r.update(o)
            rows.append(r)
    _write_csv(path, rows)


def _thumb_b64(path: str, max_side: int = 420) -> str:
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=82)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


def _group_summary(rows: List[Dict], key: str = "group") -> str:
    if not rows or key not in rows[0]:
        return ""
    groups = {}
    for r in rows:
        g = str(r.get(key, "") or "未分组")
        groups.setdefault(g, []).append(r)
    out = ["<table class='sum'><tr><th>组别</th><th>n</th><th>深染面积比 (%)</th>"
           "<th>绝对深染面积 (mm²)</th><th>局灶深染比 (%)</th><th>平均标准化密度</th></tr>"]
    for g, rs in sorted(groups.items()):
        def ms(k):
            v = [float(r.get(k, 0) or 0) for r in rs]
            return f"{np.mean(v):.2f} ± {np.std(v, ddof=1):.2f}" if len(v) > 1 else f"{np.mean(v):.2f}"
        out.append(f"<tr><td>{g}</td><td>{len(rs)}</td><td>{ms('daf_pct')}</td>"
                   f"<td>{ms('dark_mm2')}</td><td>{ms('focal_pct')}</td><td>{ms('mean_u')}</td></tr>")
    out.append("</table>")
    return "".join(out)


def export_html(path: str, rows: List[Dict], params: Params,
                overlays: Optional[Dict[str, str]] = None,
                project: str = "尼氏深染面积定量",
                operator: str = "") -> None:
    overlays = overlays or {}
    now = time.strftime("%Y-%m-%d %H:%M")
    head = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{project} — 定量报告</title>
<style>
body{{font-family:"Microsoft YaHei",Arial,sans-serif;margin:28px;color:#222;font-size:14px}}
h1{{font-size:22px;color:#1F4E79;border-bottom:2px solid #1F4E79;padding-bottom:8px}}
h2{{font-size:17px;color:#1F4E79;margin-top:26px}}
table{{border-collapse:collapse;width:100%;margin:10px 0;font-size:12.5px}}
th,td{{border:1px solid #D5DCE4;padding:5px 7px;text-align:left}}
th{{background:#EAF1F8;color:#1F4E79}}
tr:nth-child(even){{background:#FAFCFE}}
.cards{{display:flex;flex-wrap:wrap;gap:14px;margin-top:12px}}
.card{{border:1px solid #D5DCE4;border-radius:6px;padding:8px;width:300px;background:#fff}}
.card img{{width:100%;border-radius:4px}}
.card .t{{font-size:12.5px;margin-top:6px;color:#333}}
.meta{{color:#555;font-size:12.5px;line-height:1.9}}
.tag{{display:inline-block;padding:1px 7px;border-radius:9px;font-size:11.5px;color:#fff}}
.ok{{background:#2E8B57}}.warn{{background:#D68910}}.bad{{background:#C0392B}}
.note{{background:#F7F9FB;border-left:4px solid #1F4E79;padding:10px 14px;margin:12px 0;font-size:13px;line-height:1.8}}
</style></head><body>
<h1>{project} — 深染面积定量报告</h1>
<div class="meta">
生成时间：{now}　｜　软件：{APP_NAME_CN} v{VERSION}　｜　操作者：{operator or "—"}<br>
比例尺：{params.um_per_px:.4f} µm/px　｜　通道：RGB 第 {params.channel + 1} 通道　｜
错误率 α：{params.alpha}　｜　分解尺度 σ：{params.sigma_px:.1f} px　｜　最小对象面积：{params.min_area_um2:.1f} µm²
</div>
"""
    method = """
<h2>方法摘要</h2>
<div class="note">
① 以浅染参考区的中位强度为空白参考计算光密度 OD=-lg(I/I₀)；<br>
② 以浅染区与深染区作两点标定，得到标准化染色密度 u=(OD-OD_L)/(OD_D-OD_L)，u=0 对应浅染、u=1 对应深染；<br>
③ 对 u 作高斯低通得到弥漫分量 u_s，局灶分量 u_f=u-u_s；<br>
④ 由浅染参考区稳健估计零分布（中位数与 MAD），按单侧错误率 α 取检出限 τ=μ₀+z₁₋α·σ₀；<br>
⑤ 超过 τ 的像素经连通域标记，按面积下限、贴边比例、过饱和与狭长规则剔除伪影；<br>
⑥ 输出深染面积比、绝对深染面积、局灶深染比、弥漫染色指数与超额染色负荷，并用像素 bootstrap 给出 95% 置信区间。
</div>
"""
    body = ["<h2>汇总</h2>", _group_summary(rows)]
    body.append("<h2>逐张结果</h2><table><tr>"
                "<th>代号</th><th>深染面积比 %</th><th>95%CI</th><th>绝对面积 mm²</th>"
                "<th>局灶深染比 %</th><th>对象数</th><th>阈值 u</th><th>参考对比度</th>"
                "<th>可信度</th><th>告警</th></tr>")
    for r in rows:
        grade = str(r.get("qc_grade", ""))
        cls = "ok" if grade == "优" else ("warn" if grade in ("良", "可疑") else "bad")
        body.append(
            f"<tr><td>{r.get('code','')}</td>"
            f"<td>{float(r.get('daf_pct',0)):.2f}</td>"
            f"<td>{float(r.get('ci_low',0)):.2f}–{float(r.get('ci_high',0)):.2f}</td>"
            f"<td>{float(r.get('dark_mm2',0)):.4f}</td>"
            f"<td>{float(r.get('focal_pct',0)):.2f}</td>"
            f"<td>{int(r.get('n_objects',0))}</td>"
            f"<td>{float(r.get('threshold_u',0)):.3f}</td>"
            f"<td>{float(r.get('ref_contrast',0)):.2f}</td>"
            f"<td><span class='tag {cls}'>{grade}</span></td>"
            f"<td>{r.get('qc_flags','')}</td></tr>")
    body.append("</table>")

    if overlays:
        body.append("<h2>标注图</h2><div class='cards'>")
        for code, p in overlays.items():
            b64 = _thumb_b64(p)
            if not b64:
                continue
            row = next((x for x in rows if x.get("code") == code), {})
            body.append(f"<div class='card'><img src='data:image/jpeg;base64,{b64}'>"
                        f"<div class='t'><b>{code}</b>　深染 {float(row.get('daf_pct',0)):.2f}%　"
                        f"绝对 {float(row.get('dark_mm2',0)):.4f} mm²</div></div>")
        body.append("</div>")

    tail = """
<h2>结果解读与局限</h2>
<div class="note">
深染面积比是"深染像素面积／颗粒层面积"的比值，属于面积积分指标，不等同于深染细胞计数；
同一面积可由少数重度深染或多数轻度深染形成。深染成分亦不唯一，正常尼氏体密集区、皱缩的暗神经元、
切片折叠与染料沉淀均可表现为深染。建议结合局灶深染比、对象数与连续指标（平均标准化密度、超额染色负荷）
联合解读，并在论文中报告 95% 置信区间与质控告警。<br>
当质控提示"近似单峰"时，说明深染与浅染为连续过渡，此时面积比应理解为分布尾部占比，不宜作为二分类结果。
</div>
<p style="color:#888;font-size:12px;margin-top:26px">本报告由 NisslQuant 自动生成，参数与逐张结果已随会话文件保存，可复核。</p>
</body></html>"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(head + method + "".join(body) + tail)


def export_methods_md(path: str, params: Params) -> None:
    text = f"""# 定量方法说明（自动生成）

软件：{APP_NAME_CN} v{VERSION}
比例尺：{params.um_per_px:.4f} µm/px
通道：RGB 第 {params.channel + 1} 通道
错误率：α = {params.alpha}
分解尺度：σ = {params.sigma_px:.1f} px
最小对象面积：{params.min_area_um2:.1f} µm²

## 指标定义

- 标准化染色密度：u = (OD − OD_L) / (OD_D − OD_L)，OD = −lg(I/I₀)
- 深染面积比 DAF = 深染像素面积 / ROI 面积 × 100%
- 局灶深染比 FDF = 局灶分量超过阈值的像素面积 / ROI 面积 × 100%
- 弥漫染色指数 DSI = ROI 内低频分量 u_s 的中位数
- 超额染色负荷 ESL = mean(max(0, u − τ))
- 不确定度：ROI 像素 bootstrap，{params.bootstrap_n} 次，{int(params.ci_level*100)}% 置信区间

## 质控规则

- 参考对比度 = (OD_D − OD_L) / σ_light，低于 {params.ref_contrast_min} 判为标定不可靠
- 双峰系数 BC < {params.qc_bimodality_min} 提示单峰分布
- 95%CI 宽度 > {params.qc_ci_width_max} 个百分点提示结果不稳
- 饱和像素比例 > {params.qc_sat_frac_max:.0%}、伪影剔除比例 > {params.qc_artifact_frac_max:.0%} 触发告警
"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
