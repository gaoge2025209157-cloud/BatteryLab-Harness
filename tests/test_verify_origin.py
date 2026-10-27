"""verify_origin.py 的回归测试。

真机验证本身只能由装了 Origin 的人完成，但"验证脚本的判定对不对"必须由测试保证：
否则交付给用户的可能是一个永远报 PASS、或者永远报 FAIL 的脚本。

这里用假 Origin 覆盖五种结局：正常、崩溃降级、状态失败、空白图、版本不符。
"""

import io
import json
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

import verify_origin  # noqa: E402
from electrochem_harness.origin_adapter import (  # noqa: E402
    OriginInstallation,
    OriginNotFound,
    OriginPlotFailed,
    OriginStatus,
)

SOURCE = PROJECT_ROOT / "examples" / "sample_capacity_curve.csv"


def make_png(path, width, height, textured=True):
    """写一个合法 PNG。textured=False 时是纯白图，压出来会非常小。"""

    rows = b""
    for y in range(height):
        row = b"\x00"
        if textured:
            for x in range(width):
                row += bytes(((x * 7 + y * 13) % 256, (x * y) % 256, (y * 3) % 256))
        else:
            row += bytes((255, 255, 255)) * width
        rows += row

    def chunk(tag, payload):
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    Path(path).write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


