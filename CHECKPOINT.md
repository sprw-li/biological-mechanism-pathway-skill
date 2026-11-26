# CHECKPOINT — ARMI2611000060v1 · 生物机制图与通路图（challenge-83d4f050）

更新时间：2026-11-23 15:2x +08:00　｜　登记人：Lead

## 0. 一句话状态

**已交付并已提交（v2）**：attempt **100713**（`submitted`/`queued`，人工评审）。冻结树 `tree_sha256 = 2c3c9af9e22e49758c57da03c67f8e4b26e271e4f024af4b3c45255602201237`
（30 文件 / 1,128,381 B），bundle 闸门 + G10 轨迹闸门**双 PASS**；GitHub public 仓库已与冻结树同步（Contents API）。
独立验收者终验判定 **CONDITIONAL**：正向 **207 PASS / 2 FAIL**（两条同源 = **B1-residual**：节点面积混入标签长度）、
负例 **injected 33 / detected 31**（缺口 2 条 = 两个契约已冻结但未实现的码）——**不作为"达成"**，未清项见 §3。


## 1. 底座

| 项 | 值 |
|---|---|
| challenge_id | `challenge-83d4f050`（`ARMI:2611.000060v1`，`human_review_only`，100 + 5） |
| 题面/数据 | `task/task.md`、`task/challenge.json`、`task/datasets/paper2arm-task-challenge-83d4f050-8f53d166/1/` |
| 运行契约 | `/input/case.json`；`/app/work`；`/app/output`（含 `result.json`）；64 请求 / 900 秒 / 16384 tokens |
| 资源上限 | ≤50 文件 / 单文件 ≤500KB / 合计 ≤2MB / 无 symlink |
| 平台必填字段 | `case_id, status, editable_source, export_artifact, content_map, compliance_checks, exceptions`（顶层 + `output_contract` 内） |
| 接口冻结 | `work/CONTRACT.md` v1.1（含 §3.7 补充错误码、§3.8 追认策略、§4.1 locator 文法） |

**数据集获取（复现用）**：`bh.py pull` 因沙箱 node 管道 `spawn EPERM`；改用
`$env:VOUCH_CONFIG_DIR='D:\Borium_Contest\.vouch'; $env:VOUCH_CLIENT_ID='trisol-cli-10ee'` +
`wenyon-cli.exe dataset download paper2arm-task-challenge-83d4f050-8f53d166 --version 1 --output-dir <...> --output json`。

## 2. 交付与提交回执

| 项 | 值 |
|---|---|
| 交付本体 | `work/submission/`（30 文件）；`deliverables/submission/` 哈希一致镜像（30 文件，0 处不符） |
| Skill 名 | `biological-mechanism-pathway-figure`（`common.SKILL_NAME` 从 `SKILL.md` frontmatter 读取，单一真相源） |
| **attempt_id** | **100713**（v2，当前有效；v1 = 100345，两笔包 SHA 不同、均非重复提交） |
| bundle | `receipts/bundle_v2.zip` 9,499,508 B，sha256 `a0b47b1127d411057d971817a5076d3557862a2964f7dea6eee75c441fe5e5de` |
| trace | `traces/trace_v3.jsonl` 1,512,214 B / 856 记录 / 454 tool_result，sha256 `cee6bacd10fae8d2…` |
| 冻结树 | `files=30 / bytes=1,128,381 / tree_sha256 = 2c3c9af9e22e49758c57da03c67f8e4b26e271e4f024af4b3c45255602201237`；`deliverables/submission/` 逐文件哈希一致 |
| 闸门 | v2 bundle **PASS**（104 entries、unsafe 0、native_trace 恰好 1、skill_files 30、symlinks 0）；G10 **PASS exit 0**；SHA 去重通过（该题 1 条历史包，SHA 不同） |
| 回执原文 | `receipts/submit_v2.out`（v1：`submit_v1.out`） |
| GitHub | https://github.com/sprw-li/biological-mechanism-pathway-skill （public；**已与冻结 v2 树同步**，最新提交 `fe043343561cba1ce321f268c1b57b6710d4eef7`；`git push` 两次连接重置后改走 Contents API `work/publish_repo.py`） |

