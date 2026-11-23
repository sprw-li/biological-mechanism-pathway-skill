# 实现状态与核验记录（`implementation_status.md`）

**本文件是「文档与实现一致」的证据页。** 它逐条列出 Skill 宣称的能力、用什么命令核验、
以及**本版实测**的结果。任何"合同要求但本版测不到"的能力在这里标为
**UNVERIFIED / NOT_IMPLEMENTED**，`SKILL.md` / `README.md` / `references/` 不把它写成已有能力。

## 0. 采样口径（重要：本树在本采样窗口内被并发写入）

| 项 | 值 |
|---|---|
| 采样时间 | 2026-11-23 **12:2x–13:0x +08:00**（**最终一次端到端复跑：12:5x**） |
| 采样对象 | `D:\Borium_Contest\ARMI2611000060v1\work\submission`（本文档作者只拥有 `SKILL.md`/`README.md`/`references/**`/`examples/**`/`GITHUB_URL.txt`/`manifest.json`） |
| 并发事实 | 采样窗口内 `scripts/**` 由其它写者持续修改（实测：`compliance.py` 187,426→188,026 B、`render_svg.py`、新增 `schemas/mech_ontology.json`、`layout.py` 138,816→184,358 B） |
| 状态词 | **PASS**＝本版实测通过 ｜ **PARTIAL**＝部分通过 ｜ **UNVERIFIED**＝未能在稳定版本上跑通 ｜ **NOT_IMPLEMENTED**＝代码里找不到该能力 |
| 数字引用纪律 | **总字节数会随本文档自身被写入而变化**，因此本页给出的字节数是**采样值**；
冻结时的权威数字必须以 §4 的 `validate_skill_submission.py` + manifest 自校验的**原始输出**为准（文件数、单文件上限、无 symlink 这类判据不随写入变化） |
| 结论纪律 | 本页是**某次采样**的事实，不是最终冻结结论。**冻结前必须按 §4 重跑一遍**，并以重跑结果替换本表 |

本页记录的脚本指纹（SHA-256 前 12 位，采样时刻）：

| 文件 | bytes | sha256[:12] |
|---|---|---|
| `scripts/common.py` | 12,396 | `b41935018c17` |
| `scripts/ingest.py` | 66,240 | `c3979e653362` |
| `scripts/mech.py` | 55,894 | `ef36625675e0` |
| `scripts/model.py` | 93,086 | `95b344cac89f` |
| `scripts/layout.py` | 187,874 | `23b85c1ca6c7` |
| `scripts/render_svg.py` | 74,960 | `6cf617896bd9` |
| `scripts/export.py` | 98,455 | `8f28c953758b` |
| `scripts/compliance.py` | 188,026 | `aa48984dbf85` |
| `scripts/reference.py` | 12,935 | `24500594c9f5` |
| `scripts/run.py` | 59,043 | `180d95dda15a` |
| `scripts/selftest.py` | 24,288 | `d992a8c739e6` |

## 1. 能力矩阵（合同 §3/§4 ↔ 实现 ↔ 实测）

