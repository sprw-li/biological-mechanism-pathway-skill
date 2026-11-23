# 机制/通路语义合同（`mechanism_semantics.md`）

本文件是**生物机制图与通路图**的语义真相：实体类型、基因/蛋白书写区分、关系类型 → 箭头/线型、
区室与膜的定位、方向与环、证据强度、图例数据编码。它逐条对应冻结接口 `work/CONTRACT.md` §3（`:33-109`）。

**唯一实现源**：`scripts/mech.py`（常量表 + 每个检查函数）。本文件与 `mech.py` 的口径一致，
每条错误码都能在 `mech.py` 里找到同名函数；`scripts/model.py`（模型层编排）、`scripts/layout.py`（几何）、
`scripts/compliance.py`（产物侧复核）消费同一份常量。

> **两条纪律**
> 1. 本文件只描述**合同强制 + 实现真实执行**的语义。§11 给出可复现的核验命令与实测结果。
> 2. 样式**不可自由发挥**：`relations[].type` 一旦确定，箭头与线型就被 §4 的表冻结。
>    "画得像"不算对——图面上每一个箭头、每一处定位都带有语义。

---

## 1. `figure.kind`（主类型）

| 值 | 含义 |
|---|---|
| `mechanism_pathway` | **机制/通路图主类型**（本题主场景）：实体 + 有类型的关系 + 区室/膜 + 图例编码 |
| `relationship_schematic` | 关系示意图（无强制区室/方向语义） |
| `flowchart` | 流程/步骤图 |
| `chart` | 纯数据图（不画实体框） |
| `mixed` | 机制图与数据图混排（上半示意图、下半数据图） |

`mechanism_pathway` 走**全部**机制门禁（§3–§8），并且**强制要求 `figure.flow.ranks`**
（`scripts/model.py` 的 `E_FLOW_DIRECTION: figure.kind is 'mechanism_pathway' but
figure.flow.ranks is missing`）；`chart` 只走图例-数据与导出类判据。

---

## 2. 实体类型与命名规范（`entities[]`）

### 2.1 `entities[].kind` 枚举

基础（`LEGACY_ENTITY_KINDS`）：`gene | protein | process | treatment | sample | category | axis | concept | compound | cell | condition`

机制新增（`MECH_ENTITY_KINDS`，冻结）：

| kind | 含义 | label 示例 |
|---|---|---|
| `complex` | 蛋白复合物 | `cyclin E-CDK2` |
| `organelle` | 亚细胞区室实体 | `mitochondrion` |
| `cell_type` | 细胞类型 | `hepatocyte` |
| `metabolite` | 小分子代谢物 | `lactate` |
| `modification_site` | 修饰位点 | `PDH Ser293-P` |
| `stimulus` | 外源/上游刺激 | `hypoxia`、`OGD/R` |
| `drug` | 药物/化合物干预 | `2-APB` |

### 2.2 基因 vs 蛋白（硬门禁 `E_GENE_PROTEIN_CONFUSION`）

`scripts/mech.py:gene_protein_confusion()` 只裁决**已断言 kind 与 label 的自相矛盾**，
绝不对裸符号猜 kind（那是 Agent 的裁决）。触发条件：

| 断言 | 拦截条件 |
|---|---|
| `kind=gene` | label 带**蛋白修饰装饰**（`-P`、`p-`、`pSer`、`phospho-`、`（Ser293-P）` 等） |
| `kind=gene` | label 里出现 `protein` 词（`LDHA protein`） |
| `kind=gene` | label 带蛋白标签后缀（如 `-His`、`-GFP` 一类 tag） |
| `kind=protein` | label 是转录本/mRNA 写法（`mRNA`、`transcript`、`转录本`） |
| 同一符号两种 kind | 两个实体的 label **不可区分**（`normalise_key` 去重后相同）——读者分不清哪个节点是哪个 |

配套规则：

- **物种前缀与同义/旧名必须留痕**：`human `、`Hs.`、`mouse ` 等前缀由
  `strip_species_prefix()` 拆出，规范符号写 `attributes.normalized_symbol`（接受 `gene_symbol`/`symbol` 别名），
  旧名写 `attributes.synonyms`，并在 `source` 里给出逐字引文。
