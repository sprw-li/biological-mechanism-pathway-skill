# 基线对照 — 朴素基线 vs 本 Skill（ARMI2611000060v1, verify-harness）

> 采样：**2026-11-23 14:3x +08:00**（`work/verify/naive_baseline.py` 第二次运行，冻结树）
> 命令：`& $PY work\verify\naive_baseline.py` → `work/verify/baseline_results.json`（`exit 0`）
> 逐夹具原始行：
> ```
> fx-linear-pathway        naive: fixes=38 errors=['E_PROVENANCE_MISSING'] formats=['svg','pdf','png'] wall=45.6s | skill: errors=[] formats=['svg','pdf','png'] wall=33.6s
> fx-branch-feedback       naive: fixes=29 errors=['E_PROVENANCE_MISSING'] formats=['svg','pdf','png'] wall=25.0s | skill: errors=[] formats=['svg','pdf','png'] wall=22.4s
> fx-multi-compartment     naive: fixes=34 errors=['E_PROVENANCE_MISSING'] formats=['svg','pdf','png'] wall=22.2s | skill: errors=[] formats=['svg','pdf','png'] wall=35.8s
> ```

## 1. 两条臂的定义（同一管线、同一夹具、同一机器）

| | 朴素基线（naive） | 本 Skill |
|---|---|---|
| 模型来源 | **本机脚本**用正则在材料里抓 ASCII 名词（`[A-Z][A-Za-z0-9]{2,}` 等），按出现顺序**串成链**，每条边都是默认 `activation` + 实线箭头 | `work/verify/fixtures/models/*.json`：Agent 裁决后的 `figure_model.json`（实体类型、基因/蛋白、关系类型、区室/膜、rank/环、证据强度、图例编码、逐元素 source） |
| 闸门 | 同一套 `run.py render/export/finish` + `model.validate_model` + `mech.py` 机制门禁 + `compliance.py` 产物检查 | 同左（**完全相同**的实现与参数） |
| 导出 | `--journal nature --dpi 300`（脚本内固定） | 同左（脚本内固定；`harness.py run` 另测 600 dpi） |

**对照的公平性边界（必须说明）**：朴素基线是**我用脚本构造的代理**，不伪装成"真实基础 Agent 的跑分"；它享受同一个成熟导出器（PNG/PDF 都真能出），因此**不是**"基础 Agent 只会出截图"那种极端对照。平台真正的对照是基础 Agent + 组织方白板，本地无法复现（见 REVIEW.md §5）。

## 2. 对照指标（CONTRACT §3 / task.md §2 的评分点落到可数）

| 夹具 | 臂 | 人工改图条目 ↓ | 方向边有类型比例 ↑ | 溯源覆盖 ↑ | 导出格式数 | 门禁错误数 ↓ | `status` |
|---|---|---|---|---|---|---|---|
| fx-linear-pathway | naive | **38** | **0.0** (0/8) | **0.0** (0/17) | 3 (svg/pdf/png) | **17** | `partial` |
| | **skill** | **0** | **1.0** (7/7) | **1.0** (15/15) | 3 | **0** | **`ok`** |
| fx-branch-feedback | naive | **29** | **0.0** (0/6) | **0.0** (0/13) | 3 | **13** | `partial` |
| | **skill** | **0** | **1.0** (6/6) | **1.0** (12/12) | 3 | **0** | **`ok`** |
| fx-multi-compartment | naive | **34** | **0.0** (0/7) | **0.0** (0/15) | 3 | **15** | `partial` |
| | **skill** | **0** | **1.0** (9/9) | **1.0** (18/18) | 3 | **0** | **`ok`** |

指标口径（写在代码里，可复算）：
- **人工改图条目**＝把该模型改到满足 CONTRACT 所需的**逐 (元素, 字段) 修改数**（`naive_baseline.py::manual_fix_entries`）：缺 `source`、`kind` 用默认蛋白猜、有值无单位、关系无 `evidence`、缺 `figure.flow.ranks`、缺 `containers[]`、缺 `legend[].encoding` 的三个通道、缺 `membrane_role`、缺 `abundance`。skill 臂按定义 0（其合规性由 `harness.py run` 的 0 gate error 独立确认）。
- **方向边有类型比例**＝带真实 `type` 语义或带 `evidence.strength` 的关系占比（`typed_share`）。
- **溯源覆盖**＝`source{path,locator,quote}` 能在材料中**逐字解析**的元素占比（用 harness 自己的解析器，`baseline_results.json` 的 `provenance_ok/elements`）。
- **门禁错误数**＝`figure_issues.json` 的 error 条数（naive 臂 100% 是 `E_PROVENANCE_MISSING`：它根本不产出来源）。

