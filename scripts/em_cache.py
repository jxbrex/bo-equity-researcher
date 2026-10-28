#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
em_cache.py — 磁盘缓存原语与分档常量（em_fetch 拆分子模块之一，v4.8.3）

职责：跨进程磁盘缓存的通用 IO（原子写、TTL 判定、键→路径）、缓存 TTL 分档、
tushare 接口 tier 归类，以及 report_rc 跨进程频率预算。普通缓存原语由调用方显式传入
cache_dir / no_cache；本模块不持有模块级可变数据缓存——缓存状态（_CACHE_DIR/_NO_CACHE 等）归属 em_core.py
（v4.10.3 起；test_em_fetch 按 em_core 命名空间 rebind 这些配置须实时生效，
ts_call/get 作为读取者也留在 em_core，调用本模块原语时把当前配置作为参数传入）。
"""

import hashlib
import json
import math
import os
import sys
import time
from contextlib import contextmanager

# ---------------- 缓存分档常量（em_core.py import 拷贝引用） ----------------
# TTL 分档：行情 2h / 财务 12h / 治理 24h（均远小于数据自身更新周期，陈旧风险可控）；
# EM_FETCH_NO_CACHE=1 旁路数据缓存。普通缓存失败静默；report_rc 预算写失败 fail-closed。
# _CACHE_DIR/_NO_CACHE 状态在 em_core.py（test_em_fetch 按 em_core 命名空间 rebind）。
_TTL_QUOTE = 2 * 3600    # 行情（日线收盘级，2h 内唯一风险是盘中跑+收盘后 1h 内重跑，可识别）
_TTL_FIN = 12 * 3600     # 财务（季度更新）
_TTL_GOV = 24 * 3600     # 治理（公告/事件级更新）
_TS_TIER_QUOTE = {"daily", "daily_basic", "adj_factor", "hk_daily", "monthly", "index_daily",
                  "moneyflow", "margin_detail"}
_TS_TIER_GOV = {"pledge_stat", "stk_holdertrade", "repurchase", "fina_audit", "stock_basic",
                "disclosure_date", "stk_holdernumber"}

REPORT_RC_MIN_INTERVAL = 60
REPORT_RC_HOURLY_LIMIT = 10
REPORT_RC_WINDOW = 3600


@contextmanager
def _exclusive_file_lock(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            while True:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _budget_read(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        return []
    except (ValueError, UnicodeError, OverflowError):
        print("⚠️ report_rc 预算文件损坏，按空预算重建", file=sys.stderr)
        return []
    except OSError as exc:
        raise RuntimeError(f"report_rc 预算读取失败: {exc}") from exc
    if not isinstance(raw, list):
        print("⚠️ report_rc 预算结构非法，按空预算重建", file=sys.stderr)
        return []
    values = []
    for value in raw:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                values.append(float(value))
            except (ValueError, OverflowError, TypeError):
                pass
    if len(values) != len(raw):
        print("⚠️ report_rc 预算含非法时间戳，已剔除", file=sys.stderr)
    return values


def _budget_write(path: str, values: list, cache_dir: str) -> None:
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(values, handle)
        os.replace(tmp, path)
    except OSError as exc:
        raise RuntimeError(f"report_rc 预算写入失败，已阻止本次调用: {exc}") from exc


def reserve_report_rc_slot(cache_dir: str, now: float):
    state_path = os.path.join(cache_dir, "report_rc_budget.json")
    lock_path = os.path.join(cache_dir, "report_rc_budget.lock")
    with _exclusive_file_lock(lock_path):
        attempts = _budget_read(state_path)
        valid = [value for value in attempts
                 if math.isfinite(value) and now - REPORT_RC_WINDOW < value <= now + 1]
        if len(valid) != len(attempts):
            print("⚠️ report_rc 预算含非有限或异常未来时间戳，已剔除", file=sys.stderr)
        attempts = sorted(valid)
        if len(attempts) >= REPORT_RC_HOURLY_LIMIT:
            return None
        if attempts and now < attempts[-1] + REPORT_RC_MIN_INTERVAL:
            return attempts[-1] + REPORT_RC_MIN_INTERVAL - now
        attempts.append(float(now))
        _budget_write(state_path, attempts, cache_dir)
        return 0


def dc_path(cache_dir: str, tag: str, key: str) -> str:
    """缓存键 → 磁盘路径（tag 前缀 + key 的 md5 前 16 位）。cache_dir 由调用方传入。"""
    return os.path.join(cache_dir, f"{tag}_{hashlib.md5(key.encode('utf-8')).hexdigest()[:16]}.json")


def dc_read(path: str, ttl: int, no_cache: bool):
    """命中且未过期返回解析值，否则 None。no_cache=旁路开关。"""
    if no_cache:
        return None
    try:
        if time.time() - os.path.getmtime(path) > ttl:
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def dc_write(path: str, val, no_cache: bool, cache_dir: str) -> None:
    """先写临时文件再 replace，避免并发读到写了一半的文件。no_cache=旁路开关。"""
    if no_cache:
        return
    try:
        os.makedirs(cache_dir, exist_ok=True)
        # tmp 名带 PID：并发进程写同一缓存键时互不覆盖（固定 .tmp 会互踩）
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(val, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass
