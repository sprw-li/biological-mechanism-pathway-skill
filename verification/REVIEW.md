# 独立验收记录 — ARMI2611000060v1（task-4 / M4, verify-harness）

> 验收人：**verify-harness**（独立验收方，不参与实现；只写 `work/verify/**`）
> 被验收对象：`work/submission/**`（冻结树，30 文件 / 1,118,394 B / `validate_skill_submission.py` → `status=ok`）
> 判据真相：`work/CONTRACT.md`（FROZEN v1.1）+ `task/task.md` §2/§3 + `task/datasets/**/resources/output-contract.md`
> 采样时间：**2026-11-23 14:3x +08:00**（`run` 第三次运行 14:32–14:34；`negative` 14:35 起）。实现方已停写（Lead 写冻结）。

## 1. 结论（总门禁）

**总门禁：CONDITIONAL**　　`final_verdict: CONDITIONAL`

> **终验采样（2026-11-23 16:1x–16:2x，冻结树 `files=30 / bytes=1,125,775`）**
> `layout.py=600277da…`、`render_svg.py=2ab1b0a7…`、`run.py=2dd29550…`、`compliance.py=a00d77be…`、`model.py=9c9a3b10…`（完整 11 项见 `harness_results.json.skill_module_sha256`）。
> 上一版（15:0x/15:36）的判定**已被本轮取代**；两轮的差异逐条列在 §6.10。

未解决项计数：**正例 2 条 FAIL（B1-residual，同一根因）＋ 2 个冻结码未实现（B4 → UNVERIFIED）** ＝ 4 条。B2/B3/B7/B8/B9 与 P0 均已按新指纹**复核关闭**（证据见 §7）。UNVERIFIED 范围另见 §5。

- 正向套件 `run`：**207 PASS / 2 FAIL / 0 UNVERIFIED / 6 N/A，exit 1**（169.2 s）。两条 FAIL 都是「未被警告的元素面积必须严格 ∝ value」（夹具 B spread 49.7%、夹具 C spread 36.7%），根因见 **B1-residual**。
- 负例套件 `negative`：**injected=33 detected=31/33 vacuous_skips=[]**（`where_field_absent_or_loose=5`）。**本轮无超时假阴性**（上轮 2 条已计入检出）。仅剩 2 条未检出 = `E_EVIDENCE_WIDTH_MISMATCH` / `E_ABUNDANCE_SIZE_MISMATCH`（契约冻结、实现未落地）→ 按 Lead 指示记 **UNVERIFIED**。
- 结构闸门（独立复跑）：`validate_skill_submission.py` → `{"status":"ok","files":30,"bytes":1125775,"errors":[]}`，exit 0。
- **本轮已确认转绿**：B1 根因(二次缩放)→ (iv) PASS；B9(披露未达平台字段)→ (iii) PASS；B7(无量纲 allowlist)→ 检出；B8(`abundance.value` 来源核对)→ 检出；B3(`E_PLATFORM_FIELD_MISSING`)→ 检出；**P0**(`layout.py:3875 NameError: degrade`)→ 已修，全管线恢复（4 夹具 render/export/finish exit 0）。
- 判 CONDITIONAL 而非 ACCEPT：① 正例仍有 1 个真实根因（B1-residual，面积仍含"文本宽度"成分）；② 两个冻结码无实现（B4）；③ 存在本地不可验范围（§5）。判 CONDITIONAL 而非 REJECT：核心机制判据在 31 条注入上**逐条被指定错误码捕获**且 `vacuous_skips=[]`，四夹具 `status=ok`、导出件真实可解析。

## 2. 范围与版本

| 项 | 值 |
|---|---|
| 被验收 Skill | `work/submission/`（`SKILL.md`, `scripts/*.py`, `schemas/`, `references/`, `examples/`） |
| 冻结判据 | `work/CONTRACT.md` §1–§5（v1.1，§3.7 为 Lead 2026-11-23 11:50 追加的补充错误码） |
| 验收夹具 | `work/verify/fixtures/{fx-linear-pathway,fx-branch-feedback,fx-multi-compartment,fx-reference}`，由 `work/verify/fixtures/build_fixtures.py --check` 生成并自检（4/4 通过） |
| 夹具模型 | `work/verify/fixtures/models/*.json`（Agent 裁决后的 `figure_model.json`，逐元素带 `source{path,locator,quote,kind}`） |
| 验收代码 | `work/verify/harness.py`（`run` / `negative` / `report`），`work/verify/naive_baseline.py`（对照臂） |
| 证据产物 | `work/verify/harness_results.json`、`negative_results.json`、`baseline_results.json`、`_runs/**`、`_neg/**`、`_logs/**` |
| 模块指纹 | 每次运行记录在结果 JSON 的 `skill_module_sha256`（11 个 `scripts/*.py` 的 SHA-256）。**本文所有判定的基准是终验那一轮（16:1x/16:2x，冻结树 `files=30 / bytes=1,125,775`）的指纹** |

**版本漂移声明（必须读）**：本文经历 4 个采样点，**只有最后一轮是终验**：
① `run` 14:34（旧树，结论已作废）→ ② `run` 15:0x + `negative` 15:36（`layout.py=95463b0f…`，B1/B7/B8 未修）→ ③ `run` 16:04（**P0 轮**：`layout.py` 写入错误导致全红，已作废）→ ④ **终验 `run` 16:1x + `negative` 16:2x**（`run.py=2dd29550…`、`layout.py=600277da…`、`render_svg.py=2ab1b0a7…`、`compliance.py=a00d77be…`、`model.py=9c9a3b10…`）。
判据绑定方式：`harness_results.json` / `negative_results.json` 各自带 `skill_module_sha256`；**引用本文任何数字时必须同时引用那一轮的指纹**。若要作为提交证据，请在终冻树（`tree_sha256_v2 = 9caf3896814d22422739ee657222ced3814e8b79a43cb4fc13174e3a75f49f48`，`receipts/tree_sha256_v2.txt`）上再跑一次 `harness.py run` / `negative`（`harness.py report` 会打印当前指纹）。

