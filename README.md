# ElectrochemHarness v0.7.0-rc1

> **一句话说明：** 把电化学数据变成“可检查、需批准、可追溯”的关键结论、文献依据和Nature风格图，而不是让程序在后台黑盒运行。

这是一个Windows本地电化学研究工作台。普通用户可以双击打开界面，通过统一受控流程完成充放电分析，并为11类常见电化学数据生成可编辑SVG；文献知识助手可使用校园网检索流程和本地Qwen整理证据，候选知识必须由用户逐条批准。

**当前版本是阶段性候选版（RC），适合组内演示和试用，不是最终稳定版。** Phase 1受控内核、Phase 2工程层、六步生产GUI、本地大模型知识助手和通用图谱层已经实现；真实数据科学发布门仍待J/C三方复核。

## 最快上手

1. 从GitHub Release下载项目ZIP和SHA-256；
2. 按`START_HERE_WINDOWS.md`安装Python并解压；
3. 双击`start_gui.cmd`；
4. 点击左侧“充放电 / 循环”，完成预检查、计划审核和逐项批准；
5. 在结果页直接阅读`关键结论.txt`；
6. 需要本地Qwen时安装Ollama，再双击`start_gui_local_qwen_portable.cmd`。

面向零代码用户的下载、安装、Origin、本地Qwen和校园网文献步骤见 `START_HERE_WINDOWS.md`。

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

主界面只保留一个正式充放电入口和一个文献知识助手入口。点击左侧 **“充放电 / 循环”** 后进入统一受控流程：数据与实验条件 → 预检查与阻断 → 不可变分析计划 → 逐项人工批准 → 受控执行 → 关键结论、产物与审计。旧“开始分析”和“Phase 1受控演示”入口不再显示。

充放电表单采用固定单位：测试电流只填数值，单位为mA；测试温度只填数值，单位为°C。界面不再询问质量归一化口径：三列比容量文件保留仪器导出口径并提示核验质量分母，四列电流积分文件默认报告未归一化容量mAh。

分析完成后，界面优先显示无Markdown符号的 `关键结论.txt`，内容限定为关键指标、简要结论与科学依据、数据能说明/不能说明的问题、条件匹配文献DOI和下一步实验。完整表格和计算口径仍保存在 `关键参数报告.md`。

Origin 已接入独立白名单适配器 `origin_adapter.py`。执行前可选择只画充放电曲线、只画循环容量/库仑效率图或两张都画；选择进入计划哈希，改变后旧批准失效。所有Origin图统一使用Nature风格主题，失败时只降级绘图阶段，报告与绘图CSV仍保留。

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


## 常规电化学性能图谱

左侧测试类型入口现可打开统一图谱窗口，支持11类文献常见图：充放电、循环容量/库仑效率、倍率、dQ/dV、CV/LSV、EIS Nyquist、EIS Bode、GITT/PITT、电导率Arrhenius、直流极化和CCD。输入支持CSV、TXT、TSV、DAT；窗口会显示标准列名、科学问题、解释边界和方法DOI。

通用导入器自动识别中英文表头，并换算A→mA、mV→V、min/h→s、kΩ→Ω、K→°C和mS/cm→S/cm。输出为Nature风格可编辑SVG以及记录源文件SHA-256、识别列、规范单位和科学边界的 `*_plot_record.json`。完整规范见 `docs/电化学图谱与数据格式规范.md`。

首版图谱只做可审计数据读取、必要变换和绘图，不自动宣称完成EIS等效电路拟合、GITT扩散系数、Arrhenius活化能或CCD失效判定；这些计算仍需独立公式版本、质量门和标准答案。

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

## LLM文献知识助手

主界面点击 **“文献知识助手”**。主窗口直接显示关键结论；左侧EIS、CV/LSV、GITT/PITT、对称电池/CCD及“倍率/dQdV/Arrhenius”入口已接入通用图谱窗口，表征关联仍为待开发入口。知识助手按以下闭环运行：

```text
填写知识领域与科学问题
→ 设置AND/OR关键词组、精确短语、排除词和年份
→ 生成Web of Science / Scopus / CNKI等高级检索式
→ 使用校园网浏览器访问授权数据库
→ 自动检索Crossref/OpenAlex元数据
→ 读取本地全文或校园网可直接访问的出版商HTML
→ 优先提取研究背景、图注、表格和带单位参数
→ 压缩当前数据/报告为证据摘要
→ 大模型输出数据价值、候选知识、缺失实验和缺失表征
→ 保存计划、证据包、推理结果与candidate知识
→ 人工阅读正文后再决定是否approved
```

