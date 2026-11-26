# `examples/` — 最小调用示例（**示例，不是组织方正式案例**）

> ## ⚠️ 显著声明
> 本目录下的一切内容都是**为演示接口而构造的合成示例**：
> **不是**组织方正式案例的材料、**不是**任何正式案例的结果或答案，也**不**对应组织方的 `figure03`。
> 其中的分子名（`EXL1`/`EXR1`/`EXK1`/`EXTF1`/`EXG1`/`EXP1`）、通路与数值都是**虚构**的，
> 唯一用途是说明「材料 → 可编辑图稿 → 导出件」的调用方式与模型形状。
> 为避免与正式案例混淆：材料文件名、`figure.id`、`case_id` 全部带 `example-` 前缀。

## 内容

| 路径 | 说明 |
|---|---|
| `case.json` | 最小 `case.json`：`case_id=example-mechanism-pathway`、平台 7 个原字段的 `output_contract`、`figure.kind=mechanism_pathway`、180×120 mm |
| `materials/example_pathway_workorder.json` | **figure workorder**（镜像真实案例的输入形状）：区室/膜容器、实体与 `membrane_role`、冻结关系类型、`legend_encoding` |
| `materials/example_pathway_notes.md` | 机制叙述材料：逐字引文的来源（`L9`、`L14`、`L20` …） |
| `expected_model.json` | **模型示意**（不是渲染结果）：演示 `schemas/figure_model.schema.json` 的机制图完整形状与逐元素溯源绑定 |
| `cases/linear-pathway/` | 题集 ①：线性通路（配体→受体→激酶级联→核内 TF→基因→蛋白），含 `case.json` + `materials/` + `model.json` |
| `cases/branch-feedback/` | 题集 ②：**并行分支 + 显式反馈环**（`relations[].type="feedback"` 收环） |
| `cases/multi-compartment/` | 题集 ③：**多区室 + 跨膜受体 + 膜带**（extracellular/membrane/cytosol/nucleus 嵌套） |

三套 `cases/` 就是「基础对照 / 回归 / 题集」共用的那三套，同时是 `scripts/gain_check.py`
测增益时用的输入（见 `references/measured-gain.md`）。它们与根目录的最小示例一样，
**全部是合成示例**：`case_id` 带 `example-` 前缀，`figure.id` 统一为 `example-figure`
（不要与组织方的 `figure03` 混淆）。

### 跑题集（任选一套）

```powershell
python "$SKILL/scripts/run.py" prepare --input "$SKILL/examples/cases/linear-pathway" --work w --output o
# 用题集自带 model.json 代替「Agent 裁决」这一步（它就是一个已裁决好的模型）
python "$SKILL/scripts/run.py" render --work w --output o --model "$SKILL/examples/cases/linear-pathway/model.json"
python "$SKILL/scripts/run.py" export --work w --output o --model "$SKILL/examples/cases/linear-pathway/model.json" --journal nature --dpi 600
python "$SKILL/scripts/run.py" finish --work w --output o --model "$SKILL/examples/cases/linear-pathway/model.json"
```

### 一次测出"这个 Skill 到底有没有用"

```powershell
python "$SKILL/scripts/gain_check.py" `
    --case "$SKILL/examples/cases/linear-pathway" `
    --case "$SKILL/examples/cases/branch-feedback" `
    --case "$SKILL/examples/cases/multi-compartment" `
    --work <tmp>/w --out <tmp>/o
```

它会把**朴素基线**（材料名词串链、全默认激活箭头、无来源）与**本 Skill**（`model.json`）
放进同一条管线跑，输出 `gain_results.json` + `measured-gain.md`。
本仓库当前那份输出见 `references/measured-gain.md`。


`expected_model.json` 里每条 `source.quote` 都能在 `materials/example_pathway_notes.md` 的对应行**逐字**找到，
这正是 `validate_model` 会核对的那件事——示例因此同时充当「最小可核验样例」。

## 它演示了哪些机制能力

| 机制点 | 在示例里怎么体现 |
|---|---|
| 实体类型 | `protein` ×6、`gene` ×1；`kind=gene` 的 `EXG1` 渲染为斜体，蛋白为正体 |
| 区室与膜 | `compartment`（胞外/胞质/核内）+ `membrane`（质膜）；`EXR1` 是 `transmembrane`，必须落在膜带上 |
| 关系类型 | `binding`（无箭头实线）、`activation`（实线箭头）、`modification`（虚线箭头，label=磷酸化）、`transport`（跨边界，`crosses`）、`transcription`、`translation`、`feedback`（虚线环） |
| 方向与环 | `figure.flow.orientation=top_down`（合同默认值）+ `flow.ranks` 覆盖全部 7 个实体；`EXP1→EXK1` 是显式 `feedback` |
| 证据强度 | `high/medium/low` 三档 → 线宽 `1.4/1.0/0.6 pt`，并进入图例编码 |
| 图例编码 | 8 条图例项（7 个关系类型各一条 + 一条 `line_width` 的 `encoding`），`mapping` 与图面/数据取值一一对应 |

