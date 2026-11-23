# 结果合同（`result.json`）

`run.py finish` 写出的 `/app/output/result.json` 是**一次运行的回执**。它有两个不可妥协的性质：

1. **原样保留输入合同**：`/input/case.json` 里的 `output_contract` 的每一个键都必须出现且类型不变；
   只允许把空字符串占位填成本轮**真实产出**的相对路径，不得增删键、不得把 object/list 拍平成标量。
2. **不夸大**：`status` 只有 `ok|partial|needs_human` 三态；没产出的东西不写、产不出的写清原因。

## 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | str | 固定 `"1.0"` |
| `case_id` | str | **必须与输入一致**（取自 `case.json`，缺失时回退 `task.md` 标题 slug） |
| `status` | enum | `ok` = 门禁全过且导出合规；`partial` = 有产物但存在错误级问题或合规失败；`needs_human` = 材料不足/无法解析，需人工提供材料或裁决 |
| `output_contract` | object | **原合同的逐键映射**（key 不变，值为真实产物相对路径） |
| `editable_source` | str | **顶层同值**：可编辑主源路径（`figures/<stem>.svg`；模型文件为 `figure_model.json`） |
| `export_artifact` | object | **顶层同值**：`{format: {path, bytes, sha256, dpi, font_embedded, available, reason_if_unavailable}}`，**只写真产出的文件** |
| `content_map` | object | **顶层同值**：`entities[]/relations[]/containers[]/legend[]` 的图上落实清单（模型 id → 画布上的 `data-entity-id`/`data-relation-id` 等） |
| `compliance_checks` | list | **顶层同值**：每条 `{id, level: error\|warning, status: pass\|fail\|na, where, detail}`；**error 级为 fail 时 `status` 不得为 `ok`**；`compare` 阶段的 `REF_*` 检查追加在此 |
| `exceptions` | list | **顶层同值**：缺后端、缺来源、歧义未决、跳过项、`compare` 无法机器核验的语义部分，逐条给原因与影响面 |
| `reference_comparison` | object | 可选 `compare` 阶段的对照报告（字段与 code 见下节）；未跑 `compare` 时为 `semantic_status="na"` + 提示 |
| `required_fields_present` | object | `required_fields` 里每个键是否存在 |
| `missing_required_fields` | list | 仍为空的必需键（`status` 应相应降级） |
| `artifacts` | list | `[{key,path,bytes,sha256,exists}]`，每个交付件的真实大小与哈希 |
| `sources` | list | `[{path,locator,sha256}]`：实际被引用到的来源单元（来自 `source_inventory.json`） |
| `source_unit_count` / `table_count` | int | 材料规模 |
| `uncertainty` | list | `[{where,issue,action}]`：模型的未决点 + 门禁报出的溯源疑点 |
| `limitations` | list | 明确的能力边界/未完成项（缺格式、缺字体、草稿未复核、未解错误码） |
| `checks` | object | `export_ok`、逐项 `export_checks`、`model_errors`、`model_warnings`、`formats_ok`、`formats_unavailable` |
| `audit` | object | `skill`、`skill_path`、`stage`、`written_utc`、`model_file_used`、`model_sha256`、`output_dir`、`work_dir`、`deterministic` |

## 预览件（inspection previews）

运行契约要求 "Editable Office/slide/diagram outputs should also have real rendered PDF/PNG
previews for inspection"。本 Skill 的映射是**显式**的，不靠目录名暗示：

| 角色 | 路径 | 谁生成 |
|---|---|---|
| 可编辑主源（真身） | `figures/<stem>.svg` | `render` |
| 目标导出件 | `figures/<stem>.{pdf,png,tiff,eps}` | `export`（后端的真实版本记在 `export_report.json.tools`） |
| **供检查的预览** | `preview/<stem>.png` + `preview/README.md` | `export`/`edit` 末尾的 `_write_previews`，逐字节复制该次导出的 PNG |
| 预览的机检结论 | `checks.json` | `compliance.check_artifacts` |

`preview/` 是**同一张图的副本**，不是另一种渲染路径：`preview/<stem>.png` 与该次导出的
`figures/<stem>.png` 字节相同（可用 sha256 核对）。若本次运行没有产出 PNG（后端缺失），
`preview/` 不会出现，且该格式在 `export_report.json` 里是 `unavailable` 并附真实原因——
**不会**用 SVG 改名或写占位文件来充当预览。

## 两层责任：门禁核验 vs 科学判断

`result.json` 只承载**可核验性**那一层，不冒充科学正确性：

| 层 | 谁负责 | 落在哪些字段 |
|---|---|---|
| 机械可核验性（元素→逐字来源、方向语义、图例-数据一致、版式、导出合规） | 本 Skill，可执行、有错误码 | `checks.*`、`artifacts[].sha256`、`sources[]`、以及 `/app/work/figure_issues.json` 的 `E_*` 码 |
| 科学判断（实体身份、该不该入图、来源冲突时以谁为准） | Agent / LLM Judge | `uncertainty[]`、`limitations[]`，上游是 `figure_model.json` 的 `uncertainty[]` 与 `REVIEW_BATCH.json` 的 `must_decide[]`，人工改动记在 `change_log.json` |

因此 `E_QUOTE_NOT_FOUND` / `E_LABEL_NOT_IN_SOURCE` 的含义是"**该断言无来源支持**"，
不是"该论断科学上正确"；反之，门禁全绿也**不**等于科学结论成立。**逐字引文核对是溯源手段，
不替代科学判断**（组织方修订原文：*scientific judgement remains native/LLM Judge, not a
literal quote or export pass*）。材料自相矛盾时写入 `uncertainty` 并降级 `status`，不要硬编。

