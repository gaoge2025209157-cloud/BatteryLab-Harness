# Origin 2021–2026b兼容验证矩阵

## 兼容范围

| Origin版本 | 代码支持 | 本机实测 | 状态 |
|---|---|---|---|
| 2021 | 是 | 否 | 待对应安装验证 |
| 2021b | 是 | 否 | 待对应安装验证 |
| 2022 | 是 | 否 | 待对应安装验证 |
| 2022b | 是 | 否 | 待对应安装验证 |
| 2023 | 是 | 否 | 待对应安装验证 |
| 2023b | 是 | 否 | 待对应安装验证 |
| 2024 | 是 | 否 | 待对应安装验证 |
| 2024b | 是 | 否 | 待对应安装验证 |
| 2025 | 是 | 否 | 待对应安装验证 |
| 2025b | 是 | 否 | 待对应安装验证 |
| 2026 | 是 | 否 | 待对应安装验证 |
| 2026b | 是 | 是 | 通过：工程与两张PNG成功导出，无兼容警告 |

“代码支持”表示启动器能够识别该版本，绘图脚本只使用Origin 2021起的`originpro`路线和稳定LabTalk命令，并为部分版本差异提供降级路径；不等于该版本已经完成实机验证。

## 单版本验证步骤

1. 关闭其他Origin版本，避免`ApplicationSI`附加到错误实例。
2. 手动启动待测Origin一次，完成许可证与用户目录初始化，然后退出。
3. 在项目目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\run_sci_origin.ps1' `
  -InputFile '.\examples\sample_capacity_curve.csv' `
  -OutputDir '.\outputs\origin-version-test' `
  -OriginExe '待测版本Origin64.exe的完整路径'
```

4. 检查`origin_status.json`：
   - `ok`必须为`true`；
   - `origin_release`必须与待测版本一致；
   - 记录`originpro_version`和全部`compatibility_warnings`。
5. 确认生成且可打开：
   - `电化学分析.opju`；
   - `充放电曲线.png`；
   - `循环性能.png`。
6. 人工检查字体、4 pt坐标轴、主次刻度方向、双纵轴和图例。
7. 在Pull Request中附上版本、Origin补丁号、Windows版本、状态JSON和截图，不上传真实实验数据。

## 验收标准

- 合成数据关键参数与Python报告一致；
- 工程保存成功且重新打开无修复提示；
- 两张图片均非空、坐标轴和曲线完整；
- 中文使用宋体，英文/数字/图例使用Times New Roman；
- 坐标轴4 pt，主刻度与次刻度向内；
- 如果触发兼容降级，输出仍正确且警告已记录；
- 测试不改动用户已有Origin工程。

## 已知兼容措施

- 自动从注册表和常见安装目录中筛选2021–2026b；
- 多版本安装时支持显式指定`Origin64.exe`；
- 使用`ApplicationSI`附加已启动的目标版本；
- 将Python绘图脚本复制到ASCII运行时路径，规避`run -pyf`对中文项目目录的不稳定行为；
- 通过LabTalk字符串变量向已运行Origin传递作业路径和版本；
- 对绘图属性和图片宽度参数提供旧版降级。
