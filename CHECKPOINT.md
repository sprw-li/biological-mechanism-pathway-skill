# CHECKPOINT — ARMI2611000060v1 · 生物机制图与通路图（challenge-83d4f050）

更新时间：2026-11-23 15:2x +08:00　｜　登记人：Lead

## 0. 一句话状态

**已交付并已提交**（attempt **100345**，`submitted`/`queued`，人工评审）。冻结树 `tree_sha256 = 1046714de9e1a0a63eda2f80f107cbc34f6b11ce70f6ea00236b17f10c147220`
（30 文件 / 1,121,506 B），**打包后复算逐字节相同**；bundle 闸门 + G10 轨迹闸门双 PASS；GitHub public 仓库已推送并核验可见。
独立验收者判定 **CONDITIONAL**（正向 198/1、负例 injected 33 / detected 7）——**不作为"达成"**，未解决项见 §3。

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
| **attempt_id** | **100345** |
| bundle | `receipts/bundle_v1.zip` 8,453,199 B，sha256 `8a7e2bad51bf6d578d5925a479222d7523b6056d75149e21b37ccbdd8c8d669f` |
| trace | `traces/trace_v2.jsonl` 1,262,495 B / 663 记录 / 359 tool_result，sha256 `c1ce88dbd388e765bdc5f4c189663448770f4df7a74925cb58ad318b8f307fca` |
| 闸门 | bundle **PASS**（104 entries、unsafe 0、native_trace 恰好 1、skill_files 30、symlinks 0）；G10 **PASS exit 0**；SHA 去重通过 |
| 回执原文 | `receipts/submit_v1.out` |
| GitHub | https://github.com/sprw-li/biological-mechanism-pathway-skill （public，commit `2f07dd659984`；提交回执落盘后的一次 `RESULT.md` 文档增补**未能补推**——15:2x 两次 `github.com:443` 连接失败后按规则停手，仓库与本地差一次**文档**提交） |
| 轮询 | 3 次全部 `queued` ⇒ 归 **external-review**，已停手（不重投、不换 SHA） |

## 3. 独立验收与未解决缺陷

**验收者（verify-harness，非实现方）总门禁：`CONDITIONAL`**（`work/verify/REVIEW.md`）
- 正向 `run`：198 PASS / 1 FAIL / 0 UNVERIFIED / 1 N/A
- 负例 `negative`：`injected=33 / detected=7 / vacuous_skips=[]` ⇒ **26 条注入未检出**（最严重未解决项）
- 不可验范围：隐藏案例、`/skills` 实装与触发、人工视觉判断、平台计分

| 缺陷 | 状态 |
|---|---|
| B1 节点面积 ∝ `abundance.value` 被钳位 | **验收后已修**（精确 `sqrt(v/ref)` + 超界发 `W_ABUNDANCE_SIZE_CLAMPED` 披露） |
| B2 中文材料下 `E_GENE_PROTEIN_CONFUSION` 误报（`_norm_name` 删 CJK） | **已修**（与 `mech.normalise_key` 同口径；`render_svg._key` 同源缺陷一并修） |
| B3 `E_PLATFORM_FIELD_MISSING` 未实现 | **已修**（`run.py`：缺字段 ⇒ error 级 + `status` 降 `partial`） |
| B4 `E_EVIDENCE_WIDTH_MISMATCH` / `E_ABUNDANCE_SIZE_MISMATCH` 未实现 | **未修**（契约已冻结、实现未落地 ⇒ 记 UNVERIFIED） |
| 负例 26/33 未检出 | **未解决**（下一步优先） |

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

1. **负例 26/33 未检出**（`work/verify/negative_results.json`）：逐条核对是"判据缺失"还是"注入本身无效"，前者补门禁、后者修注入——**这是当前最大缺口**。
2. B4 两个冻结码落地（`E_EVIDENCE_WIDTH_MISMATCH` / `E_ABUNDANCE_SIZE_MISMATCH`）。
3. `top_down` 真转置（思路见 `RESULT.md §7.1`：转置做成构建参数 + 与 `left_right` 共用同一确定性 fit 判据）。
4. 其余 `RESULT.md §7` 的 1–10 条。
5. attempt 100345 出分后读**平台详情原文**归因（勿只看 `status`；`score=0 + scoringDetails=null + queued` 是未评分默认值）；**同 bundle SHA256 绝不重投**。
6. 补跑 opt 8×n 矩阵与 council 8 次调用（本轮未跑，见 `RESULT.md §6`）。

## 8. 污染事件（如实记录）

提交（14:57）后 15:07:45 出现 `work/submission/scripts/__pycache__/mech.cpython-312.pyc`（64,407 B，某并发运行的 import 残留；**提交时的 bundle 已核为 30 文件且无 pycache**）。Lead 已删除，复算 `tree_sha256` 与冻结值**逐字节相同**；`deliverables/submission/` 与 GitHub 副本扫描均无 `__pycache__`。