## 3. 结论（Δ 与噪声）

- **质量维度是结构性差异（0 ↔ 非 0），不是噪声**：naive 臂 3/3 夹具 `export exit=4`、`status=partial`、0% 溯源、17/13/15 条门禁错误；skill 臂 3/3 `exit=0`、`status=ok`、0 条门禁错误。按工作区铁律"单次测量不足以声称改进"——此处是**0↔非0**的结构变化，可用作证据；但**不能说**"skill 比基础 Agent 强多少分"，因为平台白板未复现。
- **人工改图条目**：38/29/34 → 0，是本对照最直接的"减少人工改图"代理量。
- **方向边有类型比例**：0.0 → 1.0；naive 臂把"抑制/磷酸化/转运"全部画成同一种激活实线箭头，正是题目 §1 点名的失败模式。

## 4. 劣势如实写（本 Skill 的代价）

| 劣势 | 实测 | 说明 |
|---|---|---|
| **墙钟更慢（中位数）** | naive **25.0 s** vs skill **33.6 s**（中位数；逐夹具 45.6 vs 33.6、25.0 vs 22.4、22.2 vs 35.8） | 3 个夹具里 skill 在 2/3 上更慢（+34% 中位数），1 个更快。差异落在同机噪声量级内，但**方向上是 skill 更慢**：它要画区室容器、膜带、图例编码块、按证据强度分线宽，还要在导出前跑机制门禁与产物合规检查 |
| **产物更多、更重** | skill 在 600 dpi 下额外产出 `tiff`+`eps`（`_runs/*/out/figures`），并多写 `source_map.json`/`render_report.json`/`export_report.json`/`checks.json`/`change_log.json` | 可核验性提升的代价是文件数与字节数上升（提交树 30 文件 / 1.12 MB；skill 资源上限 50 文件 / 2 MB，仍有余量） |
| **Agent 侧判断成本更高** | **未测**（本地只能测管线墙钟，不测模型请求数） | skill 的增益恰恰来自 prepare→render 之间那一步人工/模型裁决（`REVIEW_BATCH.json` 的 `must_decide` + 逐元素 `source` 绑定）。这一步的 token/时间成本**没有**计入上表，所以上表对 skill **有利**——请按"skill 真实成本更高"理解 |
| **对输入的苛刻度更高** | naive 臂任何输入都能画出来（代价是画错）；skill 臂在材料缺来源/缺单位/缺方向时会更早 `partial`/报错 | 这是设计取舍：题目要求"材料缺失、无法判断和运行失败要分别说明"，失败退出码（2/3/4）是特性不是回归 |
| **单夹具不稳定** | fx-multi-compartment：naive 22.2 s 比 skill 35.8 s 快 13.6 s | 说明本机墙钟受并发/磁盘影响，**不足以**支撑任何"效率提升"结论 |

## 5. 可复现

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONDONTWRITEBYTECODE='1'
$PY='C:\Users\Morrow\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
cd D:\Borium_Contest\ARMI2611000060v1
& $PY work\verify\fixtures\build_fixtures.py --check     # 4 夹具，自检 4/4
& $PY work\verify\naive_baseline.py                      # 本对照，exit 0
& $PY work\verify\harness.py run                         # 正向套件（skill 臂的独立确认）
& $PY work\verify\harness.py report                      # 汇总
```

产物：`work/verify/baseline_results.json`（含每臂 `gate_error_codes`/`typed_share`/`provenance_share`/`formats`/`wall_s`），`work/verify/_baseline/{naive,skill}_<fixture>/{work,out}`（原始 `figure.svg`/`result.json`/`figure_issues.json` 可直接比对）。
