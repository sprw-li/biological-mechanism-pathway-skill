# FROZEN INTERFACE CONTRACT — ARMI2611000060v1（生物机制图与通路图）

> 冻结人：Lead　｜　冻结时间：2026-11-23 11:4x +08:00　｜　版本 **v1.1**
> 基线：`ARMI2611000058v1\work\submission`（同族已验证产物，`selftest` 67/67 exit 0，2026-11-23 实测）
> 本文件是**唯一接口真相**。各写者只改自己 scope 内的文件；改本文件需 Lead 批准（接口冻结）。
> 向后兼容策略：**只做加法**——新增 enumerated 值、新增可选字段；已有字段语义不变。

---

## 1. 平台硬约束（不可协商，来自 `task/task.md` + dataset `resources/output-contract.md`）

- 运行契约：`/input/case.json` + `task.md` 是唯一输入真身；工作在 `/app/work`，交付在 `/app/output`。
- `result.json` **必须保留原 output_contract 全部字段**：
  `case_id, status, editable_source, export_artifact, content_map, compliance_checks, exceptions`。
- 预算：**64 次模型请求 / 900 秒 / 单次响应 16384 tokens**；3 案例 × 3 次重复。
- skill 资源上限：**≤50 个 UTF-8 文本文件 / 单文件 ≤500KB / 合计 ≤2MB / 无 symlink**。
- 必须真实：可编辑 SVG 主源 + **真实** PNG/PDF 导出 + 像素检查 + 来源保留式编辑记录。**缺后端就如实标 `unavailable`，绝不伪造文件或伪造科学数据**。
- 不提交预制答案、不提交正式案例结果；`examples/` 必须标注为「示例」。

## 2. 管线与调用面（不回退）

```
python $SKILL/scripts/run.py prepare --input /input --work /app/work --output /app/output
#   → work/INVENTORY.json, work/REVIEW_BATCH.json, work/figure_model.draft.json
#   Agent 依据材料裁决（真实科学判断只在这一步）→ 写 work/figure_model.json
python $SKILL/scripts/run.py render  --work /app/work --output /app/output      # 未修订草稿 → exit 4 / E_MODEL_NOT_REVISED
python $SKILL/scripts/run.py export  --work /app/work --output /app/output --journal nature --dpi 600
python $SKILL/scripts/run.py edit    --work /app/work --output /app/output --ops /app/work/edit_ops.json
python $SKILL/scripts/run.py finish  --work /app/work --output /app/output [--strict]
```
退出码：`0` 成功 ｜ `3` `--strict` 下有硬错误 ｜ `4` 未修订草稿 / 硬门禁 ｜ `2` 用法。

## 3. 机制/通路语义词汇表（**冻结**）

### 3.1 `figure.kind`
`relationship_schematic | chart | flowchart | mixed`（原）
**新增**：`mechanism_pathway` —— 机制/通路图主类型；`mixed` 仍表示机制图 + 数据图混排。

### 3.2 `entities[].kind`
原：`gene | protein | process | treatment | sample | category | axis | concept | compound | cell | condition`
**新增（冻结）**：`complex`（蛋白复合物）｜ `organelle`（亚细胞区室实体）｜ `cell_type`（细胞类型）｜
`metabolite`（小分子代谢物）｜ `modification_site`（修饰位点，如 `PDH Ser293-P`）｜ `stimulus`（缺氧/ROS 等外源或上游刺激）｜ `drug`

**基因/蛋白不得混用（硬门禁 `E_GENE_PROTEIN_CONFUSION`）**：
- `kind=gene` ⇒ label 为**斜体基因符号**（`HIF1A`、`Nqo1`），不得带 `-P`/`p-`/`pSer`/蛋白修饰后缀；
- `kind=protein` ⇒ label 为蛋白名（`HIF-1alpha`、`PDH`、`LDHA protein`），可带修饰（`PDH (Ser293-P)`）；
- 物种前缀（`human `、`h`、`Hs`）与旧名/同义名必须在 `entities[].attributes.synonyms` 与本 `source` 中留痕；
- 同一 `attributes.normalized_symbol` 的两个实体若 kind 不同（基因 vs 蛋白）**允许共存**，但 label 必须可区分且各自有 source。

