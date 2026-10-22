# ElectrochemHarness v0.6.0-rc1 发布说明

> 这是包含 Phase 1 受控执行和 Phase 2 科学正确性工程层的团队候选版，不是最终稳定版。

## 这一版解决了什么

旧版本主要证明“流程能运行”。本版进一步回答两个问题：计算采用什么口径，以及多个平行电池应怎样透明统计。

### 1. 科学计算口径可追溯

- 冻结恒流循环核心标准 v1.0.0；
- 记录电流方向、容量积分、恒压段、质量归一化、库仑效率、保持率、平均电压和平台算法；
- 每次单电池分析生成 `科学计算标准.json`；
- 标准内容具有稳定 SHA-256，公式改变必须升级版本，不能静默改写。

### 2. 标准答案和科学发布门

- `standards/ground_truth_v1.json` 保存独立参考值及绝对/相对容差；
- `run_phase2_validation.py` 输出逐项实际值、标准值、差值和通过状态；
- 当前极简合成案例 21/21 数值检查通过；
- 数值通过只表示技术验证通过；J/C 未完成真实数据共同复核前，`scientific_release_ready` 必须保持 `false`。

### 3. 多平行电池统计

- 使用 JSON 清单组织同条件独立电池；
- 按真实循环号对齐，保留全部原始散点；
- 输出均值、样本标准差、SEM 和双侧 95% Student t 区间；
- 少于 3 个独立电池自动标记为探索性；
- MAD 异常只提示，不自动删除；
- 人工排除必须记录事前规则、理由和原值；
- 生成 JSON、CSV、Markdown 和 SVG 快速质控图。

### 4. 可编辑文献知识

- DOI 核验文献可按 DOI 去重写入本地 Markdown；
- 自动条目默认是 `candidate`；
- 只有人工改为 `approved` 且实验条件匹配的内容才参与后续判断；
- 人工确认知识、正文位置和备注不会被自动更新覆盖；
- 私人知识文件被 Git 忽略，发布包只带空模板。

## 最快使用

1. 解压源码包；
2. 双击 `start_gui.cmd` 进行普通分析或 Phase 1 受控演示；
3. 运行 `py -3 .\run_phase2_validation.py --output .\phase2_validation.json` 检查标准答案；
4. 复制 `examples\replicate_manifest_template.json` 并填写至少 3 个同条件电池；
5. 运行 `py -3 .\run_replicates.py .\replicate_manifest.json --output-dir .\replicate_results`。

详细说明见 `README.md`、`README_发布版.md` 和 `TEAM_WORK_PACKAGES.md`。

## 已知边界

- Phase 2 工程实现已完成，但真实蓝电—仪器软件—人工计算三方复核尚未结束；
- Phase 1 演示中的 Origin 独立白名单适配器尚未完成；
- 正文文献证据、假设矩阵和完整六步生产 GUI 尚待实现；
- 仅 Origin 2026b 已实机验证，其他受支持版本仍需逐版验证；
- 不支持 CV、EIS、GITT/PITT、dQ/dV 和蓝电专有二进制数据库。

## 验证口径

发布前必须通过完整自动测试、Phase 2 标准答案命令、Python 编译、PowerShell 解析、发布包白名单和隐私审计。真实实验数据、运行输出、个人路径、凭据和本地知识不得进入 GitHub 或发布 ZIP。
