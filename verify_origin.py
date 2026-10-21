#!/usr/bin/env python3
"""Origin 真机验证：跑一次完整受控流程，逐条自检 Origin 阶段的保证。

为什么要这个脚本
----------------
``origin_compat.json`` 里的 ``locally_validated`` 只能写"真的在某台机器上跑通过"
的版本。靠人工打开界面、看两张图、说一句"看起来正常"，既不可复核，也容易漏掉
"文件存在但内容是白图"这类静默失败。

本脚本把这件事变成可复核的：跑完整六步流程，然后按 O-01～O-08 逐条检查，
产出一份可直接贴进 PR 的验证记录。

用法
----
    py -3 verify_origin.py --list          只列出本机找到的 Origin，不运行
    py -3 verify_origin.py                 自动选最新版本并验证
    py -3 verify_origin.py --all           对找到的每个版本各跑一次
    py -3 verify_origin.py --origin-exe "C:\\Program Files\\OriginLab\\Origin2023\\Origin64.exe"

判定口径
--------
O-01～O-07 全部 PASS 才算该版本通过；O-08 是信息项（记录兼容性警告，不判失败）。
联网检索一律关闭：真机验证只测 Origin，不混入网络不确定性。
"""

import argparse
import json
import os
import platform
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from electrochem_harness.gui_controller import SixStepWizard, WizardError
from electrochem_harness.origin_adapter import (
    OriginError,
    OriginInstallation,
    OriginNotFound,
    detect_release,
    find_origin,
    load_compatibility,
    _filesystem_candidates,
    _registry_candidates,
)
from electrochem_harness.production_registry import ORIGIN_ARTIFACTS

CURVE_CSV = "Origin_充放电曲线数据.csv"
REPORT_MD = "关键参数报告.md"

#: 一个正常导出的图不会小于这个尺寸；低于它基本可以断定是空白图。
MIN_IMAGE_SIDE = 100
#: 低于这个字节数几乎只可能是空图。不能设太高——纯色大图压缩后可能只有几百字节，
#: 设成 2 KB 会把"合格但内容简单"的图误判为失败。
MIN_IMAGE_BYTES = 512
#: 介于两者之间不判失败，只在报告里提示"偏小，请肉眼确认"。
SMALL_IMAGE_BYTES = 4096
#: 含数据的 Origin 工程不会是几百字节的空壳。
MIN_PROJECT_BYTES = 1024


# ---------------------------------------------------------------- 安装探测


def _release_key(release: str) -> Tuple[int, int]:
    text = str(release).strip().lower()
    base = text.rstrip("b")
    try:
        year = int(base)
    except ValueError:
        return (0, 0)
    return (year, 1 if text.endswith("b") else 0)


def scan_installations(
    project_root: Path, search_drives: Sequence[str] = ("C:", "D:", "E:")
) -> List[OriginInstallation]:
    """列出本机所有受支持的 Origin。

    这里直接用适配器的候选扫描函数：``find_origin`` 只返回"得分最高的一个"，
    而真机验证需要"每个版本各跑一次"，所以要全量列出。
    """

    compatibility = load_compatibility(project_root)
    supported = tuple(str(item).lower() for item in compatibility["supported_releases"])
    validated = {str(item).lower() for item in compatibility.get("locally_validated", [])}

    found: Dict[str, OriginInstallation] = {}
    candidates = list(_registry_candidates()) + list(_filesystem_candidates(search_drives))
    for text in candidates:
        path = Path(str(text))
        if not path.is_file():
            continue
        release = detect_release(str(path), supported)
        if release is None:
            continue
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        found[str(resolved)] = OriginInstallation(
            resolved, release, release in validated
        )
    return sorted(found.values(), key=lambda item: _release_key(item.release))


def png_size(path: Path) -> Optional[Tuple[int, int]]:
    """读 PNG 的 IHDR，返回 (宽, 高)；不是合法 PNG 则返回 None。"""

    try:
        with path.open("rb") as handle:
            header = handle.read(24)
    except OSError:
        return None
    if len(header) < 24:
        return None
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    return (width, height)


# ---------------------------------------------------------------- 检查项


@dataclass
class Check:
    code: str
    title: str
    ok: bool
    detail: str
    info: bool = False

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "ok": self.ok,
            "detail": self.detail,
            "info": self.info,
        }


