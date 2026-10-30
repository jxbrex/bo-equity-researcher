#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""score_dist.py — 评分分布台账与历史报告去重、分层和新规诊断。"""
import argparse
import calendar
import csv
import hashlib
import json
import os
import re
import statistics
from datetime import date

from extract_review import parse_report_name, norm_code, detect_quality_version
from quality_inputs import fetch_quality_inputs
from quality_rules import evaluate_dimensions, DIM_KEYS, requires_normalized_roic
from scoring import DIMS, DEFAULT_LAYER_SHARE, compute_scores, compute_valuation, compute_valuation_score, _position_steps, _num as sc_num


EVIDENCE_DIR = os.path.join("artifacts", "_quality_review", "evidence")
ARBITRATION_FILE = os.path.join("artifacts", "_quality_review", "arbitration.json")
REVIEW_DECISIONS_FILE = os.path.join("artifacts", "_quality_review", "review_decisions.json")
STATUS_ORDER = ("scorable", "review_only", "unscorable", "conflict", "duplicate", "demo")
DRIVER_STATUS_ALIASES = {
    "已验证": "已验证",
    "已验证（产能/订单落地，非价格因素）": "已验证",
    "已签约背书": "已验证",
    "订单+指引+员工持股考核三重锁定": "已验证",
    "订单与指引双重锁定": "已验证",
    "量已验证、价不计入": "已验证",
    "H1已兑现+10%，全年+2.1%可见度仍高": "已验证",
    "部分兑现": "部分兑现",
    "部分已验证": "部分兑现",
    "已验证过半": "部分兑现",
    "增长方向确定、Q2已兑现": "部分兑现",
    "量增已验证、价格为外部变量": "部分兑现",
    "量已验证、人形半场、Q2放缓": "部分兑现",
    "量已验证、价待验证": "部分兑现",
    "量已验证、价未验证": "部分兑现",
    "量已验证，价未验证": "部分兑现",
    "量已验证、价未验证（毛利率是全年利润决定项）": "部分兑现",
    "量已验证（海普），价占主导未验证": "部分兑现",
    "量已验证，价/毛利未验证": "部分兑现",
    "量已验证，价假设被击穿": "部分兑现",
    "量的驱动已兑现，价未验证": "部分兑现",
    "未兑现": "未验证",
    "未验证": "未验证",
    "未验证（价升量缩）": "未验证",
    "表观路径可达成（H2仅需同比+4.6%），但扣非连续两季负增长（Q1 -14.0%、Q2 -36.0%），非经常性收益不可持续，待Q3验证": "未验证",
    "量的部分已落地（文莱一期满负荷、长丝开工率回升），但未来12个月同比基数已是暴利期，增长故事按周期股口径是空的；量的真实增量（二期）要到2028年底之后": "未验证",
}
STAGE_ALIASES = {
    "growth": "growth", "mature": "mature", "decline": "decline",
    "mature_with_early_ai": "mature",
    "mature_with_growth_segment": "mature",
    "mature_with_growth_segments": "mature",
    "mature_declining": "mature",
    "mixed": "mature",
    "中速存量市场": "mature",
    "低增速存量市场": "mature",
    "中速稳增（天花板清晰）": "mature",
    "中速稳增（非爆发式）": "mature",
    "结构性扩容（总量减速）": "mature",
    "总量见顶的存量市场": "mature",
    "总量成熟+量平价升结构升级": "mature",
}


def _read_json(path):
    return json.load(open(path, encoding="utf-8-sig"))


def _ratio_value(value):
    number = sc_num(value)
    if number is None:
        return None
    if isinstance(value, str) and "%" in value:
        return number / 100
    return number / 100 if number > 1 else number


def _custom_value(value, dim):
    if isinstance(value, list):
        return [_custom_value(item, dim) for item in value if item is not None]
    if not isinstance(value, dict):
        return value
    result = dict(value)
    if result.get("id") is None:
        reason = str(result.get("reason") or "")
        evidence = str(result.get("evidence") or "")
        digest = hashlib.sha256(f"{dim}|{reason}|{evidence}".encode("utf-8")).hexdigest()[:8]
        result["id"] = f"CUSTOM.{dim}.{digest}"
    if result.get("points") is not None:
        result["points"] = sc_num(result["points"])
    return result


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _walk(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"artifacts", "__pycache__", "node_modules"}]
        dirs.sort()
        for name in sorted(files):
            yield os.path.join(base, name)


