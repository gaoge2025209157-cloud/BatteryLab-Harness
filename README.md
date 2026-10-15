# ElectrochemHarness v0.5.0-rc1

> **一句话说明：** 把蓝电导出的充放电数据变成“可检查、需批准、可追溯”的分析报告和Origin图，而不是直接让程序在后台黑盒运行。

这是一个Windows本地电化学数据分析工具。普通使用者可以双击打开界面、选择蓝电文件并生成报告；演示人员还可以通过“Phase 1受控演示”展示数据预检查、分析计划、人工批准、工具白名单、失败降级和完整审计记录。

**当前版本是阶段性候选版（RC），适合组内演示和试用，不是最终稳定版。** Phase 1内核和GUI最小演示已经完成；科学标准答案、多电池统计、全文证据和完整生产GUI仍在后续Phase中。

## 最快上手

1. 解压源码包；
2. 双击 `start_gui.cmd`；
3. 选择蓝电CSV/TXT及输出目录；
4. 普通分析点击“开始分析”；
5. 演示Harness控制能力点击“Phase 1受控演示”。

面向蓝电恒流充放电导出数据的本地分析工作流：自动识别文本数据、计算关键参数、生成精炼结论、检索并核验相关 DOI，并调用 Origin 生成 SCI 风格图。

## 运行条件

- Windows 10/11 64 位；
- Windows PowerShell 5.1 或更高；
- Python 3.10 或更高，并包含 Tkinter；
- 文献检索需要访问 Crossref；
- 自动绘图支持 Origin 2021、2021b、2022、2022b、2023、2023b、2024、2024b、2025、2025b、2026和2026b。

**Origin 不是数据分析的必需条件。** 没有 Origin 时仍可生成关键参数、文献证据和 Origin 可导入 CSV。不需要独立显卡、CUDA、Docker、Node.js或额外 Python 包。

## Origin近六年兼容策略

程序读取 `origin_compat.json`，自动查找2021–2026b范围内的安装；存在多个版本时默认选择最新版本，也可在界面或命令行明确指定 `Origin64.exe`。

- 共同路径：Origin内嵌Python、`originpro`和稳定LabTalk样式命令；
- 兼容降级：旧版不接受部分`set_float`、`set_int`或`save_fig(width=...)`调用时使用后备路径；
- 运行审计：`origin_status.json`记录选择的Origin版本、`originpro`版本和降级警告；
- 验证边界：**仅2026b完成本机实测**；2021–2026代码路径已纳入兼容范围，但每个版本仍需在对应安装和许可证环境中完成一次工程保存与图片导出验证。

## 首选方式：使用交互界面

解压后双击 `start_gui.cmd`，或运行：

```powershell
py -3 '.\run_gui.py'
```

界面支持：选择蓝电文件和输出目录；填写电池体系与测试条件；控制文献检索；选择Origin版本；查看实时日志、取消任务及打开结果目录。

主界面新增“Phase 1受控演示”入口，可依次展示：真实蓝电预检查、不可变分析计划、计划与输入SHA-256、人工批准范围、白名单工具执行、取消/阻断/降级状态、产物验证以及 `plan.json`、`approval.json`、`events.jsonl`、`run_record.json` 审计目录。当前演示版已接入三列和四列本地分析、联网独立授权；Origin独立白名单适配器尚未完成，勾选Origin时会明确降级并保留本地报告和绘图CSV。原“开始分析”入口继续保留，可随时回退。

无残留GUI自检：

```powershell
py -3 '.\run_gui.py' --check
```

## 第一步：检查环境

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\check_environment.ps1'
```

指定某个Origin版本：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\check_environment.ps1' `
  -OriginExe '完整的Origin64.exe路径' `
  -RequireOrigin
```

## 第二步：准备蓝电数据

支持 `.csv`、`.txt`、`.tsv` 和 `.dat` 文本文件：

1. 循环号、时间、电流、电压四列模式；
2. 测试时间、比容量、电压三列模式。

支持 UTF-8、UTF-8 BOM、GB18030，逗号、制表符或分号分隔。`.xls`、`.xlsx` 和蓝电专有数据库文件应先另存为CSV/TXT。原始文件必须保留，分析时不要覆盖。

## 第三步：一键分析、联网检索并绘图

首次使用某个Origin版本前，应手动打开一次，完成许可证和用户目录初始化：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\run_sci_origin.ps1' `
  -InputFile '蓝电导出数据.csv' `
  -OutputDir '分析结果' `
  -Guided
```

指定Origin版本：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\run_sci_origin.ps1' `
  -InputFile '蓝电导出数据.csv' `
  -OutputDir '分析结果' `
  -OriginExe '完整的Origin64.exe路径' `
  -Guided
```

仅生成报告：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\run_sci_origin.ps1' `
  -InputFile '蓝电导出数据.csv' `
  -OutputDir '分析结果' `
  -Guided `
  -SkipOrigin
```

## 输出文件

- `关键参数报告.md`：比容量、库仑效率、保持率、电压平台、结论和价值判断；
- `关键参数.csv`：循环参数；
- `完整分析.json`：完整审计结果；
- `文献证据.json`与`文献比较.csv`：DOI核验和文献对照；
- `Origin_充放电曲线数据.csv`：Origin绘图输入；
- `电化学分析.opju`、`充放电曲线.png`、`循环性能.png`：启用Origin时生成；
- `origin_status.json`：Origin版本和兼容降级记录。

## 文献结论边界

默认最多复核50个候选DOI。只有电池体系、活性物质、电池类型/对电极、电流或倍率、温度和质量归一化口径均明确匹配的论文才标记为直接可比。Crossref不提供期刊影响因子；摘要性能值仅用于初筛，正式引用前必须阅读原文。

## Origin图形规范

- 中文：宋体；英文、数字及图例：Times New Roman；
- 坐标轴线宽：4 pt；主刻度和次刻度向内；
- 同一循环同色，充放电使用实线/虚线区分。

## 数据安全

原始蓝电数据仅在本地读取。启用文献检索后，只把实验检索条件发送到Crossref。不要在检索条件中填写姓名、保密样品编号或其他敏感信息。

## 当前限制

- SCI精炼报告和Origin自动绘图主要针对三列时间—比容量—电压曲线；
- 尚未支持CV、EIS、GITT、dQ/dV和蓝电专有二进制数据库；
- 2021–2026版本需要团队成员按版本矩阵补充实机验证证据；
- 不能仅凭单个电池结果证明材料机理、重复性或创新性。

## 运行测试

```powershell
py -3 -m unittest discover -s '.\tests' -v
```

没有`py`启动器时，可将`py -3`替换为`python`。
