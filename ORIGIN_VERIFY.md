# Origin 真机验证包

这个包只做一件事：在**装了 Origin 的电脑**上，确认某个 Origin 版本能不能真的
生成工程文件和图片，并把结论整理成一份可复核的记录。

全程**不联网**，不会把任何实验数据发出去。

## 前提条件

| 项 | 要求 |
|---|---|
| 操作系统 | Windows |
| Python | **3.10 或更新版本**，安装时勾选 `Add python.exe to PATH` |
| Origin | **2021 至 2026b 的 64 位版本，且已激活**（需要能正常打开） |

没有 Python 的话，到 <https://www.python.org/downloads/windows/> 下载安装，
务必勾选 `Add python.exe to PATH`。

## 怎么用

1. 把整个文件夹解压到任意位置，**路径最好不含空格**，例如 `D:\origin-verify`
2. 双击 **`verify_origin.cmd`**
3. 窗口先列出本机找到的 Origin，再逐个版本跑一次完整流程
4. 每个版本约 10–60 秒（含 Origin 启动），**不要关闭窗口**
5. 跑完把 `origin_verification` 整个文件夹发回

## 会看到什么

窗口里是英文的步骤标题（`Step 1 of 2` / `Step 2 of 2`），中文提示由 Python 打印。
这是故意的：`.cmd` 文件若含中文，cmd.exe 会按本地代码页解析成乱码并当成命令执行。

跑完后 `origin_verification\` 下每个版本一个子目录，里面有：

| 文件 | 用途 |
|---|---|
| `verification.md` | **先看这个**，每条检查的 PASS / FAIL 和原因 |
| `verification.json` | 机器可读的同一份结论 |
| `artifacts\` | 产物副本：`.opju`、两张 PNG、`origin_status.json`、报告、绘图 CSV |

## 怎么判断通过

`verification.md` 里 O-01 ～ O-07 **全部 PASS** 才算该版本通过。

其中 **O-07 最关键**：Origin 失败时流程会自动降级并继续，最终状态仍是
`completed_with_warnings`，产物目录里还可能留着上一次运行的文件。所以判定不看
"文件在不在"，而看"有没有 `build_origin_project` 降级记录"。

O-08、O-09 是信息项，记录兼容性警告和兼容表的声称，不参与判定。

## 如果提示"未找到可用的 Origin"

按顺序排查：

1. 确认 Origin 是 **64 位**、版本在 **2021–2026b** 之间。2019、2020 或 2027 不在范围内。
2. 确认安装路径能被找到。默认会扫描 `C:` `D:` `E:` 盘的
   `OriginLab\Origin*\` 和 `\Origin*\` 目录。
3. 如果装在别的盘或自定义目录，直接指定完整路径：

   ```
   python verify_origin.py --origin-exe "D:\我的软件\OriginLab\Origin2023\Origin64.exe"
   ```

   （在包目录里打开命令行执行，注意路径用引号包住）

4. 只想看本机探测到什么，不做任何运行：

   ```
   python verify_origin.py --list
   ```

## 如果卡在某个版本超过 1 分钟

大概率是 Origin 首次启动弹了许可证 / 欢迎 / 更新提示窗口，而自动调用在等它。

**处理办法**：手动打开一次 Origin，走完首次引导（登录、许可证确认、关闭更新提示），
完全退出后再重跑本脚本。

## 常见问题

**Q：会不会改坏我的 Origin 或数据？**
不会。脚本只是读取示例 CSV（包内自带 `examples\sample_capacity_curve.csv`），
在临时运行目录里生成新的工程和图片，不碰你已有的工程文件。

**Q：要不要联网？**
不要。`search_literature` 全程关闭。

**Q：跑完需要发回什么？**
`origin_verification` 整个文件夹。里面不含真实实验数据，只有示例数据生成的产物。
