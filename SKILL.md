---
name: biological-mechanism-pathway-figure
description: >-
  Generate or edit a source-bound, publication-ready biological mechanism / pathway figure
  (and other scientific schematics, flowcharts or data-driven charts) from real case
  materials, and deliver a layered editable SVG master plus journal-compliant PDF/PNG/TIFF/EPS
  exports. Enforces mechanism semantics: entity kinds and gene-vs-protein naming, typed
  relations (activation / inhibition / binding / modification / transport / transcription /
  translation / feedback), compartment and membrane placement of transmembrane receptors,
  upstream-downstream pathway direction and explicit feedback loops, evidence-strength line
  widths, and legend-to-data encoding consistency - with per-element provenance, an optional
  comparison against the paper's original figure, and a source-preserving change log. Use when
  a mechanism or pathway figure must be traceable to its source materials and remain editable
  afterwards, not merely look pretty.
---

# 生物机制图与通路图生成与编辑（biological-mechanism-pathway-figure）

把「机制/通路材料」变成「可继续编辑的图稿」再变成「能投出去的导出件」，并且**让每一步都能被独立复核**。

本 Skill 不套模板、不生成插画。它的核心主张是：**图由一份带引文溯源的实体—关系—数据模型驱动**。
模型是可编辑源文件的真身，SVG/PDF/PNG 只是它的投影；改数据或改标签后重跑即可同步，不需要重画。

机制图不是装饰性插图，而是一份**可以被逐条质疑的机制陈述**：图上的每一个实体、每一个箭头、
每一处区室定位都带有语义。因此本 Skill 在通用溯源之外，额外强制一整组**机制语义门禁**：
基因与蛋白不混用、关系类型 → 箭头/线型冻结、跨膜受体必须落在膜带上、
上下游方向单调、环必须显式标 `feedback`、证据强度决定线宽、图例编码与图面/数据三方一致。

## 什么时候用

- 给定机制文字 / 通路描述 / 数据表 / PDF，要产出**机制图、通路图、关系示意图、流程图或数据驱动图表**；
- 材料里出现**基因、蛋白、复合物、修饰位点、代谢物、细胞类型、亚细胞区室、跨膜受体**，
  需要把它们画成有类型的关系网络，而不是一圈连线的节点；
- 需要区分**激活 / 抑制 / 结合 / 修饰 / 转运 / 转录 / 翻译 / 反馈**这些语义不同的相互作用；
- 需要表达**颜色、线宽、节点大小分别编码了什么数据**（表达量、显著性、置信度、证据强度），
  且图例必须与图面、数据三方自洽；
- 已有的图需要**保留来源地修改**（改标签、改配色、改某个数据点），并要留下改动记录；
- 要求「可编辑源文件 + 目标期刊合规导出件」同时交付，且能被审稿人逐元素追溯。

## 不适用（本 Skill 明确不负责）

- 统计检验与统计方法选择、统计分析结论（只忠实呈现已给数据的映射）；
- 实验方案设计与实验逻辑；
- 论文正文、文献综述、引言与版式美化写作；
- 海报/封面版式设计、艺术插画、图像美化、照片级渲染与风格迁移；
- 科研结论的科学裁决本身：本 Skill 保证**可核验性**，不代替领域专家判断材料是否正确
  （组织方修订原文：*scientific judgement remains native/LLM Judge, not a literal quote or export pass*）。

## 快速开始（四步 + 一次裁决，另有可选对照）

```bash
export SKILL=/skills/weekly-skill          # 平台安装位置

# 1) 盘点材料：清单 / 来源单元 / 草稿模型 / 待裁决项
python "$SKILL/scripts/run.py" prepare \
    --input /input --work /app/work --output /app/output

# 2) Agent 读 /app/work/REVIEW_BATCH.json 与 figure_model.draft.json，
#    依据材料逐项修订（机制判断只在这一步发生），写出 /app/work/figure_model.json
python "$SKILL/scripts/run.py" render --work /app/work --output /app/output

# 3) 真实导出 + 期刊合规检查
python "$SKILL/scripts/run.py" export --work /app/work --output /app/output \
    --journal nature --dpi 600

# 4) 可选但推荐：与论文原图对照（材料里有原图时；无原图时输出 na，不算失败）
python "$SKILL/scripts/run.py" compare --input /input --work /app/work --output /app/output

# 5) 汇总（result.json 保留原 output_contract 全部字段）
python "$SKILL/scripts/run.py" finish --work /app/work --output /app/output
```