- **同名基因与蛋白允许共存**：同一 `normalized_symbol` 的两个实体 kind 不同时可以同时存在，
  但 label 必须可区分（例如 `HIF1A`(gene) 与 `HIF-1alpha`(protein)），且各自有 `source`。
- **不因大小写自动判定**：命名规范（人类基因全大写、小鼠首字母大写）不足以单独定 kind；
  必须以材料原文与权威命名来源为依据，并在 `uncertainty[]` 里记录判断。
- 门禁只拦**形式上可证伪**的混用；"这个符号在该物种指基因还是蛋白"属科学判断层，
  由 Agent/评审负责（见 `SKILL.md` 的「两层责任」）。

---

## 3. 区室、膜与分组（`containers[]`）

### 3.1 `containers[].kind`（`CONTAINER_KINDS`）

| kind | 说明 | 附字段 |
|---|---|---|
| `compartment` | 亚细胞区室 | `compartment ∈ nucleus \| cytosol \| mitochondrion \| er \| golgi \| lysosome \| extracellular \| cytoplasm` |
| `membrane` | **质膜等脂双层**；实体可"坐落其上"（膜带） | `membrane_of`（可选） |
| `cell` | 细胞边界（画为细胞轮廓） | — |
| `group` | 逻辑分组（模块/通路归属），**无区室语义** | — |

`compartment` 与 `membrane` 不等价：区室是**区域**（实体在其中），膜是**界面**（实体在带上）。

**别名归一**（`COMPARTMENT_ALIASES`）：`nuclear→nucleus`、`intracellular→cytoplasm`、
`mitochondria→mitochondrion`、`endoplasmic_reticulum→er`、`cell_membrane→plasma_membrane`、
`medium→extracellular` 等常见写法归一到规范拼写后再比对。

### 3.2 膜定位硬规则（`E_MEMBRANE_PLACEMENT`）

`entities[].membrane_role ∈ transmembrane | membrane_anchored | luminal | cytosolic | extracellular | na`

| membrane_role | 强制约束 | 违规码 |
|---|---|---|
| `transmembrane` | `entities[].container` **必须**是某个 `kind=="membrane"` 的容器 | `E_MEMBRANE_PLACEMENT` |
| `membrane_anchored` | 允许在 `membrane` 容器，**或**在相邻区室（`cytosol`/`cytoplasm`/`plasma_membrane`/`extracellular`）——外周/锚定蛋白（如 RAS-GTP）本就画在胞质里贴膜 | `E_MEMBRANE_PLACEMENT` |
| `luminal` / `cytosolic` / `extracellular` | 语义是"在双层某一侧"，container 应是**区室**；若写成膜带本身 → 记警告（不拦截） | `W_MEMBRANE_ROLE_CONTAINER` |
| 未写 `membrane_role` 但 `container` 是膜容器 | 读者分不清跨膜受体与外周蛋白 → 记警告 | `W_MEMBRANE_ROLE_MISSING` |
| 值不在冻结枚举内 | 直接拦截 | `E_MEMBRANE_PLACEMENT` |

**布局要求**：`transmembrane` / `membrane_anchored` 的实体必须画在**膜带之上**（膜带内、压线），
跨膜受体的胞外域朝 `extracellular` 侧、胞内域朝 `cytosol` 侧。
**硬拦截**：把跨膜受体画进 `cytosol`/`nucleus` 容器内部 ⇒ `E_MEMBRANE_PLACEMENT`
（这是题目点名的"跨膜受体画在膜内、细胞区室错位"）。

### 3.3 区室归属优先级（与 `layout.py` 一致）

`entity.container` > `containment` 关系 > `containers[].members`。三者冲突不静默丢弃：
记 `W_CONTAINER_CONFLICT` 并保留优先级最高者。容器嵌套成环 ⇒ `E_CONTAINER_CYCLE`。

---

## 4. 关系类型 → 箭头/线型（**冻结样式表**）

