# 目标导向写作材料包（人看版）

- 当前目标：提取工艺参数与组织性能关系
- 材料规模：5 个业务主题，12 个写作点，6 张图，0 个表，0 条引用，0 条参数，0 条结果。

## 语义主题

### theme_001 | discussion
- 主题摘要：Main effect Laser power (A) 6.256 3 3.901 3.490 Scanning speed (B) 0.015 3 0.009 3.490 Wire feeding speed (C) 0.124 3 0.077 3.490 Air pressure (D) 0.020 3 0.012 3.490 Interaction effect Laser power × Scanning speed (A × B) 5.782 9 16.05 8.020
- 包含写作点：wp080, wp060, wp067, wp072, wp075, wp102

### theme_003 | mechanism
- 主题摘要：If the wire feeding speed is mismatched with the available heat input (e.g., high feed rate with insufficient energy), it can cause the wire to directly strike the melt pool or result in large droplets detaching into the pool.
- 包含写作点：wp043, wp054

### theme_002 | discussion
- 主题摘要：To clarify the independent influence patterns of laser power, scanning speed, wire feeding speed, and air pressure on the porosity of 5356 aluminum alloy samples prepared by LWDED, as well as the influence weight of each parameter and the significance of interaction terms, single-factor experiments and orthogonal experiments were conducted.
- 包含写作点：wp046

### theme_004 | mechanism
- 主题摘要：This is attributed to insufficient heat input failing to achieve adequate fusion between the wire and the substrate, resulting in substantial lack-of-fusion defects and a shallow penetration depth under this condition [34].
- 包含写作点：wp050

### theme_005 | result
- 主题摘要：Analysis of the experimental data revealed that a minimum porosity of 0.13% was achieved under the following optimized conditions: a laser power of 1450 W, a scanning speed of 650 mm/min, a wire feeding speed of 130 cm/min, and an air pressure of 0.2 MPa.
- 包含写作点：wp065, wp073

## 一致性校验

- 校验结论：FAIL｜错误 5｜警告 5
- [ERROR] writing_point:wp080 - 写作点没有任何图、表、参数、结果、引用或 source_chunk 支撑。
- [ERROR] writing_point:wp046 - 写作点没有任何图、表、参数、结果、引用或 source_chunk 支撑。
- [ERROR] writing_point:wp043 - 写作点存在结构证据，但语义层面未能支撑 claim（主题/参数/现象不匹配或存在冲突）。
- [WARNING] writing_point:wp054 - 写作点仅获得部分语义支撑，建议补充更直接的图表、参数或结果证据。
- [WARNING] writing_point:wp050 - 写作点仅获得部分语义支撑，建议补充更直接的图表、参数或结果证据。
- [ERROR] writing_point:wp073 - 写作点没有任何图、表、参数、结果、引用或 source_chunk 支撑。
- [ERROR] writing_point:wp075 - 写作点没有任何图、表、参数、结果、引用或 source_chunk 支撑。
- [WARNING] theme:theme_003 - 主题仅获得部分语义支撑，建议补充与主张直接匹配的证据文本。
- [WARNING] theme:theme_002 - 主题下写作点缺少显式图表/参数/结果/引用链接，主文支撑较弱。
- [WARNING] theme:theme_004 - 主题仅获得部分语义支撑，建议补充与主张直接匹配的证据文本。

## 写作点卡

### 1. wp080 | discussion | 页 11
- 主张：Main effect Laser power (A) 6.256 3 3.901 3.490 Scanning speed (B) 0.015 3 0.009 3.490 Wire feeding speed (C) 0.124 3 0.077 3.490 Air pressure (D) 0.020 3 0.012 3.490 Interaction effect Laser power × Scanning speed (A × B) 5.782 9 16.05 8.020
- 方向定位：机理解释与因果分析
- 内容概述：该写作点概括了扫描速度、气压、激光功率变化与组织演化、熔池行为或缺陷形成之间的因果关系。
- 用途建议：适合用于机制讨论段，先概括驱动关系，再补充具体证据。
- 小结：该写作点主要服务于“机理解释与因果分析”这一叙述方向，可作为适合用于机制讨论段，先概括驱动关系，再补充具体证据的概括性材料。
- 证据边界：｜
- 相关度：0.971｜证据强度：0.000
- 因果角色：无
- 目标对齐：
- 证据摘要：0 图 / 0 表 / 0 参数 / 0 结果 / 0 引用

