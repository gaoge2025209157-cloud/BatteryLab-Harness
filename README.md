# ElectrochemHarness v0.6.0-rc1

> **一句话说明：** 把蓝电导出的充放电数据变成“可检查、需批准、可追溯”的分析报告和Origin图，而不是直接让程序在后台黑盒运行。

这是一个Windows本地电化学数据分析工具。普通使用者可以双击打开界面、选择蓝电文件并生成报告；演示人员还可以通过“Phase 1受控演示”展示数据预检查、分析计划、人工批准、工具白名单、失败降级和完整审计记录。

**当前版本是阶段性候选版（RC），适合组内演示和试用，不是最终稳定版。** Phase 1内核和GUI最小演示已经完成；Phase 2工程层已实现冻结口径、标准答案评测门和多平行电池统计，但标准答案仍待J/C科学复核；全文证据和完整生产GUI仍在后续Phase中。

后续工作已拆成两个可并行领取的 GitHub 工作包，任务边界、建议分支、交付物和验收标准见 `TEAM_WORK_PACKAGES.md`。

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
- 验证边界：**仅2026b在本机实测**；2021–2026代码路径已纳入兼容范围，但每个版本仍需在对应安装和许可证环境中完成一次工程保存与图片导出验证。

### 如何验证某个 Origin 版本

双击 `verify_origin.cmd`，或运行：

```powershell
py -3 '.\verify_origin.py' --list    # 只看本机装了哪些受支持版本
py -3 '.\verify_origin.py' --all     # 每个版本各跑一次完整流程并自检
```

它会做四件事：列出本机所有 2021–2026b 的安装；对每个版本各跑一次完整受控流程（数据 → 预检查 → 计划 → 批准 → 执行 → 结果）；按 O-01～O-09 逐条自检；把结论写进 `origin_verification/`（含 `verification.json`、`verification.md` 和产物副本）。

其中 **O-07 是最关键的一条**：Origin 失败时流程会自动降级并继续，状态仍是 `completed_with_warnings`、目录里可能还留着上次的文件。所以判定不看"文件在不在"，而看"有没有 `build_origin_project` 降级记录"。

只有 O-01～O-07 全部 PASS 的版本，才可以把版本号写进 `origin_compat.json` 的 `locally_validated`。全程不联网。

## 首选方式：使用交互界面

解压后双击 `start_gui.cmd`，或运行：

```powershell
py -3 '.\run_gui.py'
```

界面支持：选择蓝电文件和输出目录；填写电池体系与测试条件；控制文献检索；选择Origin版本；查看实时日志、取消任务及打开结果目录。

主界面提供两个受控入口：

- **「六步受控分析」（推荐）**：数据与实验条件 → 预检查与阻断 → 不可变分析计划（计划哈希、输入 SHA-256）→ 三档独立批准 → 受控执行（可取消、失败可重跑）→ 结果与审计（产物状态、降级记录、双击打开）。计划一旦生成即不可变，改动任何字段都会让批准失效并要求回到第 1 步。
- **「Phase 1受控演示」**：早期弹窗版演示，功能已被六步入口覆盖，保留用于对比。

Origin 已接入独立白名单适配器 `origin_adapter.py`（2021–2026b 定位、COM 启动、协作式取消、ASCII 运行目录）；失败时只降级绘图阶段，报告与绘图 CSV 一定保留。原「开始分析」入口继续保留，可随时回退。

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


## Phase 2：科学正确性与多平行电池

每次单电池分析会额外生成 `科学计算标准.json`，并在报告中记录标准版本、SHA-256和“单电池仅为探索性”的证据边界。运行仓库标准答案：

```powershell
py -3 '.\run_phase2_validation.py' --output '.\phase2_validation.json'
```

数值通过不等于科学发布已批准。`standards\ground_truth_v1.json`当前为`draft`；只有J核对数据/仪器口径、C独立核对公式/误差，并共同登记后，`scientific_release_ready`才会变为`true`。

多平行电池统计：复制 `examples\replicate_manifest_template.json` 到数据所在目录，填写同条件的至少3个电池及实验元数据，再运行：

```powershell
py -3 '.\run_replicates.py' '.\replicate_manifest.json' `
  --output-dir '.\replicate_results'
```

输出 `平行电池统计.json`、`平行电池统计.csv`、`平行电池统计报告.md` 和 `平行电池统计图.svg`，包括全部原始散点、均值、样本标准差、SEM、95% Student t区间、MAD异常提示及人工排除理由。SVG直接展示放电比容量原始散点与均值±样本标准差；异常点不会自动删除，1–2个电池只能标记为探索性。

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
- `完整分析.json`：完整分析结果及科学标准身份；
- `科学计算标准.json`：本次计算公式、约定、版本和SHA-256；
- `平行电池统计.json/.csv/.md`、`平行电池统计图.svg`：多电池原始散点、离散度、置信区间和均值±样本标准差快速质控图；
- `文献证据.json`与`文献比较.csv`：DOI核验和文献对照；
- `Origin_充放电曲线数据.csv`：Origin绘图输入；
- `电化学分析.opju`、`充放电曲线.png`、`循环性能.png`：启用Origin时生成；
- `origin_status.json`：Origin版本和兼容降级记录。

## 可编辑的文献知识库

每次启用文献检索后，程序会把 DOI 已核验文献的研究定位、明确性能、摘要候选陈述和适用实验条件，按 DOI 去重写入：

```text
knowledge/literature_knowledge.md
```

GUI可点击“编辑文献知识库”直接打开。新条目默认是 `candidate`，只用于提出假设；阅读正文后，可把条目状态改为 `approved`，并在“人工确认知识”和“人工备注与正文定位”中填写结论、页码、图号、条件差异或反例。后续分析只采用 **DOI已核验、状态为 `approved`、实验条件指纹匹配** 的知识作为判断依据。

自动提炼区在重复检索时更新；人工确认知识和备注不会被覆盖。本地知识库已被Git忽略，发布包只包含空模板。旧的 `literature_knowledge.jsonl` 不再作为默认判断依据。

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
