# ElectrochemHarness v0.3.0

面向蓝电恒流充放电导出数据的本地分析工作流：自动识别文本数据、计算关键参数、生成精炼结论、检索并核验相关 DOI，并调用 Origin 生成 SCI 风格图。

## 运行条件

- Windows 10/11 64 位；
- Windows PowerShell 5.1 或更高；
- Python 3.10 或更高，并包含 Tkinter（支持 `py -3` 或 `python`）；
- 文献检索需要访问 Crossref；
- Origin 2026/2026b 仅在自动绘图时需要，并且必须由使用者自行安装和授权。

**Origin 不是数据分析的必需条件。** 没有 Origin 时可使用报告模式，仍会生成关键参数、文献证据和 Origin 可导入 CSV。

不需要独立显卡、CUDA、Docker、Node.js或额外 Python 包。

## 首选方式：使用交互界面

解压后双击 `start_gui.cmd` 即可打开中文交互界面。也可以在 PowerShell 中运行：

```powershell
py -3 '.\run_gui.py'
```

交互界面可以：

- 浏览选择蓝电文件和输出目录；
- 填写电池体系、活性物质、电池类型、对电极、测试电流、温度和质量归一化口径；
- 选择是否联网检索文献、最多核验多少个 DOI；
- 选择是否调用 Origin，或指定 `Origin64.exe`；
- 查看实时日志、取消任务，并在完成后打开结果目录。

如果只想确认本机能否创建界面而不启动分析：

```powershell
py -3 '.\run_gui.py' --check
```

## 第一步：检查环境

在解压目录打开 PowerShell：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\check_environment.ps1'
```

如果 Origin 位于非常规目录，可指定：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\check_environment.ps1' `
  -OriginExe '完整的Origin64.exe路径' `
  -RequireOrigin
```

## 第二步：准备蓝电数据

支持蓝电软件导出的 `.csv`、`.txt`、`.tsv` 和 `.dat` 文本文件：

1. 循环号、时间、电流、电压四列模式；
2. 测试时间、比容量、电压三列模式。

支持 UTF-8、UTF-8 BOM、GB18030，逗号、制表符或分号分隔。`.xls`、`.xlsx` 和蓝电专有数据库文件需要先在蓝电或 Excel 中另存为 CSV/TXT。

原始文件必须保留，分析时不要覆盖原始数据。三列比容量模式使用蓝电导出的容量值，无法重新审计活性物质量归一化。

## 第三步：一键分析、联网检索并绘图

先手动打开一次 Origin，完成许可证和用户目录初始化。然后运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\run_sci_origin.ps1' `
  -InputFile '蓝电导出数据.csv' `
  -OutputDir '分析结果' `
  -Guided
```

程序会依次询问：电池体系、活性物质、电池类型、对电极、测试电流或倍率、温度、质量归一化口径。

如果 Origin 未被自动找到：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\run_sci_origin.ps1' `
  -InputFile '蓝电导出数据.csv' `
  -OutputDir '分析结果' `
  -OriginExe '完整的Origin64.exe路径' `
  -Guided
```

## 仅生成报告，不调用 Origin

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\run_sci_origin.ps1' `
  -InputFile '蓝电导出数据.csv' `
  -OutputDir '分析结果' `
  -Guided `
  -SkipOrigin
```

## 输出文件

- `关键参数报告.md`：充放电比容量、库仑效率、保持率、电压平台、结论和数据价值判断；
- `关键参数.csv`：循环级参数表；
- `完整分析.json`：完整可审计分析结果；
- `文献证据.json`：检索条件、DOI核验记录、摘要信息和可比性；
- `文献比较.csv`：经核验文献的结构化比较表；
- `Origin_充放电曲线数据.csv`：Origin 绘图输入；
- `电化学分析.opju`、`充放电曲线.png`、`循环性能.png`：启用 Origin 时生成。

## 文献结论边界

文献检索默认最多复核 50 个候选 DOI，只保留经 Crossref 单篇接口复核的期刊论文。只有电池体系、活性物质、电池类型/对电极、电流或倍率、温度和质量归一化口径均明确匹配的论文才标记为直接可比。

Crossref 不提供期刊影响因子；引用次数只用于排序，不能替代论文质量判断。摘要提取的性能值仅用于初筛。正式用于论文前必须阅读原文并核对载量、电解液用量、截止电压、循环圈数、重复实验和误差。

## Origin 图形规范

- 中文：宋体；
- 英文、数字及图例：Times New Roman；
- 坐标轴线宽：4 pt；
- 主刻度和次刻度：向内；
- 同一循环同色，充放电用实线/虚线区分。

## 数据安全

程序会将实验条件发送到 Crossref 作为检索关键词，但不会上传原始蓝电数据。不要在实验条件中填写姓名、样品保密编号或其他敏感信息。分析结果默认保存在指定的本地输出目录。

## 当前限制

- SCI 精炼报告和 Origin 自动绘图主要针对三列时间—比容量—电压曲线；
- 尚未支持 CV、EIS、GITT、dQ/dV 和蓝电专有二进制数据库；
- 不能仅凭单个电池结果证明材料机理、重复性或创新性；
- Origin 是商业软件，不包含在本发布包中。

## 运行测试

```powershell
py -3 -m unittest discover -s '.\tests' -v
```

如果没有 `py` 启动器，可把命令中的 `py -3` 替换为 `python`。