| 能力 | 合同 | 实现处 | 核验方式 | 本版状态 |
|---|---|---|---|---|
| 机制错误码存在（6 个 E_ 码） | §3.2–§3.6 | `mech.py` | `Select-String`：`E_GENE_PROTEIN_CONFUSION`=5、`E_MEMBRANE_PLACEMENT`=11、`E_COMPARTMENT_MISMATCH`=6、`E_INTERACTION_STYLE_MISMATCH`=6、`E_FLOW_DIRECTION`=11 命中 | **PASS**（存在性证据） |
| 机制词汇进入模型层（枚举 + 判据） | §3.1–§3.6 | `scripts/mech.py`（判据本体）+ `scripts/model.py:validate_model()` 的机制段（顺序调用 `mech.check_*`） | 一度实测：机制模型跑到 `E_FLOW_DIRECTION`（"`figure.flow.ranks` has no rank for entity"）与 `W_MEMBRANE_ROLE_MISSING`、`W_LEGEND_ENCODING_MISSING` —— 证明门禁**真的在跑** | **PASS**（示例端到端 12:5x：`render exit 0 / status=ok`，0 errors） |
| 基因斜体 / 蛋白正体 | §3.2 | `render_svg.py` | 产物侧 `E_GENE_PROTEIN_CONFUSION` 检查证据：`EXG1` `italic_texts=1 label_style=italic`、`EXK1` `italic_texts=0` | **PASS**（产物侧实跑） |
| 跨膜受体落在膜带 | §3.3 | `layout.py` + `compliance.py` | 产物侧 `E_MEMBRANE_PLACEMENT`：`e_exr1` 声明 `c_membrane`、膜带矩形与绘制框相交，`ok=true` | **PASS**（产物侧实跑） |
| 区室/膜几何（`compartment`/`membrane` 带、转置） | §3.3/§3.5 | `scripts/layout.py` 模块 docstring 的 "Mechanism / pathway figures" 段 + `layout()` | 同上一次运行里容器被画成带（`data-is-membrane="true"`） | **PASS（带已知降级）**：band 几何 `data-is-membrane="true"`、容器层级正确；但请求 `top_down` 时按 `left_right` 绘制（`orientation_fallback=true`），见 §3 缺口 3 |
| 冻结关系类型 → 箭头/线型 | §3.4 | `mech.RELATION_STYLE` + `render_svg.INTERACTION_STYLE` | 产物侧 `E_INTERACTION_STYLE_MISMATCH` 曾报"图例 glyph 未带该类型头型" | **PASS**（产物侧 `E_INTERACTION_STYLE_MISMATCH` 现为 pass，图例 glyph 由冻结表派生） |
| 方向与环（`flow.ranks` 覆盖全部实体、环必须 `feedback`） | §3.5 | `scripts/mech.py:check_flow_direction()` + `scripts/model.py:validate_model()` | 产物侧 `E_FLOW_DIRECTION` `ok=true`（示例 6 条非 feedback 边全部单调，`r_fb` 为显式 feedback） | **PASS**（产物侧实跑） |
| 证据强度 → 线宽 1.4/1.0/0.6 pt | §3.6 | `mech.EVIDENCE_WIDTH_PT` + `evidence_width()` | `encodings_consistent` 的 `line_width` 通道：`mapping` 取值/视觉集合必须等于实际用的强度/线宽 | **PASS**（示例端到端 28/28 检查通过，含 `line_width` 通道） |
| 图例编码三方一致（四通道） | §3.6 | `mech.encodings_consistent` | 同上；`W_LEGEND_ENCODING_MISSING` 在缺编码时确实报警 | **PASS**（`E_LEGEND_DATA_MISMATCH` 现为 warn 级 pass） |
| 图例 glyph 带类型头型 | §3.4 图例栏 | `scripts/render_svg.py:decorate_layout()` 的 legend-glyph 段（从冻结表派生 `marker`/`stroke_style`） | 产物侧 `E_INTERACTION_STYLE_MISMATCH` | **PASS**（产物侧 `E_INTERACTION_STYLE_MISMATCH` 现为 pass） |
| 产物侧机制复核（6 项） | §3/§4 | `scripts/compliance.py` 的 `_check_interaction_style` / `_check_flow_direction` / `_check_membrane_placement` / `_check_compartment_mismatch` / `_check_legend_data_mismatch` / `_check_gene_protein_confusion`（均为符号名，按名检索；行号随并发改动漂移，故不写死） | `checks.json` 里出现 `E_INTERACTION_STYLE_MISMATCH`/`E_FLOW_DIRECTION`/`E_MEMBRANE_PLACEMENT`/`E_COMPARTMENT_MISMATCH`/`E_LEGEND_DATA_MISMATCH`/`E_GENE_PROTEIN_CONFUSION` 条目 | **PASS**（6 项全部存在且全部 pass） |
| 导出合规 + 产物侧机制复核 | §4 | `compliance.check_artifacts` | 示例实测 `checks.json` **共 28 条检查、全部 pass**（含 17 条格式/可解析类 + 机制类 + `REF_*` 位置） | **PASS（28/28）** |
| 平台 7 原字段（顶层 + `output_contract` 内） | §4 | `run.py finish` | 实测 `result.json` 同时有顶层的 `case_id/status/editable_source/export_artifact/content_map/compliance_checks/exceptions`，且 `output_contract` 内同值 | **PASS** |
| `compare` 阶段与 `REF_*` | 新增 | `reference.py` + `run.py cmd_compare` | 实测 `compare exit=0`；无原图时 `semantic_status="na"` + 原因；`REF_LABEL_COVERAGE`/`REF_PALETTE`/`REF_STRUCTURE_COUNTS`/`REF_INTERACTION_VOCABULARY`/`REF_RASTER_METRICS` 五个码在 `reference.py` 中存在 | **PASS**（存在性 + 无原图分支实跑） |
| 结构/预算闸门 | 平台 | `_shared/tools/validate_skill_submission.py` | 见 §2 | **PASS** |

