# ElectrochemHarness v0.7.0-rc1

> **一句话说明：** 选择测试类型后，程序在本机完成数据检查、人工批准、关键参数计算、文献依据、简明结论和Nature风格绘图。

当前开发版只保留一个正式充放电入口和一个文献知识助手入口。测试电流只填数值、固定为mA；测试温度只填数值、固定为°C；不再显示质量归一化选项。分析结果在界面中直接显示 `关键结论.txt`，完整Markdown作为审计附件保留。

除充放电和循环/库仑效率Origin图外，通用图谱窗口支持倍率、dQ/dV、CV/LSV、EIS Nyquist/Bode、GITT/PITT、电导率Arrhenius、直流极化和CCD，共11类图。所有图统一使用Nature风格，并输出源文件SHA-256和字段/单位审计记录。完整数据格式见 `docs/电化学图谱与数据格式规范.md`。

Phase 2已加入版本化科学口径、独立标准答案评测和多平行电池统计，但真实标准答案仍须经J/C复核后才能通过科学发布门。

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

主窗口只保留测试类型导航、关键结论、一个正式充放电入口和一个文献知识助手入口。

### 完成一次充放电分析

1. 点击左侧“充放电 / 循环”；
2. 选择蓝电CSV/TXT和结果目录；
3. 填写电池体系、活性物质、电池类型和对电极；
4. 电流只填数值（mA），温度只填数值（°C）；
5. 首次建议关闭联网检索和Origin；
6. 依次完成预检查、计划审核和逐项人工批准；
7. 执行结束后直接阅读`关键结论.txt`；
8. 需要完整证据时打开报告、CSV和审计记录。

任何输入、联网或Origin图形选择改变后，旧计划和批准自动失效。更完整的零基础步骤见`START_HERE_WINDOWS.md`。

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

- 白底、Arial英文/数字/图例，中文标签回退宋体；
- 轴线约1.0 pt、数据线约1.5 pt，主次刻度向内；
- 色盲友好NPG配色，同一循环同色，充放电使用线型区分；
- 投稿前仍需按目标Nature Portfolio期刊的最终尺寸和分辨率复核。

## 数据安全

原始蓝电数据仅在本地读取。启用文献检索后，只把实验检索条件发送到Crossref。不要在检索条件中填写姓名、保密样品编号或其他敏感信息。

## 文献知识助手

主界面点击“文献知识助手”，填写知识领域、科学问题、AND/OR关键词组、精确短语、排除词和年份。程序可生成Web of Science、Scopus、中国知网等高级检索式，并在用户自己的浏览器中打开授权数据库，复用校园IP或已有登录；程序不会读取账号、密码或Cookie。

自动检索使用Crossref/OpenAlex公开接口。校园网下载的HTML、TXT、Markdown全文可放入一个目录供程序读取；PDF需要可选`pypdf`，程序不会自动安装。程序先压缩研究背景、图注、表格、带单位参数和数据摘要，再由统一上下文管理器加入任务目标、当前权限与工具观察，生成 `context_bundle.json` 和 `context_manifest.json` 后发送给模型。模型必须输出数据价值、缺失实验、缺失表征和不可判断项。

启动GUI前在PowerShell设置OpenAI兼容模型：

```powershell
$env:ELECTROCHEM_LLM_BASE_URL = 'https://你的模型服务/v1'
$env:ELECTROCHEM_LLM_MODEL = '你的模型ID'
$env:ELECTROCHEM_LLM_API_KEY = '你的API密钥'
py -3 '.\run_gui.py'
```