可选：来源保留式编辑（改标签/配色/数据点后重绘重导，并写 `change_log.json`）：

```bash
python "$SKILL/scripts/run.py" edit --work /app/work --output /app/output \
    --ops /app/work/edit_ops.json
```

`prepare` 之后**不要**直接 `render` 就交货。`prepare` 只给草稿；草稿的每个不确定判断都写在
`REVIEW_BATCH.json` 的 `must_decide` 与 `figure_model.draft.json` 的 `uncertainty` 里，必须由 Agent
用材料裁决。直接用草稿渲染时 `render` 会报 `E_MODEL_NOT_REVISED`（exit 4），
`finish` 会把 `status` 降级并写入 limitations。

### Agent 在 `prepare` 与 `render` 之间必须裁决的机制清单

草稿是**关键词扫描的骨架，不是科研模型**（实测：机制类案例会产出数十个 `Core`/`Drawing`/色值一类的伪实体）。
以下七项必须由 Agent 依据材料裁决；完整判据见 `references/mechanism_semantics.md` §8。

| # | 必须裁决 | 判据（摘要） | 典型错误 |
|---|---|---|---|
| 1 | **实体类型** | `entities[].kind` 取机制枚举：`gene/protein/complex/organelle/cell_type/metabolite/modification_site/stimulus/drug/process/compound/…` | 把版式说明与图注名词刮成伪实体；实体 kind 乱标 |
| 2 | **基因 vs 蛋白** | `gene` = 斜体基因符号（`HIF1A`），不得带 `-P`/`p-`/`pSer` 修饰后缀；`protein` = 蛋白名（`HIF-1alpha`、`PDH (Ser293-P)`）；旧名/物种前缀进 `attributes.synonyms` | 把基因符号当蛋白、或给基因加修饰后缀 ⇒ `E_GENE_PROTEIN_CONFUSION` |
| 3 | **关系类型** | §4 冻结样式表：`activation`(实线箭头) / `inhibition`(实线平头) / `binding`(无箭头实线) / `modification`(虚线箭头) / `transport`(跨边界实线箭头) / `transcription` / `translation` / `feedback`(虚线) | 把磷酸化画成激活；把结合画成箭头 ⇒ `E_INTERACTION_STYLE_MISMATCH` |
| 4 | **区室与膜** | `containers[].kind ∈ compartment/membrane/cell/group`；`entities[].membrane_role`；`transmembrane`/`membrane_anchored` 的 container **必须**是 `membrane` 且画在膜带上，胞外域朝外侧、胞内域朝内侧 | 跨膜受体画进 `cytosol`/`nucleus` 内部 ⇒ `E_MEMBRANE_PLACEMENT` |
| 5 | **方向与环** | `figure.flow.orientation` + `figure.flow.ranks`；非 `feedback` 边必须 `rank[to] > rank[from]`；有向环必须显式标 `feedback`；`extracellular→membrane→cytosol→nucleus` 链 rank 单调递增 | 上下游颠倒、负反馈画成正向链 ⇒ `E_FLOW_DIRECTION` |
| 6 | **证据强度** | `relations[].evidence = {strength: high/medium/low, kind: direct/indirect/inferred, note, source}`；线宽冻结 `1.4/1.0/0.6 pt`；材料没给就不填、记 `uncertainty` | 凭空填 `high`；把 `inferred` 画成 `direct` 同强度 |
| 7 | **图例编码** | `legend[].encoding = {channel: color/line_width/node_size/line_style, field, unit, mapping[]}`；`mapping` 取值集合 = 图面真实视觉取值 = 数据取值（三方逐一对应） | 图例色 ≠ 图面色；线宽档位与 `evidence` 对不上 ⇒ `E_LEGEND_DATA_MISMATCH` |