### 配置大模型

使用兼容OpenAI `chat/completions`协议的远程或本地模型。密钥只从环境变量读取，不在GUI、日志或知识库保存。PowerShell示例：

```powershell
$env:ELECTROCHEM_LLM_BASE_URL = 'https://你的模型服务/v1'
$env:ELECTROCHEM_LLM_MODEL = '你的模型ID'
$env:ELECTROCHEM_LLM_API_KEY = '你的API密钥'
py -3 '.\run_gui.py'
```

本地OpenAI兼容服务可以使用 `http://127.0.0.1:端口/v1`；远程接口必须使用HTTPS。相同证据包按SHA-256缓存，避免重复消耗Token。知识助手以五个标签页实时展示：

- **实时过程**：检索计划、公开元数据检索、全文/图表提取、证据包压缩、大模型整理和本地写库；
- **结论总览**：研究背景与关键图表参数；
- **数据价值**：当前数据能说明什么、可信度、限制和不能判断的内容；
- **补充实验与表征**：形成完整研究课题仍缺少的验证工作；
- **知识审核**：每条候选知识独立显示来源和置信度，可在运行完成后立即批准或拒绝，并把状态和人工备注写回本地Markdown。

#### 通过 CC-SWITCH 本地路由接入

Harness 支持 CC-SWITCH 的本地 Codex/Responses 路由，不需要读取或复制上游 API 密钥：

```powershell
$env:ELECTROCHEM_LLM_BASE_URL = 'http://127.0.0.1:15721/v1'
$env:ELECTROCHEM_LLM_MODEL = 'gpt-5.6-sol'
py -3 '.\run_gui.py'
```

在 CC-SWITCH 中先让 Codex 进入 **Routing** 模式并选择目标 Provider，同时保持 CC-SWITCH 运行。Harness 识别到默认端口 `15721` 后会自动使用 OpenAI Responses API，并只发送官方占位凭据 `PROXY_MANAGED`；真实密钥始终留在 CC-SWITCH 的本地配置中，不进入 Harness、日志或知识库。若端口被用户修改，应在 GUI 中填写实际本地地址，并显式使用与该路由一致的协议配置。

当前 Kiro 会话本身不是可嵌入的公开模型 API，Harness 不读取或复用 Kiro 登录凭据；这里复用的是 CC-SWITCH 已配置的模型路由。

#### 本地Qwen 4B（推荐的校园网方案）

推荐安装Ollama并使用`qwen3:4b-q4_K_M`：