### 2. wp046 | discussion | 页 6
- 主张：To clarify the independent influence patterns of laser power, scanning speed, wire feeding speed, and air pressure on the porosity of 5356 aluminum alloy samples prepared by LWDED, as well as the influence weight of each parameter and the significance of interaction terms, single-factor experiments and orthogonal experiments were conducted.
- 方向定位：机理解释与因果分析
- 内容概述：To clarify the independent influence patterns of laser power, scanning speed, wire feeding speed, and air pressure on the porosity of 5356 aluminum alloy samples prepared by LWDED…。
- 用途建议：适合用作主题导读或段落收束，帮助读者快速把握研究内容。
- 小结：该写作点主要服务于“机理解释与因果分析”这一叙述方向，可作为适合用作主题导读或段落收束，帮助读者快速把握研究内容的概括性材料。
- 证据边界：｜
- 相关度：0.931｜证据强度：0.000
- 因果角色：无
- 目标对齐：
- 证据摘要：0 图 / 0 表 / 0 参数 / 0 结果 / 0 引用

### 3. wp043 | mechanism | 页 5
- 主张：If the wire feeding speed is mismatched with the available heat input (e.g., high feed rate with insufficient energy), it can cause the wire to directly strike the melt pool or result in large droplets detaching into the pool.
- 方向定位：机理解释与因果分析
- 内容概述：If the wire feeding speed is mismatched with the available heat input (e.g., high feed rate with insufficient energy), it can cause the wire to directly strike the melt pool or re…。
- 用途建议：适合放在正文论述中，用于承接图表证据并解释现象变化。
- 小结：该写作点主要服务于“机理解释与因果分析”这一叙述方向，可作为适合放在正文论述中，用于承接图表证据并解释现象变化的概括性材料。
- 证据边界：｜
- 相关度：0.870｜证据强度：0.000
- 因果角色：无
- 目标对齐：
- 证据摘要：1 图 / 0 表 / 0 参数 / 0 结果 / 0 引用
- 关联图：f2@p5

### 4. wp054 | mechanism | 页 7
- 主张：As scanning speed was progressively increased, the reduced laser interaction time brought the heat input to a reasonable level, thereby enhancing melt pool stability and leading to a continuous decline in porosity.
- 方向定位：机理解释与因果分析
- 内容概述：As scanning speed was progressively increased, the reduced laser interaction time brought the heat input to a reasonable level, thereby enhancing melt pool stability and leading t…。
- 用途建议：适合放在正文论述中，用于承接图表证据并解释现象变化。
- 小结：该写作点主要服务于“机理解释与因果分析”这一叙述方向，可作为适合放在正文论述中，用于承接图表证据并解释现象变化的概括性材料。
- 证据边界：｜
- 相关度：0.870｜证据强度：0.000
- 因果角色：无
- 目标对齐：
- 证据摘要：3 图 / 0 表 / 0 参数 / 0 结果 / 0 引用
- 关联图：f4@p7; f3@p7; f4@p7

### 5. wp050 | mechanism | 页 6
- 主张：This is attributed to insufficient heat input failing to achieve adequate fusion between the wire and the substrate, resulting in substantial lack-of-fusion defects and a shallow penetration depth under this condition [34].
- 方向定位：机理解释与因果分析
- 内容概述：This is attributed to insufficient heat input failing to achieve adequate fusion between the wire and the substrate, resulting in substantial lack-of-fusion defects and a shallow…。
- 用途建议：适合放在正文论述中，用于承接图表证据并解释现象变化。
- 小结：该写作点主要服务于“机理解释与因果分析”这一叙述方向，可作为适合放在正文论述中，用于承接图表证据并解释现象变化的概括性材料。
- 证据边界：｜
- 相关度：0.858｜证据强度：0.000
- 因果角色：无
- 目标对齐：
- 证据摘要：1 图 / 0 表 / 0 参数 / 0 结果 / 0 引用
- 关联图：f3@p7

