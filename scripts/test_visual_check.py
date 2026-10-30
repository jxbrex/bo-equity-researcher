#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_visual_check.py — visual_check 浏览器发现与跳过路径回归（全离线，不启动浏览器）

覆盖 v5.5.2 审计发现：--chrome 显式坏路径原先原样直通 → Popen 抛 FileNotFoundError；
修法 find_chrome 显式分支先验存在性，坏路径返回 None 走统一跳过。main() 无浏览器时
print 跳过语并返回 0（不卡交付）也在此钉住。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import visual_check


def test_find_chrome_explicit_existing(tmp_path):
    """显式 --chrome 路径存在 → 原样直通（既有契约不动）。"""
    fake = tmp_path / "chrome.exe"
    fake.write_bytes(b"")
    assert visual_check.find_chrome(str(fake)) == str(fake)


def test_find_chrome_explicit_missing(tmp_path):
    """显式 --chrome 坏路径 → None（走统一跳过，不再让 Popen 抛 FileNotFoundError）。"""
    assert visual_check.find_chrome(str(tmp_path / "no-such-chrome.exe")) is None


def test_find_chrome_all_candidates_missing(monkeypatch):
    """候选清单全灭（本机无 Chrome/Edge）→ None。"""
    monkeypatch.setattr(visual_check, "CHROME_CANDIDATES", [])
    assert visual_check.find_chrome(None) is None


def test_main_without_browser_skips(monkeypatch, tmp_path, capsys):
    """main() 无浏览器：print 跳过语 + 返回 0（跳过不卡交付）。"""
    page = tmp_path / "r.html"
    page.write_text("<html><body><p>x</p></body></html>", encoding="utf-8")
    monkeypatch.setattr(visual_check, "find_chrome", lambda explicit=None: None)
    monkeypatch.setattr(sys, "argv", ["visual_check.py", str(page)])
    assert visual_check.main() == 0
    assert "跳过" in capsys.readouterr().out


def test_measure_page_forces_render(monkeypatch, tmp_path):
    """v5.8.5：测量页必须注入 content-visibility 强制渲染——模板 v5.8.4 起首屏以下章节
    延迟渲染停在 contain-intrinsic-size 600px 占位高，dump-dom 无滚动场景下裁切误报 +
    折行/溢出失明（宝丰能源 16 条误报实证）。钉住 FORCE_RENDER_CSS 与 measure() 不脱钩。"""
    captured = {}

    def fake_run(chrome, page, work, ready, *flags):
        captured["html"] = page.read_text(encoding="utf-8")
        return ('<div id="visual-check-report">{"vw": 1280, "docH": 1, "hscroll": false,'
                ' "spills": [], "wrapped": [], "clipped": []}</div>')

    monkeypatch.setattr(visual_check, "chrome_run", fake_run)
    r = visual_check.measure("fake-chrome", "<html><body><p>x</p></body></html>",
                             tmp_path, 1280)
    assert "content-visibility: visible !important" in captured["html"]
    assert r["clipped"] == []


def test_main_measurement_failure_is_not_success(monkeypatch, tmp_path, capsys):
    page = tmp_path / "r.html"
    page.write_text("<html><body><p>x</p></body></html>", encoding="utf-8")
    monkeypatch.setattr(visual_check, "find_chrome", lambda explicit=None: "fake-chrome")
    monkeypatch.setattr(visual_check, "measure", lambda *args: {
        "vw": 1280, "docH": 0, "hscroll": False, "spills": [], "wrapped": [],
        "clipped": [], "error": "测量超时/失败"})
    monkeypatch.setattr(sys, "argv", ["visual_check.py", str(page)])
    assert visual_check.main() == 2
    captured = capsys.readouterr()
    assert "未完成" in captured.err and "视觉审计通过" not in captured.out


def test_main_partial_measurement_failure_is_not_success(monkeypatch, tmp_path, capsys):
    page = tmp_path / "r.html"
    page.write_text("<html><body><p>x</p></body></html>", encoding="utf-8")
    monkeypatch.setattr(visual_check, "find_chrome", lambda explicit=None: "fake-chrome")

    def fake_measure(chrome, html, work, width):
        if width == 1280:
            return {"vw": width, "docH": 0, "hscroll": False, "spills": [],
                    "wrapped": [], "clipped": [], "error": "测量超时/失败"}
        return {"vw": width, "docH": 100, "hscroll": False, "spills": [],
                "wrapped": [], "clipped": []}

    monkeypatch.setattr(visual_check, "measure", fake_measure)
    monkeypatch.setattr(sys, "argv", ["visual_check.py", str(page)])
    assert visual_check.main() == 2
    captured = capsys.readouterr()
    assert "未完成" in captured.err and "视觉审计通过" not in captured.out


def test_chrome_run_waits_after_kill(monkeypatch, tmp_path):
    import subprocess

    class FakeProcess:
        def __init__(self, *args, **kwargs):
            self.calls = []
            self.waits = 0

        def terminate(self):
            self.calls.append("terminate")

        def kill(self):
            self.calls.append("kill")

        def wait(self, timeout):
            self.waits += 1
            self.calls.append("wait")
            if self.waits == 1:
                raise subprocess.TimeoutExpired("fake-chrome", timeout)
            return 0

    process = FakeProcess()
    monkeypatch.setattr(visual_check.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(visual_check.time, "time", iter([0, 61]).__next__)
    visual_check.chrome_run("fake-chrome", tmp_path / "page.html", tmp_path, lambda out: False)
    assert process.calls == ["terminate", "wait", "kill", "wait"]


def test_main_ignores_temp_cleanup_errors(monkeypatch, tmp_path):
    import tempfile

    page = tmp_path / "r.html"
    page.write_text("<html><body><p>x</p></body></html>", encoding="utf-8")
    monkeypatch.setattr(visual_check, "find_chrome", lambda explicit=None: "fake-chrome")
    monkeypatch.setattr(visual_check, "measure", lambda *args: {
        "vw": 1280, "docH": 100, "hscroll": False, "spills": [], "wrapped": [], "clipped": []})
    monkeypatch.setattr(sys, "argv", ["visual_check.py", str(page)])
    real_tempdir = tempfile.TemporaryDirectory
    captured = {}

    def fake_tempdir(*args, **kwargs):
        captured.update(kwargs)
        return real_tempdir(*args, **kwargs)

    monkeypatch.setattr(visual_check.tempfile, "TemporaryDirectory", fake_tempdir)
    assert visual_check.main() == 0
    assert captured.get("ignore_cleanup_errors") is True
