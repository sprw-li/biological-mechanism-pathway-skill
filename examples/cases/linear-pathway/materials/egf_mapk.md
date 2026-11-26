# EGF-MAPK 线性通路（本地验收夹具 A：线性通路 + 跨膜受体定位）
本文件是该图的唯一来源真身；图上出现的每一个标签与数值都必须能在本文件中逐字定位。
任务：依据本材料绘制一张可编辑的机制图，交付分层 SVG 主源与 PDF/PNG 导出件，并给出逐元素溯源。

胞外刺激 EGF 激活质膜受体 EGFR。
EGFR 是跨膜受体，其胞外域朝向胞外区室，胞内域位于胞质。
活化的 EGFR 激活胞质接头蛋白 GRB2。
GRB2 激活激酶 MAP2K1。
MAP2K1 磷酸化并激活 MAPK1。
活化的 MAPK1 转运进入细胞核区室。
核内转录因子 ELK1 被 MAPK1 激活。
ELK1 促进 FOS 基因转录。
FOS 基因翻译为 c-Fos 蛋白。

区室层级：胞外区室、质膜、胞质、细胞核，rank 沿通路单调递增。
区室成员：胞外区室包含 EGF 与质膜。
质膜包含 EGFR 与胞质。
胞质包含 GRB2、MAP2K1、MAPK1 与细胞核。
细胞核包含 ELK1 与 FOS 基因。

冻结线宽映射：evidence.strength 为 high 对应 1.4 pt，medium 对应 1.0 pt，low 对应 0.6 pt。
丰度数据：EGFR 的丰度为 3.0 nM。
丰度数据：c-Fos 蛋白的丰度为 12.5 nM。
证据强度：EGF 到 EGFR 为 high，EGFR 到 GRB2 为 medium，GRB2 到 MAP2K1 为 high，MAP2K1 到 MAPK1 为 medium，MAPK1 到 ELK1 为 low，ELK1 到 FOS 为 high，FOS 到 c-Fos 为 medium。
# 标签词典：图上出现的全部显示标签，逐字可复制溯源（每行一个标签）
EGF-MAPK 线性通路机制图
EGF
EGFR
GRB2
MAP2K1
MAPK1
ELK1
FOS
c-Fos
胞外区室
质膜
胞质
细胞核
激活
磷酸化
转运
转录
翻译
激活（实线箭头）
修饰（虚线箭头）
转运（跨边界箭头）
转录（箭头）
翻译（箭头）
线型=相互作用类型（线型按冻结表）
线宽=证据强度（high 1.4 / medium 1.0 / low 0.6 pt）
节点面积=丰度（面积 ∝ value）
线性通路关系示意
