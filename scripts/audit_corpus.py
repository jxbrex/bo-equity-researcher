#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 JSON 清单隔离验收真实报告语料，不写回原件、不移动证据。"""
import argparse
import io
import json
import os
import re
import sys
from contextlib import redirect_stderr
from html.parser import HTMLParser

import render_report


class _ReaderTextParser(HTMLParser):
    _SKIP = {"script", "style", "svg"}
    _BLOCK = {"p", "div", "section", "article", "li", "tr", "h1", "h2", "h3", "h4", "br"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skipped = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self.skipped.append(tag)
        elif not self.skipped and tag in self._BLOCK:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if not self.skipped and tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self.skipped:
            for index in range(len(self.skipped) - 1, -1, -1):
                if self.skipped[index] == tag:
                    del self.skipped[index:]
                    break
        elif not self.skipped and tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skipped:
            self.parts.append(data)


def extract_reader_text(html: str) -> str:
    parser = _ReaderTextParser()
    parser.feed(html)
    parser.close()
    return "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())


def _case_name(name):
    return re.sub(r"[^\w.-]+", "_", str(name)).strip("._") or "case"


def run_manifest(manifest_path: str, out_dir: str) -> list[dict]:
    with open(manifest_path, encoding="utf-8") as fp:
        manifest = json.load(fp)
    base_dir = os.path.dirname(os.path.abspath(manifest_path))
    os.makedirs(out_dir, exist_ok=True)
    results = []
    for case in manifest.get("cases") or []:
        if set(case) - {"name", "fill", "expect", "contains"}:
            raise ValueError(f"清单案例含未知键：{sorted(set(case) - {'name', 'fill', 'expect', 'contains'})}")
        name = str(case["name"])
        expected = case["expect"]
        if expected not in ("pass", "reject"):
            raise ValueError(f"{name} 的 expect 只能是 pass/reject")
        fill_path = case["fill"]
        if not os.path.isabs(fill_path):
            fill_path = os.path.join(base_dir, fill_path)
        fill_path = os.path.abspath(fill_path)
        contains = str(case.get("contains") or "")
        document = None
        error = None
        fatal_error = None
        previous_cwd = os.getcwd()
        warning_buffer = io.StringIO()
        try:
            os.chdir(os.path.dirname(fill_path))
            with redirect_stderr(warning_buffer):
                document = render_report.render_document(fill_path)
        except (ValueError, TypeError) as exc:
            error = str(exc)
        except Exception as exc:
            fatal_error = f"{type(exc).__name__}: {exc}"
        finally:
            os.chdir(previous_cwd)
        warnings = warning_buffer.getvalue()
        sys.stderr.write(warnings)
        warning_hit = bool(contains and contains in warnings)
        actual = "reject" if error is not None or (expected == "reject" and warning_hit) else "pass"
        ok = actual == expected
        detail = error or (warnings if warning_hit else "")
        if fatal_error is not None:
            actual, ok, detail = "error", False, fatal_error
        if expected == "pass" and actual == "pass":
            stem = _case_name(name)
            html_path = os.path.join(out_dir, stem + ".html")
            render_report._write_html(document.html, html_path)
            with open(html_path, encoding="utf-8") as fp:
                final_html = fp.read()
            text_path = os.path.join(out_dir, stem + ".txt")
            with open(text_path, "w", encoding="utf-8") as fp:
                fp.write(extract_reader_text(final_html))
            detail = html_path
            if contains and contains not in final_html:
                ok = False
                detail = f"最终 HTML 缺少预期内容：{contains}"
        elif (expected == "reject" and actual == "reject" and error is not None
              and contains and contains not in error):
            ok = False
            detail = f"拒绝原因缺少预期内容：{contains}；实际：{error}"
        elif expected == "reject" and actual == "pass":
            detail = "预期拒绝，但实际渲染通过"
        results.append({"name": name, "expected": expected, "actual": actual, "ok": ok, "detail": detail})
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as fp:
        json.dump(results, fp, ensure_ascii=False, indent=2)
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    results = run_manifest(args.manifest, args.out)
    for item in results:
        status = "OK" if item["ok"] else "FAIL"
        print(f"{item['name']}: 预期 {item['expected']}，实际 {item['actual']} => {status}；{item['detail']}")
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