| 轮询 | 3 次全部 `queued` ⇒ 归 **external-review**，已停手（不重投、不换 SHA） |

## 3. 独立验收与未解决缺陷

**验收者（verify-harness，非实现方）终验总门禁：`CONDITIONAL`**（`work/verify/REVIEW.md`，指纹绑定 `harness_results.json.skill_module_sha256`）
- 正向 `run`：**207 PASS / 2 FAIL / 0 UNVERIFIED / 6 N/A**
- 负例 `negative`：**`injected=33 / detected=31`**，`vacuous_skips=[]`，无超时假阴性
- 不可验范围：隐藏案例、`/skills` 实装与触发、人工视觉判断、平台计分与白板、64 请求/900s 真实消耗

| 缺陷 | 状态 |
|---|---|
| **P0** 我引入的 `layout.py` `NameError: degrade`（全管线 `render exit 2`） | **已修**（验收者 `run8` 曾 84 FAIL / SVG 全空，修复后四夹具 exit 0） |
| **B1 二次缩放根因**（render 与 layout 各自缩放同一通道 ⇒ 面积恒偏 x0.68） | **已修**（删除 render 侧缩放；判据 (iv)「SVG 盒 == layout 盒」三夹具全 PASS，drift 全 x1.00） |
| **B1-residual**（面积 = 文本/列宽驱动基础盒 × √(value/ref) ⇒ 混入标签长度） | **未修**（唯一未清正例根因，2 条 FAIL；锚点 `layout.py:1947-1950`） |
| B2 中文材料下 `E_GENE_PROTEIN_CONFUSION` 误报 | **已修**（`_norm_name` 保留 CJK，与 `mech.normalise_key` 同口径；验收者新指纹复核转绿） |
| B3 `E_PLATFORM_FIELD_MISSING` 未实现 | **已修**（`run.py`；验收者负例检出） |
| B7 无量纲 allowlist 未接上报错路径（过严） | **已修**（正反两向均有验收者实测） |
| B8 `abundance.value` 不做来源核对 | **已修**（伪造值 ⇒ `E_NUMBER_NOT_IN_SOURCE`，`where` 命中元素） |
| B9 `ctx["degradations"]` 从未 flush ⇒ 披露达不到平台可见字段 | **已修**（`layout()` 末尾统一 flush；`figure_issues.json`/`compliance_checks` 实测可见） |
| B4 `E_EVIDENCE_WIDTH_MISMATCH` / `E_ABUNDANCE_SIZE_MISMATCH` 未实现 | **未修**（契约已冻结、实现未落地 ⇒ 记 UNVERIFIED，负例缺口的全部来源） |
| B6 单阶段偶发 >150s（宿主争用） | 未清（真实风险：平台 900s/案例预算） |


## 4. 本版真实成绩（可重跑）

| 检查 | 命令 | 结果 |
|---|---|---|
| 端到端集成（Lead 4 夹具） | `& $PY work\integration_check.py` | **4 case(s), 0 failing, exit 0**；每夹具 `export/finish exit=0`、`status=ok`、`compliance_checks=35/33/32/34` 无 error 级失败 |
| Skill 自测 | `& $PY work\submission\scripts\selftest.py` | **PASS 67/0/exit 0** |
| 机制判据（正负双向） | `& $PY work\fixtures\check_mech.py` | **38/38 exit 0** |
| 门禁注入负例 | `& $PY work\fixtures-render\gates.py` | **24/24 exit 0** |
| 中文取值图例编码 | `& $PY work\fixtures-render\chinese_encoding_check.py` | **PASS exit 0**（旧实现两中文键塌成 `''` ⇒ 同色；现分别映射） |
| 结构合规 | `& $PY _shared\tools\validate_skill_submission.py work\submission` | `status=ok`，30 文件 / 1,121,506 B，`errors=[]` |
| manifest 完整性 | `& $PY work\freeze_manifest.py --check` | **PASS (29 files, 0 problem(s))** |
| 未修订草稿硬门禁 | 集成内置负例 | `render exit=4` + `E_MODEL_NOT_REVISED` |

## 5. 团队与写域（全部已停写，除 verify-harness）

