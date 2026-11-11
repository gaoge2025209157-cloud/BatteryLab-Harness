# ElectrochemHarness v2

> 面向电化学研究的本地、可审计科研辅助工作台。

ElectrochemHarness v2 将**课题建档、受控文献学习、实验数据确定性分析、Origin 正式作图、Codex 课题评估和中文图文报告**组织为一次点击的自动流程。它的核心原则是：**程序先计算，模型再解释；来源先保留，结论再形成；研究者保留最终科学判断权。**

## 1. 适用场景

- 处理恒流充放电（GCD）实验数据，快速获得容量、电压、极化、库仑效率和循环保持率。
- 将原始实验曲线、可选本地 PDF 和联网文献线索汇入同一条可追溯研究链路。
- 使用 Origin 生成正式 PNG 图与可编辑 `.opju` 工程。
- 让 Codex 基于**受限的结构化特征**、来源信息与研究条件，提出竞争解释、证据边界与下一轮判别实验。
- 自动生成中文 HTML 图文科研决策报告，服务组会、实验复盘和课题推进。

> **科学边界**：程序负责文件解析、数值计算、异常识别和产物关联。Codex 负责检索、文献提炼、研究解释和实验建议。研究者负责确认材料身份、实验条件、图形与证据适用范围。原始 CSV 逐行数据和逐点时间序列不会发送给 Codex。

---

## 2. 已实现功能

| 模块 | 已实现能力 | 产出或作用 |
| --- | --- | --- |
| 课题管理 | 创建、打开、修改课题名称、材料体系和关键词；Unicode 名称可保存 | SQLite 课题记录 |
| 实验输入 | 填写实验条件与活性物质质量（mg），选择数据与可选 PDF | 可审计的输入条件 |
| 本地 PDF 学习 | 使用 PyMuPDF 按页提取文本片段、页码与覆盖信息 | 本地来源与证据片段 |
| 文献检索 | Crossref、OpenAlex 提供题录线索；Codex 联网检索补充学术来源与主流体系 | 检索主题、来源、研究缺口 |
| GCD 数据分析 | 编码与列识别、容量重置分段、完整循环配对、异常审计 | 可复算的结构化指标 |
| 电化学指标 | 放电比容量、容量加权平均放电电压、平均充电电压、极化、库仑效率、容量保持率和峰值趋势 | `analysis.json` |
| Origin 作图 | 调用已验证的 Origin 作图引擎 | 正式 PNG 与可编辑 `.opju` |
| Codex 课题评估 | 基于特征包、Origin 状态、研究条件与可追溯来源输出解释和实验路线 | `guidance.json` |
| 中文报告 | 汇总数据事实、课题阶段、文献学习、结论边界和下一步实验 | `research_decision_report.html` |
| 知识积累 | 缓存同主题研究、保存来源、页码证据、候选知识与运行产物 | 本地 SQLite 知识库 |

---

## 3. 工作流程

```text
研究者填写课题、条件、质量口径，选择数据和可选 PDF
                         │
                         ▼
本地文件哈希 ──► PDF 按页提取 ──► 题录检索（Crossref / OpenAlex）
                         │
                         ▼
原始 GCD CSV / TXT / TSV / DAT
                         │
                         ▼
确定性分析：列识别 → 分段 → 充放电配对 → 指标计算 → 异常审计
                         │
                         ├──► Origin：正式图 PNG + 可编辑 .opju
                         │
                         ▼
有限特征包：汇总指标 + 循环特征 + 质量标志 + 实验条件
                         │
                         ▼
Codex：联网学习 → 文献提炼 → 竞争解释 → 反证 → 判别实验设计
                         │
                         ▼
中文 HTML 图文科研决策报告 + 本地可追溯运行档案
```

### 3.1 单击自动流程的执行顺序

单击 GUI 中的 **“自动执行课题全流程”** 后，程序依次执行：

1. 创建或恢复课题，并为原始数据计算 SHA-256。
2. 按关键词检索题录元数据；若提供 PDF，则在本地逐页提取证据片段。
3. 解析原始实验数据，识别充放电段与完整循环，计算 GCD 指标并记录异常。
4. 按已出现的性能指标生成检索主题，调用 Codex 进行受控联网研究与知识提炼。
5. 生成 Origin 输入表，调用 Origin 导出正式曲线图与 `.opju` 工程。
6. 将**有限的特征包**交给 Codex，生成数据解释、不能判断项、反证和下一轮单变量实验建议。
7. 生成中文 HTML 图文报告，并保存本轮所有可追溯产物。

PDF、联网检索、Codex 评估任何一项失败时，已完成的本地分析不会被覆盖；报告仍会保留确定性数据结论与错误边界。

---