@dataclass
class Verification:
    installation: OriginInstallation
    checks: List[Check] = field(default_factory=list)
    run_state: Optional[str] = None
    run_dir: Optional[Path] = None
    status_payload: Optional[Mapping[str, Any]] = None
    degradations: Tuple[str, ...] = ()
    elapsed: float = 0.0
    error: Optional[str] = None
    output_dir: Optional[Path] = None

    @property
    def decisive(self) -> List[Check]:
        return [check for check in self.checks if not check.info]

    @property
    def passed(self) -> bool:
        return (
            self.error is None
            and bool(self.decisive)
            and all(check.ok for check in self.decisive)
        )

    @property
    def verdict(self) -> str:
        if self.error is not None:
            return "ERROR"
        return "PASS" if self.passed else "FAIL"

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "release": self.installation.release,
            "origin_exe": str(self.installation.path),
            "claimed_validated_by_compat_table": self.installation.locally_validated,
            "verdict": self.verdict,
            "passed": self.passed,
            "error": self.error,
            "run_state": self.run_state,
            "run_dir": None if self.run_dir is None else str(self.run_dir),
            "elapsed_seconds": round(self.elapsed, 2),
            "origin_status": self.status_payload,
            "checks": [check.to_dict() for check in self.checks],
            "output_dir": None if self.output_dir is None else str(self.output_dir),
        }


# ---------------------------------------------------------------- 主流程


def _form_values(source: Path, output_dir: Path, origin_exe: Path) -> Dict[str, Any]:
    return {
        "input_file": str(source),
        "output_dir": str(output_dir),
        # 真机验证只测 Origin；联网会引入超时和对方服务状态，不混进来。
        "search_literature": False,
        "use_origin": True,
        "origin_exe": str(origin_exe),
        "max_literature": 1,
        "battery_system": "Li-S",
        "active_material": "S/C composite",
        "cell_type": "coin cell",
        "counter_electrode": "Li",
        "test_current": "0.2 C",
        "temperature": "25 C",
        "normalization_basis": "sulfur mass",
    }


def _artifact(artifacts: Path, name: str) -> Optional[Path]:
    candidate = artifacts / name
    return candidate if candidate.is_file() else None


