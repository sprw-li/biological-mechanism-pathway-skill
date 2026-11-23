# RESULT — ARMI:2611.000060v1 · 生物机制图与通路图（challenge-83d4f050）

更新时间：2026-11-23 14:2x +08:00　｜　作者：Lead + 5 名 durable teammates（Agent Teams）
赛题：`challenge-83d4f050`　｜　评分：**human_review_only**（人工评审，满分 100 + GitHub 公开链接 5）　｜　平台固定 3 个隐藏案例

## 0. 结论（一句话）

已交付一个可安装到 `/skills/weekly-skill` 的 Skill **`biological-mechanism-pathway-figure`**：它把「来源材料 → 带逐字引文溯源的机制模型（实体/相互作用/区室/膜/方向/证据强度/图例编码）→ 确定性分层布局 → 可编辑分层 SVG 主源 + 真实 PDF/PNG/TIFF/EPS 导出 → 机制语义与导出质量门禁 → 来源保留式编辑 → 与论文原图对照」跑成一条可复现链路；
**提交包与轨迹双闸门已在本机预演 PASS**；**独立第三方验收仍为部分未完成（见 §6，如实标注）**，故本文件**不声称已达成**。

## 1. 平台事实与运行契约

| 项 | 值 |
|---|---|
| challenge_id | `challenge-83d4f050`（`ARMI:2611.000060v1`，作者 `mingjunxu-dpa`，`human_review_only`，100 + 5） |
| 题面/元数据 | `task/task.md`、`task/challenge.json`、`task/config.json` |
| 平台公开数据集 | `task/datasets/paper2arm-task-challenge-83d4f050-8f53d166/1/`（`public-manifest.json` + `resources/example-input.json` + `resources/output-contract.md`） |
| 运行契约 | 输入 `/input/case.json` + `task.md`；工作 `/app/work`；交付 `/app/output`（含 `result.json`）；**64 请求 / 900 秒 / 16384 tokens**；3 案例 × 3 重复 |
| 资源上限 | ≤50 UTF-8 文本文件 / 单文件 ≤500KB / 合计 ≤2MB / 无 symlink |
| 平台必填 result 字段 | `case_id, status, editable_source, export_artifact, content_map, compliance_checks, exceptions`（**顶层与 `output_contract` 内都有**） |
| 数据获取（可复现） | `bh.py pull` 因沙箱 node 管道 `spawn EPERM`，数据集用 wenyon CLI 直连：`VOUCH_CONFIG_DIR=D:\Borium_Contest\.vouch`、`VOUCH_CLIENT_ID=trisol-cli-10ee`、`wenyon-cli.exe dataset download ...` |

## 2. 交付物

`work/submission/`（唯一权威；提交包内为 `skills/submission/**`）

| 类别 | 内容 |
|---|---|
| 入口 | `SKILL.md`（合法 frontmatter，`name: biological-mechanism-pathway-figure`，含机制触发词、七项 must-decide 裁决清单、五道门禁、异常处理表） |
| 脚本（纯标准库核心路径） | `run.py`（prepare→render→export→compare→edit→finish）、`ingest.py`、`model.py`、`mech.py`（机制本体与判据）、`layout.py`、`render_svg.py`、`export.py`、`compliance.py`、`reference.py`（对照原图）、`common.py`、`selftest.py` |
| 本体与 schema | `schemas/figure_model.schema.json`（v1.0\|1.1）、`schemas/mech_ontology.json`（机器可读，由 `mech.py` 生成且断言无漂移）、`schemas/edit_ops.schema.json`、`schemas/review_batch.schema.json` |
| 文档 | `README.md`、`references/{mechanism_semantics,extraction_rules,layout_and_svg,export_and_compliance,result_contract,implementation_status}.md` |
| 示例（标注为非正式案例） | `examples/{case.json,expected_model.json,README.md,materials/example_pathway_notes.md,materials/example_pathway_workorder.json}` |
| 其他 | `manifest.json`（真实 path+bytes+sha256）、`GITHUB_URL.txt` |

## 3. 机制/通路语义（本题的评分核心，已冻结在 `work/CONTRACT.md`）

