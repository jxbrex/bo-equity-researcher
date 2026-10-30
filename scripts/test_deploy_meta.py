# -*- coding: utf-8 -*-
"""test_deploy_meta.py — deploy.ps1 元数据守卫（v4.11.2 BOM 事故固化）

BOM 断言：PowerShell 5.1 对无 BOM 的 .ps1 按系统 ANSI 代码页解码，中文脚本中的
字节序列会产生歧义引号/括号 → ParserError（v4.11.2 实证：编辑 deploy.ps1 后
BOM 丢失 → MissingEndCurlyBrace，预览直接失败）。任何编辑 deploy.ps1 的工具
都可能剥掉 BOM，本断言把回归钉在 pytest 里。

排除清单断言：/XD golden + /XF 六项（v4.11.2 扩充）是部署体积 -43% 的载体，
参数被误删时此处报警。

Test-DocLines 行为用例（审计#小7）：从 deploy.ps1 源里抽出该函数、指向临时目录
实跑，钉住超长行闸仍在扫描统计（bad>0 必须被输出），防函数被改哑。
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

import pytest

DEPLOY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy.ps1")


def test_bo_identity_matches_deploy_target():
    root = os.path.dirname(os.path.dirname(DEPLOY))
    with open(os.path.join(root, "SKILL.md"), encoding="utf-8-sig") as f:
        skill = f.read()
    with open(DEPLOY, encoding="utf-8-sig") as f:
        deploy = f.read()
    assert re.search(r"(?m)^name: bo-equity-researcher$", skill), \
        "SKILL frontmatter 应使用内部 ID bo-equity-researcher"
    assert r".agents\skills\bo-equity-researcher" in deploy, \
        "部署目标应与内部 ID bo-equity-researcher 一致"


def test_deploy_ps1_has_utf8_bom():
    with open(DEPLOY, "rb") as f:
        head = f.read(3)
    assert head == b"\xef\xbb\xbf", (
        "deploy.ps1 丢失 UTF-8 BOM——PowerShell 5.1 将按 ANSI 解码中文脚本并 "
        "ParserError（v4.11.2 事故实录）。恢复方法：编辑器另存为 UTF-8 with BOM。"
    )


def test_deploy_exclusion_lists_present():
    with open(DEPLOY, encoding="utf-8-sig") as f:
        src = f.read()
    for token in ("golden", "test_*.py", "conftest.py", "CHANGELOG.md",
                  "README.md", "AGENTS.md", "deploy.ps1", "/XF"):
        assert token in src, f"deploy.ps1 排除清单缺 {token}（v4.11.2 扩充项被误删？）"
    assert src.count("/XF") >= 2, "dry-run 与 -Go 两处 robocopy 都应有 /XF"


def test_deploy_doclines_guard_counts_bad_lines():
    """审计#小7：钉住 Test-DocLines 超长行闸仍在扫描统计——临时目录造 1600 字符行 .md，
    函数逻辑必须统计出 bad>0（输出含「超长行 1600 字符」明细与「文档超长行 1 处」汇总）。
    powershell 不可用时跳过，不硬失败。"""
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        pytest.skip("powershell 不可用，跳过 Test-DocLines 行为用例")
    with open(DEPLOY, encoding="utf-8-sig") as f:
        src = f.read()
    m = re.search(r"function Test-DocLines \{.*?\n\}", src, re.S)
    assert m, "deploy.ps1 缺 Test-DocLines 定义（超长行闸被误删？）"
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "references"))
        with open(os.path.join(d, "references", "bad.md"), "w", encoding="utf-8") as f:
            f.write("x" * 1600 + "\n")   # 超 1500 字符闸值一行
        script = ("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
                  + f"$repo = {json.dumps(d)}\n" + m.group(0) + "\nTest-DocLines\n")
        sp = os.path.join(d, "_t.ps1")
        # 必须带 BOM 落盘：PS 5.1 对无 BOM 中文 .ps1 按 ANSI 解码 → ParserError（同 BOM 断言）
        with open(sp, "w", encoding="utf-8-sig", newline="") as f:
            f.write(script)
        r = subprocess.run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", sp],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
    out = r.stdout + r.stderr
    assert r.returncode == 0, f"Test-DocLines 临时脚本失败: {out}"
    assert "超长行 1600 字符" in out, f"超长行明细未输出:\n{out}"
    assert "文档超长行 1 处" in out, f"bad>0 汇总未输出（闸被改哑？）:\n{out}"


def _run_move_legacy(legacy, backup):
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        pytest.skip("powershell 不可用，跳过 Move-LegacyDeployment 行为用例")
    with open(DEPLOY, encoding="utf-8-sig") as f:
        src = f.read()
    m = re.search(r"function Move-LegacyDeployment \{.*?\n\}", src, re.S)
    assert m, "deploy.ps1 缺 Move-LegacyDeployment 定义"
    script = ("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
              + f"$LegacyDir = {json.dumps(legacy)}\n"
              f"$BackupDir = {json.dumps(backup)}\n"
              "$ErrorActionPreference = 'Stop'\n"
              + m.group(0)
              + "\nMove-LegacyDeployment -LegacyDir $LegacyDir -BackupDir $BackupDir\n")
    with tempfile.TemporaryDirectory() as d:
        sp = os.path.join(d, "_move_legacy.ps1")
        with open(sp, "w", encoding="utf-8-sig", newline="") as f:
            f.write(script)
        return subprocess.run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", sp],
                              capture_output=True, text=True, encoding="utf-8", timeout=120)


def test_move_legacy_deployment_preserves_copy():
    with tempfile.TemporaryDirectory() as d:
        legacy = os.path.join(d, "legacy")
        backup = os.path.join(d, "retired", "legacy-backup")
        os.makedirs(legacy)
        marker = os.path.join(legacy, "marker.txt")
        moved_marker = os.path.join(backup, "marker.txt")
        with open(marker, "w", encoding="utf-8") as f:
            f.write("旧部署标记")
        os.chmod(marker, 0o444)
        try:
            r = _run_move_legacy(legacy, backup)
            out = r.stdout + r.stderr
            assert r.returncode == 0, f"只读旧目录迁移失败: {out}"
            assert not os.path.exists(legacy), "迁移后旧目录仍存在"
            with open(moved_marker, encoding="utf-8") as f:
                assert f.read() == "旧部署标记", "备份中的标记文件内容发生变化"
        finally:
            for path in (marker, moved_marker):
                if os.path.exists(path):
                    os.chmod(path, 0o666)


def test_move_legacy_deployment_refuses_overwrite():
    with tempfile.TemporaryDirectory() as d:
        legacy = os.path.join(d, "legacy")
        backup = os.path.join(d, "retired", "legacy-backup")
        os.makedirs(legacy)
        os.makedirs(backup)
        legacy_marker = os.path.join(legacy, "marker.txt")
        backup_marker = os.path.join(backup, "marker.txt")
        with open(legacy_marker, "w", encoding="utf-8") as f:
            f.write("旧部署标记")
        with open(backup_marker, "w", encoding="utf-8") as f:
            f.write("既有备份标记")
        r = _run_move_legacy(legacy, backup)
        out = r.stdout + r.stderr
        assert r.returncode != 0, "备份已存在时迁移必须失败"
        with open(legacy_marker, encoding="utf-8") as f:
            assert f.read() == "旧部署标记", "拒绝覆盖后旧目录内容发生变化"
        with open(backup_marker, encoding="utf-8") as f:
            assert f.read() == "既有备份标记", "既有备份被覆盖或改写"


def test_em_fetch_direct_runner_matches_pytest():
    import sys

    script = os.path.join(os.path.dirname(DEPLOY), "test_em_fetch.py")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    direct = subprocess.run([sys.executable, script], cwd=os.path.dirname(script),
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            env=env, timeout=120)
    collected = subprocess.run([sys.executable, "-m", "pytest", script, "-q", "-p", "no:cacheprovider"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               env=env, timeout=120)
    assert direct.returncode == 0, direct.stdout + direct.stderr
    assert collected.returncode == 0, collected.stdout + collected.stderr

    def passed_count(result):
        output = result.stdout + result.stderr
        match = re.search(r"(\d+) passed", output) or re.search(r"全部 (\d+) 项测试通过", output)
        assert match, f"未找到通过数量: {output[-1000:]}"
        return int(match.group(1))

    assert passed_count(direct) == passed_count(collected)


def _ps_function(src, name):
    start = src.index(f"function {name} ")
    depth = 0
    for index, char in enumerate(src[start:], start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return src[start:index + 1]
    raise AssertionError(f"PowerShell 函数未闭合: {name}")


def _run_deploy_function(repo, dest, rc):
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        pytest.skip("powershell 不可用")
    with open(DEPLOY, encoding="utf-8-sig") as f:
        src = f.read()
        function_src = _ps_function(src, "Invoke-MirroredDeployment")
        show_extra_src = _ps_function(src, "Show-ExtraLines")
    log = os.path.join(repo, "attrib.log")
    script = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
        "$ErrorActionPreference = 'Stop'\n$xd = @(); $xf = @()\n"
        + show_extra_src + "\n"
        f"function attrib {{ Add-Content -Path {json.dumps(log)} -Value ($args -join ' ') }}\n"
        "function robocopy {\n"
        "  if ($args -contains '/L') {\n"
        "    Write-Output '*EXTRA extra.txt'\n"
        "    $global:LASTEXITCODE = 0\n"
        "    return\n"
        "  }\n"
        "  $dest = $args[1]\n"
        "  New-Item -ItemType Directory -Force $dest | Out-Null\n"
        "  Set-Content -Path (Join-Path $dest 'partial.txt') -Value 'partial' -Encoding UTF8\n"
        f"  $global:LASTEXITCODE = {rc}\n"
        "}\n"
        + function_src
        + f"\nInvoke-MirroredDeployment -Repo {json.dumps(repo)} -Dest {json.dumps(dest)}\n")
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "invoke.ps1")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            f.write(script)
        result = subprocess.run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    attrib_log = open(log, encoding="utf-8").read() if os.path.exists(log) else ""
    return result, attrib_log


def test_deploy_failure_restores_backup_and_readonly(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    original = dest / "original.txt"
    original.write_text("original", encoding="utf-8")
    result, log = _run_deploy_function(str(tmp_path), str(dest), 8)
    assert result.returncode != 0, result.stdout + result.stderr
    assert original.read_text(encoding="utf-8") == "original"
    assert not (dest / "partial.txt").exists()
    assert not (tmp_path / "dest.deploy-backup").exists()
    assert "+R" in log


def test_deploy_success_removes_backup_and_readonly(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "original.txt").write_text("original", encoding="utf-8")
    result, log = _run_deploy_function(str(tmp_path), str(dest), 1)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (dest / "partial.txt").exists()
    assert not (tmp_path / "dest.deploy-backup").exists()
    assert "+R" in log


def test_deploy_existing_backup_refuses_without_touching_dest(tmp_path):
    dest = tmp_path / "dest"
    backup = tmp_path / "dest.deploy-backup"
    dest.mkdir()
    backup.mkdir()
    original = dest / "original.txt"
    original.write_text("original", encoding="utf-8")
    result, _ = _run_deploy_function(str(tmp_path), str(dest), 1)
    assert result.returncode != 0
    assert original.read_text(encoding="utf-8") == "original"
    assert not (dest / "partial.txt").exists()
    assert backup.exists()


def test_deploy_go_warns_about_extra_files(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "original.txt").write_text("original", encoding="utf-8")
    result, _ = _run_deploy_function(str(tmp_path), str(dest), 1)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "*EXTRA" in result.stdout, "正式部署必须保留目标侧额外文件提示"


def test_deploy_existing_file_target_is_preserved(tmp_path):
    dest = tmp_path / "dest"
    dest.write_text("original", encoding="utf-8")
    result, _ = _run_deploy_function(str(tmp_path), str(dest), 8)
    assert result.returncode != 0
    assert dest.read_text(encoding="utf-8") == "original"
