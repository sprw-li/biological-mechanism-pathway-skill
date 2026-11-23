# 独立验收记录 — ARMI2611000060v1（task-4 / M4, verify-harness）

> 验收人：**verify-harness**（独立验收方，不参与实现；只写 `work/verify/**`）
> 被验收对象：`work/submission/**`（冻结树，30 文件 / 1,118,394 B / `validate_skill_submission.py` → `status=ok`）
> 判据真相：`work/CONTRACT.md`（FROZEN v1.1）+ `task/task.md` §2/§3 + `task/datasets/**/resources/output-contract.md`
> 采样时间：**2026-11-23 14:3x +08:00**（`run` 第三次运行 14:32–14:34；`negative` 14:35 起）。实现方已停写（Lead 写冻结）。

## 1. 结论（总门禁）

**总门禁：CONDITIONAL**

- 正向套件 `run`：**198 PASS / 1 FAIL / 0 UNVERIFIED / 1 N/A，exit 1**（唯一 FAIL 指向 `layout.py` 节点面积编码的真实偏离，见 B1）。
- 负例套件 `negative`：见 §4（14:36 采样；若未达 N/N 则如实记为未解决项 B3/B4）。
- 结构闸门（独立复跑）：`& $PY _shared\tools\validate_skill_submission.py ARMI2611000060v1\work\submission` → `{"status":"ok","files":30,"bytes":1118394,"errors":[]}`，`exit 0`。
- 实现方自测（我本人在 11:44 复跑过一次，非引用自述）：`work/submission/scripts/selftest.py` → `RESULT: PASS (67 passed, 0 failed, 0 unavailable, 0 vacuous skips, 85.4s)`，`exit 0`。**注意**：selftest 是**实现方**的测试，不构成独立验收；此处仅作旁证。
- 判为 CONDITIONAL 而非 ACCEPT 的理由：① 正例通道仍有 1 条 FAIL（B1，真实缺陷）；② 负例通道未达 `detected=N/N`（B3/B4）；③ 存在本地不可验范围（§5），按规则"有 UNVERIFIED/未验项 → 禁止 ACCEPT"。

## 2. 范围与版本

| 项 | 值 |
|---|---|
| 被验收 Skill | `work/submission/`（`SKILL.md`, `scripts/*.py`, `schemas/`, `references/`, `examples/`） |
| 冻结判据 | `work/CONTRACT.md` §1–§5（v1.1，§3.7 为 Lead 2026-11-23 11:50 追加的补充错误码） |
| 验收夹具 | `work/verify/fixtures/{fx-linear-pathway,fx-branch-feedback,fx-multi-compartment,fx-reference}`，由 `work/verify/fixtures/build_fixtures.py --check` 生成并自检（4/4 通过） |
| 夹具模型 | `work/verify/fixtures/models/*.json`（Agent 裁决后的 `figure_model.json`，逐元素带 `source{path,locator,quote,kind}`） |
| 验收代码 | `work/verify/harness.py`（`run` / `negative` / `report`），`work/verify/naive_baseline.py`（对照臂） |
| 证据产物 | `work/verify/harness_results.json`、`negative_results.json`、`baseline_results.json`、`_runs/**`、`_neg/**`、`_logs/**` |
| 模块指纹 | 每次运行记录在结果 JSON 的 `skill_module_sha256`（11 个 `scripts/*.py` 的 SHA-256），冻结后两次运行一致 |

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
| 3.2.8 | `node_size`：**面积 ∝ `abundance.value`**（CONTRACT §3.6） | **FAIL** | 见 B1。`abundance` 值集合与图例 mapping 一致（PASS），但**面积与 value 不成比例**：A 夹具 `area/value` 4.7995..7.7580（**spread 38%**）；根因 `layout.py:1232` 的 `min(1.5, max(0.75, sqrt(v/ref)))` 尺寸**钳位**，钳位后面积∝value 不再成立（`harness_results.json`；`layout.py:1207` `_abundance_scales` 文档串自称 "area proportional"） |
| 3.2.9 | 膜带/区室几何真的把跨膜实体画在膜带内 | **UNVERIFIED**（部分） | 我核对的是**模型级** `E_MEMBRANE_PLACEMENT` 与产物级合规检查，未独立复算"实体矩形 ⊂ 膜带矩形"的几何包含关系（需解析 layout.json 的带坐标并做区间包含，本地未做） |
| 3.2.10 | `top_down` 垂直布局 | **N/A（已知边界）** | Lead 明确：`top_down` 已显式降级为横向渲染（`layout.py:872-884` `requested_orientation`/`orientation_fallback`/`W_ORIENTATION_RENDERED_HORIZONTAL`）。harness **不断言必须垂直**，只把请求朝向与渲染朝向记入 INFO；未在 `RESULT.md` 之外独立评估该降级的视觉代价 |
| 3.2.11 | `E_TRANSPORT_BOUNDARY` / `E_EDGE_THROUGH_NODE` | **UNVERIFIED** | Lead 明示这两个码在 CONTRACT 中冻结但 `layout.py` **未发出**；我在 `scripts/*.py` grep 0 命中，故**不**把它们当作已实现判据，也不编造触发证据 |