1. **实体与命名**：`gene/protein/complex/organelle/cell_type/metabolite/modification_site/stimulus/drug`；基因 vs 蛋白不得混用（`E_GENE_PROTEIN_CONFUSION`）；物种前缀/同义名归一。
2. **相互作用语义**：`activation/inhibition/binding/modification/transport/transcription/translation/feedback/association` 各有**冻结的箭头+线型**（抑制 = 平头 ⊥、结合 = 无箭头实线、修饰 = 虚线箭头、反馈 = 虚线、关联 = 点线无向）；`E_INTERACTION_STYLE_MISMATCH` 拦截样式与语义不符。
3. **区室与膜**：`membrane_role ∈ {transmembrane, membrane_anchored, luminal, cytosolic, extracellular, na}`；跨膜实体必须声明在 `kind=membrane` 的容器并画在膜带上（`E_MEMBRANE_PLACEMENT`）；区室嵌套与跨膜域朝向有几何证据。
4. **方向与拓扑**：`figure.flow.orientation` + `ranks`；非 feedback 边 rank 严格递增、有向环必须显式标 `feedback`（`E_FLOW_DIRECTION`）。
5. **证据与数据编码**：`evidence.strength` → 线宽 **1.4/1.0/0.6 pt**；`abundance` → 面积编码；`legend[].encoding` 四通道（color/line_width/node_size/line_style）由模型自动生成，`E_LEGEND_DATA_MISMATCH` 要求「图例项 = 图面实际取值 = 数据取值」三方一致。
6. **溯源**：每个图面元素带 `source{path,locator,quote,kind}`，`quote` 必须逐字存在；locator 文法含 **`json:<json-pointer>`**（真实隐藏案例的主来源 `figure-workorder.json` 正是这种形态）。

## 4. 可重跑的验证证据（本机实测）

| 检查 | 命令 | 结果 |
|---|---|---|
| Skill 自测（正向 + 注入负例 + 真实渲染导出） | `& $PY work\submission\scripts\selftest.py` | **PASS 67 passed / 0 failed / 0 unavailable / 0 vacuous skips**，exit 0（~160–240 s） |
| 机制判据（含正负双向） | `& $PY work\fixtures\check_mech.py` | **38 checks / 38 passed / 0 failed**，exit 0（M2 那条从 FAIL→PASS） |
| 端到端集成（Lead 的 4 个接口夹具） | `& $PY work\integration_check.py` | **4 夹具全部 `export exit=0` / `finish exit=0` / `status=ok`**（详见 `work/fixtures-render/integration-run-*.txt` 与 §5 的时序披露） |
| 未修订草稿硬门禁（负例） | 同上内置 `negative(unrevised draft)` | `render exit=4` 且含 **`E_MODEL_NOT_REVISED`** |
| 门禁注入负例（render-export 独立夹具） | `& $PY work\fixtures-render\gates.py` | 20/21（唯一 FAIL 为其夹具自身的退化自环场景，已定位 `compliance.py:1886`，真实管线不受影响） |
| 机制门禁正负例（mech-semantics） | `& $PY work\fixtures\check_mech.py` | `E_MEMBRANE_PLACEMENT`/`E_GENE_PROTEIN_CONFUSION`/`E_FLOW_DIRECTION` 各**正例不触发 + 注入后触发**，`where` 命中 `entities.NOTCH1`/`entities.STAT3`/`relations.b7` |
| 真实导出可解析 | 集成产物 | PNG magic `89504e470d0a1a0a` + IHDR（4252×3543 @600dpi）；PDF `%PDF` 1 页，关键标签可由 pypdf 抽出；`fonttype=42` TrueType 内嵌；TIFF/EPS 真实产出；`fake_files=[]` |
| 结构合规 | `& $PY _shared\tools\validate_skill_submission.py work\submission` | `status=ok`，`errors=[]`，exit 0；**30 文件 / ~1.11 MB** / 无 symlink / 无 `__pycache__` |
| **打包 + 轨迹双闸门预演** | `bh.py submit --challenge-id challenge-83d4f050 --outputs work\submission --skill work\submission --trace traces\trace_v1.jsonl --bundle-out receipts\bundle_dryrun.zip --harness dsh --dry-run` | **bundle 闸门 PASS**（98 entries、`unsafe_entries=0`、`duplicate_entries=[]`、`backslash_entries=0`、`native_trace` 恰好 1、`skills=[{name:'submission', files:28}]`、`skill_bytes≈1.02MB`、`skill_files=29`、`symlinks=0`）；**G10 轨迹闸门 PASS**（316 记录 / 180 tool_result）；SHA 去重预检通过；G9 仅 warn（CLI 生成 `characterization.json` 占位 stub，按规则不手改） |

**对照论文原图**（题面 step 3）：`run.py compare` 阶段——`prepare` 自动发现候选原图并记录"为什么选它/跳过了哪些"；原图为 SVG/JSON 时做**精确内容对照**（标签覆盖 `REF_LABEL_COVERAGE`、配色 `REF_PALETTE`、结构计数 `REF_STRUCTURE_COUNTS`、交互词汇 `REF_INTERACTION_VOCABULARY`）；原图为位图/PDF 时只测几何与宽高比并明确写 `semantic_status="unverifiable-machine"`（**像素无法证明语义等价，不编造相似度**）；无原图时 `na` + 原因。实测：`case-d` → `status=labels_fully_covered`；其余 → `na`。