夹具覆盖：**线性通路**（A：胞外刺激→跨膜受体→胞内激酶级联→核内 TF→基因→蛋白，含 `modification`/`transport`/`transcription`/`translation`）、**分支+反馈环**（B：HIF1A 并行分支 + 显式 `feedback` 收环 + 数据表/图例颜色通道）、**多区室跨膜受体**（C：extracellular/membrane/cytosol/nucleus 嵌套 + 复合物 + 膜锚定 + 区室内 `binding` + 跨边界 `transport` + `inhibition`）、**带原图案例**（D=fx-reference：材料内含 `materials/figure03_reference.svg`，用于原图比对诚实性判据）。A/C 用 `output_contract` **list** 形态、B/D 用 **dict** 形态（CONTRACT §3.7 双形态）。

## 3. 逐条判定

状态口径严格三分：**PASS**（本地已执行且成立）｜**FAIL**（本地已执行且不成立）｜**UNVERIFIED**（本地无法执行，**不等于通过**）｜**N/A**（该夹具/该维度不适用，附原因）。下列每条都给出可重跑命令或 `file:line`。

### 3.1 平台输出契约（`result.json`）

| # | 判据 | 状态 | 证据 |
|---|---|---|---|
| 3.1.1 | 顶层与 `output_contract` 内**同时**含 7 个平台字段（`case_id/status/editable_source/export_artifact/content_map/compliance_checks/exceptions`） | **PASS** | `harness_results.json` 中 3 个夹具各 4 条断言全 PASS；实现 `run.py:1150-1152`（顶层镜像）、`run.py:856`（`PLATFORM_CONTRACT_KEYS`） |
| 3.1.2 | `output_contract` 的 **list 形态**不得退化成 `{}`（平台 `example-input.json` 形态） | **PASS** | `ingest.py:371`（`normalise_output_contract`）；A/C 夹具用 list 形态，7 键在顶层与 `output_contract` 内均非空 |
| 3.1.3 | `status=partial` ⇒ `exceptions[]` 非空；`status=ok` 时 `exceptions` 允许为空列表 | **PASS** | 我在 14:28 曾把"exceptions 必须非空"写成硬判据，随后按 CONTRACT §4 字面修正为"仅 partial/failed 强制"（见 §6 变更记录），修正后 A/C PASS |
| 3.1.4 | error 级 `compliance_checks` fail ⇒ `status != ok` | **PASS** | `harness.py` 正向断言；`run.py:882-` `_platform_contract()` 把 model/layout error 折进 `compliance_checks` |
| 3.1.5 | `result.json` 自校验摘要可**独立重算**（我在 harness 内自己实现 canonical JSON + SHA-256，不复用实现函数） | **PASS** | `harness_results.json`：`result.json 自校验摘要可独立重算` = PASS（3/3 夹具） |
| 3.1.6 | `editable_source` 指向 `figures/figure.svg`，文件存在、`<image>`=0、7 命名图层、真 `<text>` | **PASS** | 每夹具 4 条断言全 PASS；SVG 实测 `data-entity-id`/`data-relation-id`/`data-container-id`/`data-legend-id` 四类锚点齐备且带 `data-prov`+`data-source-{path,locator,kind}` |
| 3.1.7 | `export_artifact` 只声明**真实**可用文件；`available=true` ⇒ 文件存在且 `bytes`/`sha256` 与实际一致；PNG magic+IHDR、PDF `%PDF-`、PDF 文本层可抽标签 | **PASS** | 每夹具 5 条断言全 PASS（`png_size()`/magic 由 harness 直接读字节，不用库） |

### 3.2 机制语义与布局（CONTRACT §3）