def _size_text(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return "无法读取"
    if size >= 1024 * 1024:
        return "{:.1f} MB".format(size / (1024 * 1024))
    return "{:.1f} KB".format(size / 1024.0)


def verify_one(
    project_root: Path,
    installation: OriginInstallation,
    out_root: Path,
    *,
    source: Path,
    timeout: float,
    launcher: Optional[Any] = None,
) -> Verification:
    """对一个 Origin 安装跑完整流程并自检。

    ``launcher`` 只给测试用：注入一个假的 Origin，好在没有装 Origin 的机器上
    验证本脚本的判定逻辑本身是否正确。真机验证永远走默认的 ``launch_origin``。
    """

    verification = Verification(installation=installation)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = out_root / "{}-{}".format(installation.release, stamp)
    out_dir.mkdir(parents=True, exist_ok=True)
    verification.output_dir = out_dir

    started = time.time()
    artifacts: Optional[Path] = None
    try:
        wizard = SixStepWizard(project_root, origin_launcher=launcher)
        wizard.edit_form(
            _form_values(source, out_dir / "work", installation.path)
        )
        preflight = wizard.run_preflight()
        if preflight.blocked:
            blocking = [
                item.get("message", str(item))
                for item in preflight.issues
                if item.get("blocking")
            ]
            raise WizardError("预检查被阻断：" + "；".join(blocking or ["未知原因"]))

        plan = wizard.review_plan()
        plan_text = json.dumps(plan, ensure_ascii=False, default=str)
        verification.checks.append(
            Check(
                "O-01",
                "计划中登记了 build_origin_project",
                "build_origin_project" in plan_text,
                "计划工具：{}".format(
                    [item.get("tool_id", item) if isinstance(item, Mapping) else item
                     for item in plan.get("tools", ())]
                ),
            )
        )

        # 第 4 步：必须先显式进入批准页，再批准——这正是生产链路对"勾选≠批准"的要求。
        wizard.request_approval()
        wizard.approve(list(wizard.required_scopes))
        if not wizard.can_start:
            raise WizardError("批准后仍然无法开始执行（can_start 为假）。")
        verification.run_state = str(wizard.start())
        verification.run_dir = Path(wizard.controller.controlled_run.run_dir)
        artifacts = verification.run_dir / "artifacts"
        if wizard.results is not None:
            verification.degradations = tuple(
                str(item) for item in wizard.results.degradations
            )

        status_path = _artifact(artifacts, "origin_status.json")
        if status_path is not None:
            try:
                verification.status_payload = json.loads(
                    status_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as error:
                verification.status_payload = {"parse_error": str(error)}
    except Exception as error:  # noqa: BLE001 - 任何异常都要变成可复核的结论
        verification.error = "{}: {}".format(type(error).__name__, error)
        verification.elapsed = time.time() - started
        _write_evidence(verification, out_dir, artifacts)
        return verification

    verification.elapsed = time.time() - started

    # ---- O-02 状态文件
    payload = verification.status_payload or {}
    ok_flag = payload.get("ok")
    verification.checks.append(
        Check(
            "O-02",
            "origin_status.json 存在且 ok=true",
            bool(ok_flag) and "parse_error" not in payload,
            "ok={} error={}".format(ok_flag, payload.get("error") or "无"),
        )
    )

    # ---- O-03 版本一致
    reported = str(payload.get("origin_release") or "").strip().lower()
    expected = installation.release.lower()
    verification.checks.append(
        Check(
            "O-03",
            "Origin 自报版本与探测版本一致",
            reported == expected,
            "探测 {} / origin_status 自报 {}".format(
                installation.release, reported or "（缺）"
            ),
        )
    )

    # ---- O-04 工程文件
    project = _artifact(artifacts, "电化学分析.opju")
    project_ok = False
    project_detail = "未生成 电化学分析.opju"
    if project is not None:
        size = project.stat().st_size
        project_ok = size >= MIN_PROJECT_BYTES
        project_detail = "{}（{}）".format(project.name, _size_text(project))
    verification.checks.append(
        Check("O-04", ".opju 工程文件已生成且非空壳", project_ok, project_detail)
    )

    # ---- O-05 两张图
    image_problems: List[str] = []
    image_notes: List[str] = []
    for name in ("充放电曲线.png", "循环性能.png"):
        path = _artifact(artifacts, name)
        if path is None:
            image_problems.append("{} 未生成".format(name))
            continue
        size = path.stat().st_size
        dimensions = png_size(path)
        if dimensions is None:
            image_problems.append("{} 不是合法 PNG".format(name))
            continue
        width, height = dimensions
        note = "{} {}x{} {}".format(name, width, height, _size_text(path))
        if width < MIN_IMAGE_SIDE or height < MIN_IMAGE_SIDE:
            image_problems.append("{} 尺寸过小 {}x{}".format(name, width, height))
        elif size < MIN_IMAGE_BYTES:
            image_problems.append("{} 仅 {}，疑似空白图".format(name, _size_text(path)))
        elif size < SMALL_IMAGE_BYTES:
            note += "（偏小，请肉眼确认非空白）"
        image_notes.append(note)
    verification.checks.append(
        Check(
            "O-05",
            "两张 PNG 可解析且不是空白图",
            not image_problems,
            "；".join(image_problems) if image_problems else "；".join(image_notes),
        )
    )

    # ---- O-06 降级保证：报告与绘图输入仍在
    missing = [
        name
        for name in (REPORT_MD, CURVE_CSV)
        if _artifact(artifacts, name) is None
    ]
    verification.checks.append(
        Check(
            "O-06",
            "报告与绘图 CSV 未被 Origin 阶段破坏",
            not missing,
            "缺失：{}".format("、".join(missing)) if missing else "两者都在",
        )
    )

    # ---- O-07 Origin 阶段是真的跑成功了，而不是"降级掉"了
    #
    # 这是本脚本最关键的一条：Origin 失败时流程会降级并继续，状态是
    # completed_with_warnings，产物目录里可能还留着上次的文件。只看"文件在不在"
    # 会把降级误判成成功，所以必须以"没有 build_origin_project 降级记录"为准。
    state = str(verification.run_state or "").lower()
    origin_degraded = [
        item
        for item in verification.degradations
        if item.startswith("build_origin_project")
    ]
    verification.checks.append(
        Check(
            "O-07",
            "Origin 阶段成功执行、未被降级",
            "failed" not in state and not origin_degraded,
            "最终状态：{}；降级记录：{}".format(
                verification.run_state,
                "；".join(origin_degraded) if origin_degraded else "无",
            ),
        )
    )

    # ---- O-08 兼容性警告（信息项）
    warnings = tuple(payload.get("compatibility_warnings") or ())
    verification.checks.append(
        Check(
            "O-08",
            "兼容性警告已记录",
            True,
            "无警告" if not warnings else "；".join(str(item) for item in warnings),
            info=True,
        )
    )

    # ---- O-09 版本声称与实际一致（信息项，用于纠正兼容表）
    verification.checks.append(
        Check(
            "O-09",
            "兼容表对该版本的声称",
            True,
            "origin_compat.json 已列入 locally_validated"
            if installation.locally_validated
            else "origin_compat.json 尚未列入 locally_validated（本次通过后可加入）",
            info=True,
        )
    )

    _write_evidence(verification, out_dir, artifacts)
    return verification


def _write_evidence(
    verification: Verification, out_dir: Path, artifacts: Optional[Path]
) -> None:
    """把能复核的东西搬到输出目录，再写 json + md。"""

    evidence = out_dir / "artifacts"
    evidence.mkdir(parents=True, exist_ok=True)
    if artifacts is not None and artifacts.is_dir():
        for name in ORIGIN_ARTIFACTS + (REPORT_MD, CURVE_CSV):
            source = artifacts / name
            if source.is_file():
                try:
                    shutil.copy2(source, evidence / name)
                except OSError:
                    pass

    payload = verification.to_dict()
    payload["environment"] = {
        "verified_at": datetime.now().isoformat(timespec="seconds"),
        "host": platform.node(),
        "windows": platform.platform(),
        "python": platform.python_version(),
        "project_root": str(ROOT),
    }
    (out_dir / "verification.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "verification.md").write_text(
        render_report(verification), encoding="utf-8"
    )


def render_report(verification: Verification) -> str:
    installation = verification.installation
    lines = [
        "# Origin 真机验证记录",
        "",
        "| 项 | 值 |",
        "|---|---|",
        "| 结论 | **{}** |".format(verification.verdict),
        "| Origin 版本 | {} |".format(installation.release),
        "| 可执行文件 | `{}` |".format(installation.path),
        "| originpro | {} |".format(
            (verification.status_payload or {}).get("originpro_version", "未上报")
        ),
        "| 运行状态 | {} |".format(verification.run_state or "未开始"),
        "| 耗时 | {:.1f} 秒 |".format(verification.elapsed),
        "| 验证时间 | {} |".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "| 主机 / Python | {} / {} |".format(platform.node(), platform.python_version()),
        "",
    ]

    if verification.error is not None:
        lines += [
            "## 失败原因",
            "",
            "```text",
            verification.error,
            "```",
            "",
        ]

    lines += ["## 自检项", "", "| 项 | 检查 | 结果 | 细节 |", "|---|---|---|---|"]
    for check in verification.checks:
        mark = "PASS" if check.ok else "**FAIL**"
        if check.info:
            mark = "记录"
        detail = check.detail.replace("|", "\\|")
        lines.append(
            "| {} | {} | {} | {} |".format(check.code, check.title, mark, detail)
        )

    warnings = (verification.status_payload or {}).get("compatibility_warnings") or ()
    lines += ["", "## 兼容性警告", ""]
    lines += (
        ["- 无"]
        if not warnings
        else ["- {}".format(str(item)) for item in warnings]
    )

    evidence = None if verification.output_dir is None else verification.output_dir / "artifacts"
    lines += ["", "## 产物", "", "| 文件 | 大小 |", "|---|---|"]
    if evidence is not None and evidence.is_dir():
        for path in sorted(evidence.iterdir()):
            if path.is_file():
                lines.append("| `{}` | {} |".format(path.name, _size_text(path)))
    else:
        lines.append("| （无） | 未采集到产物 |")

    lines += ["", "## 下一步", ""]
    if verification.verdict == "PASS":
        lines += [
            "1. 把 `{}` 加入 `origin_compat.json` 的 `locally_validated`。".format(
                installation.release
            ),
            "2. 打开 `artifacts/` 里的两张图肉眼确认一次：字体没有乱码、坐标轴单位正确。",
            "3. 把本目录（含 `verification.json`、`verification.md`、`artifacts/`）"
            "一起打包归档，作为该版本的验证证据。",
        ]
    else:
        lines += [
            "1. 看上面的「失败原因」或 FAIL 项，定位是环境问题还是代码问题。",
            "2. 环境问题（Origin 打不开、许可证、路径含非 ASCII）重装或换路径后重跑。",
            "3. 代码问题把 `verification.json` 发回，其中 `origin_status.error` "
            "通常带有 Origin 侧的原始报错。",
        ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 命令行


def _print_installations(items: Sequence[OriginInstallation]) -> None:
    if not items:
        print("未找到任何受支持的 Origin（2021–2026b）。")
        print("  如果已安装，请用 --origin-exe 指定 Origin64.exe 的完整路径。")
        return
    print("本机找到 {} 个受支持的 Origin：".format(len(items)))
    print()
    print("  {:<8} {:<12} {}".format("版本", "兼容表声称", "路径"))
    for item in items:
        claim = "已列验证" if item.locally_validated else "未验证"
        print("  {:<8} {:<12} {}".format(item.release, claim, item.path))
    print()
    print("提示：`--all` 会对以上每个版本各跑一次验证。")


def _not_found_hint(error: Optional[BaseException] = None) -> None:
    """把适配器的英文报错翻成下一步能照做的提示。"""

    print("未找到可用的 Origin 安装。", file=sys.stderr)
    print("  支持 2021 至 2026b 的 64 位 Origin（Origin64.exe）。", file=sys.stderr)
    print(
        "  先运行 `verify_origin.py --list` 看本机情况；"
        "或用 `--origin-exe \"路径\\Origin64.exe\"` 指定。",
        file=sys.stderr,
    )
    if error is not None:
        print("  适配器原始信息：{}".format(error), file=sys.stderr)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Origin 真机验证：跑一次完整受控流程并逐条自检。"
    )
    parser.add_argument("--list", action="store_true", help="只列出本机 Origin，不运行")
    parser.add_argument(
        "--all", action="store_true", help="对找到的每个版本各跑一次"
    )
    parser.add_argument("--origin-exe", default=None, help="指定 Origin64.exe")
    parser.add_argument(
        "--out",
        default=None,
        help="输出目录（默认 origin_verification/）",
    )
    parser.add_argument(
        "--sample",
        default=None,
        help="输入数据（默认 examples/sample_capacity_curve.csv）",
    )
    parser.add_argument(
        "--timeout", type=float, default=300.0, help="单次 Origin 超时秒数"
    )
    args = parser.parse_args(argv)

    out_root = Path(args.out).resolve() if args.out else ROOT / "origin_verification"
    source = (
        Path(args.sample).resolve()
        if args.sample
        else ROOT / "examples" / "sample_capacity_curve.csv"
    )

    if args.list:
        _print_installations(scan_installations(ROOT))
        return 0

    if not source.is_file():
        print("输入文件不存在：{}".format(source), file=sys.stderr)
        return 2

    if args.origin_exe:
        try:
            installation = find_origin(ROOT, args.origin_exe)
        except OriginNotFound as error:
            _not_found_hint(error)
            return 2
        targets = [installation]
    elif args.all:
        targets = scan_installations(ROOT)
        if not targets:
            _not_found_hint()
            return 2
    else:
        try:
            targets = [find_origin(ROOT)]
        except OriginNotFound as error:
            _not_found_hint(error)
            return 2

    out_root.mkdir(parents=True, exist_ok=True)
    results: List[Verification] = []
    for installation in targets:
        print("=" * 62)
        print("验证 Origin {} → {}".format(installation.release, installation.path))
        print("=" * 62)
        verification = verify_one(
            ROOT, installation, out_root, source=source, timeout=args.timeout
        )
        results.append(verification)
        for check in verification.checks:
            mark = "记录" if check.info else ("PASS" if check.ok else "FAIL")
            print("  [{}] {} {}".format(mark, check.code, check.title))
            if not check.ok or check.info:
                print("         {}".format(check.detail))
        if verification.error:
            print("  错误：{}".format(verification.error))
        print("  结论：{}（{:.1f} 秒）".format(verification.verdict, verification.elapsed))
        print("  产物：{}".format(verification.output_dir))
        print()

    # 多版本汇总
    if len(results) > 1:
        summary = ["# 多版本验证汇总", "", "| 版本 | 结论 | 耗时 | 输出目录 |", "|---|---|---|---|"]
        for item in results:
            summary.append(
                "| {} | {} | {:.1f}s | `{}` |".format(
                    item.installation.release,
                    item.verdict,
                    item.elapsed,
                    item.output_dir.name if item.output_dir else "",
                )
            )
        passed = [item.installation.release for item in results if item.passed]
        summary += [
            "",
            "通过：{}".format("、".join(passed) if passed else "无"),
            "",
            "把每个通过的版本加入 `origin_compat.json` 的 `locally_validated`。",
        ]
        (out_root / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
        print("汇总：{}".format(out_root / "summary.md"))

    return 0 if all(item.passed for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
