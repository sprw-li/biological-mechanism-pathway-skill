# biological-mechanism-pathway-figure — 安装与使用说明

**生物机制图与通路图**（以及关系示意图 / 流程图 / 数据驱动图表）的
**来源可溯 + 机制语义正确 + 可编辑 + 合规导出**流水线。

本文件讲安装、依赖、字体、参数、预算、边界与维护；接口与五道门禁见 `SKILL.md`，
机制语义（实体类型、关系样式表、区室/膜、方向与环、证据强度、图例编码）见
`references/mechanism_semantics.md`，字段合同见 `references/result_contract.md`。

## 1. 安装

平台会把本目录安装到 `/skills/weekly-skill`。本地验证时把 `SKILL` 指向本目录即可：

```bash
export SKILL=/skills/weekly-skill

python "$SKILL/scripts/run.py" prepare --input /input --work /app/work --output /app/output
# Agent 依材料修订 /app/work/figure_model.json（草稿在 figure_model.draft.json）
python "$SKILL/scripts/run.py" render  --work /app/work --output /app/output
python "$SKILL/scripts/run.py" export  --work /app/work --output /app/output --journal nature
python "$SKILL/scripts/run.py" compare --input /input --work /app/work --output /app/output   # 可选但推荐
python "$SKILL/scripts/run.py" finish  --work /app/work --output /app/output
```

子命令、参数与退出码：

| 子命令 | 关键参数 | 退出码 |
|---|---|---|
| `prepare` | `--input` `--work` `--output` | 0 就绪 / 2 输入或 JSON 错误 / 3 无可解析材料（`needs_human`） |
| `render` | 同上 + `--model` | 0 通过门禁 / 2 模型缺失 / 3 环境 / 4 存在错误级问题 |
| `export` | 同上 + `--journal` `--dpi` `--width-mm` `--formats` | 0 合规 / 2 配置 / 3 后端缺失 / 4 合规检查失败 |
| `edit` | 同上 + `--ops` | 0 已重绘重导 / 2 ops 非法 / 4 编辑后引入不可核验元素 |
| `compare` | 同上 + `--reference`（可选，显式指定原图） | 0 已出对照报告（无原图时 `semantic_status="na"`）/ 2 配置 |
| `finish` | 同上 + `--strict` | 0 汇总 / 2 输入错误 / 3 `--strict` 下非 `ok` |

每个子命令 **stdout 只有一个 JSON**，人类可读日志走 stderr；不要只看退出码。
`prepare` 与 `render` 之间必须插入 Agent 的机制裁决（`SKILL.md` 的七项清单 / `references/mechanism_semantics.md` §8）。

## 2. 最小可跑示例

`examples/` 是一组**示意输入**（明确标注「示例，非组织方正式案例」），用于验证安装是否成功：

```bash
WORK=$(mktemp -d); OUT=$(mktemp -d)
python "$SKILL/scripts/run.py" prepare --input "$SKILL/examples" --work "$WORK" --output "$OUT"
cp "$SKILL/examples/expected_model.json" "$WORK/figure_model.json"
python "$SKILL/scripts/run.py" render --work "$WORK" --output "$OUT"
python "$SKILL/scripts/run.py" export --work "$WORK" --output "$OUT" --journal generic --dpi 300
python "$SKILL/scripts/run.py" finish --work "$WORK" --output "$OUT"
```

示例的 `figure.id` 与材料文件名都带 `example-` 前缀，**不与组织方任何正式案例（如 `figure03`）重名**，
避免把示意图误当正式案例结果。

## 3. 依赖

**核心路径只依赖 Python 3.8+ 标准库**（`json`/`csv`/`xml`/`hashlib`/`zipfile`/`re`/`math`）。
以下第三方库**按可用性探测**，缺失时对应格式标 `unavailable` 并写明原因，绝不用占位文件冒充：

| 库 | 用途 | 缺失时 |
|---|---|---|
| `matplotlib` | PDF/EPS/PNG 矢量与位图导出（`pdf.fonttype=42` 保证字体内嵌且可编辑） | PDF/EPS 标 `unavailable` |
| `Pillow` (PIL) | TIFF/PNG、DPI 与色彩空间元数据、栅格校验 | TIFF 标 `unavailable` |
| `pypdf` | 打开 PDF、抽取文本、检查字体是否内嵌 | PDF 检查降级为 `warn` 并注明未能验证 |
| `lxml` | 可选加速；未安装时用标准库 `xml.etree` | 无影响 |