`REVIEW_BATCH.json` 的 `must_decide[]` 会把这些问题连同证据与默认值列出来。
裁决结果写回 `/app/work/figure_model.json`；不确定的写 `uncertainty[]`，**不要**为拿到 `ok` 删掉诚实的不确定项。

## 输入

| 来源 | 说明 |
|---|---|
| `/input/case.json` | 案例合同：`case_id`、`output_contract`、`required_fields`、`figure`（id/kind/canvas）等。**原样保留，不增删键** |
| `/input/task.md` | 任务说明（只作 `role=metadata`，不得当科学正文） |
| `/input/**` 其它文件 | 真实材料：`.md/.txt/.csv/.tsv/.json/.tex/.pdf/.docx/.pptx/图片` 等 |

材料不足时：`prepare` 仍会写出一份 `status=needs_human` 的 `result.json` 并返回 3，**不会**用领域常识补造数据。
PDF 解析按**实际 PDF** 读取，不使用预抽取答案层；来源标签不可信时以文件内容为准。

## 输出

`/app/output/`（正式交付；全部为本轮真实产出）

| 文件 | 作用 |
|---|---|
| `figure_model.json` | **可继续编辑的源文件**（实体/关系/区室/图例/数据/溯源，见 `schemas/figure_model.schema.json`） |
| `figures/<stem>.svg` | **主源文件**：7 个命名图层、文字为真 `<text>`、每个元素带 `id` 与 `data-prov` |
| `figures/<stem>.pdf` `.png` `.tiff` `.eps` | 目标导出件（真实生成；不可用的格式如实标 `unavailable`） |
| `preview/<stem>.png` (+`preview/README.md`) | **供人工检查的渲染预览**：运行契约要求 "real rendered PDF/PNG previews for inspection"，导出件在 `figures/`，这里再放一份同名 PNG 副本并以 `preview/README.md` 说明 |
| `source_map.json` | 每个图面元素 → 来源 `{path,locator,quote}` 或显式 `unsupported` |
| `change_log.json` | 来源保留式编辑的 before/after、理由与来源引用 |
| `export_report.json` / `checks.json` | 导出的真实后端、版本、DPI、字体与逐项合规检查 |
| `reference_comparison.json` | **可选**：与论文原图的对照报告（`compare` 阶段产出；无原图时为 `semantic_status="na"`） |
| `result.json` | **一次运行的完整回执**：含原 `output_contract` 全字段 + `case_id`、`status`、`editable_source`、`export_artifact`、`content_map`、`compliance_checks`、`exceptions`、`reference_comparison`、`sources`、`uncertainty`、`limitations`、`audit` |

`result.json` 的必需键与字段语义见 `references/result_contract.md`（对应冻结接口 `work/CONTRACT.md` §4（`:110-130`））。
平台的 **7 个原字段**（`case_id, status, editable_source, export_artifact, content_map, compliance_checks, exceptions`）
在 `result.json` **顶层与 `output_contract` 内都出现**，两处保持同值——顶层便于通用读取，`output_contract` 内保持与输入合同的逐键一致。

`/app/work/`（中间证据，不必提交）：`case_manifest.json`、`source_inventory.json`、
`figure_model.draft.json`、`REVIEW_BATCH.json`、`figure_model.json`、`figure_issues.json`、
`layout.json`、`environment.json`、`edit_ops.json`。

## 可选阶段：与论文原图对照（`compare`）

```bash
python "$SKILL/scripts/run.py" compare --input /input --work /app/work --output /app/output \
    [--reference materials/figure03.png]
```

**可选但推荐**：当案例材料里带有论文原图时，把本轮渲染结果与原图做**诚实的机器对照**。
它**不是**门禁：无原图时报告 `semantic_status="na"` 并写明原因，`compare` 不失败、不影响 `status`。

