# Windows零基础安装与第一次分析

本指南面向电脑中没有ElectrochemHarness项目文件、不会编程的用户。你不需要阅读或修改任何Python代码。

## 一、先选择使用范围

### 最小使用

只做本地数据检查、关键指标、简明结论和通用SVG图，需要：

- Windows 10或11；
- Python 3.10或更高；
- 本项目ZIP。

不需要Origin、Ollama、GPU、CUDA、Docker或Node.js。

### 完整使用

按需增加：

- Origin 2021–2026b：生成OPJU和Origin PNG；
- Ollama + Qwen3 4B：本地整理文献和辅助知识积累；
- 校园网或学校VPN：访问学校已购买的数据库和出版商全文。

## 二、从GitHub下载

1. 打开团队仓库的Releases页面：
   [BatteryLab-Harness Releases](https://github.com/gaoge2025209157-cloud/BatteryLab-Harness/releases)
2. 找到`ElectrochemHarness v0.7.0-rc2`。
3. 在Assets中下载：
   - `ElectrochemHarness-v0.7.0-rc2.zip`
   - `ElectrochemHarness-v0.7.0-rc2.zip.sha256`
4. 不要下载GitHub自动生成的“Source code (zip)”作为首选；Assets中的ZIP经过项目白名单打包和隐私检查。
5. 将ZIP移动到空间充足的目录，例如`D:\ElectrochemHarness`附近。

## 三、核对下载文件

这一步用于确认ZIP没有下载损坏。

1. 在ZIP所在文件夹空白处按住Shift并点击鼠标右键。
2. 选择“在终端中打开”或“在此处打开PowerShell窗口”。
3. 输入：

```powershell
Get-FileHash -Algorithm SHA256 '.\ElectrochemHarness-v0.7.0-rc2.zip'
```

4. 将显示的Hash与`.sha256`文件中的字符串比较。必须完全一致。
5. 如果不一致，删除ZIP并重新下载，不要继续运行。

## 四、解压项目

1. 右键ZIP，选择“全部解压缩”。
2. 建议解压到路径较短的目录，例如：

```text
D:\ElectrochemHarness-v0.7.0-rc2
```

3. 不要直接在ZIP压缩包预览窗口中运行程序。
4. 不要将真实实验数据复制进项目的`examples`或`tests`目录；应放在独立的数据目录。

## 五、安装Python

如果电脑已安装Python 3.10或更高，可以跳到下一节。

1. 打开Python官方网站：
   [Python for Windows](https://www.python.org/downloads/windows/)
2. 下载64位Python 3.11或3.12安装程序。
3. 启动安装程序时勾选：
   - `Add python.exe to PATH`
   - `tcl/tk and IDLE`
   - `pip`
4. 完成安装后，重新打开PowerShell，输入：

```powershell
py -3 --version
py -3 -c "import tkinter; print('Tkinter OK')"
```

5. 两条命令都成功后才继续。

项目核心分析和11类SVG绘图不需要安装第三方Python包。

## 六、启动软件

在解压后的项目目录中双击：

```text
start_gui.cmd
```

如果窗口没有打开：

1. 双击`check_environment.ps1`不会自动运行时，请右键项目目录空白处打开PowerShell；
2. 输入：

```powershell
py -3 '.\run_gui.py' --check
```

3. 显示`GUI check passed`说明界面环境正常；
4. 再输入：

```powershell
py -3 '.\run_gui.py'
```

## 七、准备充放电数据

支持CSV、TXT、TSV和DAT文本文件，不直接读取Excel或蓝电专有数据库。

### 三列模式

至少需要：

```text
测试时间,比容量,电压
```

示例：

```csv
测试时间/h,比容量/mAh/g,电压/V
0,0,2.0
0.1,100,3.0
```

该模式沿用仪器导出的比容量。程序不会猜测质量分母，请在实验记录中保留活性物质质量和归一化方法。

### 四列模式

至少需要：

```text
循环号,时间,电流,电压
```

示例：

```csv
循环号,测试时间/s,电流/mA,电压/V
1,0,0.1,2.0
1,3600,0.1,3.0
```

该模式根据时间和电流积分容量。没有独立活性质量时只报告mAh，不生成虚假的mAh/g。

## 八、完成第一次自动研究

1. 在主窗口左侧点击“自动研究与分析（充放电）”。
2. 首次填写并保存课题配置：
   - 电池体系、活性物质、电池类型和对电极；
   - 测试电流：只填数字，单位固定为mA；
   - 测试温度：只填数字，单位固定为°C；
   - 研究领域、课题背景和科学问题。
3. 选择蓝电CSV/TXT文件和结果目录。
4. 以后可载入相同配置，通常只需更换数据文件。
5. 点击“开始自动调研与分析”。
6. 系统自动完成预检、计划与授权记录、确定性数据计算、最多5篇真实DOI文献筛选、可读取原文学习、图像与报告生成。
7. 执行结束后直接阅读“研究结论与指导”，或点击“打开图文报告”。
8. 报告后可以继续说明整体课题并与本地Qwen对话。
9. 原文学习知识默认是`candidate`。可在结果页复核、批准或拒绝，再刷新报告；复核不是生成基础报告和对话的前提。
10. 需要完整数据时打开`关键参数报告.md`、`关键参数.csv`、JSON和审计记录。

## 九、生成常规电化学图

主界面左侧可进入：

- 倍率/dQdV/Arrhenius；
- EIS/电导率；
- CV/LSV；
- GITT/PITT；
- 对称电池/CCD。

窗口中选择图型后，会显示所需标准列名。可以复制`examples\plot_templates`中对应CSV模板，保留第一行列名并替换下面的合成数据。

点击“生成图像”后得到：

- `图型ID_nature.svg`：可用浏览器、Inkscape、Illustrator或Office打开；
- `图型ID_plot_record.json`：记录源文件哈希、字段、单位和科学边界。

程序会自动换算A→mA、mV→V、min/h→s、kΩ→Ω、K→°C和mS/cm→S/cm。

## 十、可选：使用Origin

1. 安装并授权Origin 2021–2026b。
2. 第一次使用前手动打开Origin一次，完成许可证和用户目录初始化。
3. 在受控分析中启用Origin。
4. 选择：
   - 只画充放电曲线；
   - 只画循环容量/库仑效率；
   - 两张都画。
5. `Origin64.exe`可以留空让程序自动查找；找不到时再手动选择。
6. Origin失败不会删除本地报告，运行状态会记录为降级完成。

当前只有Origin 2026b完成真机验证，其他版本属于代码兼容、待逐版验证。

## 十一、可选：安装本地Qwen

本地Qwen适合不使用VPN、同时保留校园网数据库访问的场景。

### 硬件建议

- 内存至少16 GB；
- Qwen3 4B量化模型约2.6 GB；
- 有6 GB NVIDIA显存时通常可获得更快推理；
- 不要求单独安装CUDA Toolkit。

### 安装步骤

1. 打开Ollama官网：
   [Ollama for Windows](https://ollama.com/download/windows)
2. 安装Ollama。
3. 回到项目目录，双击：

```text
start_gui_local_qwen_portable.cmd
```

4. 脚本会检查`qwen3:4b-q4_K_M`。
5. 如果模型不存在，会先提示约2.6 GB下载量；只有确认后才下载。
6. 模型准备好后自动打开GUI。

也可以在PowerShell手动运行：

```powershell
ollama pull qwen3:4b-q4_K_M
$env:ELECTROCHEM_LLM_BASE_URL = 'http://127.0.0.1:11434/v1'
$env:ELECTROCHEM_LLM_MODEL = 'qwen3:4b-q4_K_M'
py -3 '.\run_gui.py'
```

## 十二、自动文献学习、报告与人工复核

1. 连接校园网，启动本地Qwen版工作台。
2. 在“自动研究与分析（充放电）”中载入或新建课题配置，选择本轮数据后点击“开始自动调研与分析”。
3. 程序通过Crossref/OpenAlex筛选最多5篇高水平、高相关且有真实DOI的论文，并在执行页显示题名、期刊、年份、DOI和状态。
4. 程序优先下载或复用合法PDF、开放全文和本地原文；已获得PDF按DOI和SHA-256去重，不重复下载。
5. 无公开全文或需要机构登录时，本轮保留题录和确定性数据结论。可在浏览器中使用校园网合法下载PDF，放入原文目录后再运行；程序不会读取账号、密码或Cookie，也不绕过验证码。
6. 本地Qwen优先学习最相关且尚未学习的1篇可读取原文，提炼核心发现、背景、电化学基础、图表参数、数据判断、限制和下一轮建议。
7. 系统自动生成`研究结论与指导.txt`和`研究分析报告.html`，随后可以继续围绕整体课题对话。
8. 知识点默认标记为`candidate`，只用于候选解释和判别实验；复核正文后可批准为`approved`正式依据，或标记为`rejected`永久排除。复核后点击刷新报告即可更新结论依据。

## 十三、结果文件说明

充放电分析主要生成：

- `关键结论.txt`：主界面直接显示；
- `关键参数报告.md`：详细报告；
- `关键参数.csv`：逐圈指标；
- `完整分析.json`：机器可读结果；
- `科学计算标准.json`：公式和版本；
- `文献证据.json`、`文献比较.csv`：启用检索时生成；
- `电化学分析.opju`和所选PNG：启用Origin时生成；
- `plan.json`、`approval.json`、`events.jsonl`、`run_record.json`：计划、批准与审计记录。

## 十四、常见问题

### 提示“请选择存在的输入文件”

确认文件已经解压并且扩展名是CSV、TXT、TSV或DAT。

### 提示电流或温度格式错误

输入框只填数字。例如电流填`0.1`，不要填`0.1 mA`或`0.1 C`；温度填`25`，不要填`25 C`。

### 没有生成mAh/g

四列数据只有时间、电流和电压时，缺少可审计的活性物质质量。程序保守地只报告mAh。

### Origin失败

先关闭Origin选项确认本地分析正常；再手动打开Origin一次并检查许可证。

### Qwen返回JSON字段格式错误

本地4B模型偶尔会把数组返回为字符串。程序会让Qwen只修复JSON结构一次，并重新执行完整证据校验；第二次仍不合格才停止，且不会写入或批准错误知识。

### 文献数据库无法打开全文

确认仍连接校园网、学校订阅有效并使用浏览器完成机构登录。程序不会绕过数据库权限。

## 十五、科研使用边界

本工具提供数据处理、证据整理和候选判断，不替代：

- 仪器软件抽查；
- 人工计算复核；
- 至少3个独立平行样；
- 原始文献全文阅读；
- EIS拟合残差与Kramers–Kronig检查；
- GITT扩散假设检查；
- 最终实验安全和科学判断。
