# -*- coding: utf-8 -*-
"""工程会话：保存/恢复逐张 ROI、参考点、参数与已算结果。

会话文件为 UTF-8 JSON，可人工阅读与版本管理，便于复核与盲法留痕。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import Params, VERSION


@dataclass
class ImageEntry:
    path: str
    code: str
    polygon: List[List[float]] = field(default_factory=list)
    light_pts: List[List[float]] = field(default_factory=list)
    dark_pts: List[List[float]] = field(default_factory=list)
    done: bool = False
    row: Dict = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> Dict:
        return {"path": self.path, "code": self.code, "polygon": self.polygon,
                "light_pts": self.light_pts, "dark_pts": self.dark_pts,
                "done": self.done, "row": self.row, "note": self.note}

    @classmethod
    def from_dict(cls, d: Dict) -> "ImageEntry":
        return cls(path=d.get("path", ""), code=d.get("code", ""),
                   polygon=d.get("polygon", []), light_pts=d.get("light_pts", []),
                   dark_pts=d.get("dark_pts", []), done=d.get("done", False),
                   row=d.get("row", {}), note=d.get("note", ""))


class Session:
    def __init__(self, params: Optional[Params] = None):
        self.params = params or Params()
        self.entries: List[ImageEntry] = []
        self.created = time.strftime("%Y-%m-%d %H:%M:%S")
        self.blind = False
        self.blind_key: Dict[str, str] = {}
        self.project = "尼氏深染面积定量"
        self.operator = ""

    # ---------------- 条目管理 ----------------
    def add_images(self, paths: List[str]) -> None:
        known = {e.path for e in self.entries}
        for p in paths:
            if p in known:
                continue
            code = os.path.splitext(os.path.basename(p))[0]
            self.entries.append(ImageEntry(path=p, code=code))

    def find(self, path: str) -> Optional[ImageEntry]:
        for e in self.entries:
            if os.path.normcase(e.path) == os.path.normcase(path):
                return e
        return None

    def update_from_result(self, res) -> None:
        e = self.find(res.path)
        if e is None:
            e = ImageEntry(path=res.path, code=res.code)
            self.entries.append(e)
        e.code = res.code
        e.polygon = [[float(x), float(y)] for x, y in res.polygon]
        e.light_pts = [[float(x), float(y)] for x, y in res.light_pts]
        e.dark_pts = [[float(x), float(y)] for x, y in res.dark_pts]
        e.done = True
        e.row = res.as_row()

    # ---------------- 盲法 ----------------
    def apply_blind(self, seed: int = 20261112) -> None:
        """把文件名替换为随机代号，对应关系仅存于会话文件的 key 字段。"""
        import random
        rng = random.Random(seed)
        order = list(range(len(self.entries)))
        rng.shuffle(order)
        self.blind_key = {}
        for n, i in enumerate(order):
            code = f"S{n + 1:03d}"
            self.blind_key[code] = os.path.basename(self.entries[i].path)
            self.entries[i].code = code
        self.blind = True
        # 同步打乱显示顺序
        self.entries = [self.entries[i] for i in order]

    # ---------------- 持久化 ----------------
    def to_dict(self) -> Dict:
        return {
            "app": "NisslQuant",
            "version": VERSION,
            "created": self.created,
            "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
            "project": self.project,
            "operator": self.operator,
            "blind": self.blind,
            "blind_key": self.blind_key,
            "params": self.params.to_dict(),
            "images": [e.to_dict() for e in self.entries],
        }

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "Session":
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        s = cls(Params.from_dict(d.get("params", {})))
        s.created = d.get("created", s.created)
        s.project = d.get("project", s.project)
        s.operator = d.get("operator", "")
        s.blind = d.get("blind", False)
        s.blind_key = d.get("blind_key", {})
        s.entries = [ImageEntry.from_dict(x) for x in d.get("images", [])]
        return s

    def results_rows(self) -> List[Dict]:
        return [e.row for e in self.entries if e.done and e.row]