| 情形 | 行为 |
|---|---|
| `prepare` 自动发现候选原图 | 文件名匹配 `figure03/figure3/fig03/fig3/figure/reference/original`，结果写 `work/reference_index.json`，含**为什么选它**与**跳过了哪些近似文件**；有原图时 `prepare` 不再因"无文本材料"判 `needs_human` |
| 原图是 **SVG / JSON**（可编辑 / 结构化） | **精确内容对照**：模型标签 vs 原图 `<text>` 标签集合（`REF_LABEL_COVERAGE`，含 `missing_from_reference` / `reference_only_labels`）、配色集合（`REF_PALETTE`）、结构计数（`REF_STRUCTURE_COUNTS`）、交互词汇表（`REF_INTERACTION_VOCABULARY`） |
| 原图是**位图 / PDF** | 只测画布几何与宽高比漂移（`REF_RASTER_METRICS`），并把 `semantic_status` 明确写成 `unverifiable-machine`，同时在 `exceptions[]` 写明「像素无法证明语义等价（哪个实体 / 哪种箭头 / 哪个区室），仍需人来判断」 |
| 材料里**没有**原图 | `semantic_status: "na"` + 原因；**绝不编造对照结论** |

产物：`work/reference_comparison.json` **与** `output/reference_comparison.json`，
并进入 `result.json.reference_comparison`；其中 `checks[]` 会按 `{id, level, status, where, detail}`
追加进 `result.json.compliance_checks`，异常项进入 `exceptions[]`。字段表见
`references/result_contract.md` §「reference_comparison」。

**诚实性红线**：位图对照**只证明几何**，不证明语义；本阶段绝不会把"像素像"写成"机制正确"。

## 五道门禁（判据可执行，不通过就不算完成）

1. **溯源门禁** — 每个实体/关系/图例项/标题/子图说明都必须有 `source{path,locator,quote}`，且
   `quote` 能在 `source_inventory` 的对应单元里逐字找到（空白归一化）。错误码
   `E_PROVENANCE_MISSING / E_QUOTE_NOT_FOUND / E_LABEL_NOT_IN_SOURCE / E_NUMBER_NOT_IN_SOURCE`
   —— 这是对「图里出现来源中不存在的基因名、浓度、时间点或单位」的直接拦截。
   规则见 `references/extraction_rules.md`（逐字引文、**禁止**模糊匹配）。
2. **机制语义门禁（本题新增，硬拦截）** — 词汇与样式表冻结在
   `references/mechanism_semantics.md`（对应 `work/CONTRACT.md` §3（`:33-109`））：
   - `E_GENE_PROTEIN_CONFUSION`：`kind=gene` 的 label 带蛋白修饰后缀、基因/蛋白书写混用；
   - `E_MEMBRANE_PLACEMENT`：`transmembrane`/`membrane_anchored` 的实体不在 `membrane` 容器内、
     或跨膜受体被画进区室内部、膜内外域颠倒；
   - `E_COMPARTMENT_MISMATCH`：`binding` 两端不在同一区室；
   - `E_INTERACTION_STYLE_MISMATCH`：实际渲染的 `(arrow, stroke)` 与冻结样式表不符，
     或某关系类型出现在图面上而图例缺对应条目；
   - `E_FLOW_DIRECTION`：非 `feedback` 边违反 `rank[to] > rank[from]`、
     非 `feedback` 边构成有向环、或受体→胞内→核内链 rank 非单调。
3. **方向与结构门禁** — 关系必须有 `type` 与 `direction`，且与来源句中的动词线索一致：
   `E_DIRECTION_UNSUPPORTED`（抑制画成激活、上游下游颠倒）、
   `E_CONTAINER_CYCLE`（包含关系成环）、`E_ORPHAN_RELATION`（悬空端点）、`E_DANGLING_REF`、`E_DUP_ID`。
   绘图语法固定：激活=实线箭头，抑制=实线平头（⊥），结合=None 实线，修饰=虚线箭头，
   转运=跨边界箭头，反馈=虚线，包含=外框包裹，并列=同层不连线。
4. **图例—数据门禁** — 图例分类数 = 数据分类数，颜色/标记与数据系列一一对应，数值列必须有单位：
   `E_LEGEND_DATA_MISMATCH / E_UNIT_MISSING`。机制图额外要求 `legend[].encoding` 的四通道
   （`color/line_width/node_size/line_style`）满足**三方一致**：`mapping` 取值集合 = 图面真实视觉取值
   = 数据取值集合（多一项少一项都拦截）。数据表是唯一权威，任务书或旧图注与表冲突时以表为准并记入 `uncertainty`。
