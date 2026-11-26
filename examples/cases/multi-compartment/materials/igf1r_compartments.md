# IGF1R 多区室跨膜受体通路（本地验收夹具 C：多区室 + 跨膜受体）
本文件是该图的唯一来源真身；图上出现的每一个标签与数值都必须能在本文件中逐字定位。
任务：依据本材料绘制一张可编辑的多区室机制图，交付分层 SVG 主源与导出件，并给出逐元素溯源。

胞外配体 IGF1 激活质膜上的跨膜受体 IGF1R。
IGF1R 是跨膜受体，胞外域在胞外区室，胞内域在胞质。
IGFBP3 是膜锚定蛋白，锚定在质膜上。
活化的 IGF1R 激活胞质接头蛋白 IRS1。
IRS1 激活胞质复合物 PI3K。
PI3K 与 p85 在同一区室（胞质）内结合，形成稳定的复合物。
PI3K 激活胞质激酶 Akt1。
Akt1 磷酸化 GLUT4 并促使其转位。
活化的 Akt1 转运进入细胞核区室，作用于转录因子 FOXO3。
Akt1 磷酸化 FOXO3 并抑制其转录活性。
IGFBP3 与 IGF1R 存在关联，可能影响配体结合。

区室层级：胞外区室、质膜、胞质、细胞核，rank 沿受体-胞内-核内层级单调递增。
区室成员：胞外区室包含 IGF1 与质膜。
质膜包含 IGF1R、IGFBP3 与胞质。
胞质包含 IRS1、PI3K、p85、Akt1、GLUT4 与细胞核。
细胞核包含 FOXO3。

丰度数据：IGF1R 的丰度为 5.5 nM。
丰度数据：PI3K 的丰度为 2.2 nM。
冻结线宽映射：evidence.strength 为 high 对应 1.4 pt，medium 对应 1.0 pt，low 对应 0.6 pt。
证据强度：IGF1 到 IGF1R 为 high，IGF1R 到 IRS1 为 high，IRS1 到 PI3K 为 medium，Akt1 到 FOXO3 为 low，Akt1 到 GLUT4 为 medium，IGFBP3 到 IGF1R 为 low。
证据强度：Akt1 到 FOXO3 的抑制为 medium。
# 标签词典：图上出现的全部显示标签，逐字可复制溯源（每行一个标签）
IGF1R 多区室跨膜受体机制图
IGF1
IGF1R
IGFBP3
IRS1
PI3K
p85
Akt1
GLUT4
FOXO3
胞外区室
质膜
胞质
细胞核
激活
结合
磷酸化
转运
抑制
关联
激活（实线箭头）
抑制（平头线）
结合（无箭头实线）
修饰（虚线箭头）
转运（跨边界箭头）
关联（点线）
线型=相互作用类型（线型按冻结表）
线宽=证据强度（high 1.4 / medium 1.0 / low 0.6 pt）
节点面积=丰度（面积 ∝ value）
多区室受体通路示意