## 2. 实测证据（命令 + 原样结论）

```powershell
# 1) 结构/预算闸门（在 D:\Borium_Contest 下跑）
& $PY _shared\tools\validate_skill_submission.py work\submission
# -> {"status":"ok","files":30,"bytes":<采样值>,"name":"biological-mechanism-pathway-figure","errors":[],...}   exit 0

# 2) 预算实测
Get-ChildItem work\submission -Recurse -File | Measure-Object -Property Length -Sum
# -> 30 文件 / 约 1.09 MB（含 manifest 自身）/ 单文件最大 188,026 B / 无 symlink / 无 __pycache__

# 3) manifest 自校验（临时脚本，未入包）
# -> files_incl_self=30 non_self=29 total_bytes=<采样值> max_file=188026 ; MANIFEST INTEGRITY: PASS ; exit 0
#    （逐条核对 path 存在、bytes 与 sha256 与实际文件一致、文件树无遗漏、预算合规）

# 4) 示例端到端（输入全部在 examples/，不是组织方案例）
python scripts\run.py prepare --input examples --work <w> --output <o>    # exit 0；读到 7 实体 / 7 关系
python scripts\run.py render  --work <w> --output <o>                     # exit 0 / status=ok（见下方"最新一次"）
python scripts\run.py export  --work <w> --output <o> --journal generic --dpi 300
python scripts\run.py compare --input examples --work <w> --output <o>    # exit 0
python scripts\run.py finish  --work <w> --output <o>                     # exit 0
python scripts\run.py finish  --work <w> --output <o> --strict            # 非 ok 时 exit 3
```

**最新一次端到端实测（2026-11-23 12:5x +08:00，示例 `orientation="top_down"`＝合同默认值）**：

| 阶段 | 退出码 | status | 说明 |
|---|---|---|---|
| `prepare` | **0** | ok | `materials=5, source_units=305, draft_entities=7, draft_relations=7` |
| `render` | **0** | **ok** | 0 errors；warnings：`W_FLOW_RANKS_DERIVED`×6、`W_TRANSCRIPTION_ORIGIN`×1 |
| `export` | **0** | **ok** | **28 项检查全部 pass**（`svg_legend_color_map` 为 warn 级 pass） |
| `compare` | **0** | — | 材料无原图 ⇒ `semantic_status="na"` + 原因（**不编造对照**） |
| `finish` | **0** | **ok** | `limitations = []` |
| `finish --strict` | **0** | — | 与 `ok` 一致（`--strict` 下 ok 返回 0） |

产物齐全：`figures/figure.{svg,pdf,png,tiff,eps}`、`preview/`、`figure_model.json`、
`source_map.json`、`checks.json`、`export_report.json`、`reference_comparison.json`、`render_report.json`、`result.json`。
`result.json` 顶层与 `output_contract` 内同时含 7 个平台原字段。

**朝向实况**：示例请求 `top_down`（合同默认），本版 `layout.TOP_DOWN_RENDER_ENABLED = False`，
于是版面按从左到右绘制并留痕（`layout.json.flow.requested_orientation="top_down"`、
`flow.orientation_fallback=true`、布局警告 `W_ORIENTATION_RENDERED_HORIZONTAL`）。
rank/区室/边语义不变；**但该警告不出现在 `render` 的 stdout warnings 里**（只在 `work/layout.json`），
属可发现性缺口（见 §3 缺口 6）。

**`selftest.py` 未通过（exit 1，与本版 examples 改造有关，需 Lead 处置）**：`scripts/selftest.py` 仍写死旧示例的
实体/材料（`ent:e_trpm7`、`ent:e_bcl2`、`lg:lg_2apb`、`data.units.fold_change`、
`materials/demo_pathway.md`、`materials/expression.csv`；集中在 `edit_ops` 段与 `set_value` 探针，
采样时刻为第 358–397 行，行号会漂移故按符号检索），
而 task-5 要求把示例改造成机制专用并改名。报错原样：
`ERROR: edit target not found: ent:e_trpm7` → `SkillError: edit target not found: ent:e_bcl2`。
`scripts/selftest.py` 属 Lead 写域，**需要把它改为引用新的 `examples/expected_model.json`（新 id：`e_exl1`/`e_exr1`/`e_exk1`/`e_extf1`/`e_extf1n`/`e_exg1`/`e_exp1`，材料 `materials/example_pathway_notes.md`）**。
在此之前，`selftest` 的通过状态是 **UNVERIFIED**（不得写成已通过）。