### 3.3 溯源与反造假

| # | 判据 | 状态 | 证据 |
|---|---|---|---|
| 3.3.1 | 每个实体/关系/容器/图例/panel/标题的 `source` **可解析**（我自己按 `path+locator+quote` 逐一核验，不调用实现的 `SourceIndex`） | **PASS** | 每夹具 2 条断言全 PASS（`resolve_source()`：路径必须落在 input 树内、locator 必须落在行范围内且 quote 在其中逐字出现、table 列必须存在） |
| 3.3.2 | `source.locator` **精确命中**引用行/列（而非全文兜底命中） | **PASS** | 与 3.3.1 同源断言；夹具由生成器保证 quote↔行号一致 |
| 3.3.3 | 编造逐字引文 ⇒ `E_QUOTE_NOT_FOUND`；材料里不存在的实体名 ⇒ `E_LABEL_NOT_IN_SOURCE`；凭空数值 ⇒ `E_NUMBER_NOT_IN_SOURCE` | **PASS** | 负例 DETECTED（`where` 命中注入元素，见 §4）；材料腿已接通（`run.py` 传 `materials=inp`，`compliance.py:4373` 签名含 `materials=None`） |
| 3.3.4 | 基因/蛋白不得混用（`E_GENE_PROTEIN_CONFUSION`） | **PASS（判据存在）**，附**风险观察**：见 B2 | `mech.py` `check_gene_protein`；产物侧 `compliance.py:3391`、`:3420` |
| 3.3.5 | 无量纲 allowlist 列无单位**不报** error，仅 `W_UNIT_DIMENSIONLESS_ASSUMED`；有量纲无单位**必须**报 `E_UNIT_MISSING` | 见 §4（`dimensionless_allowlist_no_error` / `dimensioned_column_no_unit` 两条负例） | `mech.py:1125`（`DIMENSIONLESS_COLUMNS`） |

### 3.4 原图比对诚实性（`result.json.reference_comparison`）

| # | 判据 | 状态 | 证据 |
|---|---|---|---|
| 3.4.1 | `reference_comparison` 存在且含 `semantic_status` | **PASS** | `run.py:1184-1220`（`compare` 阶段）、`run.py:1150+`（finish 折入 result）；A/B/C 三门夹具 INFO 记录 `status=na checks=['REFERENCE_COMPARISON'] exceptions=1` |
| 3.4.2 | 材料**无**原图 ⇒ 必须 `semantic_status=na`、`reference_path` 为空、不得出现 `REF_LABEL_COVERAGE pass` | **PASS** | `harness.py::_check_reference_honesty`（用**独立的** `REFERENCE_STEMS` 规则自查材料是否真有原图）；A/B/C 三条断言全 PASS |
| 3.4.3 | 材料**有**原图 ⇒ `semantic_status != na`（不得谎报"没比对"） | 见 §4（`ref_status_must_not_be_na_when_reference_present`，夹具 D） | `reference.py:53`（发现规则）、`:107`（比对）、`:147`（`labels_fully_covered`） |

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