5. **版式与导出门禁** — 版式：节点不重叠、不出画布、文字不溢出、层级不倒退
   （`E_NODE_OVERLAP / E_OUT_OF_CANVAS / E_TEXT_OVERFLOW_EST / E_LEVEL_REGRESSION`）；
   导出：真实检查分层数、可编辑文字、字体内嵌、位图 DPI、最小线宽、色彩空间、文件可解析性、
   PDF 文本可抽取与**光栅是否真的画出标签**（`raster_pixel_ink`）。**17 项**产物侧检查 id 清单见
   `references/export_and_compliance.md` §2（`format_coverage` … `raster_pixel_ink`），
   另有 §2.2 的产物侧机制复核（`E_INTERACTION_STYLE_MISMATCH` 等）与 `compare` 的 `REF_*` 条目；
   任一 `level=error` 为假即不通过。

**硬性升级规则**：原为警告的 `E_BAR_BASELINE_TRUNCATED`（柱状图截断基线）在流水线层被**升级为错误**——
"能画"不等于"可以当作投稿图"。

## 异常处理（明确可预期的边界）

| 情况 | 行为 |
|---|---|
| 输入目录不存在 / 不可读 | `exit 3`，`result.json` 写 `needs_human`，不崩 |
| 材料无法解析出任何文本或表格 | `prepare exit 3`，草稿为空 + 写明缺什么 |
| PDF 只有扫描图像层 / 加密 / 不支持滤波 | 记 warning 并标注覆盖度，绝不猜测内容；引用前须核对 |
| 模型 JSON 非法 / 路径越界 | `exit 2`，stdout JSON 带 `error` |
| 模型有错误级溯源/机制语义/方向/图例问题 | `render exit 4`，仍写 `figure_issues.json` 与已渲染的部分产物 |
| **基因 vs 蛋白判不出来**（材料只给符号、无物种/无修饰信息） | 不猜 kind：在 `uncertainty[]` 写明"该符号的分子身份未定"，`status` 降级；门禁只在形式上可证伪时拦截 |
| **输入缺方向信息**（只列了实体、没写上下游） | 不编方向：实体全部标 `association` 或留空方向线索，写 `uncertainty[]`；不要用 `activation` 默认填充 |
| **实体名歧义**（同名基因与蛋白、旧名/同义名） | 各写法分别建实体并保留 label 与 `source`，双方 `synonyms`/`normalized_symbol` 留痕，由 Agent 裁决定夺 |
| **输入数据与图示矛盾** | 以**数据表**为准，冲突写 `uncertainty[]` 并降级 `status`；不二选一硬编 |
| **图面元素过多导致不可读** | 依赖版式门禁（重叠/出画布/文字溢出）+ `compaction_scale`；仍不可读时拆分子图（`panels`）或记 `limitations[]` |
| 导出后端缺失（如无 matplotlib/Pillow） | 该格式 `status="unavailable"` + 真实原因；**绝不伪造文件**，其余格式照常产出 |
| 目标机缺 CJK 字体 | 报告里记 font_stack 与警告；SVG 主源仍是可编辑 `<text>`；PDF/PNG 可能缺字，写进 `limitations[]` |
| PDF 有未内嵌字体 / 位图 DPI 不足 | `export exit 4`，`checks.json` 指出具体项 |
| 编辑操作非法（未知 op、目标不存在、重复 id） | `edit exit 2`，不产出半成品改动记录 |
| 材料里**没有**论文原图 | `compare` 输出 `semantic_status="na"` + 原因，exit 0，**不编造对照结论**、不影响 `status` |
| 原图是位图/PDF（语义不可机检） | 只报几何指标，`semantic_status="unverifiable-machine"`，并在 `exceptions[]` 写明仍需人工判断 |
| 候选原图有多个近似文件 | `reference_index.json` 记下**选中的理由**与被跳过的文件；不要静默挑一个 |
| 重复运行 | 布局与渲染确定性：同输入 → 同字节 SVG（`--work` 会复用已存在的模型） |