**正面证据（采样窗口内实跑到的）**：

- `prepare` 读入 `figure-workorder.json` 形状的输入：`materials=5, source_units=305, draft_entities=7, draft_relations=7`，exit 0；
- 机制门禁真的生效：机制模型缺 rank 时报 `E_FLOW_DIRECTION: figure.flow.ranks has no rank for entity 'e_vehicle'`；缺 `membrane_role` 报 `W_MEMBRANE_ROLE_MISSING`；缺 `encoding` 报 `W_LEGEND_ENCODING_MISSING`；
- 产物侧机制检查真的在跑并给出可定位证据（`e_exr1` 的膜带矩形与绘制框、`EXG1` 的 `italic_texts=1`、`flow.ranks` 与 `data-level` 交叉核对）；
- `compare` 在"材料里没有原图"时给出 `semantic_status="na"` + 原因，**没有编造对照结论**（exit 0）。

**缺陷日志（采样窗口内观测到、并逐条跟踪；"当前"一列是 12:5x 复跑的结果）**：

> 纪律：下面每一条都是**当时观测到的原样输出**。并发写者在窗口内持续修复，
> 因此"当前"列必须随每次复跑更新；**标注为"已消失"的条目仍需在冻结版本上再确认一次**。

| # | 现象（原样） | 影响 | 归属 | 当前（12:5x 复跑） |
|---|---|---|---|---|
| 1 | `run.py render` → `{"status":"error","error":"TypeError: _membrane_fields() takes 7 positional arguments but 8 were given","exit_code":2}`；栈顶 `scripts/layout.py:layout()` 调用 `_membrane_fields(eid, ent, nodes_out[eid], …)`（采样时刻为第 3738 行；行号随并发改动漂移，按符号检索） | **所有案例 render 直接崩溃** | `scripts/layout.py`（layout-engine 写域） | **已修复**（render 恢复可跑） |
| 2 | 一度实测 `E_DIRECTION_UNSUPPORTED` 误杀正确机制类型（`binding`/`modification`/`transport`/`transcription`/`feedback` 全部被判"与来源动词矛盾"），根因是 `ingest.VERB_LEXICON` 仍是旧 7 类表 | 机制案例被误判 | `scripts/ingest.py` + `model.py:384-392`（已上报） | **已修复**（不再复现） |
| 3 | 一度实测 `E_NUMBER_NOT_IN_SOURCE` 误报（`ent:e_exl1 shows the number 1 …`，示例标签里并无数字） | 产物侧误判 | `scripts/compliance.py` | **已消失**（`E_NUMBER_NOT_IN_SOURCE` 现为 pass） |
| 4 | 一度实测 `raster_pixel_ink` 报 `only 26/64 label rectangles carry ink (missing e.g. 胞外, 质膜, 胞质, 核内)` —— 而这些**容器标签**在同一运行的 PDF 文本抽取里是能取到的 | 产物侧误判或渲染对比度问题 | `scripts/compliance.py` / `scripts/render_svg.py` | **已消失**（`raster_pixel_ink` 现为 pass） |
| 5 | 一度实测 `E_OUT_OF_CANVAS`（8 条，如 `node e_exg1 lies outside the canvas`）与 `E_TEXT_OVERFLOW_EST`（7 条，如 `node e_exl1 label taller than its box`，而 `EXL1` 只有 4 个字符） | 版式门禁不可用 | `scripts/layout.py` / `check_layout` | **已消失**（`top_down`/`left_right` 均 0 errors） |
| 6 | 把示例画布放大到 240×200 mm 后 `render` **超过 4 分钟未返回**（已中断，未取到结果） | 可能存在慢循环/不收敛 | `scripts/layout.py`；因当时树在并发改动中，**需在稳定版本上复现确认** |
| 7 | **`top_down` 转置路径**：同一模型改 `orientation` 一个字段——`left_right` → `render exit 0 / status=ok`（节点 `15.0×7.2 mm`，`lines=["EXG1"]`）；`top_down` → `render exit 4`，`E_OUT_OF_CANVAS`×9、`E_TEXT_OVERFLOW_EST`×7，节点变成 `4.59×16.74 mm`、标签拆成 `["E","X","G","1"]`、`y_mm=167` 而画布高 120 mm | **`top_down` 是合同默认朝向**，默认机制图必失败 | `scripts/layout.py` 的转置段 | **改为显式降级**：请求 `top_down` 时按 `left_right` 绘制并留痕（`orientation_fallback=true` + `W_ORIENTATION_RENDERED_HORIZONTAL`）；**真正的转置仍未启用**（`TOP_DOWN_RENDER_ENABLED=False`） |
| 8 | **产物 `data-level` 与 layout 不一致**：`figures/figure.svg` 里 6/7 个实体 `data-level="0"`（仅 `e_exk1=1`），而 `layout.nodes[].level` 正确（`e_exg1=5` 等）⇒ 产物侧 `E_FLOW_DIRECTION` 判 fail（error 级，`export exit 4`） | 方向/环是核心评分点，`status` 永远到不了 `ok` | `scripts/render_svg.py`（或 layout→render 的 level 传递） | **已消失**（产物侧 `E_FLOW_DIRECTION` 现为 pass） |
| 9 | **`W_TRANSCRIPTION_ORIGIN` 误报**：原样消息 `transcription factor e_extf1n is drawn in 'c_nucleus' (not the nucleus) and the edge declares no crossing` —— 实体确实在核内，是判定把**容器 id** 送进了 `canonical_container()`（期望区室名） | 提示性噪音，不拦截 | `scripts/mech.py:check_relation_constraints` 的转录段 | **仍在**（示例仍报 1 次 `W_TRANSCRIPTION_ORIGIN`） |

