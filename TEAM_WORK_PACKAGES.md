# Phase 2 之后的团队工作包

> 基线：`v0.6.0-rc1`。Phase 1 内核及最小 GUI 演示、Phase 2 工程实现已经完成；Phase 2 的真实科学签字、Phase 3–5 仍未完成。
>
> 两个工作包文件边界不同，可以并行开发。负责人若需互换，只交换 GitHub assignee，不改变验收标准。

## 共同规则

1. 从最新 `main` 创建各自功能分支，不直接推送 `main`。
2. 真实蓝电数据、出版商 PDF、校园网凭据、Cookie、个人路径和运行结果不得提交 GitHub。
3. 只提交合成或明确脱敏的数据；每个新算法必须有独立标准答案或测试。
4. 不得把摘要内容标为正文事实，不得把单电池结果描述为重复性结论。
5. 不得静默修改 `scientific_standard.py` 的冻结口径；需要修改时升级标准版本并重建标准答案。
6. 每个 PR 写清楚输入、输出、公式/证据、失败降级、测试和已知边界。
7. 两个工作包共享的数据模型通过 PR 评审确定，避免同时修改同一核心文件。

---

## 工作包 A｜科学验收、全文证据与推理闭环

**建议负责人：GitHub `@Cheng3399`**
**建议分支：** `feature/scientific-evidence-and-reasoning`
**主要范围：** Phase 2 科学验收收尾＋Phase 3＋Phase 4。

### 目标

把“工程上能计算”推进到“科学上有独立基准、文献事实能定位、结论能追溯、假设能被实验区分”。

### A1. 完成 Phase 2 科学验收

- 独立核对 `standards/SCIENTIFIC_STANDARD_v1.md` 的公式、适用范围和误差边界；
- 使用私有真实数据完成蓝电软件—人工计算—Harness 三方对照；
- 覆盖 A/mA/μA、反向电流、恒压段、不完整循环、时间异常、负电压和容量重置；
- 给出每个指标的绝对/相对允许误差及依据；
- 只把脱敏标准输入和参考结果提交仓库；原始真实数据保留在本地；
- J/C 都确认后再将科学审核状态改为 `approved`，不能由开发者代签。

### A2. 实现 Phase 3 正文证据层

建议新增：

- `src/electrochem_harness/evidence.py`
- `src/electrochem_harness/fulltext.py`
- `src/electrochem_harness/knowledge_governance.py`
- `tests/test_evidence.py`
- `tests/test_fulltext.py`

要求：

- DOI 必须先核验；
- 区分 `abstract_only`、`fulltext_html`、`local_pdf` 和 `unavailable`；
- 正文事实必须记录 DOI、章节、页码、图号/表号或补充信息位置；
- 无正文时明确降级，不伪装成已阅读全文；
- 只处理用户正常有权访问的内容，不保存账号、密码、Cookie，不绕过付费墙；
- 保留冲突文献、适用条件和人工审核状态。

### A3. 实现 Phase 4 推理闭环

建议新增：

- `src/electrochem_harness/scientific_reasoning.py`
- `tests/test_scientific_reasoning.py`

每条结论至少包含：

```text
观测现象 -> 证据等级 -> 候选原因 -> 支持证据 -> 反对/缺失证据
-> 最小区分实验 -> 下一轮单变量方案 -> 当前状态
```

严禁仅凭恒流曲线定量反演电荷转移电阻、扩散系数或具体失效机理。无法判断时必须输出 `unknown` 和缺失证据。

### 工作包 A 交付物

- 真实科学审核流程和脱敏标准答案增量；
- 正文证据模型、全文降级链和知识治理；
- 假设矩阵及单变量实验建议；
- 对应自动测试和用户说明；
- 一份独立 PR。

### 工作包 A 验收