| 成员 | 任务 | 终态 | 备注 |
|---|---|---|---|
| Lead | 合同/run.py/common.py/selftest.py/reference.py/integration/提交 | 完成 | 含 D1/D9/D15 与 B1/B3 修复 |
| mech-semantics | task-1 `ingest/model/mech/schemas` | **complete** | `check_mech` 38/38 |
| layout-engine | task-2 `layout.py` | **released（如实未完成）** | 崩溃已由 Lead 修；6 条未修项见 `RESULT.md §7`；`top_down` 显式降级 |
| render-export | task-3 `render_svg/export/compliance` | **complete** | `gates.py` 24/24；含 `E_UNTRACED_CANVAS_ELEMENT`、CJK 修复 |
| verify-harness | task-4 `work/verify` | 进行中（已产出 REVIEW/BASELINE/negative_results） | 判 CONDITIONAL |
| docs-skill | task-5 文档与示例 | **complete** | 30 文件 / ~1.12 MB |

## 6. Exhausted（供 blocked 判定；本轮未 blocked）

- **轮询**：attempt 100345 以 `--max 3` 有界轮询 3 次全部 `queued`，到顶转 external-review，未空转、未重投。
- **替代路径**：① `bh.py pull` 沙箱 `spawn EPERM` → wenyon CLI 直连取数据集成功；② `curl.exe` schannel `SEC_E_NO_CREDENTIALS` → Python `urllib` 成功；③ `git push` schannel/askpass 双失败 → `git -c http.sslBackend=openssl` + `GIT_ASKPASS`（token 取自 `gh auth token`，**未落盘**）成功；④ `edit` 工具对 `run.py` 返回 `ReplaceFileW EIO` → 用 Python 做同字符串替换并 `ast.parse` 校验成功。
- **范围裁剪**：不在隐藏案例上可验的能力一律标 UNVERIFIED；`top_down` 不可靠 ⇒ 显式降级并留痕，而不是交付坏图。
- **验收改造**：把"图画得好不好"落成可执行判据——`selftest`（67 项含注入负例）、`integration_check`（4 夹具端到端 + 未修订草稿负例 + 导出 magic byte + 平台字段 + 原图对照）、`check_mech`（38）、`gates.py`（24）、`work/verify/harness.py`（正向 198 / 负例 33 注入）、`freeze_manifest.py --check`。

## 7. 下一轮（按优先级）

1. **B1-residual（首位）**：节点尺寸改为**只由 value 决定**（边长 ∝ √value，标签只做字号+换行降级，复用 `W_LABEL_DEGRADED` 阶梯）；或保留文本驱动盒但把 legend/契约措辞改为**方向性编码**并实现 `E_ABUNDANCE_SIZE_MISMATCH`。锚点 `layout.py:1947-1950`，证据 `work/verify/harness_results.json` 的 2 条 FAIL。
2. 实现两个已冻结未落地的码：`E_EVIDENCE_WIDTH_MISMATCH`、`E_ABUNDANCE_SIZE_MISMATCH`（可把负例从 31/33 抬到 33/33）。
3. `top_down` 真转置（思路见 `RESULT.md §7.1`：转置做成构建参数 + 与 `left_right` 共用同一确定性 fit 判据）。
4. `RESULT.md §7` 其余项（自环路由退化、面板字母溯源、`metrics.flow_scale` 恒 1.0、确定性 fit 未接线）。
5. attempt **100713** 出分后读**平台详情原文**归因（勿只看 `status`；`score=0 + scoringDetails=null + queued` 是未评分默认值）；**同 bundle SHA256 绝不重投**。
6. 补跑 opt 8×n 矩阵与 council 8 次调用（本轮未跑，见 `RESULT.md §6`）。

## 8. 污染事件（如实记录）

v1 提交（14:57）后 15:07:45 出现 `work/submission/scripts/__pycache__/mech.cpython-312.pyc`（64,407 B，并发运行的 import 残留；**提交时的 bundle 已核为 30 文件且无 pycache**）。删除后复算 `tree_sha256` 与冻结值逐字节相同。**v2 冻结前再次全树扫描 `__pycache__`/`*.pyc` 为空**；`deliverables/submission/` 与 GitHub 副本亦无。