**不能只看退出码**：每个阶段 stdout 是一个 JSON，须继续读其中的 `status` 与 `errors`。

## 预算与限制

| 项 | 限制 |
|---|---|
| 模型请求 | **64 次 / 案例**（含 reasoning） |
| 单次响应 | **16384 tokens** |
| 墙钟 | **900 秒** |
| 运行规模 | 3 个固定案例 × 3 次重复（平台提供，参赛者不自带案例） |
| Skill 资源 | **≤50 个 UTF-8 文本文件**；**单文件 ≤500KB**；**合计 ≤2MB**；**无 symlink** |
| 网络 | 不联网；只用 Python 3 标准库，第三方库按可用性探测 |
| 运行时产物 | 可为二进制（PNG/PDF/TIFF/EPS），保留在 `/app/output`，不要求 JSON 合法 |

早期保存诚实的部分交付物，再增量改进：`status=partial` 必须能在 `exceptions[]` 里说明限制。

## 目录结构

```
SKILL.md                        本文件
README.md                       安装、依赖、字体、参数、预算、边界
manifest.json                   资源清单与版本
GITHUB_URL.txt                  公开作品链接
scripts/common.py               共享件（IO/哈希/单位/依赖探测/退出码）
scripts/ingest.py               材料发现、来源单元与表格抽取、REVIEW_BATCH
scripts/model.py                草稿模型、溯源/方向/图例门禁、保守 auto_fix
scripts/mech.py                 机制语义判定（实体类型、基因vs蛋白、关系类型、区室/膜、方向/环、证据、图例编码）
scripts/layout.py               确定性分层布局（区室/膜带/rank 分层/反馈弧路由）
scripts/render_svg.py           分层可编辑 SVG 渲染
scripts/export.py               PDF/PNG/TIFF/EPS 真实导出 + 期刊预设
scripts/compliance.py           导出合规检查 + 产物侧机制复核
scripts/reference.py            论文原图发现与对照（可选 compare 阶段）
scripts/run.py                  单入口编排（prepare/render/export/edit/compare/finish）
scripts/selftest.py             自测：正例 + 注入缺陷
schemas/                        figure_model / edit_ops / review_batch 合同（机制本体随 `model.py`/`mech.py` 的冻结枚举同步）
references/mechanism_semantics.md  机制/通路语义合同（本题核心）
references/extraction_rules.md     抽取与逐字引文规则
references/layout_and_svg.md       布局与 SVG 合同（区室/膜/方向）
references/export_and_compliance.md 导出与合规检查 id 清单（17 项 + 产物侧机制复核 + REF_*）
references/result_contract.md      结果合同（平台原字段 + reference_comparison）
references/implementation_status.md 本版实测核验表（哪条能力已被实测，哪些 UNVERIFIED）
examples/                       最小调用示例（**示例**，非正式案例答案）
```

## 自测

```bash
python "$SKILL/scripts/selftest.py"        # 退出码 0 才算通过（含真实渲染与导出，非跳过）
```

结构自检（本地工具，平台外）：`py -3 _shared/tools/validate_skill_submission.py <submission-dir>`。

## 门禁做什么、不做什么（两层，别混）

**第一层——机械可核验性（本 Skill 负责，可执行、有错误码）**：图里每个元素是否指得回一条逐字来源、
关系类型与箭头/线型是否符合冻结样式表、跨膜受体是否落在膜带上、方向与环是否单调/显式、
图例与数据是否逐项对应、版式是否自洽、导出件是否满足期刊参数。
这一层只能证明"**没有无依据的断言**"，**不能**证明科学结论正确。

**第二层——科学判断（Agent / LLM Judge 负责，不入本 Skill 的错误码）**：实体身份是否成立、
该不该把这个过程画进机制链条、来源之间自相矛盾时以哪个为准。
这一层按如下路径**留痕**，而不是被门禁替代：