## 4. 安装与配置（Windows）

### 4.1 环境要求

- Windows 10/11
- Python 3.10 或更高版本
- Origin 2026 或兼容版本，用于正式 Origin 图形输出
- 可用的 Codex 本地 app-server / 代理配置，用于联网研究和课题评估

当前项目锁定依赖：

- `openai-codex==0.167.0`
- `PyMuPDF==1.28.2`

### 4.2 在 D 盘创建隔离环境

在 Windows PowerShell 中执行：

```powershell
cd D:\AI\Harness-v2
py -3 -m venv D:\AI\Harness-v2\.venv
$env:PIP_CACHE_DIR = "D:\AI\Harness-v2\.pip-cache"
& "D:\AI\Harness-v2\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "D:\AI\Harness-v2\.venv\Scripts\python.exe" -m pip install "openai-codex==0.167.0" "PyMuPDF==1.28.2"
```

### 4.3 配置 Origin

复制 `config.example.json` 为本机 `config.json`，再填入 Origin 的实际可执行文件路径。该本机配置已被 `.gitignore` 排除，不会上传到 GitHub。

```json
{
  "origin_executable": "D:\\Origin2026b\\Origin64.exe"
}
```

### 4.4 配置 Codex

Codex 的服务端地址、模型或代理配置属于本机凭据与运行环境，不应写入仓库。请在本机 Codex 配置中完成设置，例如当前环境使用的 `C:\Users\12470\.codex\config.toml`。请勿将密钥、Token、私有代理地址或该配置文件提交到 GitHub。

---

## 5. 快速开始

### 5.1 启动图形界面

双击：

```text
D:\AI\Harness-v2\start_gui.cmd
```

也可以在 PowerShell 中运行：

```powershell
cd D:\AI\Harness-v2
& ".\.venv\Scripts\python.exe" ".\run_gui.py"
```

### 5.2 一次完整实验运行

1. 填写**课题名称**、**课题类型（材料体系）**和**关键词**，关键词以分号分隔。
2. 填写实验条件，格式为 `key=value`，多项以分号分隔。例如：`temperature_C=60；current_mA=0.1；pressure_MPa=300`。
3. 填写**活性物质质量（mg）**。该值用于明确容量归一化与理论量的解释边界。
4. 选择 GCD 数据文件。支持 `.csv`、`.txt`、`.tsv`、`.dat`。
5. 按需选择本地 PDF。PDF 是可选输入，原文件仅在本地读取。
6. 单击**“自动执行课题全流程”**。
7. 运行结束后，浏览器会打开图文报告；也可使用 GUI 的**“打开最近图文报告”**或**“打开 Codex 工作记录”**按钮查看结果。

### 5.3 打开和修改已保存课题

1. 在下拉框选择目标课题。
2. 单击**“打开选中课题”**。
3. 修改课题名称、材料体系或关键词。
4. 单击**“保存课题修改”**。

---

## 6. 数据、模型和报告的科学边界

### 6.1 Codex 输入边界

在 `gcd_metrics.py` 完成本地数据处理后，`build_codex_feature_packet()` 才会构造模型输入。该输入可包含来源哈希、汇总指标、完整循环特征、候选段特征、质量标志与实验条件。

下列内容不会发送给 Codex：

- 原始 CSV 行和逐点 `points`
- 原始 `rows` 和完整时间序列
- 原始 PDF 文件
- 未带来源或条件的结论

每轮会生成 `codex_input_manifest.json`，其中记录：

```json
{
  "point_level_input_sent": false,
  "row_level_input_sent": false
}
```

#### 统一上下文管理

v2 在每个 Codex 阶段前通过 `ContextBuilder` 组装受控上下文。上下文包括本轮任务、实验条件、确定性数据特征、分级知识、候选题录、上一轮研究状态、权限与模型身份，并遵循以下规则：

- `approved` 知识可以作为正式文献依据；
- `candidate` 知识和联网结果只能用于提出假设与判别实验；
- `rejected` 知识和明确不匹配当前实验条件的证据不会进入模型；
- 原始逐行 CSV、逐点时间序列、密钥、Cookie 与本机绝对路径不会进入模型；
- 输入超过 Token 预算时优先排除低相关候选，不截断任务、实验条件和确定性事实；
- 每次调用保存上下文包、来源清单、排除原因、Token 估算与上下文哈希；
- 数据、实验条件、知识状态、研究记忆或模型身份变化时，上下文哈希随之变化。

Codex 生成的假设和下一轮实验建议会以候选研究状态保存。研究人员的确认、纠正和被排除假设由本地课题库保留，供下一轮数据分析继续使用；模型不能自行批准科学知识。

### 6.2 理论能量的正确口径

