# 评分维度 → 实现与证据（rubric mapping）

> 本题为 `human_review_only`（满分 100 + GitHub 5）。本文件把**题面 §2 的每一个评分点**逐条对到
> 「本 Skill 里哪一段实现」+「哪条命令/哪个文件能复核」。目的只有一个：让评审**不必相信叙述**——
> 每个 ✔ 后面都能落到一个可运行命令或一个真实产出文件。
>
> 约定：`scripts/x.py::fn` 指函数名（**不写行号**：行号会随版本漂移，函数名不会）；
> 命令里的 `$PY` 是解释器路径，`$SKILL` 是安装目录（如 `/skills/weekly-skill`）。

## 1. 实际效果（40 分）

| 评分点 | 分值 | 实现 | 复核方式 |
|---|---|---|---|
| 任务完成度（读材料→定实体与关系→定布局与图例→出源文件与导出件） | 15 | `scripts/run.py` 六阶段 `prepare → render → export → compare → edit → finish`；`scripts/ingest.py` 抽取、`scripts/model.py` 建模、`scripts/layout.py` 布局、`scripts/render_svg.py` 出 SVG、`scripts/export.py` 出 PDF/PNG/TIFF/EPS | `python scripts/run.py prepare/render/export/finish` 全链路 exit 0；`selftest.py` 67 项 |
| 结果正确性（实体不混用；激活/抑制/结合/修饰/转运可区分；方向与数据编码与来源一致） | 15 | `scripts/mech.py` 本体 + 判据：`check_gene_protein`、`check_membrane`、`check_flow`、`check_interaction_styles`；`scripts/compliance.py` 产物侧同名校验 | `python work/fixtures/check_mech.py` → 38/38；`references/mechanism_semantics.md` 逐条给出判据与正负例 |
| 结果完整性（覆盖实体、并行分支与反馈环、图例项、约定导出格式） | 5 | 分支/反馈环由 `figure.flow.ranks` + `relations[].type=="feedback"` 支持；图例由 `legend[].encoding` 四通道生成；导出格式 svg/pdf/png/tiff/eps | `references/measured-gain.md` 的 `formats` 列（skill 臂 5 格式 vs naive 1 格式）；`examples/cases/branch-feedback` 即反馈环夹具 |
| 结果可核验性（实体清单、边清单、图例依据、源文件、版本与导出参数可独立复核） | 5 | 每元素 `source{path,locator,quote,kind}` + SVG 上 `data-entity-id`/`data-relation-id`/`data-prov`；`result.json` 的 `content_map` 用 SVG 真实锚点判 `on_canvas`；`source_map.json`/`export_report.json`/`checks.json` 落盘 | `references/measured-gain.md` 的 `provenance share`（naive 0/11 vs skill 8/8）；`data-prov` 形如 `materials/x.json#json:entities/EGFR` |

## 2. 使用增益（25 分）

| 评分点 | 分值 | 实现 | 复核方式 |
|---|---|---|---|
| 质量增益（同输入对照，图稿质量稳定提升） | 15 | `scripts/gain_check.py`：**同一管线、同一夹具、同一 DPI**，`naive` 臂（名词串链 + 全默认激活箭头 + 无来源）vs `skill` 臂（裁决后的模型） | `python scripts/gain_check.py --case examples/cases/...`；结果见 `references/measured-gain.md`：人工返工 **65/47/53 → 0**、typed **0/7,0/7,0/8 → 7/7,6/6,9/9**、溯源 **0 → 全覆盖**、门禁错误 **21/15/17 → 0** |
| 效率增益（减少人工改图条目/重画轮次/重导出次数） | 5 | 同上：`manual_fix_entries` 即"人工还要改几处"；`scripts/run.py edit` 支持**来源保留式编辑**（改标签/配色/数据点后重绘重导，写 `change_log.json`），避免整张重画 | `measured-gain.md` 的 `manual-fix entries` 列；`selftest.py` 的 `edit` 段与 `change_log` 断言 |
| 增益可验证性（用同输入对照证明改善） | 5 | `gain_check.py` 输出 `gain_results.json`（每臂逐阶段 exit code + 原始实体/关系条数）+ `measured-gain.md`（同一 stdout） | 两个文件都在 `references/`，评审可对照重跑 |

**本项最容易被误读的地方**：效率增益**不是**管线更快——Skill 臂墙钟更慢（要画区室/膜带/图例编码 + 跑门禁）。
体现在**人要改的条目**而不是秒数。这一点在 `measured-gain.md` 的"诚实边界"里写死了。

## 3. 创新增益（15 分）