- Phase 2 数值检查通过，审核身份和误差依据可追溯；
- 所有引用具有已核验 DOI；
- 所有正文级事实具有可定位证据；
- 摘要不会被升级为正文事实；
- 每个候选原因都有反证条件或验证实验；
- 无直接可比文献时不作领先/落后判断；
- 不包含真实数据、PDF或访问凭据。

---

## 工作包 B｜生产 GUI、Origin 适配器与系统评测

**建议负责人：GitHub `@0OO0O0OO0`**
**建议分支：** `feature/production-gui-and-evaluation`
**主要范围：** Phase 5＋生产 Origin 工具化＋E-01～E-12。

### 目标

把现有“Phase 1 受控演示窗口”升级为非编程用户可以完成正式分析、失败恢复和证据查看的生产流程。

### B1. 拆分生产白名单工具

建议新增：

- `src/electrochem_harness/production_registry.py`
- `src/electrochem_harness/origin_adapter.py`
- `tests/test_production_registry.py`
- `tests/test_origin_adapter.py`

要求：

- 数据解析、指标计算、文献、报告和 Origin 分别注册，不能把整个 PowerShell 脚本作为黑盒；
- 每个工具声明输入、输出、联网权限、写入范围、超时、重试和失败策略；
- Origin 失败只降级该阶段，保留报告和绘图 CSV；
- 继续支持 Origin 2021–2026b，并记录实际版本和兼容警告；
- 不改变已确认的原版图形风格。

### B2. 完成六步生产 GUI

建议新增或修改：

- `src/electrochem_harness/gui_controller.py`
- `src/electrochem_harness/gui.py`
- `tests/test_gui_production.py`

六步流程：

1. 数据与实验条件；
2. 预检查和阻断问题；
3. 分析计划；
4. 本地/联网/正式输出独立批准；
5. 受控执行、取消、验证和失败阶段重试；
6. 报告、证据、假设、Origin 和审计记录查看。

任何输入或参数变化必须使旧批准失效。未批准时执行按钮不可用。

### B3. 完成 E-01～E-12 系统评测

建议新增：

- `src/electrochem_harness/evaluation.py`
- `tests/evaluation/`
- `run_evaluation.py`

至少覆盖：正常数据、缺列、单位变化、时间倒退、不完整循环、缺质量、负电压、条件不完整、提示词注入、未批准执行、无 Origin、重复运行一致性。

输出指标：问题识别率、误报率、核心指标正确率、阻断率、未批准执行率、产物完整率、重复运行哈希一致率和人工修正次数。

### 工作包 B 交付物

- 生产工具注册表和独立 Origin 适配器；
- 六步 GUI、证据查看和失败阶段重试；
- E-01～E-12 测试数据、批量入口和评测报告；
- 新用户演示说明；
- 一份独立 PR。

### 工作包 B 验收

- 未批准执行率为 0；
- 阻断类案例 100% 拦截；
- 网络或 Origin 失败不丢失本地结果；
- 同输入同配置的核心结果哈希一致；
- 用户可查看计划、批准、事件、验证、证据和产物哈希；
- 至少两名团队成员仅依靠 README 完成独立操作；
- 不改变冻结科学标准或代替科学审核者批准结果。

---

## 合并顺序与接口约定

1. `v0.6.0-rc1` 先作为共同基线；
2. A、B 各自从同一基线建分支并独立提交 PR；
3. A 优先定义 `EvidenceItem` 和 `Hypothesis` 的稳定 JSON 接口；
4. B 可先用固定样例实现证据查看，待 A 的 PR 合并后替换为真实数据；
5. 两个 PR 都通过后再发布下一候选版，不提前标记稳定版；
6. 冲突集中在 `README.md`、`__init__.py` 或 `gui.py` 时，由后合并者基于最新 `main` 解决，不复制另一分支实现。

## Issue 回报格式

每位负责人在 Issue 中持续更新：

```text
本周完成：
验证证据：
当前阻塞：
下一步：
改动分支/PR：
是否接触真实数据或受版权保护全文：是/否（若是，确认未提交）
```