外部命令（可选，全部走 `subprocess` 参数数组、`shell=False`）：
`rsvg-convert` / `inkscape`（优先用它把主 SVG 直接栅格化，保真度最高）、`pdffonts` / `pdfinfo`（交叉核对 PDF）、
`gs`（PDF→预览）。探测结果写入 `/app/work/environment.json` 与 `export_report.json.tools`。

安装示例（离线环境请用平台预置，不要联网）：

```bash
pip install matplotlib pillow pypdf        # 仅本地开发需要
```

## 4. 字体

- SVG 里文字是**真 `<text>`**，`font-family` 用**栈式回退**（默认 `DejaVu Sans, Liberation Sans, Arial`），
  按 `figure.style.font_stack` 覆盖，不内嵌二进制字体文件（换字体=改一个属性，不用重画）。
- **基因符号必须斜体**：`kind=gene` 的 label 渲染为 italic（机制图的公认书写规范）；`kind=protein` 用正体。
  字体栈里请确认有可供斜体渲染的字形（DejaVu/Liberation 均有）。
- PDF 走 matplotlib 时设 `pdf.fonttype=42`（TrueType 内嵌）与 `ps.fonttype=42`，避免期刊侧缺字。
  `checks.json` 的 `pdf_fonts_embedded` 会逐个 `/Font` 条目核对 `/FontFile*`。
- 中文字形需要系统里有覆盖 CJK 的字体（如 `Noto Sans CJK` / `Source Han Sans`）。没有时：
  PDF 可能出现豆腐块，`pdf_text_extractable` 仍可通过（文本层是对的），但请在 `limitations` 里写明；
  建议把 `font_stack` 显式写成环境里实际存在的字体名，例如 `["Source Han Sans CN", "DejaVu Sans"]`。
- 字号以 **pt** 存储（`figure.style.font_sizes_pt`），渲染时按画布单位换算；最小字号不要低于 5 pt。

## 5. 画布、单位与分辨率

- 画布尺寸用 **mm**（`figure.canvas.width_mm/height_mm`），因为期刊按毫米栏宽排版：
  `--journal nature` 默认单栏 89 mm、双栏 183 mm（`--width-mm` 可覆盖）。
- SVG 用户单位约定：**1 用户单位 = 1 mm × 画布缩放**，具体换算写在 `references/layout_and_svg.md`；
  用 `width="…mm" height="…mm" viewBox="…"` 让 SVG 在 Inkscape/Illustrator 里打开即为真实物理尺寸。
- 位图 DPI：`--dpi` 覆盖预设（彩色照片 300、线条图 600–1200 常见）。`checks.json` 的 `raster_dpi`
  同时核对**元数据 DPI**与**像素尺寸 ÷ 物理尺寸**，只对上一个不算过。
- 最小线宽：`line_width_min` 按预设（Nature 系建议 ≥0.25 pt 描边、≥0.5 pt 数据线），单位统一 pt。
- **机制图线宽有第二重语义**：`relations[].evidence.strength` 映射线宽 `1.4/1.0/0.6 pt`
  （`references/mechanism_semantics.md` §6）。渲染器取两者中更严格的一侧，且该通道必须出现在图例里。

## 6. 机制图专用口径（与 `references/mechanism_semantics.md` 一致）

| 主题 | 要点 |
|---|---|
| `figure.kind` | 机制/通路图用 `mechanism_pathway`；机制 + 数据混排用 `mixed` |
| 实体类型 | `gene/protein/complex/organelle/cell_type/metabolite/modification_site/stimulus/drug/…` |
| 基因 vs 蛋白 | `gene` = 斜体符号且不得带 `-P`/`p-`/`pSer` 后缀；`protein` = 蛋白名可带修饰；旧名进 `attributes.synonyms` |
| 区室与膜 | `containers[].kind ∈ compartment/membrane/cell/group`；`entities[].membrane_role` 与 `container` 必须自洽 |
| 关系语义 | 8 种机制关系各有冻结的箭头/线型（§4 表），不得自由发挥 |
| 方向与环 | `figure.flow.orientation` + `ranks`；非 `feedback` 边 rank 必须递增；环必须显式标 `feedback` |
| 证据强度 | 材料给出才填；`high/medium/low` → `1.4/1.0/0.6 pt`；`inferred` 必须标注为推断 |
| 图例编码 | `legend[].encoding` 四通道 + `mapping`；图例取值 = 图面视觉取值 = 数据取值（三方一致） |