> **关于 `top_down`（示例请求的就是它，即合同默认值）**：本版 `layout.TOP_DOWN_RENDER_ENABLED = False`，
> 因此示例的版面实际按从左到右绘制，并在 `layout.json` 里留痕
> （`flow.requested_orientation="top_down"`、`flow.orientation_fallback=true`、警告
> `W_ORIENTATION_RENDERED_HORIZONTAL`）。rank 顺序、区室嵌套与关系语义都不变，只有页面轴向不同。
> 细节与证据见 `references/implementation_status.md`。

## 跑通它（示例输出标注为 example）
```bash
export SKILL=/skills/weekly-skill
WORK=$(mktemp -d); OUT=$(mktemp -d)

# 1) 盘点示例材料（workorder + 叙述材料都会被读入）
python "$SKILL/scripts/run.py" prepare \
    --input "$SKILL/examples" --work "$WORK" --output "$OUT"

# 2) 用示例模型替代草稿（真实使用时这一步是 Agent 依材料裁决 figure_model.json）
cp "$SKILL/examples/expected_model.json" "$WORK/figure_model.json"

# 3) 渲染 → 导出 → 对照 → 汇总
python "$SKILL/scripts/run.py" render  --work "$WORK" --output "$OUT"
python "$SKILL/scripts/run.py" export  --work "$WORK" --output "$OUT" --journal generic --dpi 300
python "$SKILL/scripts/run.py" compare --input "$SKILL/examples" --work "$WORK" --output "$OUT"
python "$SKILL/scripts/run.py" finish  --work "$WORK" --output "$OUT"
```

预期产物（全部为**本轮真实生成**）：

- `$OUT/figure_model.json` — 可编辑模型（示例模型会被渲染阶段登记到输出）
- `$OUT/figures/example-mechanism-pathway.svg` — 7 个命名图层、文字是 `<text>`、每个元素带 `data-prov`
- `$OUT/figures/example-mechanism-pathway.{pdf,png,tiff,eps}` — 真实导出件（后端缺失时该格式记 `unavailable`）
- `$OUT/reference_comparison.json` — 示例材料里没有原图，故 `semantic_status="na"`（**不是失败**）
- `$OUT/checks.json`、`$OUT/export_report.json`、`$OUT/result.json`

## 示意输出（节选）

下面的片段是 `figures/<stem>.svg` 在示例输入下的**结构示意**（节选，标注为 example）：

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="180mm" height="120mm" viewBox="0 0 680.315 453.543">
  <metadata>{ "case_id": "example-mechanism-pathway", ... }</metadata>
  <g id="layer:background"><title>background</title> ... </g>
  <g id="layer:containers"><title>containers</title>
    <rect id="cnt:c_membrane" data-compartment="membrane" data-is-membrane="true"
          data-prov="materials/example_pathway_notes.md#L9" .../>
  </g>
  <g id="layer:edges"><title>edges</title>
    <g id="rel:r_mod" data-rel-type="modification" data-direction="forward" data-head-end="arrow"> ... </g>
  </g>
  <g id="layer:nodes"><title>nodes</title>
    <g id="ent:e_exr1" data-src-kind="explicit"
       data-prov="materials/example_pathway_notes.md#L10"> ... </g>
  </g>
  <g id="layer:labels"><title>labels</title>
    <text font-family="DejaVu Sans, Liberation Sans, Arial" font-size="7">EXR1</text>
  </g>
  <g id="layer:legend"><title>legend</title> ... </g>
  <g id="layer:annotations"><title>annotations</title><text>A</text></g>
</svg>
```

（真实输出会包含完整坐标、配色与全部元素；此处仅示层级、可编辑文字与溯源属性。
`rel:r_mod` 的 head/stroke 由冻结样式表派生：`modification` ⇒ 虚线 + 箭头。）

## 与正式案例的边界

- 正式案例（含组织方的 `figure03` 原图）由平台在运行时注入 `/input/`，**不随本 Skill 发布**；
- 本目录不包含任何正式案例的实体清单、边清单、图例或数值，也不代替平台提供测试案例；
- 若把这里的示例产物当作正式案例结果提交，即违反运行契约中「不得提交预制答案」的要求。