### 3.3 `containers[]`（区室/膜/分组）
`containers[].kind` **新增枚举**：
`compartment`（nucleus | cytosol | mitochondrion | er | golgi | lysosome | extracellular | cytoplasm）｜
`membrane`（**质膜等脂双层，实体可“坐落其上”**）｜ `cell` ｜ `group`。

**膜定位硬规则（`E_MEMBRANE_PLACEMENT`）**：
`entities[].membrane_role` ∈ `transmembrane | membrane_anchored | luminal | cytosolic | extracellular | na`。
- `transmembrane` / `membrane_anchored` ⇒ `entities[].container` **必须**是某个 `kind=="membrane"` 的容器 id；
- 布局必须把该实体画在**膜带之上**（膜带内），跨膜受体的胞外域朝 `extracellular` 侧、胞内域朝 `cytosol` 侧；
- 把跨膜受体画进 `cytosol`/`nucleus` 容器内部 ⇒ 硬门禁拦截。

### 3.4 `relations[].type`（**冻结语义表**，样式不可自由发挥）
原：`activation | inhibition | containment | sequence | causation | association | membership`
**新增**：`binding | modification | transport | transcription | translation | feedback`

| type | arrow | stroke | 强制约束 | 图例必须有的条目 |
|---|---|---|---|---|
| `activation` | `normal` | `solid` | 同向 rank 递增 | 箭头=激活 |
| `inhibition` | `tee` | `solid` | 同向 rank 递增 | 平头(⊥)=抑制 |
| `binding` | `none` | `solid` | 两端**同区室**（`E_COMPARTMENT_MISMATCH`） | 无箭头实线=结合 |
| `modification` | `normal` | `dashed` | `label` 必须写明修饰种类（磷酸化/泛素化/乙酰化…） | 虚线箭头=修饰 |
| `transport` | `normal` | `solid` | 必须跨 ≥1 个容器边界，且写 `crosses:[fromContainer,toContainer]` | 跨边界箭头=转运 |
| `transcription` | `normal` | `solid` | `from` 在 nucleus，`to` 为 `kind=gene` | 箭头=转录激活 |
| `translation` | `normal` | `solid` | `from` 为 `kind=gene`，`to` 为 `kind=protein` | 箭头=翻译 |
| `feedback` | `normal` | `dashed` | **参与环**：`from` rank ≥ `to` rank | 虚线=反馈 |
| `association` | `none` | `dotted` | 无方向 | 点线=关联（无方向） |
| `containment` / `membership` | `none` | `dotted` | 由 `containers` 派生 | 虚线框=区室 |
| `sequence` / `causation` | `normal` | `solid` | 同向 rank 递增 | 箭头=顺序/因果 |

**样式一致性硬门禁 `E_INTERACTION_STYLE_MISMATCH`**：实际渲染的 `(arrow, stroke)` 与上表不符，或某 type 出现在图面上但图例缺对应条目 ⇒ 拦截。

### 3.5 方向与拓扑
`figure.flow.orientation` ∈ `top_down | left_right`（默认 `top_down`）。
`figure.flow.ranks`：`{entityId: int}`。**冻结判据 `E_FLOW_DIRECTION`**：
- 非 `feedback` 的关系 `from→to` 必须满足 `rank[to] > rank[from]`（同 rank 仅允许 `binding`/`association`）；
- 由非 `feedback` 边构成的**有向环** ⇒ 拦截（必须显式标 `feedback`）；
- 受体—胞内—核内层级：若存在 `extracellular→membrane→cytosol→nucleus` 链，其 rank 必须单调递增。