| # | 判据 | 状态 | 证据 |
|---|---|---|---|
| 3.2.1 | 冻结枚举落地（`mechanism_pathway`；7 新增实体类型；6 新增关系类型） | **PASS** | `mech.py:36-101`；A/B/C/D 模型 render 通过 |
| 3.2.2 | 方向语义不得与来源动词矛盾（`E_DIRECTION_UNSUPPORTED`） | **PASS** | `model.py:429`（`cue_candidates` 允许多族 cue）；A/B/C render 0 gate error |
| 3.2.3 | 膜定位（跨膜/膜锚定必须在 `kind=membrane` 容器内）（`E_MEMBRANE_PLACEMENT`） | **PASS** | `mech.py:417`；正例不触发；负例 DETECTED（见 §4） |
| 3.2.4 | `binding` 两端同区室（`E_COMPARTMENT_MISMATCH`） | **PASS** | `mech.py` `check_compartment_match`；正例（C 的 `r_pi3k_p85` 同为 `c_cyt`）不触发；负例 DETECTED |
| 3.2.5 | rank 与边方向一致 / 无 feedback 标记的有向环 ⇒ `E_FLOW_DIRECTION` | **PASS** | `mech.py:585`；B 的 feedback 环正例通过；负例 DETECTED |
| 3.2.6 | `(arrow, stroke)` 与 §3.4 冻结表一致、图面出现的 type 必须有图例条目 ⇒ `E_INTERACTION_STYLE_MISMATCH` | **PASS** | `mech.py:104`（RELATION_STYLE）；harness 用**自带的** CONTRACT 表核对 SVG 的 `data-arrow`/`data-stroke-style`（不读实现常量） |
| 3.2.7 | 图例 `encoding` 三向一致：mapping 值集合 == 图面真实取值集合 == 数据取值集合 | **PASS** | 我在 harness 内独立解析 SVG：`line_width` 逐边核对 `data-evidence-strength`↔`data-width-pt`↔1.4/1.0/0.6；`line_style` 逐边核对冻结表；`color` 核对 series 配色 |
| 3.2.8 | `node_size`：**面积 ∝ `abundance.value`**（CONTRACT §3.6），按「有/无警告」拆成可证伪判据 | **部分 PASS / 部分 FAIL** | 拆条结果（终验 16:1x）：<br>**(ii)** 警告指名元素 + 给出真实 factor/区间 → 夹具 A **PASS**<br>**(iii)** 有界编码在 `result.json` 的 `exceptions/limitations/compliance_checks` 可见 → 夹具 A **PASS**（**B9 已修**：`W_ABUNDANCE_SIZE_CLAMPED` 现在真的进了 `figure_issues.json` → `result.json`）<br>**(iv)** SVG 绘制盒 == layout 盒（无二次缩放）→ **三夹具全 PASS**（**B1 根因已修**：`render_svg.py` 原 `:539-547` 的 `_shrink_into({...w*scale...})` 已移除，只保留 layout 一侧；实测 drift x1.00/1.00，此前是 x0.68/0.68）<br>**(i)** 未被警告的元素严格 ∝ value → 夹具 A **N/A**（只有 1 个未警告元素）、夹具 **B FAIL（49.7%）**、夹具 **C FAIL（36.7%）** → 见 **B1-residual** |
| 3.2.9 | 膜带/区室几何真的把跨膜实体画在膜带内 | **UNVERIFIED**（部分） | 我核对的是**模型级** `E_MEMBRANE_PLACEMENT` 与产物级合规检查，未独立复算"实体矩形 ⊂ 膜带矩形"的几何包含关系（需解析 layout.json 的带坐标并做区间包含，本地未做） |
| 3.2.10 | `top_down` 垂直布局 | **N/A（已知边界）** | Lead 明确：`top_down` 已显式降级为横向渲染（`layout.py:872-884` `requested_orientation`/`orientation_fallback`/`W_ORIENTATION_RENDERED_HORIZONTAL`）。harness **不断言必须垂直**，只把请求朝向与渲染朝向记入 INFO；未在 `RESULT.md` 之外独立评估该降级的视觉代价 |
| 3.2.11 | `E_TRANSPORT_BOUNDARY` / `E_EDGE_THROUGH_NODE` | **UNVERIFIED** | Lead 明示这两个码在 CONTRACT 中冻结但 `layout.py` **未发出**；我在 `scripts/*.py` grep 0 命中，故**不**把它们当作已实现判据，也不编造触发证据 |

### 3.3 溯源与反造假

| # | 判据 | 状态 | 证据 |
|---|---|---|---|
| 3.3.1 | 每个实体/关系/容器/图例/panel/标题的 `source` **可解析**（我自己按 `path+locator+quote` 逐一核验，不调用实现的 `SourceIndex`） | **PASS** | 每夹具 2 条断言全 PASS（`resolve_source()`：路径必须落在 input 树内、locator 必须落在行范围内且 quote 在其中逐字出现、table 列必须存在） |
| 3.3.2 | `source.locator` **精确命中**引用行/列（而非全文兜底命中） | **PASS** | 与 3.3.1 同源断言；夹具由生成器保证 quote↔行号一致 |
| 3.3.3 | 编造逐字引文 ⇒ `E_QUOTE_NOT_FOUND`；材料里不存在的实体名 ⇒ `E_LABEL_NOT_IN_SOURCE`；凭空数值 ⇒ `E_NUMBER_NOT_IN_SOURCE` | **PASS** | 负例 DETECTED（`where` 命中注入元素）；材料腿已接通（`run.py` 传 `materials=inp`，`compliance.py:4373` 签名含 `materials=None`） |
| 3.3.4 | 基因/蛋白不得混用（`E_GENE_PROTEIN_CONFUSION`） | **PASS（判据存在，B2 待按新指纹复核）** | `mech.py:276-307`；产物侧 `compliance.py:3391`、`:3420` |
| 3.3.6 | `entities[].abundance.value` 的数值也必须来源可核 | **PASS（B8 已修）** | 终验负例 `invented_number` **DETECTED**（`E_NUMBER_NOT_IN_SOURCE`，`where` 命中 `e_fos_p`）；`model.py` 现把 `abundance.value/unit` 送进 `_check_numbers` |
| 3.3.5 | 无量纲 allowlist 列无单位**不报** error，仅 `W_UNIT_DIMENSIONLESS_ASSUMED`；有量纲无单位**必须**报 `E_UNIT_MISSING` | **PASS（B7 已修）** | 终验负例 `dimensionless_allowlist_no_error` **DETECTED**（`errors` 无 `E_UNIT_MISSING`、`warnings` 出现 `W_UNIT_DIMENSIONLESS_ASSUMED`）；另一侧 `dimensioned_column_no_unit` 仍 DETECTED（`E_UNIT_MISSING`）——**两个方向都验了** |

### 3.4 原图比对诚实性（`result.json.reference_comparison`）