## 5. 缺陷账本（真缺陷 → 根因 → 状态）

| # | 缺陷 | 根因（`file:line`） | 状态 |
|---|---|---|---|
| D1 | `result.json` 缺平台 7 字段 | `run.py` finish 只写嵌套 `output_contract`，且 token 提示把 `editable_source` 映射成 `figure_model.json` | **已修**（顶层+嵌套双写；`export_artifact` 为 `{format:{path,bytes,sha256,dpi,available,reason_if_unavailable}}`；`content_map` 用 SVG 真实 `data-*-id` 锚点判 `on_canvas`） |
| D2 | `output_contract` 为 list 时被退化成 `{}`，平台字段全丢 | `ingest.py` 旧逻辑只认 dict（平台 `example-input.json` 给的是 list） | **已修**（`ingest.normalise_output_contract` + `run.py:_contract_keys` 纵深防御） |
| D3 | 无量纲列（`p_value`/`fold_change`）硬报 `E_UNIT_MISSING` | `model.py` 单位判据 | **已修**（无量纲 allowlist → `W_UNIT_DIMENSIONLESS_ASSUMED`；`time_h` 从列名后缀取 `h`）；**并堵住反向漏洞 M2**：`unit_status` 为权威，`unknown` 仍报 error |
| D4 | 小数被按 "." 切碎：`2.9-fold` → 伪实体 `9-fold` → 伪 `E_NUMBER_NOT_IN_SOURCE` | 抽取层词元切分 | **已修**（正则加 `(?<![A-Za-z0-9.])` + 量值短语过滤；负例"裸 9 仍报错"通过） |
| D5 | 免责声明行被抽成实体 | 抽取层 | **已修**（boilerplate 跳过 + warning） |
| D6 | 机制枚举未落地 → `E_CONTRACT_KEY_MISSING` | `model.py`/`ingest.py` 旧枚举 | **已修**（枚举由 `mech.py` 单源驱动，schema 断言 `same=True`） |
| D7 | `VERB_LEXICON` 无机制 cue ⇒ **用正确的机制类型反而过不了 render** | `ingest.py` 旧 7 类表 | **已修**（机制 cue + 判据改为"断言类型 ∈ 该引文候选集合"） |
| D8 | Pillow `IFDRational` 无法 JSON 序列化 ⇒ `export` 全案例 exit 2 | 导出侧 DPI 元数据 | **已修**（源头 `float()` + `common.write_json/jsonl` 全局兜底） |
| D9 | `json:` 前缀 locator 被三处白名单拒绝 ⇒ 产物层溯源丢失 | `render_svg.py`/`layout.py`/`compliance.py` | **已修**（文法冻结进 CONTRACT §4.1；实测 `data-prov` 稳定含 `json:entities/EGFR` 等） |
| D10 | `E_LABEL_NOT_IN_SOURCE`：自动生成的图例 label 声明 `explicit` 却非材料原文 | `model.py` 图例 source 声明 | **已修**（改判 `derived` + `derived_from`；**判据未放宽**；负例"材料查无此 label"仍触发） |
| D11 | 产物 `data-level` 与 `layout.nodes[].level` 不一致 ⇒ 产物侧 `E_FLOW_DIRECTION` 必 fail | `render_svg.py` | **已修**（三级回退链） |
| D12 | 自环（`EGFR→EGFR`）被误判方向/rank/环 | `compliance.py` | **已修**（自环豁免 + advisory；负例保留） |
| D13 | `membrane_anchored` 被当作必须落在膜容器 | `compliance.py` / `mech.py` | **已修**（仅 `transmembrane` 强制；anchored 降 advisory 并按已画膜带量测） |
| D14 | **`top_down`（合同默认朝向）转置路径崩溃/溢出**：节点被拆成一字一行、9×`E_OUT_OF_CANVAS` | `layout.py` 转置路径（把转置当成成品后处理 + 列宽预算取错轴） | **显式降级**：`TOP_DOWN_RENDER_ENABLED=False`，请求 `top_down` 时按 `left_right` 渲染，输出 `flow.requested_orientation`/`orientation_fallback=true` + `W_ORIENTATION_RENDERED_HORIZONTAL`。**语义（rank 顺序、区室层级、边的方向）不变，仅页面轴向不同**。修法思路已移交（见 §7） |
| D15 | `layout.py` 半成品崩溃（`transform_record` 未定义、`_compartments_out` 未实现、`_membrane_fields` 参数多一个、`lreg/rreg` 未绑定） | `layout.py:3839/3845/3738/3713` | **已修**（Lead 在冻结前做的 4 处最小修复） |