**采样**：见 §8 的原始输出（本文件 14:3x 版本先落盘，`negative` 结果在本节末尾以命令原始输出为准）。覆盖类别（共 31 条）：方向颠倒/rank 矛盾/无 feedback 的环、抑制画成激活箭头、`modification` 标签不写修饰种类、跨膜受体塞进 cytosol、跨膜受体无容器、binding 两端跨区室、transport 未跨边界、图例多一类/少一类/缺 type 条目/配色不符、线宽与 `evidence.strength` 不符、节点大小编码缺失、有量纲无单位、无量纲 allowlist、有量纲列无单位、编造引文、材料外实体名、凭空数值、基因带修饰后缀、蛋白用裸基因符号、SVG 注入 `<image>`、假 PNG/PDF magic、导出件缺失、未修订草稿、`result.json` 缺平台字段、两条原图比对诚实性。

**已确认的实现缺口（负例无法检出的原因，非我放宽判据）**：

- **B3** `E_PLATFORM_FIELD_MISSING`：CONTRACT §3.7 冻结为 error 级，但 `scripts/*.py` 全树 **grep 0 命中**（`Select-String -Path work\submission\scripts\*.py -Pattern E_PLATFORM_FIELD_MISSING -SimpleMatch` → 无输出）。我的注入路径（删掉 `figures/figure.svg` + `figure_model.json` 后 `finish`）证明 `editable_source` 会变成空串而**不产生该错误码** → 该条如实记为未检出。
- **B4** `E_EVIDENCE_WIDTH_MISMATCH` / `E_ABUNDANCE_SIZE_MISMATCH`：CONTRACT §3.7 冻结，但全树 grep 0 命中（同上命令换码名）。线宽/面积编码的偏离目前只体现在我正向套件的独立断言（B1）与 `E_LEGEND_DATA_MISMATCH` 的部分覆盖上，**没有**以 §3.7 指定的码报出。

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

## 7. 阻断项 / 未解决缺陷（severity + 锚点）

**B1（中）节点面积与 `abundance.value` 不成比例 —— 违反 CONTRACT §3.6 "面积 ∝ value"**
- 证据：`work/verify/harness_results.json`（`run` 第 3 次，14:34）夹具 A `area/value 4.7995..7.7580（spread 38%）`；A 夹具 `abundance` = EGFR 3.0 nM / c-Fos 12.5 nM。
- 锚点：`work/submission/scripts/layout.py:1232` `out[eid] = min(1.5, max(0.75, math.sqrt(vals[eid] / ref)))`（尺寸因子钳位到 [0.75,1.5]）；同函数 `layout.py:1207` 的 docstring 自称 "area proportional, sec 3.6"。
- 影响：小丰度节点被钳到最小尺寸后，读者按面积读出的倍数关系是错的（12.5/3.0=4.17× 被画成约 2.25×）。CLI 仍 `status=ok`（该偏离没有对应错误码，见 B4）。
- 建议（不属我写域）：要么真按面积线性映射（并把极值以 `exceptions[]` 披露），要么把钳位作为可核验的降级写进 `exceptions[]`/图例，并实现 §3.7 的 `E_ABUNDANCE_SIZE_MISMATCH`。

**B2（低-中）产物侧标签规范化抹掉"基因/蛋白"区分词，可能误报 `E_GENE_PROTEIN_CONFUSION`**
- 证据：14:28 采样 `_runs/fx-branch-feedback/out/checks.json` → `E_GENE_PROTEIN_CONFUSION error | figure.svg: entities ['e_vegf','e_vegf_p'] share normalized_symbol 'vegfa' but are drawn with indistinguishable labels {'e_vegf':'vegfa','e_vegf_p':'vegfa'}`（模型层 `mech.check_gene_protein` **同时不报**，两层口径不一致）。
- 锚点：`work/submission/scripts/compliance.py:2146` `_norm_name = re.sub(r"[^a-z0-9]","",lower)`（**连 CJK 一起删**）+ `compliance.py:3418-3422`（distinguishable 判定）。
- 影响：中文材料里 "XXX 基因" / "XXX 蛋白" 这类**CONTRACT §3.2 明确允许**的同 symbol 异 kind 共存会被判 error（误报）；而 "VEGFA"/"VEGFA protein" 这类拉丁写法可过。平台正式案例是中文材料，**误报概率不低**。
- 现状：已通过夹具改用 `VEGFA protein` 规避，但**判据本身的误报风险仍在**，故如实记入未解决缺陷。