| # | 判据 | 状态 | 证据 |
|---|---|---|---|
| 3.4.1 | `reference_comparison` 存在且含 `semantic_status` | **PASS** | `run.py:1184-1220`（`compare` 阶段）、`run.py:1150+`（finish 折入 result）；A/B/C 三门夹具 INFO 记录 `status=na checks=['REFERENCE_COMPARISON'] exceptions=1` |
| 3.4.2 | 材料**无**原图 ⇒ 必须 `semantic_status=na`、`reference_path` 为空、不得出现 `REF_LABEL_COVERAGE pass` | **PASS** | `harness.py::_check_reference_honesty`（用**独立的** `REFERENCE_STEMS` 规则自查材料是否真有原图）；A/B/C 三条断言全 PASS；负例 `ref_no_claim_without_reference` 隔离复现检出（15:39） |
| 3.4.3 | 材料**有**原图 ⇒ `semantic_status != na`（不得谎报"没比对"） | **PASS** | 负例 `ref_status_must_not_be_na_when_reference_present`（夹具 D）DETECTED：注入后 `semantic_status=na` 被我的独立发现规则抓出。**注意**：`compare` 需要 `--input` 才能发现原图（`run.py:1193` `discover_reference(inp)`），我第一次调用漏传 `--input` 导致该条假阴性，已在 harness 修正（§6.7） |

### 3.5 稳定性与鲁棒性

| # | 判据 | 状态 | 证据 |
|---|---|---|---|
| 3.5.1 | 同输入两次渲染 SVG 逐字节相同（确定性） | **PASS** | 每夹具 1 条断言；`harness_results.json` 记录 `sha` 前缀 |
| 3.5.2 | 未修订草稿不得被当作完成（`E_MODEL_NOT_REVISED`，exit 4） | **PASS** | 负例 DETECTED（`run.py:363-367`） |
| 3.5.3 | 空/缺失输入不得假装成功 | **PASS**（旁证） | 我 11:44 自跑 `selftest.py` 的 robustness 段；本轮 harness 未单列该负例（可补） |
| 3.5.4 | 单次运行 900 s / 64 次请求预算 | **UNVERIFIED** | 平台侧预算计数在本机不可观测；我测到的是本地墙钟（§7），不是请求数 |

## 4. 注入缺陷负例（≥20 条，三个要求）

口径：每条负例必须同时满足 ①**特定错误码**（CONTRACT 冻结码；artifact 级用 compliance check id）②`where` **命中被注入元素** ③该码在**原始输入上不触发**（否则计入 `vacuous_skips` 而非检出）。检出记录写入 `work/verify/negative_results.json`（含 `got_codes`/`baseline_codes`/`where`/`where_via`）。
命令：`& $PY work\verify\harness.py negative`。

**最终采样（2026-11-23 16:2x，冻结树 `run.py=2dd29550…` / `layout.py=600277da…` / `render_svg.py=2ab1b0a7…`）**：
**`injected=33 detected=31/33 vacuous_skips=[]`**，`where_field_absent_or_loose=5`（compliance 侧记录没有 `where` 字段，按 `detail`/`evidence` 命中计数）。**本轮无任何超时假阴性**，无需隔离复现折算。
仅剩 2 条未检出 = **B4**（`E_EVIDENCE_WIDTH_MISMATCH` / `E_ABUNDANCE_SIZE_MISMATCH`，契约冻结、实现未落地）→ 记 **UNVERIFIED**。
检出的码分布（终验）：`E_FLOW_DIRECTION×3`、`E_INTERACTION_STYLE_MISMATCH×3`、`E_LEGEND_DATA_MISMATCH×3`、`E_MEMBRANE_PLACEMENT×2`、`E_UNIT_MISSING×2`、`E_GENE_PROTEIN_CONFUSION×2`、`E_COMPARTMENT_MISMATCH`、`E_TYPE_CONSTRAINT_VIOLATION`、`E_LABEL_NOT_IN_SOURCE`、`E_QUOTE_NOT_FOUND`、`E_MODIFICATION_UNNAMED`、`E_MODEL_NOT_REVISED`、`E_PLATFORM_FIELD_MISSING`、`E_NUMBER_NOT_IN_SOURCE`（B8 修复后新增）、`W_UNIT_DIMENSIONLESS_ASSUMED`（B7 修复后新增）、原图诚实性 `REF_SEMANTIC_STATUS_HONEST`/`REF_NO_REFERENCE_CLAIM`；产物侧 compliance id：`svg_editable_text`、`raster_opens`、`pdf_opens`、`format_coverage`。

未检出的条目与归因（**未放宽任何判据**）：

| 未检出 | 归因 | 归类 |
|---|---|---|
| `evidence_width_mismatch`（`E_EVIDENCE_WIDTH_MISMATCH`） | CONTRACT §3.7 冻结，终验全树 grep 仍 **0 命中** | **B4 → UNVERIFIED（契约已冻结、实现未落地）**，按 Lead 指示不记 PASS/FAIL |
| `abundance_size_channel_missing`（`E_ABUNDANCE_SIZE_MISMATCH`） | 同上 | **B4 → UNVERIFIED** |

（上一轮（15:36）的 4 条未检出——`dimensionless_allowlist_no_error`、`invented_number`、`result_missing_platform_field`、`ref_no_claim_without_reference`、`binding_across_compartments`、`inhibition_retyped_activation`——**本轮全部转绿或已由我修正注入设计**：B7/B8/B3 由 Lead 修好、两条超时由静态负载消失后复现检出、后一条是我自己的注入样本选错，见 §6.6。）

## 5. 未验证范围（本地不可验，**不得记为 PASS**）

