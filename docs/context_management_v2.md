# ElectrochemHarness v2 上下文管理

## 1. 目的

v2 的上下文管理位于确定性分析、课题知识库和 Codex 之间。它不计算电化学指标，也不审批科学知识；它负责在每次模型调用前选择、标记、压缩和记录本轮允许使用的信息。

核心目标：

1. 让 Codex 明确本轮任务、实验条件和完成标准；
2. 区分确定性数据事实、已批准知识、候选知识和待验证假设；
3. 只选择与当前体系和问题相关的证据；
4. 保存上一轮假设、用户决定、纠正和未解决问题；
5. 控制输入 Token，并排除原始逐行数据、密钥和本机路径；
6. 记录模型实际使用和排除的来源，支持复核与缓存失效。

## 2. 接入位置

```text
课题与实验条件
    +
确定性 GCD 特征
    +
本地/联网文献与知识状态
    +
上一轮研究状态
    ↓
ContextBuilder
    ↓
contexts/<stage>.bundle.json
contexts/<stage>.manifest.json
    ↓
Codex（只读、deny-all）
    ↓
guidance.json + 研究状态更新 + HTML 报告
```

`ResearchWorkflow` 在以下 Codex 阶段调用 ContextBuilder：

- `pdf_candidate_extraction`：本地 PDF 候选知识提取；
- `online_research`：围绕确定性数据特征进行联网研究；
- `literature_synthesis`：把本地和联网候选压缩为人工审核队列；
- `codex_assessment`：形成竞争假设、反证实验和下一轮实验建议。

## 3. 上下文组成

### 3.1 核心规则

每轮固定保留：

- 不编造数据、文献、DOI、数值、实验条件或机理；
- 数据事实只来自确定性程序；
- 候选知识不得表述为已批准事实；
- 证据不足时必须说明无法确定；
- 模型不得修改数据、扩大权限、批准知识或控制设备。

### 3.2 任务与课题

包括任务目标、完成标准、当前科学问题、课题名称、材料体系、关键词和研究目标。

### 3.3 实验与确定性数据

包括实验条件、数据哈希、容量、电压、极化、效率、保持率、循环特征、异常和限制。原始 `rows`、`points` 及逐点时间序列被明确排除。

### 3.4 分级知识

- `approved`：可以作为正式文献依据；
- `candidate`：只能用于候选解释和实验设计；
- `rejected`：不进入模型上下文；
- 明确与当前实验条件冲突的知识会被排除并记录原因；
- 条件缺失时标记为 `insufficient_context`，不能静默视为可比。

### 3.5 研究记忆

SQLite 中保存：

- 用户确认的决定；
- 用户纠正；
- 最近确定性发现；
- 候选假设及反证实验；
- 已拒绝假设；
- 未解决问题；
- 下一轮验证目标；
- 最近运行编号和状态版本。

Codex 输出只以 `candidate` 状态进入研究记忆，不能自动成为已批准科学事实。

### 3.6 权限和模型身份

上下文记录是否允许联网、是否允许读取原始数据、是否允许写回原始数据、是否允许批准知识和是否允许控制设备。v2 当前仅在 `online_research` 阶段授予联网标志，其他高风险权限均为 `false`。

## 4. 预算、筛选和隐私

默认配置：

```json
{
  "max_input_tokens": 14000,
  "reserved_output_tokens": 3000,
  "max_approved_claims": 10,
  "max_candidate_claims": 6,
  "max_metadata_records": 12
}
```

筛选顺序：

1. 人工审核状态；
2. 实验条件是否明确冲突；
3. 当前任务和数据现象相关性；
4. 证据位置、限制和优先级；
5. 数量和 Token 预算。

当受保护的任务、实验条件和确定性事实已经超过预算时，构建器停止并报告错误，不机械截断核心内容。

下列内容不会进入模型：

- 原始逐行 CSV 和逐点数据；
- API 密钥、密码、Cookie、授权头和访问令牌；
- 本机绝对路径；
- 已拒绝知识；
- 明确不匹配当前实验条件的证据；
- 超出数量或 Token 上限的低优先级候选。

## 5. 运行产物

每个有运行编号的 Codex 阶段在当前运行目录生成：

```text
contexts/
├─ online_research.bundle.json
├─ online_research.manifest.json
├─ literature_synthesis.bundle.json
├─ literature_synthesis.manifest.json
├─ codex_assessment.bundle.json
└─ codex_assessment.manifest.json
```

`bundle.json` 是 Codex 实际接收的受控上下文。

`manifest.json` 记录：

- 纳入的来源及原因；
- 排除的来源及原因；
- 已批准、候选、题录和联网来源数量；
- 输入 Token 估算；
- 数据逐行/逐点内容是否发送；
- 任务、课题、实验、知识、研究记忆、权限和模型身份哈希；
- 最终上下文哈希。

数据、实验条件、知识状态、研究记忆、权限或模型身份变化时，对应哈希和最终上下文哈希会变化，旧缓存不得继续视为同一输入。

## 6. 跨轮研究闭环

```text
第一轮数据
→ 确定性事实
→ 候选假设和反证实验
→ 研究人员确认下一步
→ 保存研究状态
→ 第二轮数据
→ 自动带入上一轮假设和验证目标
→ 支持、削弱或排除候选解释
```

当前模块已经保存 Codex 产生的候选假设、不可判断项和下一轮实验。研究人员确认、纠正和拒绝假设可通过 `ResearchStore.update_research_state()` 写入；GUI 的人工编辑入口属于后续界面工作，不由模型自动执行。

## 7. 下一轮实验输出

每项建议允许记录：

- `action`：具体实验动作；
- `hypothesis`：要验证的候选解释；
- `purpose`：为什么做；
- `variable`：唯一改变项；
- `controls`：保持不变或必须设置的对照；
- `expected_evidence`：需要观察的证据；
- `expected_if_supported`：支持假设时的预期结果；
- `expected_if_refuted`：反对假设时的预期结果；
- `requires_confirmation`：是否需要研究人员确认。

## 8. 科学与安全边界

- ContextBuilder 不取代 GCD 数值计算；
- ContextBuilder 不认定候选知识已经通过审核；
- ContextBuilder 不允许 Codex 控制设备或修改原始数据；
- 文献条件不完整时只能形成背景或候选解释；
- 单个电池或单条曲线不能证明重复性、机理或创新性；
- 最终科学判断仍由研究人员作出。

## 9. 验证

专项测试覆盖：

- 原始数据、敏感信息和绝对路径排除；
- approved/candidate/rejected 分层；
- 实验条件冲突与条件不足；
- 支持联网候选的明确标记；
- Token 超限阻断；
- 实验或知识状态变化引起哈希变化；
- 用户决定和候选假设跨轮保存；
- Codex 课题评估通过统一上下文运行；
- 上下文包、清单、研究状态和报告审计落盘。
