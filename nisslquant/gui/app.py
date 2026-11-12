# -*- coding: utf-8 -*-
"""主窗口与工作流。"""
from __future__ import annotations

import os
import queue
import threading
import traceback
from typing import Dict, List, Optional

import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..config import APP_NAME, APP_NAME_CN, VERSION, Params, IMAGE_EXTS
from ..imageio import list_images, read_image, save_mask_png, save_overlay, format_caption
from ..pipeline import AnalysisResult, analyze
from ..report import export_html, export_methods_md, export_objects, export_results
from ..session import Session
from .canvas import ImageView

FONT = ("Microsoft YaHei", 9)
FONT_B = ("Microsoft YaHei", 9, "bold")
FONT_T = ("Microsoft YaHei", 12, "bold")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME_CN}  v{VERSION}")
        self.geometry("1420x900")
        self.minsize(1120, 720)
        self.configure(bg="#F2F5F8")

        self.session = Session()
        self.index = 0
        self.current_image = None
        self.current_result: Optional[AnalysisResult] = None
        self.current_path: Optional[str] = None
        self._busy = False
        self._objects_by_code: Dict[str, List[Dict]] = {}
        self._queue: "queue.Queue" = queue.Queue()

        self._build_style()
        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._build_status()
        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(120, self._first_hint)

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------
    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background="#F2F5F8")
        style.configure("TLabel", background="#F2F5F8", font=FONT)
        style.configure("TButton", font=FONT, padding=(8, 4))
        style.configure("Accent.TButton", font=FONT_B, foreground="#FFFFFF", background="#1F4E79")
        style.map("Accent.TButton", background=[("active", "#2E6DA4")])
        style.configure("TNotebook", background="#F2F5F8")
        style.configure("TNotebook.Tab", font=FONT, padding=(12, 5))
        style.configure("TLabelframe", background="#F2F5F8")
        style.configure("TLabelframe.Label", background="#F2F5F8", font=FONT_B, foreground="#1F4E79")
        style.configure("Treeview", font=("Microsoft YaHei", 9), rowheight=23)
        style.configure("Treeview.Heading", font=("Microsoft YaHei", 9, "bold"))

    def _build_menu(self) -> None:
        m = tk.Menu(self)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="打开图像文件…", command=self.open_files, accelerator="Ctrl+O")
        fm.add_command(label="打开文件夹…", command=self.open_folder, accelerator="Ctrl+Shift+O")
        fm.add_separator()
        fm.add_command(label="打开工程…", command=self.open_project)
        fm.add_command(label="保存工程", command=self.save_project, accelerator="Ctrl+S")
        fm.add_command(label="工程另存为…", command=lambda: self.save_project(True))
        fm.add_separator()
        fm.add_command(label="导出逐张结果 CSV…", command=self.export_csv)
        fm.add_command(label="导出逐对象明细 CSV…", command=self.export_objects)
        fm.add_command(label="导出 HTML 质控报告…", command=self.export_html)
        fm.add_separator()
        fm.add_command(label="退出", command=self.on_close)
        m.add_cascade(label="文件", menu=fm)

        em = tk.Menu(m, tearoff=0)
        em.add_command(label="清除当前标注", command=self.clear_annotation, accelerator="Esc")
        em.add_command(label="盲法随机代号", command=self.apply_blind)
        m.add_cascade(label="编辑", menu=em)

        vm = tk.Menu(m, tearoff=0)
        vm.add_command(label="适应窗口", command=lambda: self.view.fit(), accelerator="F")
        vm.add_command(label="放大", command=lambda: self.view.zoom_at(1.25, 450, 330))
        vm.add_command(label="缩小", command=lambda: self.view.zoom_at(1 / 1.25, 450, 330))
        m.add_cascade(label="视图", menu=vm)

        hm = tk.Menu(m, tearoff=0)
        hm.add_command(label="使用说明", command=self.show_help)
        hm.add_command(label="方法学参数说明", command=self.show_methods)
        hm.add_command(label="关于", command=self.show_about)
        m.add_cascade(label="帮助", menu=hm)
        self.config(menu=m)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(side="top", fill="x")
        self.mode_var = tk.StringVar(value="roi")
        for text, val in (("① 勾画 ROI", "roi"), ("② 浅染参考", "light"),
                          ("③ 深染参考", "dark"), ("浏览/平移", "pan")):
            ttk.Radiobutton(bar, text=text, value=val, variable=self.mode_var,
                            command=self._mode_changed).pack(side="left", padx=(0, 6))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(bar, text="闭合轮廓", command=self.close_roi).pack(side="left", padx=3)
        ttk.Button(bar, text="计算", style="Accent.TButton", command=self.compute).pack(side="left", padx=3)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(bar, text="◀ 上一张", command=self.prev_image).pack(side="left", padx=3)
        ttk.Button(bar, text="下一张 ▶", command=self.next_image).pack(side="left", padx=3)
        ttk.Button(bar, text="保存并下一张", command=self.save_and_next).pack(side="left", padx=3)
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=120)
        self.progress.pack(side="right", padx=6)

    def _build_body(self) -> None:
        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        left = ttk.Frame(body)
        self.view = ImageView(left, on_change=self._annotation_changed)
        self.view.pack(fill="both", expand=True)
        body.add(left, weight=4)

        right = ttk.Frame(body, width=380)
        right.pack_propagate(False)
        body.add(right, weight=1)
        self._build_right(right)

    def _build_right(self, parent) -> None:
        nb = ttk.Notebook(parent)
        nb.pack(fill="both", expand=True)
        self.nb = nb

        # --- 参数页 ---
        pf = ttk.Frame(nb, padding=10)
        nb.add(pf, text="参数")
        self.var_scale = tk.StringVar(value=str(self.session.params.um_per_px))
        self.var_alpha = tk.StringVar(value=str(self.session.params.alpha))
        self.var_sigma = tk.StringVar(value=str(self.session.params.sigma_px))
        self.var_minarea = tk.StringVar(value=str(self.session.params.min_area_um2))
        self.var_channel = tk.StringVar(value=str(self.session.params.channel + 1))
        self.var_decomp = tk.BooleanVar(value=self.session.params.decompose)

        rows = [("比例尺（µm/px）", self.var_scale), ("错误率 α", self.var_alpha),
                ("分解尺度 σ（px）", self.var_sigma), ("最小对象面积（µm²）", self.var_minarea),
                ("颜色通道（1=R）", self.var_channel)]
        for i, (label, var) in enumerate(rows):
            ttk.Label(pf, text=label).grid(row=i, column=0, sticky="w", pady=5)
            ttk.Entry(pf, textvariable=var, width=14).grid(row=i, column=1, sticky="e", pady=5)
        ttk.Checkbutton(pf, text="启用局灶/弥漫分解", variable=self.var_decomp).grid(
            row=len(rows), column=0, columnspan=2, sticky="w", pady=8)
        ttk.Button(pf, text="应用参数", command=self.apply_params).grid(
            row=len(rows) + 1, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Separator(pf, orient="horizontal").grid(row=len(rows) + 2, column=0, columnspan=2, sticky="ew", pady=10)
        ttk.Label(pf, text="操作提示", font=FONT_B, foreground="#1F4E79").grid(
            row=len(rows) + 3, column=0, columnspan=2, sticky="w")
        tip = ("1. 沿颗粒层外缘逐点单击，点回起点或按 Enter 闭合；\n"
               "2. 在浅色组织上点 1–3 处浅染参考；\n"
               "3. 在深色斑块上点 1–3 处深染参考；\n"
               "4. 点「计算」，查看叠加图与质控；\n"
               "5. 「保存并下一张」自动入库。\n\n"
               "滚轮缩放，右键拖动平移，右键单击撤销上一个点。")
        ttk.Label(pf, text=tip, justify="left", wraplength=330).grid(
            row=len(rows) + 4, column=0, columnspan=2, sticky="w", pady=6)

        # --- 结果页 ---
        rf = ttk.Frame(nb, padding=10)
        nb.add(rf, text="结果")
        self.result_text = tk.Text(rf, height=16, font=("Consolas", 9), wrap="none",
                                   bg="#FFFFFF", relief="flat", padx=8, pady=8)
        self.result_text.pack(fill="both", expand=True)

        # --- 质控页 ---
        qf = ttk.Frame(nb, padding=10)
        nb.add(qf, text="质控")
        self.qc_text = tk.Text(qf, height=10, font=FONT, wrap="word",
                               bg="#FFFFFF", relief="flat", padx=8, pady=8)
        self.qc_text.pack(fill="both", expand=True)
        self.qc_text.tag_config("warn", foreground="#B9770E")
        self.qc_text.tag_config("fail", foreground="#C0392B")
        self.qc_text.tag_config("ok", foreground="#2E8B57")
        self.qc_text.tag_config("info", foreground="#1F4E79")

        # --- 列表页 ---
        lf = ttk.Frame(nb, padding=6)
        nb.add(lf, text="清单")
        cols = ("code", "daf", "grade")
        self.tree = ttk.Treeview(lf, columns=cols, show="headings", height=18)
        for c, t, w in (("code", "代号", 110), ("daf", "深染%", 80), ("grade", "可信度", 70)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._tree_select)

    def _build_status(self) -> None:
        bar = ttk.Frame(self, padding=(12, 4))
        bar.pack(side="bottom", fill="x")
        self.status = tk.StringVar(value="就绪")
        ttk.Label(bar, textvariable=self.status, foreground="#555").pack(side="left")
        self.counter = tk.StringVar(value="0 / 0")
        ttk.Label(bar, textvariable=self.counter, foreground="#555").pack(side="right")

    def _bind_keys(self) -> None:
        self.bind("<Control-o>", lambda e: self.open_files())
        self.bind("<Control-O>", lambda e: self.open_folder())
        self.bind("<Control-s>", lambda e: self.save_project())
        self.bind("<Return>", lambda e: self.close_roi())
        self.bind("<Escape>", lambda e: self.clear_annotation())
        self.bind("<F>", lambda e: self.view.fit())
        self.bind("<Prior>", lambda e: self.prev_image())
        self.bind("<Next>", lambda e: self.next_image())
        self.bind("<Control-Return>", lambda e: self.compute())

    # ------------------------------------------------------------------
    # 状态与提示
    # ------------------------------------------------------------------
    def _first_hint(self) -> None:
        self.status.set("请打开图像或文件夹开始；按 F1 查看使用说明")
        self.bind("<F1>", lambda e: self.show_help())

    def set_status(self, text: str) -> None:
        self.status.set(text)

    def _mode_changed(self) -> None:
        self.view.set_mode(self.mode_var.get())
        names = {"roi": "勾画 ROI：沿颗粒层外缘逐点单击，Enter 或点回起点闭合",
                 "light": "浅染参考：在浅色组织上点 1–3 处",
                 "dark": "深染参考：在深色斑块上点 1–3 处",
                 "pan": "浏览模式：左键拖动平移，滚轮缩放"}
        self.set_status(names.get(self.mode_var.get(), ""))

    def _annotation_changed(self) -> None:
        n = len(self.view.polygon)
        self.set_status(f"ROI 顶点 {n} 个；浅参考 {len(self.view.light_pts)} 处；"
                        f"深参考 {len(self.view.dark_pts)} 处")

    # ------------------------------------------------------------------
    # 参数
    # ------------------------------------------------------------------
    def collect_params(self) -> Params:
        p = Params()
        p.um_per_px = float(self.var_scale.get())
        p.alpha = float(self.var_alpha.get())
        p.sigma_px = float(self.var_sigma.get())
        p.min_area_um2 = float(self.var_minarea.get())
        ch = int(self.var_channel.get())
        p.channel = max(0, min(2, ch - 1))
        p.decompose = bool(self.var_decomp.get())
        return p

    def apply_params(self) -> None:
        try:
            p = self.collect_params()
        except ValueError as e:
            messagebox.showerror("参数错误", f"请检查参数格式：{e}")
            return
        self.session.params = p
        p.save(os.path.join(os.path.expanduser("~"), ".nisslquant_params.json"))
        self.set_status("参数已应用")

    # ------------------------------------------------------------------
    # 文件与工程
    # ------------------------------------------------------------------
    def open_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择尼氏染色图像",
            filetypes=[("图像文件", "*.jpg *.jpeg *.png *.tif *.tiff *.bmp"), ("全部文件", "*.*")])
        if not paths:
            return
        self.session.add_images(list(paths))
        self.index = max(0, len(self.session.entries) - len(paths))
        self.load_index(self.index)

    def open_folder(self) -> None:
        folder = filedialog.askdirectory(title="选择图像文件夹")
        if not folder:
            return
        paths = list_images(folder)
        if not paths:
            messagebox.showwarning("提示", "该文件夹内没有可识别的图像文件")
            return
        self.session.add_images(paths)
        self.index = 0
        self.load_index(0)
        self.set_status(f"已载入 {len(paths)} 张图像")

    def load_index(self, i: int) -> None:
        if not self.session.entries:
            return
        i = max(0, min(i, len(self.session.entries) - 1))
        self.index = i
        e = self.session.entries[i]
        self.current_path = e.path
        try:
            self.current_image = read_image(e.path)
        except Exception as ex:
            messagebox.showerror("读取失败", f"{e.path}\n{ex}")
            return
        self.view.set_image(self.current_image.rgb)
        self.after(60, self.view.fit)
        self.view.polygon = [tuple(p) for p in e.polygon]
        self.view.light_pts = [tuple(p) for p in e.light_pts]
        self.view.dark_pts = [tuple(p) for p in e.dark_pts]
        self.view.closed = len(e.polygon) >= 3
        self.view.set_overlays()
        self.current_result = None
        self._clear_result_text()
        if e.row:
            self._show_row(e.row)
        self.counter.set(f"{i + 1} / {len(self.session.entries)}　{e.code}")
        self.set_status(f"{e.code}　{os.path.basename(e.path)}")
        self._refresh_tree()

    def prev_image(self) -> None:
        if self.index > 0:
            self.load_index(self.index - 1)

    def next_image(self) -> None:
        if self.index + 1 < len(self.session.entries):
            self.load_index(self.index + 1)

    def save_and_next(self) -> None:
        if self.current_result is None:
            if not self._can_compute():
                return
            self.compute(after_save=True)
            return
        self._store_current()
        if self.index + 1 < len(self.session.entries):
            self.load_index(self.index + 1)
        else:
            self.set_status("已到最后一题")

    def _store_current(self) -> None:
        if self.current_result is None:
            return
        self.session.update_from_result(self.current_result)
        self._refresh_tree()

    def save_project(self, save_as: bool = False) -> None:
        if not self.session.entries:
            return
        path = None
        if not save_as:
            path = getattr(self, "_project_path", None)
        if not path:
            path = filedialog.asksaveasfilename(
                title="保存工程", defaultextension=".nqproj",
                filetypes=[("NisslQuant 工程", "*.nqproj"), ("JSON", "*.json")])
        if not path:
            return
        self.session.params = self.collect_params()
        self.session.save(path)
        self._project_path = path
        self.set_status(f"工程已保存：{path}")

    def open_project(self) -> None:
        path = filedialog.askopenfilename(
            title="打开工程", filetypes=[("NisslQuant 工程", "*.nqproj"), ("JSON", "*.json")])
        if not path:
            return
        try:
            self.session = Session.load(path)
        except Exception as ex:
            messagebox.showerror("打开失败", str(ex))
            return
        self._project_path = path
        self.var_scale.set(str(self.session.params.um_per_px))
        self.var_alpha.set(str(self.session.params.alpha))
        self.var_sigma.set(str(self.session.params.sigma_px))
        self.var_minarea.set(str(self.session.params.min_area_um2))
        self.var_channel.set(str(self.session.params.channel + 1))
        self.var_decomp.set(self.session.params.decompose)
        if self.session.entries:
            self.load_index(0)
        self.set_status(f"已打开工程：{os.path.basename(path)}")

    def apply_blind(self) -> None:
        if not self.session.entries:
            return
        if not messagebox.askyesno("盲法", "将把文件名替换为随机代号并打乱顺序，\n对应关系仅保存在工程文件中。是否继续？"):
            return
        self.session.apply_blind()
        self.load_index(0)
        self.set_status("已启用盲法：界面只显示随机代号")

    def close_roi(self) -> None:
        if self.view.polygon and not self.view.closed:
            self.view.close_polygon()
            self.set_status("轮廓已闭合，请点选浅染与深染参考区")

    def clear_annotation(self) -> None:
        self.view.undo_all()
        self.current_result = None
        self.view.set_overlays()
        self._clear_result_text()

    # ------------------------------------------------------------------
    # 计算
    # ------------------------------------------------------------------
    def _can_compute(self) -> bool:
        if self.current_image is None:
            messagebox.showinfo("提示", "请先打开图像")
            return False
        if len(self.view.polygon) < 3:
            messagebox.showinfo("提示", "请先勾画并闭合 ROI")
            return False
        if not self.view.light_pts or not self.view.dark_pts:
            messagebox.showinfo("提示", "请分别点选浅染参考与深染参考")
            return False
        return True

    def compute(self, after_save: bool = False) -> None:
        if self._busy or not self._can_compute():
            return
        try:
            params = self.collect_params()
        except ValueError as e:
            messagebox.showerror("参数错误", str(e))
            return
        self._busy = True
        self.progress.start(12)
        self.set_status("正在计算…")
        poly = list(self.view.polygon)
        lp = list(self.view.light_pts)
        dp = list(self.view.dark_pts)
        img = self.current_image
        code = self.session.entries[self.index].code if self.session.entries else os.path.basename(img.path)
        path = img.path

        def work():
            try:
                res = analyze(path, poly, lp, dp, params, code=code, image=img)
                self._queue.put(("ok", (res, after_save)))
            except Exception as ex:
                self._queue.put(("err", (ex, traceback.format_exc())))

        threading.Thread(target=work, daemon=True).start()
        self.after(80, self._poll_queue)

    def _poll_queue(self) -> None:
        try:
            kind, payload = self._queue.get_nowait()
        except queue.Empty:
            self.after(80, self._poll_queue)
            return
        if kind == "ok":
            res, after_save = payload
            self._on_result(res, after_save)
        else:
            ex, err = payload
            self._on_error(ex, err)

    def _on_error(self, ex: Exception, err: str) -> None:
        self._busy = False
        self.progress.stop()
        self.set_status("计算失败")
        messagebox.showerror("计算失败", f"{ex}\n\n{err.splitlines()[-3] if err else ''}")

    def _on_result(self, res: AnalysisResult, after_save: bool) -> None:
        self._busy = False
        self.progress.stop()
        self.current_result = res
        self.session.params = res.params
        self.view.set_overlays(dark=res.dark_mask, focal=res.focal_mask, roi=res.roi_mask)
        self._show_result(res)
        self._objects_by_code[res.code] = [o.as_row() for o in res.objects]
        self.session.update_from_result(res)
        self._refresh_tree()
        self.set_status(f"完成：{res.code}　用时 {res.elapsed_s:.2f} s")
        if after_save and self.index + 1 < len(self.session.entries):
            self.load_index(self.index + 1)

    def _clear_result_text(self) -> None:
        self.result_text.delete("1.0", "end")
        self.qc_text.delete("1.0", "end")

    def _show_result(self, res: AnalysisResult) -> None:
        m = res.metrics
        lines = [
            f"图像　{res.code}",
            f"文件　{os.path.basename(res.path)}",
            "",
            f"ROI 面积　　　{res.roi_mask.sum() * res.params.um_per_px ** 2 / 1e6:.4f} mm²",
            f"深染面积　　　{m.dark_mm2:.4f} mm²",
            f"深染面积比　　{m.daf_pct:.2f} %　(95%CI {m.ci_low:.2f}–{m.ci_high:.2f})",
            f"剔除前面积比　{m.daf_raw_pct:.2f} %　(伪影占候选 {m.artifact_pct:.1f}%)",
            f"局灶深染比　　{m.focal_pct:.2f} %",
            "",
            f"平均标准化密度　{m.mean_u:.3f}",
            f"弥漫染色指数　　{m.diffuse_u:.3f}",
            f"超额染色负荷　　{m.excess_load:.4f}",
            "",
            f"深染对象数　　{m.n_objects}",
            f"对象平均面积　{m.obj_mean_um2:.1f} µm²",
            f"伪影剔除　　　{m.n_rejected} 个连通域",
            "",
            f"浅参考 R　　　{res.calibration.light_value:.1f}",
            f"深参考 R　　　{res.calibration.dark_value:.1f}",
            f"标定跨度 OD　 {res.calibration.span:.3f}",
            f"参考对比度　　{res.calibration.contrast:.2f}",
            f"零分布 μ/σ　　{res.null.mu:.3f} / {res.null.sigma:.3f}",
            f"阈值 τ_u　　　{res.tau_u:.3f}（强度 {res.tau_int:.0f}）",
            "",
            f"阈值敏感性　{res.metrics.daf_tau_low:.2f} / "
            f"{res.metrics.daf_tau_mid:.2f} / {res.metrics.daf_tau_high:.2f} %",
            f"可信度　　　　{res.qc.grade}（{res.qc.score} 分）",
        ]
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", "\n".join(lines))
        self._show_qc(res)

    def _show_qc(self, res: AnalysisResult) -> None:
        self.qc_text.delete("1.0", "end")
        tags = {"fail": "fail", "warn": "warn", "info": "info"}
        self.qc_text.insert("end", f"综合可信度：{res.qc.grade}（{res.qc.score} 分）\n\n", "ok" if res.qc.grade == "优" else "info")
        if not res.qc.flags:
            self.qc_text.insert("end", "未见异常。\n", "ok")
        for f in res.qc.flags:
            mark = {"fail": "✕", "warn": "!", "info": "i"}[f.level]
            self.qc_text.insert("end", f"[{mark}] {f.message}\n", tags.get(f.level, "info"))
            if f.value is not None:
                self.qc_text.insert("end", f"      当前值 {f.value:.3g}，阈值 {f.limit:.3g}\n")
        self.qc_text.insert("end", "\n提示：质控只标注不确定性来源，不替代人工复核。\n")

    def _show_row(self, row: Dict) -> None:
        keys = ["code", "daf_pct", "dark_mm2", "focal_pct", "mean_u", "n_objects",
                "threshold_u", "ref_contrast", "qc_grade"]
        txt = "\n".join(f"{k:16s}{row.get(k, '')}" for k in keys)
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", txt)

    def _refresh_tree(self) -> None:
        for i in self.tree.get_children():
            self.tree.delete(i)
        for e in self.session.entries:
            daf = e.row.get("daf_pct", "")
            grade = e.row.get("qc_grade", "")
            self.tree.insert("", "end", values=(e.code, f"{float(daf):.2f}" if daf != "" else "", grade))

    def _tree_select(self, ev) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        if 0 <= idx < len(self.session.entries) and idx != self.index:
            self.load_index(idx)

    # ------------------------------------------------------------------
    # 导出
    # ------------------------------------------------------------------
    def export_csv(self) -> None:
        rows = self.session.results_rows()
        if not rows:
            messagebox.showinfo("提示", "尚无已完成的结果")
            return
        path = filedialog.asksaveasfilename(title="导出逐张结果", defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        export_results(path, rows)
        base = os.path.splitext(path)[0]
        export_methods_md(base + "_方法说明.md", self.session.params)
        self.set_status(f"已导出：{path}")

    def export_objects(self) -> None:
        if not self.session.entries:
            return
        objects = dict(self._objects_by_code)
        if not objects:
            messagebox.showinfo("提示", "逐对象明细需在本次会话中重新计算后导出")
            return
        path = filedialog.asksaveasfilename(title="导出逐对象明细", defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            export_objects(path, objects)
            self.set_status(f"已导出：{path}")

    def export_html(self) -> None:
        rows = self.session.results_rows()
        if not rows:
            messagebox.showinfo("提示", "尚无已完成的结果")
            return
        path = filedialog.asksaveasfilename(title="导出 HTML 报告", defaultextension=".html",
                                            filetypes=[("HTML", "*.html")])
        if not path:
            return
        outdir = os.path.splitext(path)[0] + "_标注图"
        os.makedirs(outdir, exist_ok=True)
        overlays = {}
        if self.current_result is not None:
            p = os.path.join(outdir, self.current_result.code + ".jpg")
            res = self.current_result
            save_overlay(p, self.current_image.rgb, res.roi_mask, res.dark_mask, res.focal_mask,
                         res.light_pts, res.dark_pts, res.polygon,
                         format_caption(res.code, res.metrics.daf_pct, res.metrics.dark_mm2, res.tau_u))
            overlays[res.code] = p
        export_html(path, rows, self.session.params, overlays,
                    project=self.session.project, operator=self.session.operator)
        self.set_status(f"已导出：{path}")

    # ------------------------------------------------------------------
    # 帮助
    # ------------------------------------------------------------------
    def show_help(self) -> None:
        text = """【使用流程】

1. 打开图像或文件夹（Ctrl+O / Ctrl+Shift+O）。
2. 选择「① 勾画 ROI」，沿颗粒层外缘逐点单击；
   点回起点、双击或按 Enter 闭合；右键单击撤销上一个点。
3. 选择「② 浅染参考」，在层内浅色组织上点 1–3 处。
4. 选择「③ 深染参考」，在深色斑块上点 1–3 处。
5. 点「计算」（Ctrl+Enter），查看叠加图、结果与质控。
6. 点「保存并下一张」入库；结束后导出 CSV 与 HTML 报告。

【操作技巧】
- 滚轮缩放；「浏览/平移」模式下左键拖动平移。
- Esc 清除当前标注；F 适应窗口。
- 参数改动后需重新点「计算」。

【质控含义】
- 参考对比度过低：浅/深参考太接近，标定不可靠。
- 近似单峰：深染与浅染为连续过渡，面积比应按分布尾部解读。
- 置信区间过宽：该张结果不稳，建议复核参考点或 ROI。"""
        self._text_dialog("使用说明", text, 620, 560)

    def show_methods(self) -> None:
        text = """【指标定义】

标准化染色密度  u = (OD − OD_L) / (OD_D − OD_L)
光密度          OD = −lg(I / I₀)，I₀ 取浅参考中位强度

深染面积比 DAF   = 深染像素面积 / ROI 面积 × 100%
局灶深染比 FDF   = 局灶分量超阈像素面积 / ROI 面积 × 100%
弥漫染色指数 DSI = ROI 内低频分量中位数
超额染色负荷 ESL = mean(max(0, u − τ))

【阈值】
零分布由浅参考区稳健估计（中位数与 MAD），
τ = μ₀ + z(1−α)·σ₀，α 为单侧错误率（默认 0.01）。

【局灶/弥漫分解】
u_s = Gauss(σ) * u，u_f = u − u_s；
σ 默认 35 px，约合一个颗粒细胞胞体直径。

【不确定度】
ROI 像素 bootstrap，默认 120 次，报告 95% 置信区间。
该区间只反映抽样误差，不含染色与切片本身的不确定性。"""
        self._text_dialog("方法学参数说明", text, 640, 560)

    def show_about(self) -> None:
        messagebox.showinfo(
            "关于",
            f"{APP_NAME_CN}\n版本 {VERSION}\n\n"
            "面向尼氏染色海马齿状回颗粒层深染面积的\n"
            "半自动化定量工具。\n\n"
            "算法：双参考光密度标定 + 多尺度密度分解 +\n"
            "误差率控制阈值 + 伪影剔除 + 不确定度评估。")

    def _text_dialog(self, title: str, text: str, w: int, h: int) -> None:
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry(f"{w}x{h}")
        txt = tk.Text(win, font=("Microsoft YaHei", 10), wrap="word", padx=16, pady=14,
                      bg="#FFFFFF", relief="flat")
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", text)
        txt.config(state="disabled")

    # ------------------------------------------------------------------
    def on_close(self) -> None:
        if self.session.entries and any(e.done for e in self.session.entries):
            if not messagebox.askyesno("退出", "是否保存工程后再退出？"):
                self.destroy()
                return
            self.save_project()
        self.destroy()