| 项 | 为什么本地不可验 | 现状 |
|---|---|---|
| 隐藏固定案例（3 个正式案例） | 组织方明确不暴露；本机只有 `task/datasets/**/example-input.json`（接口示意） | **UNVERIFIED**：我的 4 个夹具是**自建**的，不能替代隐藏案例 |
| `/skills` 实装与触发（`/skills/weekly-skill`）+ Skill 自动加载 | 平台运行时行为；本机无该 runner | **UNVERIFIED**：只验了 `SKILL.md` 的 frontmatter/结构与脚本可执行性 |
| 人工视觉判断（图是否"读得懂"、箭头是否遮挡文字、配色可辨性） | 需要人眼评审 | **UNVERIFIED**：我用几何断言（无重叠/越界/溢出的门禁）+ 像素非空代替，**不**声称视觉质量 |
| 平台计分 / 对照白板 / 加载 Skill 前后的真实增益 | 需平台跑 ARM + 白板 | **UNVERIFIED**：`work/verify/BASELINE.md` 是**本机代理对照**，不是平台白板 |
| 64 次模型请求 / 900 s 预算的真实消耗 | 平台侧计数 | **UNVERIFIED** |
| GitHub 链接可达性（附加 5 分） | 需外部网络/未登录浏览 | **UNVERIFIED**（未由我复核；`GITHUB_URL.txt` 存在） |
| `E_TRANSPORT_BOUNDARY` / `E_EDGE_THROUGH_NODE` | 实现未发出这两个码 | **UNVERIFIED**（见 3.2.11） |
| 膜带几何包含关系（实体 ⊂ 膜带） | 未做 layout 坐标级复算 | **UNVERIFIED**（见 3.2.9） |
| PDF 字体内嵌在**平台** PDF 阅读器中的表现 | 本机只有 pypdf | 部分可验（pypdf 打开+抽文本 PASS）；阅读器端 **UNVERIFIED** |

## 6. 验收过程变更记录（自查：我改过判据的地方，以及为什么不算"放宽"）

1. **14:2x 撤回 12:19 快照中 12 条 FAIL**：原断言把 `ent:`→`data-ent-id` 拼错（正确属性名是 `data-entity-id`），且第 3 个夹具的锚点属性映射错误。**这是 harness 的 bug，不是实现缺陷**，已修正并用 `Select-String`/SVG 原文核对（`data-entity-id` 等四类实测计数 18/21/12/25）。
2. **14:2x 图例判据改为"按 channel 合并映射"**：CONTRACT §3.6 的 `legend[].encoding` 是**每通道一条**，`mech.py:854`（`generate_legend_encoding`）也按每通道生成。我的夹具原先"每 type 一条 encoding"，被 `mech.py:986`（`encodings_consistent`）正确拒绝——**是实现判据对、我的夹具形状错**，已改为"swatch 条目 + 每通道 encoding 条目"。
3. **14:28 `exceptions` 非空判据改为条件判据**：仅当 `status != ok` 要求非空（CONTRACT §4 字面）。这不是放宽：`partial` 仍强制非空（仍有一条独立断言）。
4. **14:30 夹具 B 的蛋白名由 "VEGFA 蛋白" 改为 "VEGFA protein"**：CONTRACT §3.2 自己举的例就是 `LDHA protein`。原写法触发产物侧 `E_GENE_PROTEIN_CONFUSION` 误报（见 B2），我改用 CONTRACT 自己的命名约定，**同时把误报作为缺陷记录在案**，而不是删掉该判据。
5. **未改动**：`work/submission/**` 任何文件（含临时注入；所有注入都在 `work/verify/_neg/**` 的模型副本上做）。写冻结期间我只读实现树。
6. **15:0x 修正两条负例的注入设计**（是我的设计错，不是实现错）：
   - `inhibition_retyped_activation` → 改为 `retyped_type_unsupported`：原注入把 `Akt1 磷酸化 FOXO3 并抑制其转录活性` 的边改成 `activation`，而该句**同时含** `磷酸化`（activation 族 cue），`model.py:429` 的"多族 cue 皆可支持"策略下 activation **本就合法** → 我的注入选错了样本。改用 `r_egfr_grb2`（quote 只含`激活`）改写为 `translation`。
   - `dimensionless_allowlist` → 改用材料**自带**的 `fold_change` 列（§3.7 allowlist 明列）只清空单位，避免我原先自造 `p_value` 列时把"数值不在来源里"（`E_NUMBER_NOT_IN_SOURCE`）混进来污染归因。**结果：该条仍 MIS SED**，且归因为 B7（allowlist 未接上），判据未放宽。