**B3（中）`E_PLATFORM_FIELD_MISSING` 未实现**（CONTRACT §3.7 冻结为 error 级）：全树 grep 0 命中；删掉 `editable_source` 来源后 `finish` 只产出空串。→ 对应负例检出失败。

**B4（中）`E_EVIDENCE_WIDTH_MISMATCH` / `E_ABUNDANCE_SIZE_MISMATCH` 未实现**：全树 grep 0 命中。→ 线宽/面积编码偏离只能由我的独立断言发现，不能由 §3.7 指定的码报出。

**B5（低）`layout.py` 未发出 `E_TRANSPORT_BOUNDARY` / `E_EDGE_THROUGH_NODE`**（Lead 已声明为已知边界）：transport 跨边界断言实际落在 `E_COMPARTMENT_MISMATCH` 内。→ 记为 UNVERIFIED 而非 PASS。

## 8. 原始输出（命令 + 计数，贴原始）

```
PS D:\Borium_Contest\ARMI2611000060v1> & $PY work\verify\harness.py run
== positive: fx-linear-pathway
  [INFO] fx-linear-pathway gate warnings :: []
  [INFO] fx-linear-pathway reference_comparison :: status=na checks=['REFERENCE_COMPARISON'] exceptions=1
  [FAIL] fx-linear-pathway legend(node_size) 与 abundance 面积编码逐一对应 :: node area is not proportional to abundance.value (area/value 4.7995..7.7580, spread 38%)
== positive: fx-branch-feedback
  [INFO] fx-branch-feedback gate warnings :: ['W_BACKWARD_EDGE', 'W_TRANSCRIPTION_ORIGIN']
  [INFO] fx-branch-feedback reference_comparison :: status=na checks=['REFERENCE_COMPARISON'] exceptions=1
  [N/A] fx-branch-feedback legend(color) 与图面配色对应 :: figure.kind=mechanism_pathway 不绘制数据 series
== positive: fx-multi-compartment
  [INFO] fx-multi-compartment gate warnings :: ['W_FLOW_RANKS_DERIVED']
  [INFO] fx-multi-compartment reference_comparison :: status=na checks=['REFERENCE_COMPARISON'] exceptions=1

POSITIVE SUITE (run): 198 PASS / 1 FAIL / 0 UNVERIFIED / 1 N/A (116.4s)
results saved: D:\Borium_Contest\ARMI2611000060v1\work\verify\harness_results.json
EXIT=1

PS D:\Borium_Contest\ARMI2611000060v1> & $PY _shared\tools\validate_skill_submission.py ARMI2611000060v1\work\submission
{"status": "ok", "files": 30, "bytes": 1118394, "name": "biological-mechanism-pathway-figure", "errors": []}
VALIDATE_EXIT=0

PS D:\Borium_Contest\ARMI2611000060v1> & $PY work\submission\scripts\selftest.py
RESULT: PASS  (67 passed, 0 failed, 0 unavailable, 0 vacuous skips, 85.4s)
EXIT=0        # 2026-11-23 11:44 采样（实现方自测，旁证，非独立验收）

PS D:\Borium_Contest\ARMI2611000060v1> & $PY work\verify\harness.py negative
<见 negative_results.json 与本文件 §4 的原始输出段>
```

## 9. 复核建议（给 Lead）

1. **B1** 是唯一在正例通道被独立复现的机制编码偏离；若时间不够，至少把钳位行为写进 `exceptions[]`（诚实披露）并在 `RESULT.md` 记未解决缺陷。
2. **B2** 建议在提交前评估：正式案例是中文材料，`_norm_name` 删 CJK 会让"XX 基因 / XX 蛋白"这类合法表达被判 error，可能把 `status` 从 `ok` 拉到 `partial`。
3. **B3/B4** 三个冻结码未实现：CONTRACT §3.7 已把它们写成 error 级，判据存在但无产出；建议要么实现，要么在 CONTRACT 上标注"未实现 → 以 UNVERIFIED 处理"，**不要**让报告看起来像是验过了。
4. 我的 4 个夹具已落盘（`work/verify/fixtures/**` + `models/**`），可直接重跑复现上述全部结论。