`relations[].type` 枚举（`RELATION_TYPES`）：基础 `activation | inhibition | containment | sequence |
causation | association | membership`；机制新增 `binding | modification | transport |
transcription | translation | feedback`。

| type | arrow | stroke | 强制约束 | 违规码 | 图例必须有的条目 |
|---|---|---|---|---|---|
| `activation` | `normal` | `solid` | 同向 rank 递增 | `E_FLOW_DIRECTION` | 箭头=激活 |
| `inhibition` | `tee` | `solid` | 同向 rank 递增 | `E_FLOW_DIRECTION` | 平头(⊥)=抑制 |
| `binding` | `none` | `solid` | 两端**同区室**（膜上伙伴与膜外配体互为邻侧，豁免） | `E_COMPARTMENT_MISMATCH` | 无箭头实线=结合 |
| `modification` | `normal` | `dashed` | `label` 必须写明修饰种类（磷酸化/泛素化/乙酰化…） | `E_MODIFICATION_UNNAMED` | 虚线箭头=修饰 |
| `transport` | `normal` | `solid` | 必须写 `crosses:[fromContainer,toContainer]`，且两端**不同**容器 | `E_TYPE_CONSTRAINT_VIOLATION` | 跨边界箭头=转运 |
| `transcription` | `normal` | `solid` | `to` 为 `kind ∈ {gene, concept}`；`from` 为 `kind ∈ {protein, complex, transcription_factor, concept}` | `E_TYPE_CONSTRAINT_VIOLATION` | 箭头=转录激活 |
| `translation` | `normal` | `solid` | `from` 为 `kind=gene`；`to` 为 `kind=protein` | `E_TYPE_CONSTRAINT_VIOLATION` | 箭头=翻译 |
| `feedback` | `normal` | `dashed` | **参与环**：`from` rank ≥ `to` rank（它被排除在 rank 推导与环检测之外，是闭合环的许可） | — | 虚线=反馈 |
| `association` | `none` | `dotted` | 无方向 | — | 点线=关联（无方向） |
| `containment` / `membership` | `none` | `dotted` | 由 `containers` 派生（画为外框包裹，不是线）；不建层级边 | — | 虚线框=区室 |
| `sequence` / `causation` | `normal` | `solid` | 同向 rank 递增 | `E_FLOW_DIRECTION` | 箭头=顺序/因果 |

`direction` 仍取 `forward | backward | none | bidirectional`；`type` 决定"语义"，`direction` 只决定"朝向"。
**机制图里优先用 `type` 表达语义**，不要用 `activation + direction=backward` 冒充抑制。
自环（`from == to`，如 EGFR 自磷酸化）豁免 rank 检查，不参与环检测。

### 4.1 样式一致性硬门禁（`E_INTERACTION_STYLE_MISMATCH`）

拦截两种情形：

1. 模型显式写的 `style.arrow` / `style.stroke` 与上表不符（缺省 `style` 由 `mech.RELATION_STYLE` 生成，不算违规）；
2. 某 `type` 出现在图面上，而**图例缺该 type 的对应条目**——匹配方式为
   `legend[].value == type`（大小写不敏感）或 `legend[].label` 含该 type 的冻结图例词
   （`RELATION_LEGEND_LABEL`）。

### 4.2 结合关系的区室约束（`E_COMPARTMENT_MISMATCH`）

`binding` 的两端必须在**同一容器**；两端任一在 `membrane` 容器时豁免
（配体在胞外、受体在膜上是经典的跨双层结合对，不是同区室结合）。
跨区室的物理结合应改成 `transport`（有方向、跨边界）或 `association`（无方向、弱语义）。

---

## 5. 方向与拓扑（`figure.flow`）

```jsonc
"figure": {
  "kind": "mechanism_pathway",
  "flow": {
    "orientation": "top_down",          // top_down | left_right（默认 top_down）
    "ranks": {"e_receptor": 0, "e_kinase": 1, "e_tf": 2, "e_gene": 3}
  }
}
```

冻结判据 `E_FLOW_DIRECTION`（`scripts/model.py` 的 `validate_model()`（`flow.ranks` 检查段）+ `scripts/mech.py:check_flow_direction()`）：