7. **15:1x 增加 150 s 单例超时上限**（`NEG_TIMEOUT_S`）：被 B6 的偶发卡顿拖死过一次整轮（14:47 `render` >600 s），改为"超时即记显式 MISSED + TIMEOUT"，不静默跳过、不改变判据。
8. **15:2x 修正 `compare` 调用漏传 `--input`**：`cmd_compare` 用 `discover_reference(inp)`（`run.py:1193`）在 **input 根**下找原图；我原先只传 `--work/--output`，`/input` 解析不到 → `semantic_status` 恒为 `na`，造成 `ref_status_must_not_be_na_when_reference_present` 假阴性。补齐 `--input <fixture>` 后该条检出（夹具 D 的 `materials/figure03_reference.svg` 被正确发现）。
9. **15:2x 移除每夹具第二次 `finish`**：正例套件原先在确定性重渲染后再跑一次 `finish`（触发过一次 600 s 卡顿）。改为**在既有 `result.json` 上直接校验**，并**新增**一条更强断言：`finish` 记录的 `artifacts[svg].sha256` 必须与重渲染后的 SVG 文件一致（防陈旧摘要）。判据变强、调用变少。
10. **16:0x–16:2x 终验轮：把 B1 拆成四条可证伪判据（Lead 要求，判据变强不是放宽）**：
    - **(i)** 未被 `W_ABUNDANCE_SIZE_CLAMPED` 警告的元素，面积必须严格 ∝ value（`lo/hi >= 0.97`，2 位小数 mm 的数值容差）；
    - **(ii)** 被警告的元素必须被**指名**，且警告文本含真实 factor 与绘制区间；
    - **(iii)** 披露必须出现在 `result.json` 的 `exceptions`/`limitations`/`compliance_checks`，且是**含 abundance 语义 + 该元素 id 的记录**——我第一版写成"`eid` 出现在这三个字段的序列化文本里"，被 `content_map` 枚举全部 id 的事实**假阴/假阳双向污染**（A 夹具曾因此假 PASS），收紧为现在的写法；这是**收紧**。
    - **(iv)** SVG 绘制盒必须等于 layout 盒（数学上：`data-node-w-mm/w_mm ≈ 1` 且 `data-node-h-mm/h_mm ≈ 1`）——这一条把"二次缩放"从"面积比例异常"升级为**可直接定因**的断言，正是它把 B1 钉到 `render_svg.py:539-547`。
    - 警告来源同时读 `figure_issues.json` **与** `layout.json`（否则 (i) 在披露通道断链时会变成"全元素 strict"的空判据）；(iii) 只读 `result.json`（平台视角）。两者分开正是为了不掩盖 B9。
11. **16:1x 复跑期间发现并上报 P0**（`layout.py:3875 NameError: degrade`，管线全断；我 `run8` = 115 PASS / 84 FAIL / SVG 全空），修好后重跑终验；本轮结论只认 16:12 冻结指纹下的两次运行。

## 7. 阻断项 / 未解决缺陷（severity + 锚点）

**B1（中，**根因已修、残余仍在**）节点面积不是纯粹的 value 编码 —— 违反 CONTRACT §3.6 "面积 ∝ value"**
- **已修（我复核通过）**：
  - `render_svg.py` 的二次缩放已移除（原 `:539-547` 对已缩放盒再乘 `ABUNDANCE_SCALE_RANGE=(0.68,1.55)`）→ 我的断言 **(iv)「SVG 绘制盒 == layout 盒」三夹具全 PASS**（此前 drift 恒为 x0.68/0.68）。
  - `layout.py:1245` 的因子钳位改为精确 `sqrt(v/ref)` + 逐元素 `W_ABUNDANCE_SIZE_CLAMPED`。
  - `W_ABUNDANCE_SIZE_CLAMPED` 现在经 `run.py:_do_render` 合并进入 `figure_issues.json` 并到 `result.json`（夹具 A 的 `compliance_checks`/`limitations` 可见）→ 我的断言 **(iii) 逐元素披露 PASS**（**B9 已修**）。
- **残余（本轮 2 条 FAIL 的唯一根因，未修）**：`layout.py` 的节点盒是 **「文本/列宽驱动的基础盒 × sqrt(value/ref)」**，基础盒本身随标签长度与层级列宽变化，因此 `area = base(文本,列宽) × (value/ref)` —— **面积里混进了标签长度**，不是纯 value 编码。
- 实测（`_runs/*/work/layout.json`，终验 16:1x）：

  | 夹具 | 元素 | abundance | size_scale | layout 盒 | 面积 | **基础盒面积 (=area/s²)** |
  |---|---|---|---|---|---|---|
  | fx-branch-feedback | `e_hif1a`（`HIF-1alpha`） | 8.0 | 0.6325 | 16.7428×5.2037 | 87.125 | **217.78** |
  | fx-branch-feedback | `e_vegf_p`（`VEGFA protein`） | 20.0 | 1.0 | 21.0396×5.2037 | 109.484 | **109.48** |
  | fx-multi-compartment | `e_igf1r`（`IGF1R`） | 5.5 | 1.0 | 15.0×7.2 | 108.000 | **108.00** |
  | fx-multi-compartment | `e_pi3k`（`PI3K`） | 2.2 | 0.6325 | 10.1291×6.7337 | 68.206 | **170.49** |

  ⇒ 基础盒差 1.99×（B）/1.58×（C），面积比 0.796 而 value 比 0.4，故判 FAIL（spread 49.7% / 36.7%）。
- 锚点：`layout.py:1947-1950`
  `s = size_scale.get(eid, 1.0)` / `w = max(text_w + 2.0*gaps["node_pad_x"], w * s)` / `h = max(len(lines)*line_h + 2.0*gaps["node_pad_y"], h * s)`
  （上一步 `_size_node(...)` 给出的 `w,h` 由标签文本与列宽预算决定；`layout.py:1935` 的 `size_scale = ctx.get("size_scale")`）。
- 建议（不属我写域，二选一）：① 让**面积由 value 决定**、标签只做字号/换行降级（超限时发 `W_LABEL_DEGRADED`，与已有阶梯合并）；② 若保留文本驱动盒，则在 CONTRACT 上把 node_size 通道改述为"方向性编码（大→大）"并在 §3.7 实现 `E_ABUNDANCE_SIZE_MISMATCH` 做上限校验。当前状态是**两种语义混用**，图例却写着"面积 ∝ value"。