def _fill_index(root):
    fills, preferred = {}, {}
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "node_modules"}]
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(base, name)
            if name == "_index.jsonl":
                for line in open(path, encoding="utf-8-sig"):
                    try:
                        row = json.loads(line)
                        key = (norm_code(row.get("code")), row.get("date"))
                        preferred.setdefault(key, []).append(row.get("html"))
                    except (ValueError, TypeError):
                        continue
            elif name.startswith("fill_") and name.endswith(".json") and "门禁" not in name and "旧形态" not in name:
                try:
                    fill = _read_json(path)
                    key = (norm_code(fill.get("code")), fill.get("date"))
                    fills.setdefault(key, []).append((path, fill))
                except (ValueError, TypeError, OSError):
                    continue
    return fills, preferred


def _base_row(path):
    normalized_path = re.sub(r"-v\d+\.html$", ".html", path, flags=re.I)
    info = parse_report_name(normalized_path)
    text = open(path, encoding="utf-8", errors="replace").read()
    parts = set(path.lower().split(os.sep))
    name = os.path.basename(path).lower()
    demo_path = ("artifacts" in parts or "公众号发布" in parts
                 or any(part.startswith("preview") for part in parts)
                 or any(part == "demo" or part.endswith("_demo") for part in parts)
                 or name.startswith(("demo", "_demo")))
    if not info or demo_path:
        return {"path": path, "sha256": _sha(path), "status": "demo", "canonical": False,
                "reason": "非正式报告/演示/无渲染标记"}
    company, code, report_date = info["company"], norm_code(info["code"]), info["date"]
    version = detect_quality_version(text, normalized_path)
    marked = "generated by render_report.py" in text
    return {"path": path, "sha256": _sha(path), "company": company, "code": code,
            "report_date": report_date, "quality_version": version, "status": "review_only",
            "canonical": marked or version == "legacy-single-track",
            "reason": "" if marked else "旧版无渲染标记，仅审阅不纳入数值分布", "old_quality": info["quality"],
            "old_dimensions": {}, "new_quality": None, "complete": False,
            "review_status": "", "review_reason": ""}


def _attach_fill(rows, fills):
    html_counts = {}
    for row in rows:
        key = (row.get("code"), row.get("report_date"))
        html_counts[key] = html_counts.get(key, 0) + 1
    for row in rows:
        key = (row.get("code"), row.get("report_date"))
        candidates = fills.get(key) or []
        if candidates:
            report_dir = os.path.dirname(os.path.abspath(row["path"]))
            same_dir = [item for item in candidates
                        if os.path.dirname(os.path.dirname(os.path.abspath(item[0]))) == report_dir]
            if len(same_dir) == 1:
                path, fill = same_dir[0]
            elif len(candidates) == 1 and html_counts[key] == 1:
                path, fill = candidates[0]
            else:
                row["fill_conflict"] = True
                continue
            row["fill_path"], row["fill"] = path, fill
            row["stock_type"] = fill.get("stock_type") or row.get("stock_type") or "未知"
            row["quality_version"] = fill.get("quality_version", row["quality_version"])
            try:
                sc = compute_scores(fill)
                row["old_quality"] = sc["quality"]
                row["old_dimensions"] = sc["adj_scores"]
                row["old_sc"] = sc
            except (ValueError, TypeError, KeyError):
                pass


def _manual_preferred():
    if not os.path.exists(ARBITRATION_FILE):
        return {}
    try:
        raw = _read_json(ARBITRATION_FILE)
        return {(norm_code(key.split("_", 1)[0]), key.split("_", 1)[1]): value
                for key, value in raw.items()}
    except (OSError, ValueError, TypeError):
        return {}


