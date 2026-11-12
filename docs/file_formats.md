# 文件格式

## 工程文件 `.nqproj`

UTF-8 JSON，可人工阅读与版本管理。

```json
{
  "app": "NisslQuant",
  "version": "1.0.0",
  "created": "2026-11-12 10:00:00",
  "saved": "2026-11-12 12:00:00",
  "project": "示例工程",
  "operator": "",
  "blind": false,
  "blind_key": {},
  "params": { "um_per_px": 0.4975, "alpha": 0.01, "sigma_px": 35.0 },
  "images": [
    {
      "path": "D:/data/S001.jpg",
      "code": "S001",
      "polygon": [[120.0, 300.0], [180.0, 295.0]],
      "light_pts": [[420.0, 310.0]],
      "dark_pts": [[560.0, 330.0]],
      "done": true,
      "row": { "daf_pct": 12.6, "qc_grade": "优" },
      "note": ""
    }
  ]
}
```

注意：`path` 为绝对路径。跨机器迁移时需批量替换，或重新打开图像逐张指定。

## 逐张结果 CSV

每张图像一行，主要列：

| 列 | 含义 |
|---|---|
| `code` | 代号 |
| `roi_px`, `roi_mm2` | ROI 像素数与面积 |
| `dark_px`, `dark_mm2` | 深染像素数与面积 |
| `daf_pct`, `daf_raw_pct` | 剔除后 / 剔除前深染面积比 |
| `focal_pct` | 局灶深染比 |
| `mean_u`, `median_u`, `diffuse_u`, `excess_load` | 连续指标 |
| `n_objects`, `n_rejected` | 保留 / 剔除的连通域数 |
| `ci_low`, `ci_high`, `ci_width` | 95% 置信区间 |
| `light_R`, `dark_R`, `od_span`, `ref_contrast` | 标定参数与参考对比度 |
| `null_mu`, `null_sd`, `threshold_u` | 零分布与阈值 |
| `alpha` | 错误率 |
| `qc_grade`, `qc_score`, `qc_flags` | 质控 |
| `elapsed_s` | 处理耗时 |

## 逐对象 CSV

每个深染连通域一行：`label, area_px, area_um2, x, y, mean_u, max_u, border_frac, aspect, solidity, reject`。
`reject` 为空表示保留，否则为剔除原因。

## 掩膜

`save_overlay` 与 `save_mask_png` 可输出叠加图与二值掩膜（0/255 PNG）。
