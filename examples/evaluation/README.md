# 评测用合成数据

E-01～E-12 使用的最小数据集，全部由 `evaluation.build_fixtures()` 生成，不含任何真实电池数据。修改夹具请改 `evaluation.FIXTURES`，不要手改本目录。

| 文件 | 用途 |
|---|---|
| `raw_4col.csv` | 四列原始数据（循环/时间/电流/电压），正常样本 |
| `raw_4col_units.csv` | 与 raw_4col 同一组物理量，改用 μA / mV / min 表达 |
| `raw_4col_time_regression.csv` | 时间列中途倒退，应被阻断 |
| `raw_4col_truncated.csv` | 末圈只有充电段、没有放电段（不完整循环） |
| `curve_3col.csv` | 三列比容量曲线，正常样本 |
| `curve_3col_negative_v.csv` | 含负电压点，应提示但不阻断 |
| `curve_missing_voltage.csv` | 缺少电压列，应被阻断 |
