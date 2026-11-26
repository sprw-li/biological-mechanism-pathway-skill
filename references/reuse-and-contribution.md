# 可复用资产与共享（reuse and contribution）

> 本文件对应评分点「资源可复用性 4 分」「分享推广价值 3 分」。写法上刻意做成**清单**：
> 每一项写清"这是什么 / 拿走怎么用 / 依赖什么 / 不能拿去做什么"，避免"可复用"停留在形容词。

## 1. 拿走就能用的资产

| 资产 | 文件 | 怎么复用 | 依赖 | 不能拿去的场景 |
|---|---|---|---|---|
| **机制本体（机器可读）** | `schemas/mech_ontology.json` | 直接当词表用：实体类型 18 类、关系类型 13 类、`HEAD_FOR_TYPE`/`STROKE_FOR_TYPE` 冻结样式表、无量纲列名 allowlist、区室顺序 | 无（纯 JSON） | 不得用来"补造"材料里没有的实体；它只是词表，不提供事实 |
| **机制判据实现** | `scripts/mech.py` | 独立 import：`check_gene_protein` / `check_membrane` / `check_flow` / `check_interaction_styles` / `check_abundance` / `is_dimensionless_column` / `compartment_of`。可挂到别的绘图管线里当**前置校验** | Python 3 标准库 | 判据会**报错**而不是修图；它不替你决定科学内容 |
| **题集（3 套）** | `examples/cases/{linear-pathway,branch-feedback,multi-compartment}/` | 每套 = `case.json` + `materials/` + `model.json`。可当回归夹具、可当 few-shot 示范、可当教学样例 | 无（文本） | 三套都是**合成示例**，不是组织方案例，也不是真实实验数据 |
| **区室/膜带布局模板** | `scripts/layout.py` | 区室嵌套（extracellular ⊃ membrane ⊃ cytosol ⊃ {nucleus, mitochondrion, er, golgi}）、膜带窄条、膜上实体胞外域朝外、确定性分层 | 与 `run.py` 的模型结构耦合（见 `schemas/figure_model.schema.json`） | 换到非机制图（如纯图表）时用不上；`top_down` 真转置**未实现**（见 `rubric-mapping.md §7`） |
| **冻结调色与线宽映射** | `scripts/render_svg.py` 的 `ARROW_FOR_TYPE` / `STROKE_FOR_TYPE` / 调色板；`scripts/export.py` 的期刊预设（nature/science/cell/ieee/generic） | 可单独抄走当"机制图配色与线型约定" | 无 | 配色可换，但**线宽↔证据强度**（1.4/1.0/0.6 pt）与**箭头↔相互作用**是语义，换掉就等于改论断 |
| **校验/门禁脚本** | `scripts/compliance.py`（产物侧 30+ 检查）、`scripts/mech.py`（模型侧） | 挂到 CI：给定 SVG/PDF/PNG + 模型，输出 `checks.json`（每条带 `id`/`level`/`status`/`where`） | Python 标准库；PDF 文本层检查需 `pypdf`（缺失时如实标 `unavailable`） | 它不是"质量评分器"，只回答"契约是否满足" |
| **增益度量方法** | `scripts/gain_check.py` + `references/measured-gain.md` | 这是**方法**资产：把"我的 Skill 到底有没有用"变成可复跑的同管线 A/B（naive 臂 由脚本构造，指标机械可算） | 同一套 `run.py` | 不能用来算平台分数；naive 臂是代理，不是真实基础 Agent |
| **结果合同** | `references/result_contract.md` + `schemas/figure_model.schema.json` | 想接同一评测体系的其他绘图 Skill 可以照这个字段表产出 `result.json` | 无 | 平台字段是组织方规定的，不要自创同义字段 |

## 2. 三套题集覆盖了什么（对应题面"题集至少覆盖六个方面"）

| 方面 | linear-pathway | branch-feedback | multi-compartment |
|---|---|---|---|
| 科学实体 | 配体/受体/激酶/转录因子/基因 | 同上 + 并行分支 | + 复合物、膜锚定蛋白 |
| 空间/区室关系 | 胞外→膜→胞质→核 | 同左（含核内/核外） | 四区室嵌套 + 膜带 |
| 相互作用类型 | activation / modification / transport / transcription / translation | + **feedback**（显式收环） | + inhibition + 区室内 binding |
| 数据编码 | 图例线宽 = 证据强度 | + CSV → 颜色通道 | 图例多通道 |
| 图例标注 | 有（自动生成，禁手写） | 有 | 有 |
| 可编辑源 + 导出 | SVG 7 图层 + PDF/PNG/TIFF/EPS | 同左 | 同左 |

## 3. 分享与推广（能对外讲的三件事）

1. **"机制图不是插图，是可被逐条质疑的陈述"** —— 本 Skill 把这句话落成了判据：
   每个箭头有类型、每个实体有来源、每个区室有位置、每条证据有强度。
2. **"图例与数据必须三方一致"** —— 图例项 / 图面实际取值 / 数据取值三者逐一对应，
   不一致就拦（`E_LEGEND_DATA_MISMATCH`，四通道 color/line_width/node_size/line_style）。
3. **"增益要能被别人重跑"** —— `gain_check.py` 的写法可以推广到任何"AI 画图有没有用"的问题：
   同一管线、同一输入、只换模型，指标机械可算，劣势照写。

## 4. 维护

- 版本：`manifest.json` 记录每个文件的 `bytes` + `sha256`；改动后重跑
  `python work/freeze_manifest.py`（模板见仓库 `verification/`）。
- 词表变更必须同步三处：`schemas/mech_ontology.json`、`scripts/mech.py`、`references/mechanism_semantics.md`；
  `work/fixtures/check_mech.py` 有一条断言"本体 == 实现"（`same=True`），不同步会直接失败。
- 已知未落地项列在 `references/rubric-mapping.md §7` 与 `references/implementation_status.md`，
  引用时不得把它们说成已完成。