缺陷 2–6 的复现命令见 §4；它们都在 `scripts/**`，不在本文档作者的写域内。

## 3. 已知缺口与已解除的缺口（文档必须与实现对齐的部分）

**已解除（12:5x 复跑实测，附证据）**

1. ~~图例 glyph 不带类型头型~~ → **已解除**：产物侧 `E_INTERACTION_STYLE_MISMATCH` 现为 **pass**，
   渲染器从冻结表派生图例 glyph（`data-marker` / `data-stroke-style`）。
2. ~~`json:<pointer>` locator 被产物层拒绝~~ → **已解除**：三个白名单已扩为
   `L\d+|p\d+|table:…|fig:…|json:…|[a-z]+:…`。**实测探针**：把示例里 `e_exr1` 的 source 换成
   `{"path": "materials/example_pathway_workorder.json", "locator": "json:entities/e_exr1", "kind": "explicit"}`
   后 `render exit 0`，SVG 里真的写出了
   `data-prov="materials/example_pathway_workorder.json#json:entities/e_exr1" data-src-kind="explicit"`，
   且全图 `(none)#(none)` 计数为 **0**（此前该元素会被降级为 unsupported）。
3. ~~`data-level` 与 layout 不一致~~ → **已解除**：产物侧 `E_FLOW_DIRECTION` 现为 **pass**。
4. ~~`E_OUT_OF_CANVAS` / `E_TEXT_OVERFLOW_EST`~~ → **已解除**：两种朝向都 0 errors。
5. ~~`E_NUMBER_NOT_IN_SOURCE` / `raster_pixel_ink` 误报~~ → **已解除**：均现为 **pass**。

**仍存在 / 需处置**

6. **`top_down` 只降级、不转置**：本版 `layout.TOP_DOWN_RENDER_ENABLED = False`，
   请求 `top_down` 时按 `left_right` 绘制，留痕于 `layout.json.flow.orientation_fallback=true`、
   `flow.requested_orientation="top_down"` 和布局警告 `W_ORIENTATION_RENDERED_HORIZONTAL`。
   - 语义不受影响（rank 顺序、区室嵌套、边界语义都按模型声明执行，只有页面轴向不同）；
   - **但该警告不出现在 `render` 的 stdout warnings 里**（只在 `work/layout.json`），
     用户若只看 `render` 输出会以为朝向已按请求执行。这是可发现性缺口，已上报。
   - 文档处置：`references/mechanism_semantics.md` §5 与 `examples/README.md` 都写明了这一降级。
