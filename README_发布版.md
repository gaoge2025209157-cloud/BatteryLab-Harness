# ElectrochemHarness v0.6.0-rc1

> **一句话说明：** 选择蓝电导出文件后，程序在本机完成数据检查、关键参数计算、报告生成和可选Origin绘图；Phase 1演示模式还会在执行前展示计划并要求人工批准。

本版本是供团队演示和试用的候选版。普通分析入口保持可用；Phase 1受控演示已接入GUI。Phase 2已加入版本化科学口径、独立标准答案评测和多平行电池统计，但标准答案仍为`draft`，须经J/C共同复核后才能通过科学发布门。Origin独立白名单适配器仍待完成，因此Phase 1演示中启用Origin会明确降级并保留本地报告。

团队后续开发已拆为“科学验收/证据/推理”和“生产GUI/Origin/系统评测”两个工作包，详见 `TEAM_WORK_PACKAGES.md`。

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

### 如何演示Phase 1

1. 在主界面选好蓝电文件和输出目录；
2. 首次演示建议取消文献检索和Origin绘图；
3. 点击“Phase 1受控演示”；
4. 点击“1. 生成计划”，查看输入哈希、计划哈希、工具顺序和预期文件；
5. 勾选“批准本地分析”和“批准正式输出”；
6. 点击“2. 批准计划”，再点击“3. 受控执行”；
7. 完成后点击“打开审计目录”，查看 `plan.json`、`approval.json`、`events.jsonl` 和 `run_record.json`。

演示重点：未批准不能执行；输入问题可阻断；修改条件后旧批准失效；网络或Origin失败不会删除已经完成的本地结果。

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

## Phase 2科学验证与多电池统计

验证当前冻结公式和仓库标准答案：

```powershell
py -3 '.\run_phase2_validation.py' --output '.\phase2_validation.json'
```

数值通过后仍须查看`scientific_release_ready`：当前标准答案为`draft`，J/C未共同复核前必须为`false`。

多平行电池分析时，将`examples\replicate_manifest_template.json`复制到数据目录，填写至少3个同条件独立电池后运行：

```powershell
py -3 '.\run_replicates.py' '.\replicate_manifest.json' `
  --output-dir '.\replicate_results'
```

结果保留全部原始散点，并给出均值、样本标准差、SEM和95% Student t区间，同时生成放电比容量原始散点与均值±样本标准差的SVG快速质控图；异常提示不会自动删除样本。

## 可编辑文献知识

启用文献检索后，程序会把核验过 DOI 的文献摘要知识按 DOI 去重保存到：

```text
knowledge/literature_knowledge.md
```

可在主界面点击“编辑文献知识库”。新内容默认标记为 `candidate`；核对论文正文后，将状态改为 `approved`，并填写“人工确认知识”和正文页码/图号。以后只有与当前实验条件匹配的 `approved` 条目会成为报告判断依据，人工内容不会被自动更新覆盖。

## 输出文件

- `关键参数报告.md`：比容量、库仑效率、保持率、电压平台、结论和价值判断；
- `关键参数.csv`：循环参数；
- `完整分析.json`：完整分析结果及科学标准身份；
- `科学计算标准.json`：本次计算公式、约定、版本和SHA-256；
- `平行电池统计.json/.csv/.md`、`平行电池统计图.svg`：多电池原始散点、离散度、置信区间和快速质控图；
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