模型结果写入本地 `knowledge\research_knowledge.md`，默认状态为`candidate`。运行证据保存在 `knowledge\runs\`，相同证据包可命中缓存。模型不能自动批准知识；阅读正文并核对图表、条件和反例后，才可人工改为`approved`。

## 当前限制

- 11类常规图谱已支持数据读取与Nature风格SVG输出，但EIS等效电路拟合、GITT扩散系数、Arrhenius活化能和CCD自动失效判定仍待独立科学验收；
- 蓝电专有二进制数据库仍需先导出为CSV/TXT。
- 2021–2026版本需要团队成员按版本矩阵补充实机验证证据；
- 不能仅凭单个电池结果证明材料机理、重复性或创新性。

## 运行测试

```powershell
py -3 -m unittest discover -s '.\tests' -v
```

没有`py`启动器时，可将`py -3`替换为`python`。
# ElectrochemHarness v0.7.0-rc1

> **一句话说明：** 选择测试类型后，程序在本机完成数据检查、人工批准、关键参数计算、文献依据、简明结论和Nature风格绘图。

当前开发版只保留一个正式充放电入口和一个文献知识助手入口。测试电流只填数值、固定为mA；测试温度只填数值、固定为°C；不再显示质量归一化选项。分析结果在界面中直接显示 `关键结论.txt`，完整Markdown作为审计附件保留。

除充放电和循环/库仑效率Origin图外，通用图谱窗口支持倍率、dQ/dV、CV/LSV、EIS Nyquist/Bode、GITT/PITT、电导率Arrhenius、直流极化和CCD，共11类图。所有图统一使用Nature风格，并输出源文件SHA-256和字段/单位审计记录。完整数据格式见 `docs/电化学图谱与数据格式规范.md`。

Phase 2已加入版本化科学口径、独立标准答案评测和多平行电池统计，但真实标准答案仍须经J/C复核后才能通过科学发布门。

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

主窗口只保留测试类型导航、关键结论、一个正式充放电入口和一个文献知识助手入口。

### 完成一次充放电分析

1. 点击左侧“充放电 / 循环”；
2. 选择蓝电CSV/TXT和结果目录；
3. 填写电池体系、活性物质、电池类型和对电极；
4. 电流只填数值（mA），温度只填数值（°C）；
5. 首次建议关闭联网检索和Origin；
6. 依次完成预检查、计划审核和逐项人工批准；
7. 执行结束后直接阅读`关键结论.txt`；
8. 需要完整证据时打开报告、CSV和审计记录。

任何输入、联网或Origin图形选择改变后，旧计划和批准自动失效。更完整的零基础步骤见`START_HERE_WINDOWS.md`。

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

- 白底、Arial英文/数字/图例，中文标签回退宋体；
- 轴线约1.0 pt、数据线约1.5 pt，主次刻度向内；
- 色盲友好NPG配色，同一循环同色，充放电使用线型区分；
- 投稿前仍需按目标Nature Portfolio期刊的最终尺寸和分辨率复核。

## 数据安全

原始蓝电数据仅在本地读取。启用文献检索后，只把实验检索条件发送到Crossref。不要在检索条件中填写姓名、保密样品编号或其他敏感信息。

## 文献知识助手

主界面点击“文献知识助手”，填写知识领域、科学问题、AND/OR关键词组、精确短语、排除词和年份。程序可生成Web of Science、Scopus、中国知网等高级检索式，并在用户自己的浏览器中打开授权数据库，复用校园IP或已有登录；程序不会读取账号、密码或Cookie。

自动检索使用Crossref/OpenAlex公开接口。校园网下载的HTML、TXT、Markdown全文可放入一个目录供程序读取；PDF需要可选`pypdf`，程序不会自动安装。模型优先接收研究背景、图注、表格、带单位参数和压缩后的数据摘要，并必须输出数据价值、缺失实验、缺失表征和不可判断项。

启动GUI前在PowerShell设置OpenAI兼容模型：

```powershell
$env:ELECTROCHEM_LLM_BASE_URL = 'https://你的模型服务/v1'
$env:ELECTROCHEM_LLM_MODEL = '你的模型ID'
$env:ELECTROCHEM_LLM_API_KEY = '你的API密钥'
py -3 '.\run_gui.py'
```

模型结果写入本地 `knowledge\research_knowledge.md`，默认状态为`candidate`。运行证据保存在 `knowledge\runs\`，相同证据包可命中缓存。模型不能自动批准知识；阅读正文并核对图表、条件和反例后，才可人工改为`approved`。

## 当前限制

- 11类常规图谱已支持数据读取与Nature风格SVG输出，但EIS等效电路拟合、GITT扩散系数、Arrhenius活化能和CCD自动失效判定仍待独立科学验收；
- 蓝电专有二进制数据库仍需先导出为CSV/TXT。
- 2021–2026版本需要团队成员按版本矩阵补充实机验证证据；
- 不能仅凭单个电池结果证明材料机理、重复性或创新性。

## 运行测试

```powershell
py -3 -m unittest discover -s '.\tests' -v
```

没有`py`启动器时，可将`py -3`替换为`python`。