### 3.6 证据与数据编码
- `relations[].evidence`（可选但材料给出时**必须**填）：`{strength: high|medium|low, kind: direct|indirect|inferred, note, source}`。
  **线宽冻结映射**：high `1.4pt` ｜ medium `1.0pt` ｜ low `0.6pt`。图例必须写明该通道。
- `entities[].abundance`（可选）：`{value:number, unit, source}` ⇒ **节点大小**编码（面积 ∝ value，`E_UNIT_MISSING` 若无单位）。
- `legend[].encoding`（**新增，图例由模型生成，禁止手写**）：
  `{channel: color|line_width|node_size|line_style, field, unit, mapping:[{value, visual}]}`
  **`E_LEGEND_DATA_MISMATCH` 判据**：`mapping` 的值集合 == 图面上真实使用的视觉取值集合 == 数据中的取值集合（三者逐一对应，多一项少一项都拦截）。

### 3.7 补充冻结错误码（2026-11-23 11:50 追加，Lead 裁定）
| code | 触发 | 级别 |
|---|---|---|
| `E_EVIDENCE_WIDTH_MISMATCH` | 边线宽 ≠ §3.6 的 `evidence.strength` 冻结映射（high 1.4 / medium 1.0 / low 0.6 pt） | error |
| `E_ABUNDANCE_SIZE_MISMATCH` | 节点面积 ≠ `abundance.value` 的编码（面积 ∝ value），或图例未声明该通道 | error |
| `E_PLATFORM_FIELD_MISSING` | `result.json` 顶层或 `output_contract` 内缺平台 7 字段之任一（`case_id/status/editable_source/export_artifact/content_map/compliance_checks/exceptions`） | error |
| `W_UNIT_DIMENSIONLESS_ASSUMED` | 列名命中**无量纲 allowlist**（`p_value,padj,q_value,fdr,fold_change,log2fc,logfc,ratio,score,count,n,n_cells,r2,r_squared,z_score,auc,index,rank,level,replicate,id,cv,se,sd`，大小写/下划线归一）且材料未给单位 ⇒ 按惯例视为无量纲 | warning |
| `E_TRANSPORT_BOUNDARY` | `type=transport` 的边未跨越 ≥1 个真实容器边界（或未声明 `crosses`） | error |
| `E_EDGE_THROUGH_NODE` | 边几何穿过非端点的节点框 / 标签（布局可读性） | error |

> **实现状态如实标注（2026-11-23 13:5x，layout-engine 实测）**：`E_TRANSPORT_BOUNDARY` 与 `E_EDGE_THROUGH_NODE`
> **在 `layout.py` 侧只声明未实现**——`check_layout` 实际只发出 4 个码：`E_NODE_OVERLAP` / `E_OUT_OF_CANVAS` /
> `E_TEXT_OVERFLOW_EST` / `E_LEVEL_REGRESSION`。`transport` 的跨边界断言目前落在 `E_COMPARTMENT_MISMATCH`（`compliance.py`）；
> 膜定位的几何证据（`membrane_on_band` / `membrane_outward` / `membrane_probe_mm`）由布局**计算并记录**在
> `layout.compartments`，硬拦截由 `compliance.py`/`model.py` 的 `E_MEMBRANE_PLACEMENT` 承担。
> 引用这两个码时不得声称"layout 已拦截"。

**`output_contract` 双形态（冻结）**：平台 `resources/example-input.json` 给的是**列表** `["case_id","status",...]`，
其他案例可能给 mapping。两者语义相同（这些字段必须出现在 `result.json`），实现必须都接受，**非 dict 不得退化成 `{}`**。
`result.json` 中这 7 个字段**同时**出现在**顶层**与 `output_contract` 内（两种读法都要能取到）。

