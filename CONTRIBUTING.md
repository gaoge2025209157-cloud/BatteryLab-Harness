# 贡献指南

## 协作原则

- `main`只保存经过审核、测试通过的版本；禁止直接推送。
- 每项工作建立独立分支和Pull Request。
- 计算口径、单位、电流方向或循环分段发生变化时，必须同时增加测试。
- 文献结论必须提供已核验DOI，并写明电池体系、对电极、倍率、电流、温度和质量归一化口径。
- 不得上传真实原始数据、未脱敏样品编号、个人信息、凭据或私人实验经验库。

## 分支命名

```text
feature/功能名称
fix/问题名称
docs/文档名称
test/测试名称
```

例如：

```text
feature/cv-analysis
fix/land-cycle-segmentation
docs/gui-guide
```

## 开发流程

1. 从最新`main`创建分支。
2. 先写能复现需求或问题的测试。
3. 完成最小实现并运行全部测试。
4. 更新用户文档和`CHANGELOG.md`。
5. 创建Pull Request并说明输入、输出、计算依据和已知限制。
6. 至少由一名未参与实现的成员审核。
7. CI和人工审核都通过后才能合并。

## 本地验证

```powershell
python -m unittest discover -s '.\tests' -v
python '.\run_gui.py' --check
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\check_environment.ps1'
```

Origin不是自动化测试的强制依赖。涉及Origin样式或COM接口的修改，需要在有许可证的Windows电脑上补充人工验证记录。

## 数据样例

测试只能使用：

- 人工合成数据；
- 已获授权的脱敏小样例；
- 不含样品真实编号、人员信息或未公开工艺参数的数据。

大文件和原始实验数据应保存在实验室批准的共享存储中，不应提交到GitHub。