1. **`mechanism_pathway` 必须给 `figure.flow.ranks`**——上下游顺序必须显式声明，不能靠画图顺序暗示；
2. **ranks 必须覆盖每一个实体**（缺一个 ⇒ 报错）；
3. **非 `feedback` 且有向的关系** `from→to` 必须 `rank[to] > rank[from]`；
   **同 rank 仅允许** `binding`/`association`（无方向语义）；
4. 由非 `feedback` 边构成的**有向环** ⇒ 拦截——环必须显式标 `feedback`（并满足 `rank[from] ≥ rank[to]`）。
   这是"负反馈画反"的直接拦截；
5. **受体—胞内—核内层级单调**：若图面上存在
   `extracellular → membrane → cytosol → nucleus` 链，其 rank 必须严格递增；
6. `orientation` 只接受 `top_down`/`left_right`，其它值 ⇒ `E_CONTRACT_KEY_MISSING`。

绘图语法：`top_down` 表示上游在上、下游在下；`left_right` 表示上游在左、下游在右；
两种朝向下"上游/下游"的语义相同，只是版面轴不同。

> **本版渲染实况（诚实披露，见 `implementation_status.md`）**：本版 `layout.TOP_DOWN_RENDER_ENABLED = False`，
> 因此请求 `top_down` 时**版面仍按从左到右绘制**，并在三处留痕：
> `layout.json` 的 `flow.orientation_fallback = true`、`flow.requested_orientation = "top_down"`、
> 以及布局警告 `W_ORIENTATION_RENDERED_HORIZONTAL`（"rank order, compartment nesting and edge
> semantics are unchanged, only the page axis differs"）。
> ⚠️ 该警告**只出现在 `work/layout.json` 的 warnings 里**，不出现在 `render` 的 stdout warnings 中；
> 要判断朝向是否被替换，请读 `layout.json` 的 `flow` 字段，而不是只看 `render` 输出。
> **语义不受影响**：rank 顺序、区室嵌套、边界语义都按模型声明执行；被替换的只是页面轴向。


**警告（不拦截）**：声明 rank 与由边推导出的拓扑 rank 不一致 ⇒ `W_FLOW_RANKS_DERIVED`
（可能是合理的机制提示，也可能是写错了；报告出来给人看，不擅自改）。
rank 缺省时 `layout.py` 用最长路径推导；推导 rank 只是拓扑序，**不是生物学断言**。

---

## 6. 证据强度与不确定性

`relations[].evidence`（**材料给出时必须填**）：

```jsonc
"evidence": {"strength": "high|medium|low", "kind": "direct|indirect|inferred",
             "note": "材料原句的要点", "source": {"path": "...", "locator": "L12", "quote": "…"}}
```

**线宽冻结映射**（`EVIDENCE_WIDTH_PT`）：

| strength | 线宽 | 图例必需 |
|---|---|---|
| `high` | `1.4 pt` | 图例写明"粗线=强证据" |
| `medium` | `1.0 pt` | 图例写明"中线=中等证据" |
| `low` | `0.6 pt` | 图例写明"细线=弱证据" |

- `evidence.strength` 必须是 `high|medium|low`，`evidence.kind` 必须是 `direct|indirect|inferred`，
  否则 ⇒ `E_CONTRACT_KEY_MISSING`（枚举外值一律报错，不静默忽略）。
- `kind=inferred`（推断）必须在 `result.json.uncertainty[]` 与图面标注里体现"推断"，
  不得画成与 `direct` 同强度的断言。
- 材料**没给**证据强度时：不猜。留空并在 `uncertainty[]` 写明——**不要**默认填 `medium`。
- 关系线宽取"证据强度映射"与 `figure.style.line_widths_pt` 中更严格的一侧。

数值编码：`entities[].abundance = {value, unit, source}` ⇒ **节点大小**，面积 ∝ `value`；
`value` 缺失或 `unit` 为空 ⇒ `E_UNIT_MISSING`（"有无单位"是可机械判定的）。

---

## 7. 图例与数据编码（`legend[]`）

**图例由模型生成，禁止手写坐标/SVG**。每个图例项可带 `encoding`，也接受工单级
`model.legend_encoding[]`（两者都进同一张检查表）：