## 7. 与论文原图对照（可选但推荐的 `compare` 阶段）

材料里带论文原图时（`figure03` / `figure` / `reference` / `original` 等命名），
跑一次 `compare` 得到**诚实的机器对照**：

```bash
python "$SKILL/scripts/run.py" compare --input /input --work /app/work --output /app/output
# 或显式指定：--reference materials/figure03.png
```

| 原图形态 | 能机器核验的 | 报告里的 code |
|---|---|---|
| SVG / JSON（可编辑 / 结构化） | 标签集合、配色集合、结构计数、交互词汇表 | `REF_LABEL_COVERAGE` / `REF_PALETTE` / `REF_STRUCTURE_COUNTS` / `REF_INTERACTION_VOCABULARY` |
| 位图 / PDF | 只测画布几何与宽高比漂移；`semantic_status="unverifiable-machine"` | `REF_RASTER_METRICS` |
| 没有原图 | 无；`semantic_status="na"` + 原因，**不编造对照** | — |

`prepare` 会先把候选原图记进 `work/reference_index.json`（选中理由 + 被跳过的近似文件），
避免静默挑一个。产物 `work/reference_comparison.json` 与 `output/reference_comparison.json` 同时生成，
并进入 `result.json.reference_comparison`；字段表见 `references/result_contract.md`。

**位图对照只证明几何，不证明语义**——报告与 `exceptions[]` 会明确写出"哪个实体 / 哪种箭头 /
哪个区室仍需人工判断"。

## 8. 期刊预设

`python "$SKILL/scripts/run.py" export --journal {nature|science|cell|ieee|generic}`。
预设字段含 `width_mm` / `dpi` / `min_line_width_pt` / `font_embedding_required` / `color_space` / `max_height_mm`
与 `source`（依据说明）。**预设里的数值是可核对的通行要求或保守默认值**；`source` 会明确写是前者还是后者。
投稿前请用目标期刊当期 author guidelines 复核一遍，并把它写进 `references/export_and_compliance.md`。

## 9. 常见失败与处置

| 现象 | 原因 | 处置 |
|---|---|---|
| `render` 返回 4，`E_QUOTE_NOT_FOUND` | 模型里的 `quote` 在材料中找不到 | 用 `source_inventory.json` 的实际文本替换；不要改成模糊匹配 |
| `E_LABEL_NOT_IN_SOURCE` | 引入了材料里没有的基因名/处理组/时间点 | 删掉该实体，或把材料里真正支持的说法补进 `quote` |
| `E_GENE_PROTEIN_CONFUSION` | `kind=gene` 的 label 带 `-P`/`pSer` 等蛋白修饰后缀，或基因/蛋白书写混用 | 按 `references/mechanism_semantics.md` §2.2 改 label 与 `kind`；旧名/物种前缀补进 `attributes.synonyms` |
| `E_MEMBRANE_PLACEMENT` | 跨膜受体不在 `membrane` 容器内，或被画进 `cytosol`/`nucleus` 内部 | 设 `membrane_role`，把 `container` 指向 `kind=="membrane"` 的容器；检查膜内外域朝向 |
| `E_COMPARTMENT_MISMATCH` | `binding` 的两端不在同一区室 | 同区室的用 `binding`；跨区室的改成 `transport`（有方向）或 `association` |
| `E_INTERACTION_STYLE_MISMATCH` | `(arrow, stroke)` 与冻结样式表不符，或图面有该 type 而图例缺条目 | 按 §4 表修正 `style`（或删掉显式 `style` 走缺省映射）；补图例条目 |
| `E_FLOW_DIRECTION` | 非 `feedback` 边 rank 未递增 / 构成有向环 / 受体→核内链非单调 | 修 `figure.flow.ranks`；把环显式标 `feedback`（并要求 `rank[from] >= rank[to]`） |
| `E_DIRECTION_UNSUPPORTED` | 抑制被写成激活、上下游颠倒 | 按材料动词改 `type`；`references/extraction_rules.md` §3 有词表 |
| `E_LEGEND_DATA_MISMATCH` | 图例分类数 ≠ 数据分类数；颜色或线宽档位对不上；`encoding.mapping` 与图面/数据不一致 | 以**数据表**为准重算图例与 `encoding.mapping`；旧图注/任务书与表冲突时记入 `uncertainty` |
| `E_MODEL_NOT_REVISED` | 未修订草稿就直接 `render` | 完成 `SKILL.md` 的七项裁决，写出 `/app/work/figure_model.json` |
| `E_TEXT_OVERFLOW_EST` | 标签太长撑破节点 | 缩短标签或加宽画布；`W_LONG_LABEL` 会先给警告 |
| 图面元素过多、间距被压扁 | 内容超出画布 | 渲染器走 `compaction_scale` 阶梯压缩间距；仍不可读时拆 `panels` 或记 `limitations[]` |
| `export` 返回 4 且 `raster_dpi` 假 | DPI 不足或像素尺寸与物理尺寸不符 | 提高 `--dpi`，或检查 `--width-mm` |
| `pdf_fonts_embedded` 假 | 用了 Type3/未内嵌字体 | 确认 `pdf.fonttype=42`；换用带完整字形的字体 |
| `formats_unavailable` 非空 | 环境缺 matplotlib/Pillow | 如实记录；投 PDF-only 期刊时 SVG+PDF 已足够 |