def fake_origin(job_path, project_root, *, mode="ok", release="2023", **_kwargs):
    """模拟 Origin 侧的行为：按 job 里给出的路径写产物。"""

    if mode == "raise":
        # 真实崩溃时什么都不会产出：没有 status，也没有图。
        raise OriginPlotFailed("模拟：Origin 进程超时退出")

    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    Path(job["project_path"]).write_bytes(b"PK\x03\x04" + b"\x00" * 4096)
    if mode == "tiny":
        make_png(job["curve_png"], 1, 1, textured=False)
        make_png(job["cycling_png"], 1, 1, textured=False)
    else:
        make_png(job["curve_png"], 640, 480)
        make_png(job["cycling_png"], 640, 480)

    status = OriginStatus(
        ok=(mode != "not_ok"),
        project=None if mode == "not_ok" else job["project_path"],
        origin_release=release,
        originpro_version="1.2.3",
        warnings=() if mode == "ok" else ("模拟警告",),
        error="模拟：许可证无效" if mode == "not_ok" else None,
    )
    Path(job["status_path"]).write_text(
        json.dumps(status.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    return status


class JudgementTests(unittest.TestCase):
    """五种结局的判定必须各不相同，否则脚本等于没验。"""

    @classmethod
    def setUpClass(cls):
        cls._temp = tempfile.TemporaryDirectory()
        # gui_controller 会校验 origin_exe 必须真实存在，所以要造一个假的可执行文件。
        exe = Path(cls._temp.name) / "Origin2023" / "Origin64.exe"
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"MZ" + b"\x00" * 512)
        cls.installation = OriginInstallation(exe, "2023", False)

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()

    def _verify(self, mode, release="2023"):
        # 不能包在 with TemporaryDirectory 里：断言要检查产出的文件，
        # 目录必须在断言之后才删，所以交给 addCleanup。
        out = tempfile.mkdtemp(prefix="verify_out_")
        self.addCleanup(shutil.rmtree, out, True)
        launcher = lambda *a, **kw: fake_origin(  # noqa: E731
            a[0], a[1], mode=mode, release=release
        )
        return verify_origin.verify_one(
            PROJECT_ROOT,
            self.installation,
            Path(out),
            source=SOURCE,
            timeout=30,
            launcher=launcher,
        )

    def test_healthy_origin_passes(self):
        result = self._verify("ok")

        self.assertEqual(result.verdict, "PASS", [c.to_dict() for c in result.checks])
        self.assertEqual([c.code for c in result.decisive if not c.ok], [])

    def test_crashed_origin_is_failed_not_passed(self):
        result = self._verify("raise")

        failed = [c.code for c in result.decisive if not c.ok]
        self.assertEqual(result.verdict, "FAIL")
        # 关键：Origin 崩溃时流程会降级继续，必须以"降级记录"判失败，
        # 否则看起来像成功。
        self.assertIn("O-07", failed)
        self.assertIn("build_origin_project", " ".join(result.degradations))

    def test_status_ok_false_is_reported(self):
        result = self._verify("not_ok")

        self.assertEqual(result.verdict, "FAIL")
        self.assertIn("O-02", [c.code for c in result.decisive if not c.ok])

    def test_blank_one_pixel_images_are_rejected(self):
        result = self._verify("tiny")

        self.assertEqual(result.verdict, "FAIL")
        self.assertIn("O-05", [c.code for c in result.decisive if not c.ok])

    def test_version_mismatch_is_rejected(self):
        result = self._verify("ok", release="2025")

        self.assertEqual(result.verdict, "FAIL")
        self.assertEqual(
            [c.code for c in result.decisive if not c.ok], ["O-03"]
        )

    def test_evidence_is_written_even_when_verification_fails(self):
        result = self._verify("raise")

        out = result.output_dir
        self.assertIsNotNone(out)
        self.assertTrue((out / "verification.json").is_file())
        self.assertTrue((out / "verification.md").is_file())
        payload = json.loads((out / "verification.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["release"], "2023")


class PngParsingTests(unittest.TestCase):
    def test_reads_real_dimensions(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ok.png"
            make_png(path, 320, 240)

            self.assertEqual(verify_origin.png_size(path), (320, 240))

    def test_rejects_non_png(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.png"
            path.write_bytes(b"not a png at all")

            self.assertIsNone(verify_origin.png_size(path))

    def test_returns_none_for_missing_file(self):
        self.assertIsNone(verify_origin.png_size(Path("does-not-exist.png")))


class CommandLineTests(unittest.TestCase):
    def test_list_works_without_origin(self):
        with tempfile.TemporaryDirectory() as temp:
            stdout = io.StringIO()
            with patch.object(verify_origin, "scan_installations", return_value=[]):
                with patch("sys.stdout", stdout):
                    code = verify_origin.main(["--list"])

            self.assertEqual(code, 0)
            self.assertIn("未找到", stdout.getvalue())

    def test_missing_origin_exits_with_two_and_speaks_chinese(self):
        with tempfile.TemporaryDirectory() as temp:
            stderr = io.StringIO()
            with patch.object(
                verify_origin,
                "find_origin",
                side_effect=OriginNotFound("No supported Origin installation was found."),
            ):
                with redirect_stderr(stderr):
                    code = verify_origin.main(
                        ["--origin-exe", str(Path(temp) / "Origin64.exe")]
                    )

            self.assertEqual(code, 2)
            message = stderr.getvalue()
            self.assertIn("未找到可用的 Origin 安装", message)
            # 原始英文信息保留在末尾，便于排查，但不再作为唯一提示。
            self.assertIn("No supported Origin installation", message)


class CmdEncodingTests(unittest.TestCase):
    """批处理入口必须是纯 ASCII。

    cmd.exe 按本地代码页（中文 Windows 是 936）解码 .cmd 文件本身，而不是按
    UTF-8。把中文提示写进 .cmd 会变成乱码，乱码片段还会被当成命令执行，用户看到
    的就是一连串"xxx 不是内部或外部命令"。中文提示一律交给 Python 输出——CPython
    在 Windows 通过 Unicode 控制台 API 写屏，不受代码页影响。
    """

    def test_entry_scripts_are_pure_ascii(self):
        for name in ("verify_origin.cmd", "start_gui.cmd"):
            with self.subTest(script=name):
                data = (PROJECT_ROOT / name).read_bytes()
                offenders = [byte for byte in data if byte > 127]
                self.assertEqual(
                    offenders,
                    [],
                    "{} 含 {} 个非 ASCII 字节，cmd.exe 会解码成乱码并当成命令执行".format(
                        name, len(offenders)
                    ),
                )

    def test_entry_script_uses_crlf(self):
        """用了 ``goto`` 的批处理必须是 CRLF 换行。

        .gitattributes 已声明 ``*.cmd text eol=crlf``，但用编辑器直接写文件会绕过
        它。纯 LF 的批处理在部分 Windows 版本上 label 匹配失败，表现为 goto 之后
        整段不执行——症状很像"脚本跑到一半就退了"。
        """

        data = (PROJECT_ROOT / "verify_origin.cmd").read_bytes()
        lf_only = data.count(b"\n") - data.count(b"\r\n")
        self.assertEqual(lf_only, 0, "{} 行只有 LF 换行".format(lf_only))

    def test_launcher_does_not_set_variables_inside_parenthesised_blocks(self):
        """在 ``if (...)`` 块里 set 的变量，块内展开为空，命令会静默失败。"""

        text = (PROJECT_ROOT / "verify_origin.cmd").read_text(encoding="ascii")
        for line in text.splitlines():
            stripped = line.strip().lower()
            # 只看赋值语句本身，注释与 label 不算。
            if stripped.startswith("set ") and "pycmd" in stripped:
                # 赋值必须在 label 之后、而非 if 块内部（缩进即代表块内）。
                self.assertEqual(
                    line,
                    line.lstrip(),
                    "PYCMD 的赋值不应出现在括号块内：{}".format(line),
                )


class TrialDetectionTests(unittest.TestCase):
    """试用版会在每张导出图上平铺 demo 水印。

    自动化链路照样能跑通，但产出的图不能用于论文，所以报告必须点明这一点，
    否则使用者会以为"验证通过 = 图可以直接用"。
    """

    def test_trial_marker_in_install_log(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "InstallLog.txt").write_text(
                "10-21-2026 20:34:51 Install std trial version=243", encoding="ascii"
            )

            self.assertTrue(verify_origin.is_trial_build(Path(temp)))

    def test_missing_install_log_is_not_trial(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(verify_origin.is_trial_build(Path(temp)))

    def test_licensed_install_log_is_not_trial(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "InstallLog.txt").write_text(
                "10-21-2026 20:34:51 Install started", encoding="ascii"
            )

            self.assertFalse(verify_origin.is_trial_build(Path(temp)))


if __name__ == "__main__":
    unittest.main()