def _arbitrate(rows, preferred):
    manual = _manual_preferred()
    by_hash = {}
    for row in rows:
        if row["status"] != "review_only":
            continue
        if row["sha256"] in by_hash:
            row.update(status="duplicate", canonical=False, reason="字节相同重复")
            continue
        by_hash[row["sha256"]] = row
    groups = {}
    for row in by_hash.values():
        groups.setdefault((row.get("code"), row.get("report_date")), []).append(row)
    for key, group in groups.items():
        if len(group) == 1:
            continue
        html_names = preferred.get(key) or []
        chosen = None
        manual_name = (manual.get(key) or {}).get("html")
        if manual_name:
            matches = [row for row in group if os.path.basename(row["path"]) == manual_name]
            chosen = matches[0] if matches else False
        for name in (reversed(html_names) if chosen is None else []):
            matches = [row for row in group if os.path.basename(row["path"]) == name]
            if matches:
                chosen = matches[0]
                break
        if chosen is None:
            with_fill = [row for row in group if row.get("fill")]
            if len(with_fill) == 1:
                chosen = with_fill[0]
        if chosen is None:
            for row in group:
                row.update(status="conflict", canonical=False, reason="同代码同日期内容冲突")
        else:
            for row in group:
                if row is not chosen:
                    row.update(status="duplicate", canonical=False, reason="同日非首选版本")


def _profile(row, context):
    fill = row.get("fill") or {}
    stock_type = (context or {}).get("stock_type") or fill.get("stock_type") or row.get("stock_type") or ""
    industry = (context or {}).get("industry_profile") or row.get("industry_profile") or fill.get("industry_profile")
    if not industry:
        if "银行" in stock_type:
            industry = "financial_bank"
        elif "保险" in stock_type:
            industry = "financial_insurance"
        elif "证券" in stock_type or "券商" in stock_type:
            industry = "financial_broker"
        elif "未盈利" in stock_type or "管线" in stock_type:
            industry = "pre_profit"
        elif "困境反转" in stock_type:
            industry = "turnaround"
        else:
            industry = "generic"
    return {"stock_type": stock_type, "industry_profile": industry,
            "growth_tier": (context or {}).get("growth_tier", fill.get("growth_tier")),
            "report_date": row["report_date"]}


def _evidence_day(value):
    if re.fullmatch(r"\d{4}-\d{2}", value):
        year, month = map(int, value.split("-"))
        return date(year, month, calendar.monthrange(year, month)[1])
    return date.fromisoformat(value)


def _evidence(row, evidence_dir):
    path = os.path.join(evidence_dir, f"{row['code']}_{row['report_date']}.json")
    if not os.path.exists(path):
        return None, None
    payload = _read_json(path)
    if payload.get("report_date") != row["report_date"]:
        raise ValueError("证据报告日与目标报告不一致")
    specs = {}
    for dim, facts in (payload.get("facts") or {}).items():
        if dim == "custom":
            continue
        if facts is None:
            specs[dim] = None
            continue
        specs[dim] = {}
        for name, item in facts.items():
            if item is None:
                specs[dim][name] = None
                continue
            if name == "custom":
                raw_custom = item if "value" not in item else item["value"]
                source = item.get("source_excerpt") or (
                    raw_custom.get("evidence") if isinstance(raw_custom, dict) else "")
                evidence_date = item.get("evidence_date", row["report_date"])
                try:
                    evidence_day = _evidence_day(str(evidence_date or ""))
                except ValueError:
                    raise ValueError(f"{dim}.{name} 的证据日缺失或非法: {evidence_date!r}") from None
                if not str(source or "").strip():
                    raise ValueError(f"{dim}.{name} 缺少来源摘要")
                if evidence_day > date.fromisoformat(row["report_date"]):
                    raise ValueError(f"{dim}.{name} 的证据日晚于报告日")
                specs[dim][name] = _custom_value(raw_custom, dim)
                continue
            evidence_date = str(item.get("evidence_date") or "")
            try:
                evidence_day = _evidence_day(evidence_date)
            except ValueError:
                raise ValueError(f"{dim}.{name} 的证据日缺失或非法: {evidence_date!r}") from None
            if not str(item.get("source_excerpt") or "").strip():
                raise ValueError(f"{dim}.{name} 缺少来源摘要")
            if evidence_day > date.fromisoformat(row["report_date"]):
                raise ValueError(f"{dim}.{name} 的证据日晚于报告日")
            if name in ("roic", "wacc", "incremental_roic"):
                specs[dim][name] = _ratio_value(item.get("value"))
            elif name == "driver_status":
                value = item.get("value")
                specs[dim][name] = DRIVER_STATUS_ALIASES.get(value, value)
            elif name == "stage":
                value = item.get("value")
                specs[dim][name] = STAGE_ALIASES.get(value, value)
            else:
                specs[dim][name] = item.get("value")
    return specs, payload.get("context")


