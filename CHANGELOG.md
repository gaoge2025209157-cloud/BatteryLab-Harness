# Changelog

## Unreleased — Work package A

- add DOI-backed evidence, full-text availability, publication-gate and
  falsifiable-hypothesis modules;
- keep the scientific release gate closed until real-data review, experimental
  issues, metric tolerances and J/C confirmations are recorded;
- report negative voltage, incomplete current direction and source-cycle jumps
  in four-column data;
- record applied current-sign reversal in LAND import metadata;
- make rounded-display tolerance depend on the least-significant digit and the
  actual reported unit;
- add executable boundary tests for constant-voltage integration, non-finite
  input, uA/mV conversion and the new quality warnings.
- record candidate B as the deterministic three-column draft calculation
  convention while keeping instrument-defined cycle mapping pending;
- add a privacy-safe current review record with reserved placeholders for the
  unavailable raw export, device cycle summary and voltage-window evidence;
- document DOI-backed general definitions for capacity, coulombic efficiency,
  retention, energy and normalization boundaries.

## 0.4.0 — 2026-10-12

### Origin兼容范围

- 新增Origin 2021、2021b至2026、2026b共12个版本的兼容矩阵；
- 自动检测并选择最新的受支持安装，也可显式指定`Origin64.exe`；
- 对旧版`originpro`绘图属性和图片宽度参数增加兼容降级；
- `origin_status.json`记录Origin版本、originpro版本和降级警告；
- 当前仅Origin 2026b完成本机实测，其他版本标记为代码支持、待实机验证。

## 0.3.0 — 2026-10-12

### 新增

- 基于 Python Tkinter 的本地中文交互界面；
- 文件与输出目录选择器；
- 电池体系、活性物质、电池类型、对电极、测试条件和归一化口径表单；
- 文献检索、候选 DOI 数量和 Origin 绘图开关；
- Origin 可执行文件选择与自动定位；
- 后台运行、实时日志、任务取消和结果目录打开；
- 双击启动入口和无残留 GUI 自检。

### 安全与兼容性

- 子进程使用参数列表，不拼接 shell 命令；
- 原始蓝电数据仅在本地读取；
- 只有用户填写的检索条件会发送至 Crossref；
- 不新增第三方 Python 依赖。

## 0.2.0 — 2026-10-12

首个源码发布候选版本。

### 已实现

- 蓝电四列逐点数据和三列比容量曲线自动识别；
- 充放电比容量、库仑效率、容量保持率、平均电压和主平台提取；
- 精炼 Markdown、CSV 和完整 JSON 报告；
- 引导式实验元数据问卷；
- Crossref 候选检索、逐 DOI 复核和直接可比性筛选；
- Origin 2026/2026b 工程与两张 SCI 风格图；
- Origin 自动定位、显式路径覆盖和无 Origin 报告模式；
- 白名单式源码打包、SHA-256 校验和环境检查。

### 已知限制

- 不支持蓝电专有二进制数据库及 Excel 直接输入；
- 文献性能值来自公开题名/摘要时只能用于初筛；
- 期刊影响因子不属于 Crossref 开放元数据；
- 恒压段在有电流和时间时计入容量与能量；独立 CV 分析、EIS、GITT 和 dQ/dV 尚未实现。