### 6. wp060 | discussion | 页 8
- 主张：In this work, laser power, scanning speed, and wire feeding speed were fixed at 1350 W, 850 mm/min, and 130 cm/min, respectively.
- 方向定位：机理解释与因果分析
- 内容概述：In this work, laser power, scanning speed, and wire feeding speed were fixed at 1350 W, 850 mm/min, and 130 cm/min, respectively.
- 用途建议：适合放在正文论述中，用于承接图表证据并解释现象变化。
- 小结：该写作点主要服务于“机理解释与因果分析”这一叙述方向，可作为适合放在正文论述中，用于承接图表证据并解释现象变化的概括性材料。
- 证据边界：｜
- 相关度：0.846｜证据强度：0.000
- 因果角色：无
- 目标对齐：
- 证据摘要：2 图 / 0 表 / 0 参数 / 0 结果 / 0 引用
- 关联图：f6@p9; f5@p8

### 7. wp065 | result | 页 9
- 主张：Analysis of the experimental data revealed that a minimum porosity of 0.13% was achieved under the following optimized conditions: a laser power of 1450 W, a scanning speed of 650 mm/min, a wire feeding speed of 130 cm/min, and an air pressure of 0.2 MPa.
- 方向定位：参数影响与结果变化
- 内容概述：Analysis of the experimental data revealed that a minimum porosity of 0.13% was achieved under the following optimized conditions: a laser power of 1450 W, a scanning speed of 650…。
- 用途建议：适合放在正文论述中，用于承接图表证据并解释现象变化。
- 小结：该写作点主要服务于“参数影响与结果变化”这一叙述方向，可作为适合放在正文论述中，用于承接图表证据并解释现象变化的概括性材料。
- 证据边界：｜
- 相关度：0.846｜证据强度：0.000
- 因果角色：无
- 目标对齐：
- 证据摘要：1 图 / 0 表 / 0 参数 / 0 结果 / 0 引用
- 关联图：f6@p9

### 8. wp067 | discussion | 页 9
- 主张：Laser power (W) 700, 950, 1200, 1450 Scanning speed (mm/min) 450, 650, 850, 1050 Wire feeding speed (cm/min) 80, 110, 140, 170 Air pressure (MPa) 0.05, 0.2, 0.32, 0.4
- 方向定位：机理解释与因果分析
- 内容概述：该写作点概括了扫描速度、气压、激光功率变化与组织演化、熔池行为或缺陷形成之间的因果关系。
- 用途建议：适合用于机制讨论段，先概括驱动关系，再补充具体证据。
- 小结：该写作点主要服务于“机理解释与因果分析”这一叙述方向，可作为适合用于机制讨论段，先概括驱动关系，再补充具体证据的概括性材料。
- 证据边界：｜
- 相关度：0.846｜证据强度：0.000
- 因果角色：无
- 目标对齐：
- 证据摘要：2 图 / 0 表 / 0 参数 / 0 结果 / 0 引用
- 关联图：f5@p8; f6@p9

### 9. wp072 | discussion | 页 10
- 主张：Note: LP: laser power, SS: scanning speed, WFS: wire feeding speed, AP: air pressure.
- 方向定位：机理解释与因果分析
- 内容概述：Note: LP: laser power, SS: scanning speed, WFS: wire feeding speed, AP: air pressure.
- 用途建议：适合放在正文论述中，用于承接图表证据并解释现象变化。
- 小结：该写作点主要服务于“机理解释与因果分析”这一叙述方向，可作为适合放在正文论述中，用于承接图表证据并解释现象变化的概括性材料。
- 证据边界：｜
- 相关度：0.846｜证据强度：0.000
- 因果角色：无
- 目标对齐：
- 证据摘要：1 图 / 0 表 / 0 参数 / 0 结果 / 0 引用
- 关联图：f6@p9