| 评分点 | 分值 | 实现 | 复核方式 |
|---|---|---|---|
| 新增能力（机制文字→图元与边的结构化映射；箭头类型语义判定；区室/跨膜位置约束布局；图例与数据编码一致性校验；可编辑源文件自动生成） | 5 | 逐项对应：`scripts/mech.py`（本体与语义判定）、`scripts/layout.py` 的区室/膜带几何与 `membrane_role` 落实、`scripts/model.py` 的 `legend[].encoding` 自动生成、`scripts/render_svg.py` 的 7 图层可编辑 SVG | `references/mechanism_semantics.md`（词表→判据一一对应）；`schemas/mech_ontology.json` 机器可读本体 |
| 方法改进（实体消歧与命名归一、相互作用判定、通路布局、图例生成、导出校验） | 5 | `mech.compartment_of`（容器 id/区室名归一）、`mech.check_gene_protein`（基因/蛋白同一 symbol 共存须可区分）、`relations[].type` 候选集合语义（`磷酸化` 的候选含 `modification` 与 `activation`，不再二选一硬判）、`layout` 的确定性分层 | `work/fixtures/check_mech.py` 的 38 条（含"正例不触发 / 注入后触发"双向） |
| 创新证据（证明相对已有方案的边界与价值） | 5 | ① `measured-gain.md` 的同管线对照；② `references/implementation_status.md` 逐条能力实测状态（含**未落地**项，不吹）；③ 本文件的"未实现/未验证"清单 | `implementation_status.md` 与本文 §6 |

## 4. 可靠体验（10 分）

| 评分点 | 分值 | 实现 | 复核方式 |
|---|---|---|---|
| 调用与易用性（能正确触发、按说明把材料变成图稿） | 3 | `SKILL.md` frontmatter 的 `description` 写清触发条件；`README.md` 给出安装/调用/依赖；四步快速开始 | `SKILL.md` 快速开始段；`examples/README.md` |
| 运行稳定性（不同通路类型、重复运行结构一致） | 4 | 布局**确定性**（无随机种子；同一模型两次运行几何一致）；三类夹具（线性/分支+反馈环/多区室跨膜）均 exit 0 | `examples/cases/{linear-pathway,branch-feedback,multi-compartment}` 三套；`selftest.py` 的 `robustness` 段 |
| 异常处理（缺方向信息、名称歧义、输入与图示矛盾、字体/图元缺失、导出失败、元素过多） | 3 | 退出码语义（`0`/`3`/`4`/`2`）；`REVIEW_BATCH.json` 的 `must_decide`；`uncertainty[]`；缺后端时 `available=false` + 真实原因（**不写假文件**）；元素过密时降级并发 `W_LABEL_DEGRADED` | `selftest.py` 的 `negative`/`robustness` 段；`references/export_and_compliance.md` 的失败处置表 |

## 5. 生态贡献（10 分）

| 评分点 | 分值 | 实现 | 复核方式 |
|---|---|---|---|
| 文档完整性（说明/依赖/配置/示例/绘图规范/适用范围/限制/维护） | 3 | `README.md` + `references/` 六份（机制语义、抽取规则、布局与 SVG、导出与合规、结果合同、实现状态）+ 本文 | 文件清单见 `manifest.json` |
| 资源可复用性（本体、题集、图元库、布局模板、配色方案、校验脚本） | 4 | 可复用资产逐项：`schemas/mech_ontology.json`（本体）、`examples/cases/**`（**3 套题集**：线性/分支+反馈环/多区室）、`layout.py` 的区室与膜带模板、`render_svg.py` 的冻结调色与线宽映射、`compliance.py` + `mech.py`（校验脚本） | `references/reuse-and-contribution.md` 逐项列出"拿走就能用"的边界 |
| 分享推广价值（沉淀可分享的案例、规范、题集与实践经验） | 3 | 同上 + `examples/cases` 三套 + `references/measured-gain.md`（可复用的"如何证明增益"方法本身） | — |

## 6. GitHub 公开链接（5 分）

`GITHUB_URL.txt` 第一行 = 仓库地址，第二行 = `SKILL.md`。评审无需登录即可打开仓库根并看到
`SKILL.md` / `scripts/` / `references/` / `schemas/` / `examples/` / `verification/`。

## 7. 本 Skill **没有**做到的（同一张表，反向列）

写在这里是因为评分点「创新证据」明确要求"证明边界"，藏起来的边界会变成扣分项：

| 项 | 状态 | 说明 |
|---|---|---|
| `top_down`（合同默认朝向）真转置 | **降级** | 请求 `top_down` 时按 `left_right` 渲染，并在 `layout.flow.requested_orientation` / `orientation_fallback=true` + `W_ORIENTATION_RENDERED_HORIZONTAL` 留痕。rank 顺序/区室层级/边方向语义不变，**只是页面轴向不同** |
| 面积编码与标签长度的耦合 | **已知偏差** | 节点盒 = 基础盒（受标签长度与列宽影响）× √(value/ref)，所以"面积严格 ∝ value"只在无标签挤压时成立；被挤压的元素逐条发 `W_ABUNDANCE_SIZE_CLAMPED` 披露 |
| `E_EVIDENCE_WIDTH_MISMATCH` / `E_ABUNDANCE_SIZE_MISMATCH` | **契约已冻结、实现未落地** | 引用时不得声称已拦截 |
| 平台隐藏案例上的真实表现 | **未知** | 本地只有自建夹具；隐藏案例、`/skills` 实装与触发、人工视觉判断均无法本地验证 |
| 复杂排版（多面板期刊版式、封面图） | 不在范围 | 题面已把版式美化划给相邻课题 |

## 8. 一句话

> 这张表的用法是：评审**任选一个 ✔**，后面都能追到一个可运行命令或一个真实文件；
> 任选一个 §7 的条目，都会发现我们**已经自己写明了它没做到**。