## 10. 预算与限制

| 项 | 限制 |
|---|---|
| 模型请求 / 单次响应 / 墙钟 | **64 次 / 16384 tokens / 900 秒**（每案例） |
| 案例规模 | 平台 3 个固定案例 × 3 次重复；参赛者不自带案例 |
| Skill 资源 | ≤50 个 UTF-8 文本文件 / 单文件 ≤500KB / 合计 ≤2MB / 无 symlink |
| 网络 | 不联网检索补数据；材料里没有的事实不会被补进来，只会进 `uncertainty`/`limitations` |

本 Skill 明确不做：统计检验与统计方法选择；实验方案设计；海报/封面版式、艺术插画、图像美化；
论文正文与文献综述写作。科学结论的正确性属 Agent/评审责任层（见 `SKILL.md` 的「两层责任」）。

## 11. 维护

- 版本：`manifest.json` 的 `version`；模型合同版本：`schemas/figure_model.schema.json` 的 `schema_version`。
- **本版能力实测状态**：`references/implementation_status.md`（每条能力的核验命令与实测结果）；
  合同要求但本版未达标的能力在该文件里如实列出，`SKILL.md`/`README.md` 不冒充已实现。
- 改动纪律：接口（`run.py` 子命令/退出码、模型 schema、产物路径）一旦变更，必须同步 `SKILL.md`、
  `references/`、`scripts/selftest.py`，并让 `selftest.py` 重新通过。
- 自测：`python "$SKILL/scripts/selftest.py"`（正例真跑 + 注入缺陷必须被检出，`vacuous_skips` 必须为 0）。
- 结构自检（本地工具）：`py -3 _shared/tools/validate_skill_submission.py <submission-dir>`。

## 12. 本作品的证据文档（评审可从这里入手）

| 想知道什么 | 看这个 |
|---|---|
| 每个评分点对应哪段实现、哪条命令能复核，以及**哪些没做到** | `references/rubric-mapping.md` |
| 这个 Skill 相比"把名词串成链"的朴素做法到底强在哪、代价是什么 | `references/measured-gain.md`（由 `scripts/gain_check.py` 真实产出，可重跑） |
| 三套题集覆盖了哪些机制形态 | `examples/cases/{linear-pathway,branch-feedback,multi-compartment}` |
| 哪些资产可以拿走复用、边界在哪 | `references/reuse-and-contribution.md` |
| 本版每条能力的实测状态（含 UNVERIFIED） | `references/implementation_status.md` |

- 已知限制：CJK 字体是否可用取决于运行环境；PDF 文本抽取依赖 `pypdf`；EPS 由 matplotlib 输出，
  不含 `<text>` 语义但仍保留矢量与字体引用，可编辑性以 SVG 主源文件为准。