- Ollama官方下载：[Ollama for Windows](https://ollama.com/download/windows)；
- 本地接口：`http://127.0.0.1:11434/v1`；
- 模型ID：`qwen3:4b-q4_K_M`；
- 便携入口：双击`start_gui_local_qwen_portable.cmd`。

便携入口会自动查找Ollama；模型缺失时先说明约2.6 GB下载量并要求用户确认，不会静默下载。模型、缓存和日志位置由用户自己的Ollama安装决定。模型推理不经过OpenAI或VPN；Crossref/OpenAlex和用户浏览器仍使用当前校园网。数据库登录与全文下载继续由用户自己的浏览器完成，Harness只把筛选后的文献摘录和数据摘要发送给本机Qwen。4B量化模型适合知识提炼和实验建议，但正式机理结论仍须人工核对正文证据。

### 高级学术检索与校园网

- Crossref、OpenAlex：程序通过公开API自动检索和整理元数据；
- Web of Science、Scopus、中国知网、Google Scholar：程序生成高级检索式并在用户自己的浏览器中打开；
- 校园IP、机构登录、验证码和下载选择均由用户浏览器处理；程序不会读取账号、密码或Cookie，也不绕过数据库限制；
- 可将校园网下载的论文放入一个本地目录，再由知识助手批量读取；
- 支持HTML、TXT和Markdown；PDF文本提取需要可选的`pypdf`，程序不会自动安装依赖；没有该依赖时可从数据库导出HTML/TXT。

### 模型接收与输出

模型不会直接接收孤立的证据包。程序先生成受限的 `evidence_packet.json`：数据JSON中的大数组会被删除，CSV只保留表头和边界行，全文只保留限定长度的引言、方法、图注、表格和正文摘录；随后由统一上下文管理器将任务目标、实验摘要、权限、工具观察和待审核证据包组装为 `context_bundle.json`，再发送给模型。

每次调用同时生成 `context_manifest.json`，记录模型本轮实际看到了哪些来源、排除了哪些来源、当前权限、估算Token和上下文SHA-256。文献与数据仍属于不可信证据，不能改变系统规则、权限或工具边界。

模型必须输出严格JSON，至少包含：

- 研究背景及来源和证据等级；
- 关键图表参数、数值、单位、条件和位置；
- 当前数据的研究价值、可信度和局限；
- 一个完整课题仍需补充的实验；
- 仍需补充的结构、成分和界面表征；
- 当前不能判断的问题；
- 可写入知识库的候选知识及核验要求。

每次运行在 `knowledge\runs\<run_id>\` 生成 `plan.json`、`evidence_packet.json`、`context_bundle.json`、`context_manifest.json`、`reasoning_result.json` 和 `run_record.json`；候选综合知识写入 `knowledge\research_knowledge.md`。这些文件均被Git忽略，发布包只包含空模板。大模型无权把条目标记为`approved`，最终科学判断仍由用户完成。

## 文献结论边界

默认最多复核50个候选DOI。只有电池体系、活性物质、电池类型/对电极、电流或倍率、温度和质量归一化口径均明确匹配的论文才标记为直接可比。Crossref不提供期刊影响因子；摘要性能值仅用于初筛，正式引用前必须阅读原文。

## Origin图形规范

- 白底、Arial英文/数字/图例，中文标签回退宋体；
- 轴线约1.0 pt、数据线约1.5 pt，主次刻度向内；
- 统一使用色盲友好的NPG配色，同一循环同色，充放电用线型区分；
- 采用Nature官方图稿规范控制字体、线宽和成图可读性，投稿前仍需按目标期刊尺寸终审。

## 数据安全

原始蓝电数据仅在本地读取。启用文献检索后，只把实验检索条件发送到Crossref。不要在检索条件中填写姓名、保密样品编号或其他敏感信息。

## 当前限制

- 11类常规图谱已支持数据读取与Nature风格SVG输出，但EIS等效电路拟合、GITT扩散系数、Arrhenius活化能和CCD自动失效判定仍待独立科学验收；
- 蓝电专有二进制数据库仍需先导出为CSV/TXT；
- 2021–2026版本需要团队成员按版本矩阵补充实机验证证据；
- 不能仅凭单个电池结果证明材料机理、重复性或创新性。

## 运行测试

```powershell
py -3 -m unittest discover -s '.\tests' -v
```

没有`py`启动器时，可将`py -3`替换为`python`。
# ElectrochemHarness v0.7.0-rc1

> **一句话说明：** 把电化学数据变成“可检查、需批准、可追溯”的关键结论、文献依据和Nature风格图，而不是让程序在后台黑盒运行。

这是一个Windows本地电化学研究工作台。普通用户可以双击打开界面，通过统一受控流程完成充放电分析，并为11类常见电化学数据生成可编辑SVG；文献知识助手可使用校园网检索流程和本地Qwen整理证据，候选知识必须由用户逐条批准。

**当前版本是阶段性候选版（RC），适合组内演示和试用，不是最终稳定版。** Phase 1受控内核、Phase 2工程层、六步生产GUI、本地大模型知识助手和通用图谱层已经实现；真实数据科学发布门仍待J/C三方复核。

## 最快上手

1. 从GitHub Release下载项目ZIP和SHA-256；
2. 按`START_HERE_WINDOWS.md`安装Python并解压；
3. 双击`start_gui.cmd`；
4. 点击左侧“充放电 / 循环”，完成预检查、计划审核和逐项批准；
5. 在结果页直接阅读`关键结论.txt`；
6. 需要本地Qwen时安装Ollama，再双击`start_gui_local_qwen_portable.cmd`。

面向零代码用户的下载、安装、Origin、本地Qwen和校园网文献步骤见 `START_HERE_WINDOWS.md`。

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

主界面只保留一个正式充放电入口和一个文献知识助手入口。点击左侧 **“充放电 / 循环”** 后进入统一受控流程：数据与实验条件 → 预检查与阻断 → 不可变分析计划 → 逐项人工批准 → 受控执行 → 关键结论、产物与审计。旧“开始分析”和“Phase 1受控演示”入口不再显示。

充放电表单采用固定单位：测试电流只填数值，单位为mA；测试温度只填数值，单位为°C。界面不再询问质量归一化口径：三列比容量文件保留仪器导出口径并提示核验质量分母，四列电流积分文件默认报告未归一化容量mAh。

分析完成后，界面优先显示无Markdown符号的 `关键结论.txt`，内容限定为关键指标、简要结论与科学依据、数据能说明/不能说明的问题、条件匹配文献DOI和下一步实验。完整表格和计算口径仍保存在 `关键参数报告.md`。

Origin 已接入独立白名单适配器 `origin_adapter.py`。执行前可选择只画充放电曲线、只画循环容量/库仑效率图或两张都画；选择进入计划哈希，改变后旧批准失效。所有Origin图统一使用Nature风格主题，失败时只降级绘图阶段，报告与绘图CSV仍保留。

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


## 常规电化学性能图谱

左侧测试类型入口现可打开统一图谱窗口，支持11类文献常见图：充放电、循环容量/库仑效率、倍率、dQ/dV、CV/LSV、EIS Nyquist、EIS Bode、GITT/PITT、电导率Arrhenius、直流极化和CCD。输入支持CSV、TXT、TSV、DAT；窗口会显示标准列名、科学问题、解释边界和方法DOI。

通用导入器自动识别中英文表头，并换算A→mA、mV→V、min/h→s、kΩ→Ω、K→°C和mS/cm→S/cm。输出为Nature风格可编辑SVG以及记录源文件SHA-256、识别列、规范单位和科学边界的 `*_plot_record.json`。完整规范见 `docs/电化学图谱与数据格式规范.md`。

首版图谱只做可审计数据读取、必要变换和绘图，不自动宣称完成EIS等效电路拟合、GITT扩散系数、Arrhenius活化能或CCD失效判定；这些计算仍需独立公式版本、质量门和标准答案。

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

## LLM文献知识助手

主界面点击 **“文献知识助手”**。主窗口直接显示关键结论；左侧EIS、CV/LSV、GITT/PITT、对称电池/CCD及“倍率/dQdV/Arrhenius”入口已接入通用图谱窗口，表征关联仍为待开发入口。知识助手按以下闭环运行：

```text
填写知识领域与科学问题
→ 设置AND/OR关键词组、精确短语、排除词和年份
→ 生成Web of Science / Scopus / CNKI等高级检索式
→ 使用校园网浏览器访问授权数据库
→ 自动检索Crossref/OpenAlex元数据
→ 读取本地全文或校园网可直接访问的出版商HTML
→ 优先提取研究背景、图注、表格和带单位参数
→ 压缩当前数据/报告为证据摘要
→ 大模型输出数据价值、候选知识、缺失实验和缺失表征
→ 保存计划、证据包、推理结果与candidate知识
→ 人工阅读正文后再决定是否approved
```

### 配置大模型

使用兼容OpenAI `chat/completions`协议的远程或本地模型。密钥只从环境变量读取，不在GUI、日志或知识库保存。PowerShell示例：

```powershell
$env:ELECTROCHEM_LLM_BASE_URL = 'https://你的模型服务/v1'
$env:ELECTROCHEM_LLM_MODEL = '你的模型ID'
$env:ELECTROCHEM_LLM_API_KEY = '你的API密钥'
py -3 '.\run_gui.py'
```

本地OpenAI兼容服务可以使用 `http://127.0.0.1:端口/v1`；远程接口必须使用HTTPS。相同证据包按SHA-256缓存，避免重复消耗Token。知识助手以五个标签页实时展示：

- **实时过程**：检索计划、公开元数据检索、全文/图表提取、证据包压缩、大模型整理和本地写库；
- **结论总览**：研究背景与关键图表参数；
- **数据价值**：当前数据能说明什么、可信度、限制和不能判断的内容；
- **补充实验与表征**：形成完整研究课题仍缺少的验证工作；
- **知识审核**：每条候选知识独立显示来源和置信度，可在运行完成后立即批准或拒绝，并把状态和人工备注写回本地Markdown。

#### 通过 CC-SWITCH 本地路由接入

Harness 支持 CC-SWITCH 的本地 Codex/Responses 路由，不需要读取或复制上游 API 密钥：

```powershell
$env:ELECTROCHEM_LLM_BASE_URL = 'http://127.0.0.1:15721/v1'
$env:ELECTROCHEM_LLM_MODEL = 'gpt-5.6-sol'
py -3 '.\run_gui.py'
```

在 CC-SWITCH 中先让 Codex 进入 **Routing** 模式并选择目标 Provider，同时保持 CC-SWITCH 运行。Harness 识别到默认端口 `15721` 后会自动使用 OpenAI Responses API，并只发送官方占位凭据 `PROXY_MANAGED`；真实密钥始终留在 CC-SWITCH 的本地配置中，不进入 Harness、日志或知识库。若端口被用户修改，应在 GUI 中填写实际本地地址，并显式使用与该路由一致的协议配置。

当前 Kiro 会话本身不是可嵌入的公开模型 API，Harness 不读取或复用 Kiro 登录凭据；这里复用的是 CC-SWITCH 已配置的模型路由。

#### 本地Qwen 4B（推荐的校园网方案）

推荐安装Ollama并使用`qwen3:4b-q4_K_M`：

- Ollama官方下载：[Ollama for Windows](https://ollama.com/download/windows)；
- 本地接口：`http://127.0.0.1:11434/v1`；
- 模型ID：`qwen3:4b-q4_K_M`；
- 便携入口：双击`start_gui_local_qwen_portable.cmd`。

便携入口会自动查找Ollama；模型缺失时先说明约2.6 GB下载量并要求用户确认，不会静默下载。模型、缓存和日志位置由用户自己的Ollama安装决定。模型推理不经过OpenAI或VPN；Crossref/OpenAlex和用户浏览器仍使用当前校园网。数据库登录与全文下载继续由用户自己的浏览器完成，Harness只把筛选后的文献摘录和数据摘要发送给本机Qwen。4B量化模型适合知识提炼和实验建议，但正式机理结论仍须人工核对正文证据。

### 高级学术检索与校园网

- Crossref、OpenAlex：程序通过公开API自动检索和整理元数据；
- Web of Science、Scopus、中国知网、Google Scholar：程序生成高级检索式并在用户自己的浏览器中打开；
- 校园IP、机构登录、验证码和下载选择均由用户浏览器处理；程序不会读取账号、密码或Cookie，也不绕过数据库限制；
- 可将校园网下载的论文放入一个本地目录，再由知识助手批量读取；
- 支持HTML、TXT和Markdown；PDF文本提取需要可选的`pypdf`，程序不会自动安装依赖；没有该依赖时可从数据库导出HTML/TXT。

### 模型接收与输出

模型接收的是受限的 `evidence_packet.json`，不是完整原始文件。数据JSON中的大数组会被删除，CSV只保留表头和边界行；全文只保留限定长度的引言、方法、图注、表格和正文摘录。

模型必须输出严格JSON，至少包含：

- 研究背景及来源和证据等级；
- 关键图表参数、数值、单位、条件和位置；
- 当前数据的研究价值、可信度和局限；
- 一个完整课题仍需补充的实验；
- 仍需补充的结构、成分和界面表征；
- 当前不能判断的问题；
- 可写入知识库的候选知识及核验要求。

每次运行在 `knowledge\runs\<run_id>\` 生成 `plan.json`、`evidence_packet.json`、`reasoning_result.json` 和 `run_record.json`；候选综合知识写入 `knowledge\research_knowledge.md`。这些文件均被Git忽略，发布包只包含空模板。大模型无权把条目标记为`approved`，最终科学判断仍由用户完成。

## 文献结论边界

默认最多复核50个候选DOI。只有电池体系、活性物质、电池类型/对电极、电流或倍率、温度和质量归一化口径均明确匹配的论文才标记为直接可比。Crossref不提供期刊影响因子；摘要性能值仅用于初筛，正式引用前必须阅读原文。

## Origin图形规范

- 白底、Arial英文/数字/图例，中文标签回退宋体；
- 轴线约1.0 pt、数据线约1.5 pt，主次刻度向内；
- 统一使用色盲友好的NPG配色，同一循环同色，充放电用线型区分；
- 采用Nature官方图稿规范控制字体、线宽和成图可读性，投稿前仍需按目标期刊尺寸终审。

## 数据安全

原始蓝电数据仅在本地读取。启用文献检索后，只把实验检索条件发送到Crossref。不要在检索条件中填写姓名、保密样品编号或其他敏感信息。

## 当前限制

- 11类常规图谱已支持数据读取与Nature风格SVG输出，但EIS等效电路拟合、GITT扩散系数、Arrhenius活化能和CCD自动失效判定仍待独立科学验收；
- 蓝电专有二进制数据库仍需先导出为CSV/TXT；
- 2021–2026版本需要团队成员按版本矩阵补充实机验证证据；
- 不能仅凭单个电池结果证明材料机理、重复性或创新性。

## 运行测试

```powershell
py -3 -m unittest discover -s '.\tests' -v
```

没有`py`启动器时，可将`py -3`替换为`python`。