### 3.8 已追认的实现策略（2026-11-23 13:4x 冻结，来源 `schemas/mech_ontology.json.policies`）
以下 5 条不是放宽门禁，而是把「可判据化 + 留痕」写进契约；实现必须**在输出里记录**采用了哪一条：
1. `membrane_anchored` 允许被建模在相邻胞质区室，布局将其移到膜带并记 `W_MEMBRANE_ANCHOR_COMPARTMENT`；只有 `transmembrane` 强制 `container.kind == "membrane"`。
2. 跨膜带上的配体—受体 `binding` 不算 `E_COMPARTMENT_MISMATCH`（两端分处胞外与膜带属正常拓扑）。
3. 自环（`from == to`）豁免 rank 递增与有向环判定（一条边一个节点无法满足 rank 严格递增）。
4. `transcription` 的起点可在核外，但必须声明 `crosses`。
5. `transport` 缺少 `crosses` 而两端容器已不同 ⇒ 降为 warning（几何上确实跨界时不以 error 结束）。

## 4. 输出契约（`/app/output/result.json`）

### 4.1 locator 文法（**2026-11-23 12:0x 冻结**）
`source.locator` 的合法形式：`L12` ｜ `L12-L18` ｜ `p12` ｜ `table:<col>` ｜ `fig:<n>` ｜
**`json:<json-pointer>`**（如 `json:entities/e_exr1`，由 `ingest.py:694` 为 `figure-workbench`/`figure-workorder.json`
类结构化输入生成）｜ `csv:<col>`。
**所有校验点必须接受该文法**（`render_svg.py` 的 `_valid_locator`、`layout.py` 的 `_valid_locator`、
`compliance.py` 的 `_LOCATOR_RE`）。仅当 `quote` 在来源单元里**逐字找不到**时才允许把
`data-src-kind` 降级为 `unsupported`；**不得仅因 locator 是 `json:`/`csv:` 前缀就降级**。
（真实隐藏案例的 workorder 正是这种形态 ⇒ 这条直接决定「结果可核验性」得分。）

### 4.2 result 字段
必需键（平台原样保留）：`case_id, status, editable_source, export_artifact, content_map, compliance_checks, exceptions`。
其中：
- `status` ∈ `ok | partial | failed`；`partial` **必须**在 `exceptions[]` 写明限制。
- `editable_source`：主源路径（`figures/<stem>.svg`，7 命名图层，文字为真 `<text>`，`<image>` 数为 0，逐元素溯源属性和 `data-*`）。
- `export_artifact`：`{format: {path, bytes, sha256, dpi, font_embedded, available, reason_if_unavailable}}`，**只写真产出的文件**。
- `content_map`：`entities[] / relations[] / containers[] / legend[]` 的图上落实清单（id → 画布上可定位的 `data-entity-id` / `data-relation-id`）。
- `compliance_checks`：每条 `{id, level: error|warning, status: pass|fail|na, where, detail}`，**error 级为 fail 时 `status` 不得为 `ok`**。
- `exceptions`：缺后端、缺来源、歧义未决、跳过项，逐条给原因与影响面。

## 5. 写域（互不重叠，违反即返工）

| 写者 | 独占文件 |
|---|---|
| Lead | `work/CONTRACT.md`, `scripts/run.py`, `scripts/common.py`, `scripts/selftest.py`, `RESULT.md`, `CHECKPOINT.md`, `work/submission/manifest.json` |
| mech-semantics | `scripts/ingest.py`, `scripts/model.py`, `scripts/mech.py`(新), `schemas/**` |
| layout-engine | `scripts/layout.py` |
| render-export | `scripts/render_svg.py`, `scripts/export.py`, `scripts/compliance.py` |
| docs-skill | `SKILL.md`, `README.md`, `references/**`, `examples/**`, `GITHUB_URL.txt` |
| verify-harness | `work/verify/**` |
| acceptance-reviewer | `work/review/**` |

**测试入口**：任何改动后必须 `python work/submission/scripts/selftest.py`（Lead 在集成后跑全量）；写者自查用 `python -m py_compile` 之外的真实运行，禁止 `__pycache__` 进树（`PYTHONDONTWRITEBYTECODE=1`）。