def _old_position(row):
    fill = row.get("fill")
    if not fill:
        return None, None, None
    try:
        calc = compute_valuation(fill)
        vc = compute_valuation_score(calc, fill.get("valuation_inputs"), fill.get("gap_tier"))
        if not vc:
            return None, None, None
        sc = row.get("old_sc") or compute_scores(fill)
        position = _position_steps(sc["quality"], vc["score"], calc, sc["red_flag"],
                                   vc.get("floor_uplift"))[0]
        return position, calc, vc
    except (ValueError, TypeError, KeyError, ZeroDivisionError):
        return None, None, None


def _apply_critical(position, critical):
    if not critical:
        return position
    return {"重仓 ≤20%": "标准仓 ≤10%", "标准仓 ≤10%": "轻仓 ≤5%", "轻仓 ≤5%": "观察池"}.get(position, position)


def _band(score):
    return "好公司" if score >= 7 else "中上" if score >= 5.5 else "一般" if score >= 4 else "回避"


def _merge_evidence(fetched, evidence):
    if not isinstance(evidence, dict):
        return fetched
    merged = dict(fetched)
    for key, value in evidence.items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_evidence(merged[key], value)
        else:
            merged[key] = value
    return merged


def _score_row(row, evidence_dir, fetch_missing):
    if row["status"] != "review_only":
        return
    try:
        specs, evidence_context = _evidence(row, evidence_dir)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        row.update(status="unscorable", reason=str(exc))
        return
    if specs is None:
        row["complete"] = False
        row["reason"] = "缺少九维历史证据"
        return
    profile = _profile(row, evidence_context)
    if profile["stock_type"]:
        row["stock_type"] = profile["stock_type"]
    row["industry_profile"] = profile["industry_profile"]
    weights = {key: float((row.get("fill", {}).get("weights") or {}).get(key, default))
               for key, _layer, _name, default in DIMS}
    layer_share = (row.get("fill", {}).get("layer_share") or DEFAULT_LAYER_SHARE)
    context = dict(profile, weights=weights, layer_share=layer_share)
    try:
        preliminary = evaluate_dimensions(specs, context)
    except (ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
        row.update(status="unscorable", reason=str(exc))
        return
    if fetch_missing:
        for dim in ("1D", "1F"):
            if preliminary["dimensions"][dim]["status"] == "missing":
                fetched = fetch_quality_inputs(row["code"], row["fill"].get("secucode") if row.get("fill") else None,
                                               row["report_date"], profile)
                if fetched.get("status") not in ("ok", "partial"):
                    continue
                historical = dict(specs.get(dim) or {})
                if (dim == "1F" and requires_normalized_roic(profile)
                        and fetched[dim].get("roic_basis") == "normalized"
                        and historical.get("roic_basis") != "normalized"):
                    for key in ("roic", "roic_period_months", "roic_basis"):
                        historical.pop(key, None)
                specs[dim] = _merge_evidence(fetched[dim], historical)
    try:
        result = evaluate_dimensions(specs, context)
    except (ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
        row.update(status="unscorable", reason=str(exc))
        return
    row["score_inputs"] = specs
    row["complete"] = result["complete"]
    row["new_dimensions"] = {key: result["dimensions"][key]["final"] for key in DIM_KEYS}
    row["dimension_results"] = result["dimensions"]
    row["critical_weaknesses"] = result["critical_weaknesses"]
    if not result["complete"] or result["quality"] is None:
        reasons = [f"{key}: {result['dimensions'][key].get('missing_reason', '必需证据不完整')}"
                   for key in DIM_KEYS if result["dimensions"][key]["status"] != "ok"]
        row.update(status="unscorable", reason="；".join(reasons) or "九维必需证据不完整")
        return
    row["new_quality"] = result["quality"]
    old_position, calc, vc = _old_position(row)
    new_position = None
    if vc:
        sc = row["old_sc"]
        new_position = _position_steps(row["new_quality"], vc["score"], calc, sc["red_flag"],
                                       vc.get("floor_uplift"))[0]
        new_position = _apply_critical(new_position, row["critical_weaknesses"])
    row["old_position"], row["new_position"] = old_position, new_position
    row["position_change"] = old_position != new_position if old_position and new_position else None
    row["diagnostic_delta"] = round(row["new_quality"] - row["old_quality"], 2)
    row["delta_meaning"] = "rule_diagnostic_not_company_change"
    row["band_migration"] = f"{_band(row['old_quality'])}→{_band(row['new_quality'])}"
    row["status"] = "scorable"
    row["reason"] = ""


def _manual_reviews():
    if not os.path.exists(REVIEW_DECISIONS_FILE):
        return {}
    try:
        raw = _read_json(REVIEW_DECISIONS_FILE)
        return {(norm_code(key.split("_", 1)[0]), key.split("_", 1)[1]): value
                for key, value in raw.items()}
    except (OSError, ValueError, TypeError, IndexError):
        return {}


def scan_reports(root: str, fetch_missing: bool = False, evidence_dir: str = None) -> list:
    """扫描正式报告，仲裁重复/冲突后按证据完整性返回逐份诊断。"""
    evidence_dir = evidence_dir or EVIDENCE_DIR
    fills, preferred = _fill_index(root)
    reviews = _manual_reviews()
    rows = []
    for path in _walk(root):
        if path.lower().endswith(".html"):
            rows.append(_base_row(path))
    _attach_fill(rows, fills)
    _arbitrate(rows, preferred)
    for row in rows:
        if row.get("fill_conflict"):
            row.update(status="conflict", canonical=False, reason="同代码同日期 fill 归属冲突")
        _score_row(row, evidence_dir, fetch_missing)
        decision = reviews.get((row.get("code"), row.get("report_date")))
        if decision:
            row["review_status"] = decision.get("review_status", "")
            row["review_reason"] = decision.get("review_reason", "")
        elif row["status"] in ("review_only", "unscorable"):
            row["review_status"] = "unscorable"
            row["review_reason"] = row.get("reason") or "缺少可复算证据"
    return rows


def _pct(values, q):
    values = sorted(values)
    pos = (len(values) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def _dist(rows):
    groups = {}
    for row in rows:
        if (row["status"] not in ("scorable", "review_only", "unscorable") or not row["canonical"]
                or row["quality_version"] == "legacy-single-track"):
            continue
        stock_type = row.get("stock_type") or "未知"
        series = [("old", row["quality_version"], row["old_quality"], row.get("old_dimensions") or {})]
        if row["status"] == "scorable":
            series.append(("v2", 2, row["new_quality"], row.get("new_dimensions") or {}))
        for label, version, quality, dimensions in series:
            groups.setdefault((label, version, stock_type, "quality"), []).append(quality)
            for key, value in dimensions.items():
                if value is not None:
                    groups.setdefault((label, version, stock_type, key), []).append(value)
    out = []
    for (label, version, stock_type, dimension), values in sorted(groups.items()):
        out.append({"series": label, "quality_version": version, "stock_type": stock_type,
                    "dimension": dimension, "count": len(values), "median": round(statistics.median(values), 2),
                    "p10": round(_pct(values, 0.1), 2), "p90": round(_pct(values, 0.9), 2),
                    "ge8": sum(v >= 8 for v in values), "le3": sum(v <= 3 for v in values)})
    return out


def summarize(rows):
    counts = {status: sum(row["status"] == status for row in rows) for status in STATUS_ORDER}
    migrations = [{key: row.get(key) for key in ("company", "code", "report_date", "old_quality",
                  "new_quality", "diagnostic_delta", "delta_meaning", "band_migration", "old_position",
                  "new_position", "position_change")}
                 for row in rows if row["status"] == "scorable"]
    drift = []
    by_company = {}
    for row in rows:
        if row["status"] == "scorable":
            by_company.setdefault(row["code"], []).append(row)
    for company_rows in by_company.values():
        company_rows.sort(key=lambda row: row["report_date"])
        for previous, current in zip(company_rows, company_rows[1:]):
            delta = round(current["new_quality"] - previous["new_quality"], 2)
            if abs(delta) > 0.5:
                drift.append({"code": current["code"], "from": previous["report_date"],
                              "to": current["report_date"], "delta": delta,
                              "meaning": "same_rule_quality_drift"})
    peer_reversals = []
    latest = {}
    for row in rows:
        if row["status"] == "scorable":
            current = latest.get(row["code"])
            if current is None or row["report_date"] > current["report_date"]:
                latest[row["code"]] = row
    peer_groups = {}
    for row in latest.values():
        peer_groups.setdefault(_profile(row, None)["industry_profile"], []).append(row)
    for profile, group in peer_groups.items():
        if len(group) < 2:
            continue
        old_order = [row["company"] for row in sorted(group, key=lambda row: row["old_quality"], reverse=True)]
        new_order = [row["company"] for row in sorted(group, key=lambda row: row["new_quality"], reverse=True)]
        if old_order != new_order:
            peer_reversals.append({"basis": "latest_per_company_cross_section", "industry_profile": profile,
                                   "old_order": old_order, "new_order": new_order,
                                   "report_dates": {code: row["report_date"] for code, row in
                                                    sorted((row["code"], row) for row in group)}})
    return {"counts": counts, "distributions": _dist(rows), "migrations": migrations,
            "same_company_drift": drift, "peer_reversals": peer_reversals}


def _write_csv(path, fields, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_review(rows: list, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    _write_csv(os.path.join(out_dir, "manifest.csv"),
               ["path", "sha256", "company", "code", "report_date", "status", "canonical", "reason",
                "quality_version"], rows)
    _write_csv(os.path.join(out_dir, "cases.csv"),
               ["company", "code", "report_date", "old_quality", "new_quality", "diagnostic_delta",
                "delta_meaning", "band_migration", "old_position", "new_position", "position_change",
                "status", "reason", "review_status", "review_reason", "path"], rows)
    coverage = []
    for row in rows:
        for key in DIM_KEYS:
            result = (row.get("dimension_results") or {}).get(key) or {}
            coverage.append({"company": row.get("company"), "code": row.get("code"),
                             "report_date": row.get("report_date"), "dimension": key,
                             "status": result.get("status", row["status"]),
                             "reason": result.get("missing_reason", row.get("reason", ""))})
    _write_csv(os.path.join(out_dir, "coverage.csv"),
               ["company", "code", "report_date", "dimension", "status", "reason"], coverage)
    chains = [{key: row.get(key) for key in ("company", "code", "report_date", "old_quality", "new_quality",
               "old_position", "new_position", "score_inputs", "dimension_results", "critical_weaknesses",
               "review_status", "review_reason")}
              for row in rows if row["status"] == "scorable"]
    with open(os.path.join(out_dir, "score_chains.json"), "w", encoding="utf-8") as handle:
        json.dump(chains, handle, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as handle:
        json.dump(summarize(rows), handle, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--evaluate-v2", action="store_true")
    parser.add_argument("--fetch-missing", action="store_true")
    parser.add_argument("--evidence-dir", default=EVIDENCE_DIR)
    parser.add_argument("--out")
    args = parser.parse_args()
    rows = scan_reports(args.root, fetch_missing=args.fetch_missing, evidence_dir=args.evidence_dir)
    if args.out and args.evaluate_v2:
        write_review(rows, args.out)
    elif args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump(summarize(rows), handle, ensure_ascii=False, indent=2)
    else:
        print(json.dumps(summarize(rows), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