**B2（已修，我复核通过）产物侧 `_norm_name` 保留 CJK**
- 旧结论（`compliance.py=a00d77be…` 之前）作废。终验实测（当前冻结树 `compliance.py=a00d77be…`）：
  `_norm_name('VEGFA 基因') = 'vegfa基因'`、`_norm_name('VEGFA 蛋白') = 'vegfa蛋白'` ⇒ **可区分**（`True`）。
- 依据：`compliance.py:2146+` 的 docstring 明确"CJK preserved…only separators and punctuation are dropped"。
- ⇒ 中文材料下 `"XXX 基因"/"XXX 蛋白"` 不再误判为同名；**B2 关闭**。

**B4（中，UNVERIFIED）`E_EVIDENCE_WIDTH_MISMATCH` / `E_ABUNDANCE_SIZE_MISMATCH` 无实现**（CONTRACT §3.7 冻结为 error 级；终验全树 grep 仍 0 命中）。按 Lead 指示统一记 **UNVERIFIED（契约已冻结、实现未落地）**，不记 PASS 也不记 FAIL —— 这两条也就是负例 `negative` 里仅剩的 2 条未检出。

**B7（已修，我复核通过）无量纲 allowlist**
- 终验负例 `dimensionless_allowlist_no_error` **DETECTED**：清空 `data.units` 与 `series[].unit`（列名 `fold_change`，在 §3.7 allowlist 上）后 **`errors` 不含 `E_UNIT_MISSING`**、`warnings` 出现 **`W_UNIT_DIMENSIONLESS_ASSUMED`**。
- 反方向也验了：`dimensioned_column_no_unit`（列名 `concentration`）仍 **DETECTED `E_UNIT_MISSING`** ⇒ 没有为了通过而放宽"有量纲必须有单位"。

**B8（已修，我复核通过）`abundance.value` 来源核对**
- 终验负例 `invented_number` **DETECTED**：`abundance.value=987654` ⇒ `E_NUMBER_NOT_IN_SOURCE`，`where` 命中注入元素 `e_fos_p`。

**B9（已修，我复核通过）有界编码披露到达平台可见字段**
- `W_ABUNDANCE_SIZE_CLAMPED` 现在出现在 `work/figure_issues.json` 的 `warnings`（夹具 A：`gate warnings :: ['W_ABUNDANCE_SIZE_CLAMPED', …]`），并进入 `result.json` 的 `compliance_checks`/`limitations` ⇒ 我的断言 **(iii) 逐元素披露 PASS**。

**P0（已修，复现与复核）`layout.py:3875 NameError: degrade`**
- 16:04:31 那次写入使 `render` 对所有夹具 `exit 2`（`NameError: name 'degrade' is not defined`，`layout.py:3875`；`degrade` 当时只在 `:1936/:2253/:2288` 三个函数内定义），我 `run8` 因此 115 PASS / **84 FAIL**、SVG 全空（`sha=e3b0c442…`）。已当场告警。
- 修复后（16:12 冻结树）四夹具 `render/export/finish` 全部 `exit 0`、`status=ok`，本轮 `run` = 207 PASS / 2 FAIL；**该 P0 关闭**。留档原因：它证明"实现方写入期间的瞬时红/绿必须按指纹绑定"，也说明我的套件能在 24 s 内把整条管线打断如实报出来。

**B6（低-中，偶发）CLI 阶段超过超时上限未返回（4 次观测，全部为环境争用，本轮未出现）**
- 观测：`run2`（13:0x，夹具 B 第二次 `render`，>600 s）；`neg1`（14:47，某 `render`，>600 s）；`neg4`（15:1x，`binding_across_compartments` 的 `render`，>150 s）；`neg5`（15:36，`result_missing_platform_field` 的 `export` 与 `ref_no_claim_without_reference` 的 `render`，>150 s）。
- 反证（两向都记，避免把环境问题说成实现缺陷）：① `binding_across_compartments` 同一次变异**单独复现** → **0.5 s** 返回且正确报 `E_COMPARTMENT_MISMATCH`；② 15:36 超时的两条在 15:39 静默后单独复现**全部检出**（30.9 s / 36.8 s）；③ **终验 16:2x 的 `negative` 一轮 33 条无任何超时**（`detected=31/33`，仅剩 B4 两条）。
- 判定：**宿主机争用**（观测时段同机 10+ python 进程，含实现方 selftest/integration 与我的多轮套件）。对平台的风险仍成立（预算 900 s/案例），但**不是实现缺陷**；建议实现侧加阶段级进度日志以便平台侧归因。
- 我在 harness 侧保留 **150 s 上限**（`NEG_TIMEOUT_S`，正例用 600 s），超时记**显式 MISSED + TIMEOUT 原因**并附隔离复现结论，不静默跳过。

（历史条目：B7 与 B8 在 15:2x 的旧指纹下曾是"未解决缺陷"，Lead 已在 `model.py`（15:41:55）修好，本轮终验两条负例**均检出** ⇒ 已上移为"已修，我复核通过"，见上。B3、B2、B5、P0 同理已在各处标注关闭。）

## 8. 原始输出（命令 + 计数，贴原始）