```jsonc
{"id": "lg_evidence", "label": "证据强度（线宽）", "kind": "value_scale",
 "encoding": {"channel": "line_width", "field": "relations[].evidence.strength", "unit": "pt",
              "mapping": [{"value": "high", "visual": "1.4"},
                          {"value": "medium", "visual": "1.0"},
                          {"value": "low", "visual": "0.6"}]}}
```

`channel ∈ color | line_width | node_size | line_style`（冻结四通道）。

机制图有悬停关系或数据系列、却**没有任何** `encoding` ⇒ 警告 `W_LEGEND_ENCODING_MISSING`
（"必须说明颜色/线宽/节点大小编码了什么"）。

### 7.1 `E_LEGEND_DATA_MISMATCH` 的逐通道判据

| channel | 判据（多一项、少一项都拦截） |
|---|---|
| `color` | `mapping[].value` 集合 == `data.series[].name` 集合；每个系列的 `visual` == `series.color`；`legend` 里 `kind=category` 的色块 == 该 value 的 `visual`；若 `field` 命中 `data.columns` 的列，还要 == 该列的真实取值集合 |
| `line_width` | `field` 含 `evidence` 时：`mapping[].value` 集合 == 实际用到的 `evidence.strength` 集合；`mapping[].visual` 集合 == 实际画出的线宽集合（来自 `EVIDENCE_WIDTH_PT`） |
| `node_size` | `mapping[].value` 集合 == 实体 `abundance.value` 集合 |
| `line_style` | `mapping[].value` 集合 == 图面上真实出现的关系 `type` 集合；每个 `visual` == 冻结样式表里该 type 的 `stroke` |

另保留既有判据：`legend` 的 `category` 条数 = 数据分类数；每个 series 有对应图例项；
图例色 = series 色（`E_LEGEND_DATA_MISMATCH`），数值列必须有单位（`E_UNIT_MISSING`）。

### 7.2 必须写进图例的条目（图面出现即需要）

- 每种出现的 `relations[].type` 的线型/箭头语义（§4 表最后一列）——缺则 `E_INTERACTION_STYLE_MISMATCH`；
- 证据强度 → 线宽通道（§6）；
- 数值/丰度 → 节点大小的口径与单位（若用了 `abundance`）；
- 颜色 → 分类/条件/时间点的映射（若用了颜色编码）。

图面即使"画得出来"，图例缺失/不一致也判不通过——这正是题目点名的"图例说明与实际配色、线宽不一致"。

---

## 8. Agent 在 `prepare → render` 之间必须裁决的机制清单

草稿（`figure_model.draft.json`）是**关键词扫描的骨架，不是科研模型**。以下七项不裁决，
图稿即使渲染成功也是错的。`REVIEW_BATCH.json` 的 `must_decide[]` 会逐条列出候选与默认值。

| # | 裁决项 | 判据 / 证据 | 常见错误 |
|---|---|---|---|
| 1 | **实体集合与实体类型** | 只保留材料里真实存在的实体，并给出机制的 `kind`（§2.1）；每种联系方式都有 `source` | 把版式说明、图注名词、"Core/Drawing" 之类刮成伪实体 |
| 2 | **基因 vs 蛋白** | §2.2 书写区分；同义/旧名进 `attributes.synonyms`，规范符号进 `normalized_symbol` | `HIF1A` 画成蛋白带修饰后缀；把基因符号当蛋白 ⇒ `E_GENE_PROTEIN_CONFUSION` |
| 3 | **关系类型** | §4 冻结样式表；`modification` 的 `label` 必须写修饰种类 | 把磷酸化写成 `activation`；把结合画成箭头 ⇒ `E_INTERACTION_STYLE_MISMATCH` / `E_MODIFICATION_UNNAMED` |
| 4 | **区室与膜** | §3；`membrane_role` 与 `container` 必须自洽 | 跨膜受体画进 `cytosol` 内部；忘写 `membrane_role` ⇒ `E_MEMBRANE_PLACEMENT` |
| 5 | **方向与环** | §5；`mechanism_pathway` 必给 `flow.ranks` 且覆盖每个实体；环必须标 `feedback` | 上下游颠倒；负反馈画成正向链 ⇒ `E_FLOW_DIRECTION` |
| 6 | **证据强度** | §6；材料给出才填，缺则记 `uncertainty` | 凭空格 `high`；枚举外值 ⇒ `E_CONTRACT_KEY_MISSING`；`inferred` 画成 `direct` |
| 7 | **图例编码** | §7；四通道映射逐通道一致 | 图例色 ≠ 图面色；线宽档位与 `evidence` 对不上；漏掉 `feedback` 条目 ⇒ `E_LEGEND_DATA_MISMATCH` / `W_LEGEND_ENCODING_MISSING` |