程序采用 `mAh g⁻¹ × V = Wh kg⁻¹` 计算活性物质质量口径的理论或投影比能量。若使用实验平均放电电压，该结果必须标注为“理论容量 × 实验平均电压”的投影。

未计入电解质、导电剂、集流体、负极、封装等质量时，**不得**将该数值称作复合正极、全电池或电池包能量密度。

### 6.3 文献比较的边界

文献来源、质量分母、构型、温度、倍率/电流、压力、载量、电压窗口和循环定义不匹配时，只能作为研究背景或单指标情境参考，不能形成正式的综合性能优劣结论。

---

## 7. 每轮运行产物

每次运行在以下目录生成独立档案：

```text
outputs/research_cockpit/<project_id>/runs/<run_id>/
├─ analysis.json                    # 确定性数据、GCD 指标与异常审计
├─ benchmark_research.json          # 题录线索、Codex 联网研究和理论计算
├─ literature_review.json           # 文献学习结果、来源与研究缺口
├─ codex_activity.json              # Codex 阶段、检索主题、来源和判断摘要
├─ codex_input_manifest.json        # 模型输入边界及受控上下文入口
├─ contexts/
│  ├─ online_research.bundle.json   # 联网研究阶段实际使用的上下文
│  ├─ online_research.manifest.json # 纳入/排除来源、Token和哈希
│  ├─ literature_synthesis.*.json   # 文献精选阶段的上下文与清单
│  └─ codex_assessment.*.json       # 课题评估阶段的上下文与清单
├─ guidance.json                    # Codex结构化课题评估、上下文依据与实验建议
├─ figures/                         # Origin 正式导出图片
├─ origin/                          # Origin 工程与作图状态
├─ manifest.json                    # 本轮产物和状态清单
└─ research_decision_report.html    # 中文图文科研决策报告
```

`outputs/`、本地 SQLite 知识库、Origin 工程和本机配置均被 `.gitignore` 排除。默认上传源代码、测试、使用说明、示例配置和工具介绍；不上传原始实验数据、PDF、运行报告、数据库、Token 或本机 Origin 配置。

---

## 8. 测试

在项目根目录执行：

```powershell
cd D:\AI\Harness-v2
$env:PYTHONPATH = "$PWD\src"
& ".\.venv\Scripts\python.exe" -m unittest discover -s tests -v
```

> 当前 Windows 环境请使用 `discover -s tests`。不要使用 `python -m unittest tests.test_...`，该调用方式在本环境可能将 `tests` 解析错误。

自动化测试覆盖 CSV 导入、GCD 指标、Codex 输入边界、统一上下文构建、知识状态筛选、Token预算、隐私脱敏、跨轮研究记忆、PDF 提取、文献检索、知识提炼、Origin 适配、报告生成、理论能量、缓存与一键工作流。

---

## 9. 目录说明

```text
Harness-v2/
├─ src/electrochem_harness_v2/      # 核心领域模块和 GUI
├─ scripts/                         # Origin 调用脚本
├─ tests/                           # 自动化测试
├─ docs/                            # 设计稿与样式参考
├─ config.example.json              # Origin 本机配置模板
├─ run_gui.py                       # GUI 启动入口
├─ start_gui.cmd                    # Windows 双击启动入口
├─ 工作流.md                         # 设计、门禁和可追溯原则
├─ 验收报告.md                       # 本地验收记录
└─ ElectrochemHarness_v2_工具介绍汇报.html  # 可交互工具介绍汇报
```

---

## 10. GitHub 发布说明

本项目准备作为独立新版本发布。推荐仓库名：`ElectrochemHarness-v2`。

发布前请确认以下事项：

1. 两个 GitHub 目标仓库的完整地址，例如个人账号和课题组组织各自的 `https://github.com/<owner>/ElectrochemHarness-v2.git`。
2. 目标仓库是公开还是私有。
3. 本机安装 Git，并通过 Git Credential Manager、SSH 或 GitHub CLI 完成账号授权。
4. 确认不上传 `outputs/`、`knowledge/*.sqlite3`、`.venv/`、`config.json`、`.env`、实验数据、PDF 或任何凭据。

建议发布方式是：在本地创建一次初始提交，创建 `release/v1.0.0` 分支，并将**完全相同的提交**推送到个人仓库与课题组仓库。这样两个仓库保持同一代码版本，后续可以通过 Pull Request 向主分支合并。

---

## 11. 许可证与引用

当前仓库尚未指定开源许可证。向公开 GitHub 仓库推送前，应由项目负责人明确选择许可证（例如 MIT、Apache-2.0、GPL-3.0 或仅限内部使用的私有仓库）。在许可证确定前，请将仓库设置为私有，避免默认版权状态引发使用范围歧义。