### 10. wp073 | result | 页 10
- 主张：Among them, laser power (R = 1.589) has the most significant effect on porosity, followed by wire feeding speed, while scanning speed and air pressure have relatively smaller effects on porosity.
- 方向定位：参数影响与结果变化
- 内容概述：该写作点概括了孔隙率、扫描速度、气压对核心结果的主效应、交互作用或变化规律。
- 用途建议：适合用于结果分析或参数对比段，先总括规律，再衔接具体图表或数据。
- 小结：该写作点主要服务于“参数影响与结果变化”这一叙述方向，可作为适合用于结果分析或参数对比段，先总括规律，再衔接具体图表或数据的概括性材料。
- 证据边界：｜
- 相关度：0.846｜证据强度：0.000
- 因果角色：无
- 目标对齐：
- 证据摘要：0 图 / 0 表 / 0 参数 / 0 结果 / 0 引用

### 11. wp075 | discussion | 页 10
- 主张：Laser power (W) 1.797 0.768 0.331 0.208 1.589 Scanning speed (cm/min) 0.821 0.744 0.752 0.787 0.077 Wire feeding speed (mm/min) 0.834 0.634 0.774 0.862 0.228
- 方向定位：机理解释与因果分析
- 内容概述：该写作点概括了扫描速度、激光功率、送丝速度变化与组织演化、熔池行为或缺陷形成之间的因果关系。
- 用途建议：适合用于机制讨论段，先概括驱动关系，再补充具体证据。
- 小结：该写作点主要服务于“机理解释与因果分析”这一叙述方向，可作为适合用于机制讨论段，先概括驱动关系，再补充具体证据的概括性材料。
- 证据边界：｜
- 相关度：0.846｜证据强度：0.000
- 因果角色：无
- 目标对齐：
- 证据摘要：0 图 / 0 表 / 0 参数 / 0 结果 / 0 引用

### 12. wp102 | discussion | 页 12
- 主张：To verify the prediction capability of machine learning models for the process window, Figure 8 shows the porosity prediction maps of the four machine learning models when laser power (700~1700 W) and scanning speed (450~1150 mm/min) vary under a fixed wire feeding speed of 130 cm/min and an air pressure of 0.24 MPa.
- 方向定位：机理解释与因果分析
- 内容概述：该写作点概括了孔隙率、扫描速度、气压变化与组织演化、熔池行为或缺陷形成之间的因果关系。
- 用途建议：适合用于机制讨论段，先概括驱动关系，再补充具体证据。
- 小结：该写作点主要服务于“机理解释与因果分析”这一叙述方向，可作为适合用于机制讨论段，先概括驱动关系，再补充具体证据的概括性材料。
- 证据边界：｜
- 相关度：0.846｜证据强度：0.000
- 因果角色：无
- 目标对齐：
- 证据摘要：2 图 / 0 表 / 0 参数 / 0 结果 / 0 引用
- 关联图：f8@p13; f8@p13

## 单图证据卡

### f2 | 页 5
- 图题：Figure 2. Porosity detection method. (a,b) Schematic diagram of the sample cutting method; (c) Cross-section of the sample.
- 相关度：0.500
- 选择理由：

### f3 | 页 7
- 图题：Figure 3. Influence of Laser Power on Porosity. (a) 850 W; (b) 1350 W; (c) 1600 W.
- 相关度：0.500
- 选择理由：

### f4 | 页 7
- 图题：Figure 4. Influence of Scanning Speed on Porosity. (a) 500 mm/min; (b) 850 mm/min; (c) 1100 mm/min.
- 相关度：0.500
- 选择理由：

### f5 | 页 8
- 图题：Figure 5. Influence of Wire Feeding Speed on Porosity. (a) 80 cm/min; (b) 130 cm/min; (c) 180 cm/min.
- 相关度：0.500
- 选择理由：

### f6 | 页 9
- 图题：Figure 6. Influence of Air Pressure on Porosity. (a) 0.05 MPa; (b) 0.2 MPa; (c) 0.32 MPa.
- 相关度：0.500
- 选择理由：

### f8 | 页 13
- 图题：Figure 8. Porosity prediction maps generated by the different models at a wire feeding speed of 130 cm/min and an air pressure of 0.24 MPa. (The dashed black lines represent a set of contour lines corresponding to a constant value). (a) SVR; (b) RF; (c) GPR; (d) XGBoost.
- 相关度：0.500
- 选择理由：
