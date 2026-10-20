# 评测用合成数据

E-01～E-12 使用的最小数据集，全部由 `evaluation.build_fixtures()` 生成，不含任何真实电池数据。

| 文件 | 用途 |
|---|---|
| `raw_4col.csv` | 四列原始数据（循环/时间/电流/电压），正常样本 |
| `raw_4col_units.csv` | 与上面同一组物理量，改用 μA / mV / min 表达 |
| `raw_4col_time_regression.csv` | 时间列中途倒退 |
| `curve_3col.csv` | 三列比容量曲线，正常样本 |
| `curve_3col_incomplete.csv` | 末尾放电段没有容量归零，属不完整循环 |
| `curve_3col_negative_v.csv` | 含负电压点 |
| `curve_missing_voltage.csv` | 缺少电压列 |