裁决结果写进 `/app/work/figure_model.json`（**不要覆盖草稿**）；不确定的写 `uncertainty[]`，
`status` 相应降级——不要为了拿到 `ok` 而删掉诚实的不确定项。

---

## 9. 实现策略与已记录的放宽（**诚实披露**）

`scripts/mech.py:POLICIES` 记录了 4 条**对合同字面表述的刻意放宽**，每条都有真实工单依据；
它们不是漏洞，而是把"机制上合法的形状"与"机制上错误的形状"区分开：

| 策略 | 放宽内容 | 理由 |
|---|---|---|
| `membrane_anchored_container` | `membrane_anchored` 允许在膜带**或**相邻区室 | 外周/锚定蛋白（RAS-GTP）本就画在胞质里、贴膜 |
| `binding_compartment` | 一端在 `membrane` 时豁免同区室要求 | 配体（胞外）—受体（膜上）是经典跨双层结合对 |
| `self_edge_rank` | `from == to` 自环豁免 rank 检查 | EGFR 自磷酸化 |
| `transcription_origin` | `transcription` 的起点按 **kind** 判定（蛋白/复合物/TF），不强制查容器；起点不在核内且 `crosses` 未含核时，报**警告** `W_TRANSCRIPTION_ORIGIN`（不拦截） | 真实模型常把 TF 直接放在 nucleus，但也有跨区室写法 |

**已知实现缺口（本版实测，见 `implementation_status.md`）**：`W_TRANSCRIPTION_ORIGIN` 的判定把
**容器 id** 直接送进 `canonical_container()`（该函数期望的是**区室名**），因此当容器 id 形如
`c_nucleus` 而不是 `nucleus` 时，即使实体确实在核内也会误报。示例实测原样消息：
`transcription factor e_extf1n is drawn in 'c_nucleus' (not the nucleus) and the edge declares no crossing`。
修好前请把它当**提示性噪音**而不是机制结论。

**属科学判断、机器不判的**（写进 `uncertainty[]` 而不是硬编）：该符号是基因还是蛋白、
该不该把某过程画进链条、来源冲突时以谁为准、`inferred` 证据是否够格入图。

---

## 10. 核验命令（每条都能跑出 exit code）

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONDONTWRITEBYTECODE='1'

# 1) 机制门禁码在实现里是否存在（每个码都应有 >=1 命中）
Select-String -Path scripts\*.py -Pattern 'E_GENE_PROTEIN_CONFUSION','E_MEMBRANE_PLACEMENT',`
  'E_COMPARTMENT_MISMATCH','E_INTERACTION_STYLE_MISMATCH','E_FLOW_DIRECTION',`
  'E_MODIFICATION_UNNAMED','E_TYPE_CONSTRAINT_VIOLATION'

# 2) 机制模型能否通过模型 + 布局门禁（exit 0 = 通过；exit 4 = 报机制错误）
python scripts\run.py render --work <work> --output <output>

# 3) 示例端到端（示例输入在 examples/，不是任何正式案例）
python scripts\run.py prepare --input examples --work <work> --output <output>
python scripts\run.py export  --work <work> --output <output> --journal generic --dpi 300
```

第 1 条"命中数"只是**存在性证据**；能力是否真的生效以第 2、3 条的退出码与 stdout JSON 为准。
本版实测结果（命令、退出码、原样 stdout 片段）见 `references/implementation_status.md`。