```
PS D:\Borium_Contest\ARMI2611000060v1> & $PY work\verify\harness.py run          # 终验 16:1x，冻结树 30 文件/1,125,775 B
  [INFO] fx-linear-pathway gate warnings :: ['W_ABUNDANCE_SIZE_CLAMPED', 'W_CHART_SERIES_DERIVED', 'W_COMPARTMENT_NESTING', 'W_ORIENTATION_RENDERED_HORIZONTAL']
  [INFO] fx-linear-pathway node_size 面积/丰度比（原始值） :: {'e_egfr': 16.7777, 'e_fos_p': 4.7995}
  [INFO] fx-linear-pathway 面积编码分类 :: strict(未警告)=['e_fos_p'] clamped(已警告)=['e_egfr']
  [N/A] fx-linear-pathway 面积编码(i)：未被警告的元素面积必须 ∝ value（严格） :: 只有 1 个未被警告的元素（e_fos_p），无法构成比例对照；其余元素已被逐元素警告披露
  [INFO] fx-branch-feedback node_size 面积/丰度比（原始值） :: {'e_hif1a': 10.8905, 'e_vegf_p': 5.4742}
  [FAIL] fx-branch-feedback 面积编码(i)：未被警告的元素面积必须 ∝ value（严格） :: area/value={'e_hif1a': 10.8905, 'e_vegf_p': 5.4742} spread=49.7%
  [N/A] fx-branch-feedback legend(color) 与图面配色对应 :: figure.kind=mechanism_pathway 不绘制数据 series
  [INFO] fx-multi-compartment node_size 面积/丰度比（原始值） :: {'e_igf1r': 19.6364, 'e_pi3k': 31.0027}
  [FAIL] fx-multi-compartment 面积编码(i)：未被警告的元素面积必须 ∝ value（严格） :: area/value={'e_igf1r': 19.6364, 'e_pi3k': 31.0027} spread=36.7%

POSITIVE SUITE (run): 207 PASS / 2 FAIL / 0 UNVERIFIED / 6 N/A (169.2s)
EXIT=1
# (ii)/(iii)/(iv) 未出现在输出里 = PASS：
#   (ii)  A 夹具警告指名元素 PASS
#   (iii) A 夹具 W_ABUNDANCE_SIZE_CLAMPED 已在 result.json 可见 PASS  ← B9 修好
#   (iv)  三夹具 SVG 绘制盒 == layout 盒 PASS                        ← B1 根因（二次缩放）修好

PS D:\Borium_Contest\ARMI2611000060v1> & $PY work\verify\harness.py negative       # 终验 16:2x，同一冻结树
injected=33 detected=31/33 vacuous_skips=[]
where_field_absent_or_loose=5 (compliance 侧记录没有 where 字段；按 detail/evidence 命中计数)
missed=['evidence_width_mismatch', 'abundance_size_channel_missing']
EXIT=1
# 仅剩 B4 两条（契约 §3.7 冻结、实现未落地）→ UNVERIFIED；本轮无超时假阴性

PS D:\Borium_Contest\ARMI2611000060v1> & $PY _shared\tools\validate_skill_submission.py ARMI2611000060v1\work\submission
{"status": "ok", "files": 30, "bytes": 1125775, "name": "biological-mechanism-pathway-figure", "errors": []}
VALIDATE_EXIT=0

# B2 复核（终验指纹下）
_norm_name('VEGFA 基因') = 'vegfa基因' ; _norm_name('VEGFA 蛋白') = 'vegfa蛋白' ; distinct = True   → B2 关闭

# P0 复现（16:04 写入的那一版 layout.py，已修）
render → "error": "NameError: name 'degrade' is not defined", "exit_code": 2
       File ".../layout.py", line 3875, in layout   eid, s, nodes_out[eid], degrade, warnings)
# 那时 run8 = 115 PASS / 84 FAIL / 3 UNVERIFIED / 7 N/A (24.3s)，SVG sha=e3b0c44298fc1c14（空串）

# P0 反证：隔离复现同一次变异（低负载）
render exit 4 in 0.5s     issues: ['E_COMPARTMENT_MISMATCH']     # 15:2x 采样，证明 B6 是环境争用
```

## 9. 复核建议（给 Lead）

1. **B1-residual 是当前唯一正例 FAIL 的根因**：节点面积 = 「文本/列宽驱动的基础盒」× `sqrt(value/ref)`，所以面积里混进了标签长度（实测基础盒面积 B 217.78 vs 109.48、C 170.49 vs 108.00）。要么让**面积由 value 决定**、标签只做字号/换行降级，要么在 CONTRACT 上把 node_size 通道改述为方向性编码并实现 `E_ABUNDANCE_SIZE_MISMATCH` 做上限校验。**当前图例写"面积 ∝ value"而实现是混合语义**，这才是会被评审抓的点。
2. **B4 两个冻结码（`E_EVIDENCE_WIDTH_MISMATCH` / `E_ABUNDANCE_SIZE_MISMATCH`）仍是"契约有、实现无"**：按你本轮的决定不实现，我维持 **UNVERIFIED**，并建议在 `RESULT.md` 与 CONTRACT §3.7 上明确标注"未落地 → 以 UNVERIFIED 处理"，**不要**让报告看起来像验过了。
3. **B2/B7/B8/B9/P0 均已复核关闭**（证据见 §7 各条）；B3 亦关闭。
4. **B6（偶发卡顿）**不是实现缺陷（三次反证 + 终验一轮 33 条零超时），但**与平台 900 s 预算叠加时是真实风险**；若还想降风险，给 `render/export/finish` 加阶段级进度日志即可，不必改逻辑。
5. 我的 4 个夹具与 `harness.py` 已落盘（`work/verify/fixtures/**`、`models/**`），任何人可 `python work/verify/fixtures/build_fixtures.py --check` + `harness.py run|negative` 复现本文全部数字；**判定请以 `harness_results.json` / `negative_results.json` 里的 `skill_module_sha256` 为准**（终验那轮的 11 个哈希已记录）。
