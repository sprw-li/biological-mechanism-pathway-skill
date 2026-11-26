# 缺氧-HIF1A 分支与反馈通路（本地验收夹具 B：分支 + 反馈环）
本文件是该图的唯一来源真身；图上出现的每一个标签与数值都必须能在本文件中逐字定位。
任务：依据本材料绘制一张可编辑的机制图，包含并行分支与负反馈环，交付分层 SVG 主源与导出件。

缺氧刺激激活 HIF-1alpha 蛋白的稳定化。
HIF1A 促进 VEGFA 基因转录。
HIF1A 促进 EPO 基因转录。
VEGFA 基因翻译为 VEGFA protein。
VEGFA 蛋白激活 VHL 蛋白。
VHL 蛋白抑制 HIF-1alpha 蛋白，构成负反馈环。

区室成员：胞外区室包含缺氧刺激。
胞质包含 HIF-1alpha 蛋白与 VEGFA protein。
细胞核包含 VEGFA 基因与 EPO 基因。
胞质包含 VHL 蛋白。

冻结线宽映射：evidence.strength 为 high 对应 1.4 pt，medium 对应 1.0 pt，low 对应 0.6 pt。
丰度数据：HIF-1alpha 蛋白的丰度为 8.0 nM。
丰度数据：VEGFA protein 的丰度为 20.0 nM。
表达数据：常氧组与缺氧组的 fold_change 见 expression.csv。
# 标签词典：图上出现的全部显示标签，逐字可复制溯源（每行一个标签）
缺氧-HIF1A 分支与反馈通路
缺氧刺激
HIF-1alpha
VEGFA 基因
EPO 基因
VEGFA protein
VHL 蛋白
胞外区室
胞质
细胞核
激活
转录
翻译
负反馈
激活（实线箭头）
转录（箭头）
翻译（箭头）
反馈（虚线）
线型=相互作用类型（线型按冻结表）
线宽=证据强度（high 1.4 / medium 1.0 / low 0.6 pt）
节点面积=丰度（面积 ∝ value）
Normoxia
Hypoxia
配色=分组（category 配色映射）
分支与反馈环示意
