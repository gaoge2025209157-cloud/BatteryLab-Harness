# ElectrochemHarness v0.7.0-rc2

> **一句话说明：** 保存一次课题配置后，选择新实验数据并点击一次，程序即可在本机完成数据分析、原文调研、知识学习、Nature风格绘图、图文报告和课题对话。

当前开发版只保留“自动研究与分析（充放电）”这一正式入口。课题配置可保存电池体系、测试参数、研究领域和问题，以后通常只需更换数据文件。测试电流只填数值、固定为mA；测试温度只填数值、固定为°C；不显示质量归一化选项。

除充放电和循环/库仑效率Origin图外，通用图谱窗口支持倍率、dQ/dV、CV/LSV、EIS Nyquist/Bode、GITT/PITT、电导率Arrhenius、直流极化和CCD，共11类图。所有图统一使用Nature风格，并输出源文件SHA-256和字段/单位审计记录。完整数据格式见 `docs/电化学图谱与数据格式规范.md`。

Phase 2保留版本化科学口径、独立标准答案数值检查和多平行电池统计。人工核对直接面向论文原文知识点和本轮数据流程，不再设置指定角色签字门。

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

主窗口只保留测试类型导航、关键结论和“自动研究与分析（充放电）”入口。运行结束后，界面显示`研究结论与指导.txt`和自包含的`研究分析报告.html`；完整Markdown、CSV和审计记录作为附件保留。

### 完成一次充放电分析

1. 点击左侧“自动研究与分析（充放电）”；
2. 首次填写并保存课题配置：电池体系、活性物质、电池类型、对电极、电流、温度、研究领域、课题背景和科学问题；
3. 以后选择已有配置后通常只需更换蓝电CSV/TXT和结果目录；
4. 点击“开始自动调研与分析”；
5. 系统自动执行预检、数据计算、最多5篇真实文献筛选、可读取原文学习、结论、图像和报告生成；
6. 执行结束后直接阅读`研究结论与指导.txt`或打开`研究分析报告.html`；
7. 可在结果页复核、批准或拒绝知识，并刷新报告；
8. 需要完整证据时打开CSV、JSON和审计记录。

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

结果中的`reference_checks_passed`表示全部冻结参考值均在允许误差内。它只核对数值流程，不依赖指定角色签字；知识点与数据解释由用户在对应核对窗口逐项确认。

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

可在结果页复核文献知识。原文学习内容默认是 `candidate`，只能用于候选解释和判别实验；核对论文正文后可改为 `approved` 作为正式依据，或标记为 `rejected` 永久排除。系统不会把模型提炼静默升级为事实。

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

每轮最终学习论文不超过5篇。程序先按研究问题相关性和项目内可审计的高水平/权威专业期刊名单筛选，再要求取得与DOI或题名匹配的可读取原文。元数据和摘要只用于发现，无法取得原文时不调用知识写入。模型按“逐篇核心内容→领域背景→电化学基础→体系参数与逻辑→相对已批准知识的新增认识”提炼；所有结果先进入candidate审核队列。

## Origin图形规范

- 白底、Arial英文/数字/图例，中文标签回退宋体；
- 轴线约1.0 pt、数据线约1.5 pt，主次刻度向内；
- 色盲友好NPG配色，同一循环同色，充放电使用线型区分；
- 投稿前仍需按目标Nature Portfolio期刊的最终尺寸和分辨率复核。

## 数据安全

原始蓝电数据仅在本地读取。启用文献检索后，只把实验检索条件发送到Crossref。不要在检索条件中填写姓名、保密样品编号或其他敏感信息。

## 自动文献学习与本地Qwen

文献调研已整合到“自动研究与分析（充放电）”。程序根据保存的电池体系、研究领域、课题背景和科学问题，在统一闭环中展示最多5篇高水平、高相关且有真实DOI的论文。

程序优先下载合法PDF、开放全文或读取用户提供的本地PDF，并通过DOI、SHA-256和下载索引去重。受限论文需要用户在校园网浏览器中合法访问，程序不会读取账号、密码或Cookie，也不绕过验证码。每轮本地Qwen优先学习最相关且尚未学习的1篇原文，并将任务目标、数据摘要、证据等级、既有知识和Token预算通过统一上下文管理器提供给模型。

模型学习结果会自动写入本地知识库并生成报告。`candidate`可用于候选解释和判别实验；`approved`才能作为正式文献依据；`rejected`不再复用。报告生成后，用户可以立即继续围绕整体课题对话，也可在结果页复核知识并刷新报告。

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