| 判断发生在 | 记录在哪 | 谁可复核 |
|---|---|---|
| `prepare` 之后 | `REVIEW_BATCH.json` 的 `must_decide[]`（问题 + 依据 + 默认值，≤12 条） | 任何人读该文件 |
| `draft_model` 的每个猜测 | `figure_model.draft.json` 的 `uncertainty[]` | 同上 |
| Agent 的最终裁决 | Agent 自己写的 `figure_model.json`（它的 `uncertainty[]` 与每个元素的 `source.kind: explicit\|derived`） | `validate_model` 会重新核对引文 |
| Agent 对最终结果的不确定性 | `result.json` 的 `uncertainty[]` / `limitations[]` | 任何人读该文件 |
| 人工确认的修改 | `change_log.json` 的 `entries[]`（op / before / after / reason / source_refs） | 逐条 diff |

因此 `E_QUOTE_NOT_FOUND`、`E_LABEL_NOT_IN_SOURCE`、`E_GENE_PROTEIN_CONFUSION` 这类**阻断**的含义是
"这个断言在形式上无法核验 / 与冻结语法冲突"，**不是**"这个论断科学上正确"。

**第一层能拦什么、不能拦什么（别把主张说大）**：

| | 例子 | 门禁 |
|---|---|---|
| **能拦**：无来源支持的断言 | 图里出现材料中没有的 `TRPM6`、凭空的时间点/浓度/单位 | `E_LABEL_NOT_IN_SOURCE` / `E_NUMBER_NOT_IN_SOURCE` / `E_UNIT_MISSING` / `E_QUOTE_NOT_FOUND` |
| **能拦**：与来源语义相反的方向 | 来源写"抑制"却画成激活 | `E_DIRECTION_UNSUPPORTED` / `E_FLOW_DIRECTION` |
| **能拦**：机制语法冲突 | 基因带蛋白修饰后缀；跨膜受体画进胞内；结合用箭头；环未标 `feedback` | `E_GENE_PROTEIN_CONFUSION` / `E_MEMBRANE_PLACEMENT` / `E_INTERACTION_STYLE_MISMATCH` / `E_COMPARTMENT_MISMATCH` |
| **能拦**：图与所依据数据不一致 | 图例分类数 ≠ 数据分类数；线宽档位与证据强度对不上；柱状图截断基线 | `E_LEGEND_DATA_MISMATCH` / `E_BAR_BASELINE_TRUNCATED` |
| **能拦**：该裁决却没裁决 | Agent 未修订草稿就直接渲染 | `E_MODEL_NOT_REVISED` |
| **不能拦**：有逐字来源但**科学上不该入图**的实体 | 材料里确实写着、但把它画进机制链条是错的 | 属第二层，由 Agent/评审负责；Skill 只能把该判断的留痕与不确定项摆出来 |

### 两条硬门禁（会阻止 `status=ok`，不是提示）

- **`E_MODEL_NOT_REVISED`**：`render` 回退到 `figure_model.draft.json` 时必然产生 ⇒ 该次运行不可能以
  `status=ok` 结束（`render` exit 4，`finish` 降级，`finish --strict` exit 3）。
- **`E_BAR_BASELINE_TRUNCATED`**：柱状图几何与"值域必须含 0"相伴出现非零基线时产生。layout 侧原为
  警告，本 Skill 在流水线层把它**升级为错误**——因为"能画"不等于"可以当作投稿图"。

## 实现状态与诚实性

- **本版每条能力的实测状态**（哪条已落地、用哪条命令跑的、退出码是什么）见
  `references/implementation_status.md`；合同要求但本版实测未达标的能力在那里如实标为
  **UNVERIFIED / 未实现**，不在本文件里冒充已实现。
- 不联网；只用 Python 3 标准库（第三方按可用性探测，缺失如实记录）。
- 科学判断由 Agent/评审负责：本 Skill 保证**可核验性**（每个图面元素都能指回来源、每处方向都有动词依据），
  不代替领域专家裁决材料本身的错误；材料自相矛盾时写入 `uncertainty` 并降级状态，而不是二选一硬编。
- 不虚构评测分数、不虚构工具版本、不把未生成的产物写进 `result.json`。