## 三种状态的判定（冻结）

```
无任何来源单元且无表格                      -> needs_human
有错误级模型/布局问题，或导出检查不过，或核心产物缺失 -> partial（核心产物也缺则 needs_human）
其余                                        -> ok
```

`--strict` 下：`finish` 在 `status != "ok"` 时返回 3（供 CI/自测使用）。

## 与输出合同键的匹配规则

键名到产物的映射是**保守**的（`run.py:_CONTRACT_HINTS`）：只有键名里出现
`svg/pdf/png/tiff/eps/source/model/editable/changelog/export/report/check/result` 这类明确记号时才填，
每个产物按 token 优先匹配一次；**认不出的键保留原值**，不会被猜成某个路径。
若合同点名了 `pdf`/`tiff`/`eps` 而环境缺后端，该键保持空字符串，同时 `status` 降级并把原因写进 `limitations`。

## 示例（示意，非正式案例结果）

```json
{
  "schema_version": "1.0",
  "case_id": "example-relationship-schematic",
  "status": "ok",
  "output_contract": {
    "editable_source": "figure_model.json",
    "figure_svg": "figures/figure.svg",
    "figure_pdf": "figures/figure.pdf",
    "result_json": "result.json"
  },
  "artifacts": [
    {"key": "model", "path": "figure_model.json", "bytes": 8123, "sha256": "…", "exists": true}
  ],
  "sources": [{"path": "materials/demo_pathway.md", "locator": "L8", "sha256": "…"}],
  "uncertainty": [],
  "limitations": [],
  "checks": {"export_ok": true, "model_errors": 0, "model_warnings": 1,
             "formats_ok": ["svg", "pdf", "png"], "formats_unavailable": []},
  "audit": {"skill": "biological-mechanism-pathway-figure", "stage": "finish",
            "written_utc": "2026-01-01T00:00:00Z", "deterministic": true}
}
```

## 平台 7 个原字段：顶层与 `output_contract` 内都有（冻结）

`title`/`output_contract` 的 7 个键现在**同时**出现在两个位置，两处保持同值：

| 位置 | 用途 |
|---|---|
| `result.json` **顶层** | `case_id, status, editable_source, export_artifact, content_map, compliance_checks, exceptions` —— 便于评审/通用读取器直接取值 |
| `result.json.output_contract` **内** | 同 7 键 + 输入合同其余键的逐键映射（值 = 本轮真实产物相对路径） —— 保持与 `/input/case.json` 的 `output_contract` 逐键一致 |

**不得**只写一处或让两处不一致：平台按原字段读结果，输入合同要求"不增删键"。

## `reference_comparison`（`compare` 阶段，实现见 `scripts/reference.py`）

`run.py compare` 产出 `work/reference_comparison.json` 与 `output/reference_comparison.json`，
同一份对象进入 `result.json.reference_comparison`。实现分三支：**原图发现**
（`reference.discover_reference()`，`prepare` 阶段调用并写 `work/reference_index.json`）、
**结构化对照**（原图是 SVG/JSON：标签集合、配色、结构计数、交互词汇表）、
**几何对照**（原图是位图/PDF：只测画布与宽高比，语义不可机检）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `reference_path` | str/null | 实际用于对照的原图相对路径；无原图为 `null` |
| `reference_ext` | str | 原图扩展名（决定走精确对照还是几何对照） |
| `compared_against` | str/null | 本轮用于对照的渲染件文件名（通常 `figures/<stem>.png`） |
| `semantic_status` | enum | `labels_partial` / `verifiable-machine` 类（结构化原图）/ **`unverifiable-machine`**（位图或 PDF）/ **`na`**（无原图） |
| `checks` | list | 下表的检查项；`{id, level, status, detail, …}`，并追加进 `compliance_checks` |
| `exceptions` | list | 无法机器核验的部分（逐条写原因与影响面），并追加进 `exceptions[]` |
| `discovery` | object | `prepare` 的候选发现记录：`{selected, candidates[], skipped[], reason}` |

| check id | 何时产生 | 核验内容（如实照实） |
|---|---|---|
| `REF_LABEL_COVERAGE` | 原图为 SVG/JSON | 模型标签 vs 原图 `<text>` 标签集合；附 `missing_from_reference[]`、`reference_only_labels[]`；`status=warn` 表示有缺项（**不是**失败，是"待人工判断"） |
| `REF_PALETTE` | 原图为 SVG/JSON | 原图声明的 `#rrggbb` 颜色集合（`reference_colours[]`） |
| `REF_STRUCTURE_COUNTS` | 原图为 SVG/JSON | 原图实体数/关系数 vs 模型实体数/关系数 |
| `REF_INTERACTION_VOCABULARY` | 原图为 SVG/JSON | 原图出现的交互类型 vs 模型关系类型；附 `reference_only_types[]` |
| `REF_RASTER_METRICS` | 原图为位图/PDF（或 Pillow 可用时） | 只测画布像素尺寸与宽高比漂移（阈值 0.15），**不证明语义等价** |
| `REFERENCE_COMPARISON` | 无原图 | `status="na"` + 原因（"材料里没有原图"），**不编造对照结论** |

**诚实性红线（必须写进 `exceptions[]`）**：位图/PDF 原图的对照只能证明**几何**；
"某个实体是否存在、某种箭头是否正确、某区室是否放对"属语义，机器无法从像素判断，仍需人工复核。