## 6. 独立验收状态（**不得声称 ACCEPT**）

- **第三方验收者（verify-harness，非实现方）**：harness 已建（`work/verify/harness.py` 72KB + `naive_baseline.py` + 夹具），但其冻结后的最终 `run`/`negative` 出口与 `REVIEW.md`/`BASELINE.md` **在本轮结束时仍未落盘** ⇒ 总门禁只能报 **INCOMPLETE**，不是 PASS。
- **本地不可验项（如实列出）**：① 组织方 3 个隐藏案例从未在本地运行；② `/skills/weekly-skill` 的真实安装与触发；③ 人工视觉判断（图是否"读得懂"）；④ 平台真实计分（`human_review_only`，无自动分）。
- **我方夹具不是组织方案例**：`work/fixtures-lead/*`、`work/fixtures/*`、`work/fixtures-render/*`、`work/verify/fixtures/*` 均为自建接口夹具，材料中已显著标注 `SYNTHETIC FIXTURE - NOT AN OFFICIAL CASE`，**不得**当作组织案例结果引用。
- **council / opt 矩阵**：本轮**未跑** 8×n 矩阵与 8 次 council 调用（成本与时间预算），**不冒充**；`work/council/` 无记录。这是本版最明确的流程缺口，见 §7。
- **验收时序披露**：`integration-run-4`（`work/fixtures-render/`，13:28）为 4/4 PASS；13:32 与 13:38 的收尾改动（`render_svg.py` 两处、`run.py` 传 `materials=inp`）**未被该次覆盖**，其后由 `run-5` 与 Lead 的复跑覆盖；本 RESULT 的数字以最后一次复跑为准，采样时间已标注。

## 7. 已定位但**未修**（下一轮直接接手）

1. **`top_down` 真转置**：应把转置做成**构建参数**（先把真实区域转置成引擎输入 `w=rh,h=rw`、`canvas_w=H`、`_size_node(swap=True)` 按跨轴换行），并让转置走与 `left_right` **同一套**确定性 fit 判据；根因是 `slot` 用真实区域**宽**而转置后应取**高**，列宽被挤到 `avail=2.0mm` 下限。（`layout.py:214`、`TOP_DOWN_RENDER_ENABLED`）
2. **确定性 fit 未接线**：`metrics.flow_scale` 恒 `1.0`（读取从未赋值的 `stats["fit"]`）；`MIN_FIT_SCALE`/`ctx["font_scale"]` 已定义未接。
3. **`legend[].encoding` 在布局侧未展开**（图例实际由 `render_svg.py` 从模型渲染）。
4. **自环边路由退化**：同节点边去重后只剩共线点，画面上看不出自环。
5. **面板字母无溯源**：`layout.py:3160-3161` 在 caption 无 source 时给面板字母 `_src(None)` ⇒ 全 SVG 仅剩 1 处 `(none)#(none)`（`pnl:A`）。
6. **画布上"模型未声明的元素"无判据**：注入 `<text>NOTINMODEL_XYZ</text>` 后 `export exit=0`（未检出）；建议新增 `E_UNTRACED_CANVAS_ELEMENT`。**反方向（声明了但引文对不上）已能拦**。
7. **`compliance.py:1886` tee 启发式**在"退化零长度折线 + `evidence.strength=high`"时误判；`compliance.py:1974` advisory 文案多一个 `$`。
8. **`layout.py` 只声明未实现**：`E_TRANSPORT_BOUNDARY`、`E_EDGE_THROUGH_NODE`（`check_layout` 实际只发 4 个码）；已在 CONTRACT §3.7 如实标注。
9. **council / opt 8×n 矩阵未跑**（流程缺口，非技术缺陷）。
10. **`integration_check.py` 的 runtime 目录需实例隔离**（并发实例会互相 `rmtree`，造成假失败）。

## 8. 诚实边界

- 本版**未在组织方隐藏案例上运行过**；所有"通过"均来自自建夹具。
- 无 `cairosvg`/`inkscape`/`gs`：PNG/PDF/EPS 走 matplotlib **按同一 model+layout 重绘**（与 SVG 同源，非光栅化）；该事实写入 `export_report.notes` 与 `exceptions`。
- `top_down` 为**显式降级**而非实现；文档与输出均留痕，不静默改写。
- 缺后端时一律 `available=false` + 真实原因，**绝不写假文件**（magic-byte 扫描证明）。
- 本文件所有数字均为某次真实命令的输出；`RESULT.md` 不是验收结论，验收结论见 §6。