7. **`W_TRANSCRIPTION_ORIGIN` 误报（仍在）**：判定把**容器 id** 送进 `canonical_container()`（期望区室名），
   于是容器 id 形如 `c_nucleus` 时即使实体在核内也会报警。示例实测 1 次。
   文档处置：`references/mechanism_semantics.md` §9 已把它标为"提示性噪音"。
8. **`layout.py` 注释里列了但本版不发出的码**：模块 docstring 的 "Error codes owned by this module" 段声明
   `E_TRANSPORT_BOUNDARY` / `E_EDGE_THROUGH_NODE`，但代码里只发出
   `E_NODE_OVERLAP` / `E_OUT_OF_CANVAS` / `E_TEXT_OVERFLOW_EST` / `E_LEVEL_REGRESSION` / `E_MEMBRANE_PLACEMENT`。
   本页与 `references/layout_and_svg.md` §9 已按**实际发出的码**书写（不冒充未实现的能力）。
9. **`selftest.py` 仍耦合旧示例（需 Lead 处置）**：见 §2 末尾；在它被更新前，
   `selftest` 的通过状态保持 **UNVERIFIED**。
10. **`manifest.json` 随并发写入漂移（流程性）**：采样窗口内实测到多次漂移
    （`compliance.py`/`render_svg.py` 变化、新增 `schemas/mech_ontology.json`）。
    冻结前必须重新生成 + 重跑自校验。
11. **`__pycache__` 打包风险（流程性）**：采样窗口内 `scripts/__pycache__/` 曾出现 6 个 `.pyc`
    （由**本文档作者**一次未设 `PYTHONDONTWRITEBYTECODE=1` 的排障命令产生，已删除）。
    冻结前必须再确认一次"无 `__pycache__`"。

## 4. 复跑清单（冻结前必须执行，结果替换本页表格）

```powershell
cd D:\Borium_Contest
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONDONTWRITEBYTECODE='1'   # 必须；否则生成 __pycache__
$s = "ARMI2611000060v1\work\submission"
$w = "$env:TEMP\bmp-work"; $o = "$env:TEMP\bmp-out"
Remove-Item -Recurse -Force $w, $o -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $w, $o | Out-Null

# A. 结构闸门 + 预算 + manifest 自校验
& $PY _shared\tools\validate_skill_submission.py $s
Get-ChildItem -Recurse -File $s | Measure-Object -Property Length -Sum
Get-ChildItem -Recurse -Force -Directory $s | Where-Object Name -eq '__pycache__'    # 必须为空

# B. 自带自测（最权威的一体化证据）
& $PY "$s\scripts\selftest.py"; "selftest exit=$LASTEXITCODE"      # 期望 0

# C. 示例端到端（示例输入，不是组织方案例）
& $PY "$s\scripts\run.py" prepare --input "$s\examples" --work $w --output $o
Copy-Item "$s\examples\expected_model.json" "$w\figure_model.json" -Force
& $PY "$s\scripts\run.py" render  --work $w --output $o; "render exit=$LASTEXITCODE"
& $PY "$s\scripts\run.py" export  --work $w --output $o --journal generic --dpi 300; "export exit=$LASTEXITCODE"
& $PY "$s\scripts\run.py" compare --input "$s\examples" --work $w --output $o; "compare exit=$LASTEXITCODE"
& $PY "$s\scripts\run.py" finish  --work $w --output $o; "finish exit=$LASTEXITCODE"

# D. 机制门禁的存在性证据（没有这 6 个码就不可能实现合同 §3）
Select-String -Path "$s\scripts\*.py" -Pattern 'E_GENE_PROTEIN_CONFUSION','E_MEMBRANE_PLACEMENT',`
  'E_COMPARTMENT_MISMATCH','E_INTERACTION_STYLE_MISMATCH','E_FLOW_DIRECTION','E_LEGEND_DATA_MISMATCH'
```

**判据**：A 段 `status=ok` 且预算合规；B 段 `exit 0`；C 段 `render/export/finish` 的 `status` 与
`checks.json` 的 error 级条目全部 pass；D 段每个码 ≥1 命中。任一条不满足，
本页对应行保持 **UNVERIFIED**，且**不得**在 `SKILL.md`/`README.md` 里写成已有能力。
