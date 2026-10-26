#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_valuation.py — 估值结构化校验域（v5.8.3 自 validate.py 按域拆分）。

内容：valuation_inputs 四件套、三情景结构（valuation_scenarios）、赔率地板
（odds_floor）、估值锚纪律（anchor_discipline/blind_fly）、Hero 互查
（hero_cross/hero_band_claims）、thesis 手写价一致性、DCF 双卡，
及 _fin_subclass/_discount_premium_cap 股权成本参考带工具。
契约：raise = 硬拒渲染；warns.append = 软告警。
"""
import re
from scoring import (
    _num,
    _scenario_numbers,
    _plain_text,
    _SCENARIO_NAMES,
    _parse_prev_scenarios,
    _parse_horizon_months,
    REGIME_DEV_THRESHOLD,
    regime_scale_devs)
from validate import (
    _scenario_by_key,
    _normalize_stock_type,
    _resolve_type_tier,
    _anchor_unanchored_type)


def _check_valuation_inputs(fill: dict) -> None:
    """valuation_inputs 必填（估值分强制脚本化，四键缺一不可）。"""
    vi = fill.get("valuation_inputs")
    if not isinstance(vi, dict):
        raise ValueError('valuation_inputs 为必填字段：{"pe_ttm":…, "pe_band":[低,高], '
                         '"div_yield":…, "risk_free":…}（估值分由脚本四件套计算，不再接受手填）')
    miss_vi = [k for k in ("pe_ttm", "pe_band", "div_yield", "risk_free") if k not in vi]
    if miss_vi:
        raise ValueError(f"valuation_inputs 缺键: {miss_vi}（四键必填：pe_ttm / pe_band / div_yield / risk_free）")


def _check_valuation_scenarios(fill: dict, warns: list) -> None:
    """valuation 结构化三情景必填且完整（每情景：profit+PE 区间 或 mcap 市值区间 + horizon）。
    v4.11.1（审核 D2）：增跨情景顺序硬校验（pess.mid ≤ base.mid ≤ opt.mid，倒挂拒渲染）——
    旧版只校验单情景内部区间，跨档倒挂只告警不拒，负离散度还会被决策链误判为
    「低不确定性」上浮一档；docstring 承诺的「校验层拒渲染」此前未覆盖跨情景路径。
    v4.11.1（审核 D1）：profit+pe 口径负 profit 告警不拒（困境反转/未盈利应走正常化利润
    或 mcap 口径，提示模型确认口径）。"""
    v = fill.get("valuation")
    if not isinstance(v, dict) or not v.get("scenarios"):
        raise ValueError("valuation 为必填字段：结构化三情景假设（shares / horizon / scenarios），"
                         "目标价与估值分全部由脚本计算")
    shares_n = _num(v.get("shares"))
    if shares_n is None or shares_n <= 0:
        raise ValueError("valuation.shares 缺失、非法或 ≤0（总股本，亿股，必须为正数）")
    skeys = set()
    modes = set()
    mids = {}
    for s in v.get("scenarios") or []:
        skey = str(s.get("key") or "").lower()
        if skey in skeys:
            # F6：重复 key 拒渲染——双 pess 曾使地板门禁（next() 首个）与计算层（by_key 末个）
            # 口径分裂，重复键没有合法语义
            raise ValueError(f"valuation.scenarios key 重复: {skey!r}——同一情景只许一条，"
                             f"重复键会让地板门禁与估值计算取到不同情景（口径分裂），请去重后重渲")
        skeys.add(skey)
        slab = s.get("label") or s.get("key") or "?"
        # 三组数值机械解析与 compute_valuation 共用（_scenario_numbers），口径唯一
        profit, pe_lo, pe_hi, mc_lo, mc_hi = _scenario_numbers(s)
        has_mc = mc_lo is not None and mc_hi is not None
        has_profit = profit is not None
        if has_mc and has_profit:
            raise ValueError(f"valuation.scenarios[{slab}] 口径冲突：profit+pe 与 mcap 同情景只能二选一")
        if has_mc:
            # 市值口径（NAV/rNPV/SOTP 行业附录）：mcap = [低, 高] 目标总市值（亿元）
            if mc_lo <= 0 or mc_hi < mc_lo:
                raise ValueError(f"valuation.scenarios[{slab}] mcap 区间非法（mcap: [低, 高]，亿元，需 0<低≤高）")
            modes.add("mcap")
            mids[str(s.get("key") or "").lower()] = (mc_lo + mc_hi) / 2 / shares_n
        else:
            if not has_profit:
                raise ValueError(f"valuation.scenarios[{slab}] 缺净利假设（profit，归母净利亿元）"
                                 f"或目标市值区间（mcap: [低, 高]，亿元）")
            if pe_lo is None or pe_hi is None:
                raise ValueError(f"valuation.scenarios[{slab}] 缺 PE 区间（pe: [低, 高]）")
            # 与 mcap 侧对称的区间校验：倒挂（高<低）或非正值一律拒渲染
            if pe_lo <= 0 or pe_hi < pe_lo:
                raise ValueError(f"valuation.scenarios[{slab}] PE 区间非法（pe: [低, 高]，需 0<低≤高）")
            if profit < 0:
                warns.append(f"valuation.scenarios[{slab}] profit={profit:g} 为负：困境反转/未盈利标的"
                             f"请确认口径——profit+pe 口径应用正常化利润，原始亏损口径请改 mcap 市值区间")
            modes.add("pe")
            mids[str(s.get("key") or "").lower()] = profit * (pe_lo + pe_hi) / 2 / shares_n
        if not str(s.get("horizon") or v.get("horizon") or "").strip():
            raise ValueError(f"valuation.scenarios[{slab}] 缺时间维度（horizon，可放情景级或 valuation 级）")
    _check_scenario_horizons(fill, warns)
    if len(modes) > 1:
        raise ValueError("valuation.scenarios 口径混用：profit+pe 与 mcap 三情景必须统一口径")
    if not {"pess", "base", "opt"} <= skeys:
        raise ValueError(f"valuation.scenarios 必须含 pess/base/opt 三情景，当前只有: {sorted(skeys)}")
    # 跨情景顺序：悲观中枢 ≤ 基础中枢 ≤ 乐观中枢（相等允许——三情景同值是合法的极端保守写法）
    if {"pess", "base", "opt"} <= set(mids):
        if mids["pess"] > mids["base"] or mids["base"] > mids["opt"]:
            raise ValueError(f"valuation 三情景中枢跨档倒挂：悲观 {mids['pess']:.2f} / 基础 {mids['base']:.2f} / "
                             f"乐观 {mids['opt']:.2f}（目标价口径，需 悲观≤基础≤乐观）——请检查各情景 "
                             f"profit/pe/mcap 假设是否填反（倒挂会产生负离散度假信号，污染仓位决策链）")


def _check_scenario_horizons(fill: dict, warns: list) -> None:
    """新报告的三情景共用单一明确期限；旧报告的混用/区间期限只告警兼容。"""
    v = fill.get("valuation") or {}
    parsed = [(str(s.get("horizon") or v.get("horizon") or "").strip(),
               _parse_horizon_months(s.get("horizon") or v.get("horizon"), strict=True))
              for s in v.get("scenarios") or []]
    strict_date = str(fill.get("date") or "") >= "2026-10-26"
    invalid = [raw for raw, months in parsed if months is None]
    if invalid:
        kind = "区间期限" if any(re.search(r"\d\s*[-–—~～]\s*\d", raw) for raw in invalid) else "非法期限"
        msg = f"估值情景存在{kind}（{'、'.join(invalid)}）：只接受单一年/月数值，且三情景须同一时间尺"
        if strict_date:
            raise ValueError(msg)
        warns.append(f"旧报告兼容：{msg}；本版仍按原计算口径，后续新报告会拒渲染")
        return
    months = {round(months, 8) for _raw, months in parsed}
    if len(months) > 1:
        msg = f"三情景期限不一致（{'、'.join(raw for raw, _months in parsed)}）：中枢、赔率与离散度必须使用同一时间尺"
        if strict_date:
            raise ValueError(msg)
        warns.append(f"旧报告兼容：{msg}；后续新报告会拒渲染")


def _check_odds_floor(fill: dict, warns: list, calc=None) -> None:
    """v5.0 机制三（赔率 ∞ 收紧·地板分级）：悲观下限 ≥ 现价（即 compute_valuation 赔率 ∞
    条件，down = price − pess_low ≤ 0）时，pess 情景必须带 floor 证据对象且托得住下限——
    floor 存在、type ∈ {net_cash, dividend}、evidence 非空、value ≥ 悲观下限×0.99
    （「悲观下限 ≤ 证据地板值」容差 1%）；任一不满足 → 拒渲染。
    floor 存在但赔率有限（下限 < 现价）→ 软告警（此时 floor 无作用）。
    挂载在 _check_valuation_scenarios 之后：shares/scenarios 合法性已由前者硬拒，
    这里取不到数时静默跳过（不重复报错）。"""
    v = fill.get("valuation")
    if not isinstance(v, dict):
        return
    # F17：floor 是悲观情景（pess）子键——写在 base/opt 不生效，软告警提示挪位
    for s in v.get("scenarios") or []:
        k = str((s or {}).get("key") or "").lower()
        if k != "pess" and isinstance((s or {}).get("floor"), dict):
            warns.append(f"valuation.scenarios[{k or '?'}] 含 floor 子键：floor 是悲观情景子键，"
                         f"写错位置不生效——请移到 pess 情景或删除")
    price = _num(fill.get("price"))
    shares = _num(v.get("shares"))
    if price is None or shares is None or shares <= 0:
        return
    pess = _scenario_by_key(v.get("scenarios"), "pess")
    if not pess:
        return
    # 悲观下限与 compute_valuation 同源（v5.1.5 热核 P0-5 公式双写收敛）：有 calc 直取
    # pess 行 low；calc 为 None（纯 --check 无估值输入路径）按同公式复算兜底
    if calc is not None:
        row = next((r for r in calc.get("rows") or [] if r.get("key") == "pess"), None)
        if row is None:
            return
        low = row["low"]
    else:
        profit, pe_lo, _pe_hi, mc_lo, _mc_hi = _scenario_numbers(pess)
        if mc_lo is not None:
            low = mc_lo / shares
        elif profit is not None and pe_lo is not None:
            low = profit * pe_lo / shares
        else:
            return
    floor = pess.get("floor")
    if low < price:
        if floor:
            warns.append(f"valuation.scenarios[悲观].floor 在赔率有限时无作用"
                         f"（悲观下限 {low:g} < 现价 {price:g}），可删——"
                         f"floor 只在悲观下限 ≥ 现价（赔率 ∞）时生效")
        return
    why = None
    if not isinstance(floor, dict):
        why = "floor 字段缺失"
    else:
        ftype = str(floor.get("type") or "").strip()
        fvalue = _num(floor.get("value"))
        fevidence = str(floor.get("evidence") or "").strip()
        if ftype not in ("net_cash", "dividend"):
            why = f"floor.type 非法: {floor.get('type')!r}（只接受 net_cash 净现金 / dividend 保底分红折现）"
        elif not fevidence:
            why = "floor.evidence 为空（须写明地板值推导，如「净现金123亿÷总股本10亿」）"
        elif fvalue is None or fvalue < low * 0.99:
            why = f"floor.value {floor.get('value')!r} 托不住悲观下限 {low:g}（须 ≥ 下限×0.99，容差 1%）"
    if why:
        raise ValueError(f"悲观下限 {low:g} 不低于现价 {price:g}（≥，含相等边界）但地板证据缺失/不足（{why}），"
                         f"赔率 ∞ 不予认定；请下修悲观情景或补 floor 字段"
                         f'（pess 情景加 "floor": {{"type":"net_cash"/"dividend",'
                         f'"value":元/股,"evidence":"地板值推导"}}）')


# v5.1.0 估值锚纪律一：PE 带跨版移动的增量证据类型白名单
_ANCHOR_EVIDENCE_TYPES = ("基本面", "价格", "卖方观点", "市场参数")


def _check_anchor_discipline(fill: dict, warns: list) -> None:
    """v5.1.0 估值锚纪律（恒瑞 2026-09 实证：两版报告间无新增基本面证据——中报对两版
    均为存量——悲观 PE 带却 35-40→26-32，驱动量只有股价与卖方研报，循环论证）：
    ①回测模式 prev.scenarios 必填（锚移动台账数据源，照抄 extract_review 输出禁手改）；
    ②增量证据锁死：基础情景 PE 带相对上版移动 → valuation.pe_band_evidence 必填且至少
      一条 type=基本面或市场参数；带未移动 → 该键须缺席/空（防口径漂移）。价格/卖方观点不构成
      移动理由（双向禁用：跌不许下修、涨不许上修）；上版解析失败降级告警不拒；
    ③回滚条款前置（v5.4.0 双尺全量生效）：合理带与基础情景带任一中枢偏离历史 P25-P75
      中枢 >15%（重构声明）→ valuation.rollback_html 必填——首版（无 prev）同样执行；
      两尺混用（一尺越界一尺不越、或两尺越界但偏离异号）→ 拒渲染（纪律四）；
      两尺同向同越界 = 一致重构，只要求 rollback_html。
    ①②为复盘专属（prev 缺失才跳过）；③全量生效（尺子一致性不因是否复盘而变）。
    尺子不可算（None：市值口径 metric_label / 情景无 pe / pe_history 缺 p25/p75）→ 该尺
    不参与判定，混用检查仅在两尺均可算时执行（不可算 ≠ 未越界）。"""
    prev = fill.get("prev")
    if prev:
        if not isinstance(prev.get("scenarios"), list) or not prev["scenarios"]:
            raise ValueError("回测模式 prev.scenarios 缺失或非数组：照抄 extract_review 输出的 "
                             "scenarios 数组（锚移动台账数据源，禁手改；v5.1.0 起必填）")
        v = fill.get("valuation") or {}
        scen = v.get("scenarios") or []
        base = _scenario_by_key(scen, "base")
        prev_pe = (_parse_prev_scenarios(prev["scenarios"]).get("base") or {}).get("pe")
        ev = v.get("pe_band_evidence")
        if base is not None and prev_pe is not None:
            pe = base.get("pe") or []
            cur_pe = (_num(pe[0]) if len(pe) >= 1 else None, _num(pe[1]) if len(pe) >= 2 else None)
            if None not in cur_pe:
                moved = (cur_pe[0], cur_pe[1]) != prev_pe
                if moved:
                    if not ev or not isinstance(ev, list):
                        raise ValueError(
                            f"基础情景 PE 带相对上版移动（{prev_pe[0]:g}-{prev_pe[1]:g}x → "
                            f"{cur_pe[0]:g}-{cur_pe[1]:g}x）但 valuation.pe_band_evidence 缺失："
                            f"增量证据锁死纪律——两版间无新增基本面证据时 PE 带不得移动"
                            f"（v5.1.0 估值锚纪律一）")
                    for i, e in enumerate(ev):
                        if not isinstance(e, dict) or e.get("type") not in _ANCHOR_EVIDENCE_TYPES:
                            raise ValueError(
                                f"pe_band_evidence[{i}].type 非法: {(e or {}).get('type') if isinstance(e, dict) else e!r}"
                                f"——四选一：{'/'.join(_ANCHOR_EVIDENCE_TYPES)}")
                        if not str(e.get("note") or "").strip():
                            raise ValueError(f"pe_band_evidence[{i}].note 为空——证据须写明可核查内容")
                    if not any(e["type"] in ("基本面", "市场参数") for e in ev):
                        raise ValueError(
                            f"pe_band_evidence 无「基本面」或「市场参数」类条目（现有："
                            f"{'/'.join(e['type'] for e in ev)}）——PE 带移动必须锚定新增基本面或市场参数证据"
                            f"（基本面|市场参数），纯价格/卖方观点触发不合法；若两类证据均无，请将 PE 带锁回上版数值")
                elif ev:
                    raise ValueError("PE 带与上版一致，pe_band_evidence 应缺席（画蛇添足防口径漂移）")
        elif ev:
            warns.append("上版三情景 PE 解析失败或本版为市值口径：PE 带移动校验跳过，"
                         "pe_band_evidence 已填无法比对——请人工核对锚移动归因")
    # ③ 回滚门禁 + 双尺混用（v5.4.0 全量生效，首版同样执行；形状单源 regime_scale_devs）
    v = fill.get("valuation") or {}
    devs = regime_scale_devs(fill)          # 只含可算的尺，顺序固定：合理带、基础情景带
    if len(devs) == 2:                       # 两尺都可算才判混用（缺一尺=不可判定，不误判）
        (n_band, dev_band), (n_base, dev_base) = devs
        out_band = abs(dev_band) > REGIME_DEV_THRESHOLD
        out_base = abs(dev_base) > REGIME_DEV_THRESHOLD
        if out_band != out_base:
            raise ValueError(
                f"估值锚双尺混用：{n_band}中枢偏离历史 P25-P75 中枢 {dev_band * 100:+.0f}%、"
                f"{n_base} {dev_base * 100:+.0f}%——一尺越界一尺未越（{n_band if out_band else n_base}"
                f"越界），属「纪律四：禁止评分用旧尺、目标价用新尺」的精选混合；"
                f"请把两把尺对齐（同越界须配 rollback_html，同不越界则两处都锁回历史带）后重渲")
        if out_band and (dev_band > 0) != (dev_base > 0):
            raise ValueError(
                f"估值锚双尺偏离方向相反：{n_band} {dev_band * 100:+.0f}%、{n_base} {dev_base * 100:+.0f}%"
                f"（两尺均 >15% 但一上一下）——同一份报告的合理带与目标价 PE 带指向相反的重构方向，"
                f"属「纪律四：禁止评分用旧尺、目标价用新尺」的双尺混用；请统一重构方向后重渲")
    off = [(n, d) for n, d in devs if abs(d) > REGIME_DEV_THRESHOLD]
    if off:
        rb = str(v.get("rollback_html") or "").strip()
        if not rb:
            which = "合理带/基础情景带两尺" if len(off) == 2 else off[0][0]
            deltas = "、".join(f"{n} {d * 100:+.0f}%" for n, d in off)
            absent = "；另一把尺输入缺失不可算，未参与判定" if len(devs) == 1 else ""
            raise ValueError(
                f"{which}中枢偏离历史 P25-P75 中枢（{deltas}）>15%，属估值重构声明"
                f"但 valuation.rollback_html 缺失：回滚条款前置纪律——必须写明"
                f"「回滚条件：〈可观测证据〉→ 回滚至历史带/上版带」（v5.1.0 估值锚纪律二，"
                f"v5.4.0 起首版同样生效）{absent}")


def _check_anchor_blind_fly(fill: dict, warns: list) -> None:
    """v5.4.0 校验盲飞（软告警）：估值带依赖历史 PE 时段锚的分型（周期股 / 稳定价值 /
    困境反转 / 成长型·中速层——四型对应 _anchor_unanchored_type），若既无行业口径
    metric_label 又缺 pe_history.p25/p75，则两把尺的偏离度都算不出来——形态合规但校准
    零机械校验（盲飞），要求正文写明降级取数路径（时段 PE 自算口径与出处）。"""
    if not _anchor_unanchored_type(fill):
        return
    vi = fill.get("valuation_inputs") or {}
    if vi.get("metric_label"):
        return
    ph = fill.get("pe_history") or {}
    if _num(ph.get("p25")) is not None and _num(ph.get("p75")) is not None:
        return
    warns.append("校验盲飞：本分型（估值带依赖历史 PE 时段锚）既无 metric_label 行业口径、"
                 "pe_history 又缺 p25/p75——双尺偏离与时段校准均无法机械对账（形态合规但无尺）。"
                 "请在 valuation_html 写明降级取数路径：时段 PE 自算口径 + 数据出处"
                 "（E2 月线/自算 PE 的月份与公式），并注明 p25/p75 缺失原因（E1 落盘 pe_p25/pe_p75 未回填）")


def _check_thesis_consistency(fill: dict, calc: dict) -> None:
    """thesis 三情景价一致性：手写 span 价 vs 脚本按 valuation 算出的中枢价。"""
    th = fill.get("thesis_html", "")
    span_prices = {}
    for cls, key in (("scenario-pess", "pess"), ("scenario-base", "base"), ("scenario-opt", "opt")):
        m = re.search(r'<span\b[^>]*class="[^"]*\b' + cls + r'\b[^"]*"[^>]*>(.*?)</span>', th, re.I | re.S)
        if m:
            span_prices[key] = _num(re.sub(r"<[^>]+>", "", m.group(1)))
    if len(span_prices) == 3 and calc:
        cmap = {r["key"]: r["mid"] for r in calc["rows"]}
        bad = []
        for k in ("pess", "base", "opt"):
            c, f = cmap.get(k), span_prices[k]
            if c is None or f is None:
                continue
            if c > 0:
                mismatch = abs(f - c) > 0.1 and abs(f - c) / c > 0.02
            else:
                # c≤0（极端负中枢）时相对偏差无意义，只按绝对差 >0.1 判定
                mismatch = abs(f - c) > 0.1
            if mismatch:
                bad.append(f"{_SCENARIO_NAMES[k]} 手写 {f:g} vs 脚本 {c:.2f}")
        if bad:
            # v4.11.1（审核 D7）：推导式抽成局部变量，不再 f-string 内嵌双层花括号
            hand = {k: span_prices[k] for k in ("pess", "base", "opt")}
            calc_m = {k: round(cmap.get(k, 0), 2) for k in ("pess", "base", "opt")}
            raise ValueError("thesis_html 三情景手写价与 valuation 计算值不一致（相对偏差>2% 且绝对差>0.1）："
                             + "；".join(bad)
                             + f"。手写={hand}，脚本={calc_m}")


def _check_hero_cross(fill: dict, warns: list) -> None:
    """v5.1.2：Hero 指标卡与估值结构化字段互查（存量 fill 无 quote 时两处自说自话实证）——
    顶层 pe_ttm 与 valuation_inputs.pe_ttm 并存且偏差 >1% → 拒渲染（metric_label 行业口径
    跳过，语义非 PE(TTM)）；horizon 顶层 vs valuation 不一致 → 告警；
    mcap vs price×shares 偏差 >5% → 告警。"""
    vi = fill.get("valuation_inputs") or {}
    if not vi.get("metric_label"):
        hpe, vpe = _num(fill.get("pe_ttm")), _num(vi.get("pe_ttm"))
        if hpe is not None and vpe:
            dev = abs(hpe - vpe) / abs(vpe)
            if dev > 0.01:
                raise ValueError(f"Hero pe_ttm（{hpe:g}）与 valuation_inputs.pe_ttm（{vpe:g}）"
                                 f"偏差 {dev * 100:.1f}% > 1%：同一 PE 两处填写必有一处错"
                                 "（v5.1.2 起拒渲染；行业口径见 metric_label 豁免）")
    v = fill.get("valuation") or {}
    vh = str(v.get("horizon") or "").strip()
    if not vh:
        hs = {str(s.get("horizon") or "").strip()
              for s in v.get("scenarios") or [] if isinstance(s, dict)}
        hs.discard("")
        vh = hs.pop() if len(hs) == 1 else ""
    hh = str(fill.get("horizon") or "").strip()
    if hh and vh and hh != vh:
        warns.append(f"horizon 顶层「{hh}」与 valuation「{vh}」不一致：Hero 目标价卡与情景表"
                     "时间维度同源，请统一（v5.1.2）")
    mc, pr, sh = _num(fill.get("mcap")), _num(fill.get("price")), _num(v.get("shares"))
    if mc is not None and pr is not None and sh:
        exp = pr * sh
        if exp > 0 and abs(mc - exp) / exp > 0.05:
            warns.append(f"mcap（{mc:g} 亿）与 price×shares（{pr:g}×{sh:g}={exp:g} 亿）偏差 "
                         f"{abs(mc - exp) / exp * 100:.1f}% > 5%：总市值两处应基本一致（v5.1.2）")


def _check_hero_band_claims(fill: dict, warns: list) -> None:
    """Hero 文案引用「分位/历史带」概念时的数据支撑核对（v4.9）：
    概念必须在 pe_history（第 11 章同源数据，与 E1 落盘 pe_p25/pe_p75、历史带同口径）有对应字段
    可佐证——「分位」→ p25/p75，「历史带/历史区间」→ hist_lo/hist_hi；有分位字段时再做
    现价 PE 相对位置的极性核对（称「低分位」而现价高于 P75、称「高分位」而现价低于 P25 即矛盾）。
    缺支撑字段 → 告警提示补数据或改文案（数据侧不存在该口径即不可信）。"""
    ph = fill.get("pe_history") or {}
    p25, p75 = _num(ph.get("p25")), _num(ph.get("p75"))
    has_iq = p25 is not None and p75 is not None
    has_extreme = _num(ph.get("hist_lo")) is not None and _num(ph.get("hist_hi")) is not None
    pe_ttm = _num((fill.get("valuation_inputs") or {}).get("pe_ttm"))
    for name in ("pe_sub", "price_sub_html", "target_sub_html"):
        txt = _plain_text(fill.get(name) or "")
        if not txt:
            continue
        # 只盯明确引用概念的字样；无概念字面的 sub（「PE」「现价」）不打扰
        if "分位" not in txt and not re.search(r"历史带|历史区间", txt):
            continue
        if "分位" in txt:
            if not has_iq:
                warns.append(f"{name} 引用「分位」但 pe_history 未填 p25/p75（E1 落盘 pe_p25/pe_p75 "
                             f"回填该字段）：Hero 分位说法在报告内无数据佐证，请补数据或改文案")
            elif pe_ttm is not None and (("低分位" in txt or "低位" in txt) and pe_ttm > p75):
                warns.append(f"{name} 称「低分位/低位」但现价 PE(TTM) {pe_ttm:g}x > P75 {p75:g}x——"
                             f"分位说法与 pe_history 数据矛盾，请核对口径")
            elif pe_ttm is not None and (("高分位" in txt or "高位" in txt) and pe_ttm < p25):
                warns.append(f"{name} 称「高分位/高位」但现价 PE(TTM) {pe_ttm:g}x < P25 {p25:g}x——"
                             f"分位说法与 pe_history 数据矛盾，请核对口径")
        if re.search(r"历史带|历史区间", txt) and not has_extreme:
            warns.append(f"{name} 引用「历史带/历史区间」但 pe_history 未填 hist_lo/hist_hi"
                         f"（E1 落盘历史带回填该字段）：该说法在报告内无数据佐证，请补数据或改文案")


def _fin_subclass(st: str) -> str:
    """稳定价值金融子类判定（v5.5.0 单源）："银行" / "高贝塔"（保险·券商·证券）/
    "金融"（泛称金融但非上述子类）/ ""（非金融或无法识别）。
    B6 参考带（_discount_premium_cap）与 DCF 强制豁免（_check_dcf）共用本判定——
    此前两处各写词表，B6 认「证券」、豁免词表不认，同型两套口径（热核审计 P1）。"""
    st = str(st or "")
    if "银行" in st:
        return "银行"
    if re.search(r"保险|券商|证券", st):
        return "高贝塔"
    if re.search(r"(?<!非)金融", st):
        return "金融"
    return ""


def _discount_premium_cap(fill: dict):
    """**股权成本 r** 的加点参考带上限（v5.5.0 B6，scoring.md DDM 节）→ (带名, 上限%)。
    定义域是股权成本 r（DDM/合理 PB 用），不是 WACC——本函数只给 validate 侧对 `dcf.wacc`
    做 sanity 粗筛用（WACC 是加权口径，天然低于 r，拿 r 带当硬尺不成立）。
    未盈利·管线 / 困境反转返回 None（无股权成本锚，跳过）；稳定价值子类走 _fin_subclass 单源。"""
    st = str(fill.get("stock_type") or "")
    std, legacy_tier, _legacy = _normalize_stock_type(st)
    if std == "周期股":
        return ("周期股 5.5-7%", 7.0)
    if std == "成熟/停滞":
        return ("成熟/停滞 3.5-4.5%", 4.5)
    if std == "成长型":
        return ("成长型 4.5-6%", 6.0)
    if std == "稳定价值":
        sub = _fin_subclass(st)
        if sub == "银行":
            return ("金融·银行 4.5-5.5%", 5.5)
        if sub == "高贝塔":
            return ("金融·保险/券商 6-7.3%", 7.3)
        return ("稳定价值/红利（非金融）3.5-4.5%", 4.5)
    return None


def _check_dcf(fill: dict, warns: list) -> None:
    """v4.11.3：DCF 双卡字段校验（dcf，软告警迁移期——缺失不拒）。
    强制分型（v5.4.1 归一判定）：**成长型·中速层/未声明 high**（含旧名「稳健成长股」）、
    **稳定价值（非金融）与成熟/停滞**缺 dcf → 告警；成长型·高速层（含旧名「快速成长」）走远期 PE 折现、
    金融类稳定价值走 PB-ROE/DDM，均不强制（子类判定走 _fin_subclass 单源）。填了 →
    八键齐全性 + value/implied_g/wacc/growth_5y/g_perp 可解析性 + verdict ≥40 字；
    valuation_html 仍手写 DCF 表 → 重复告警。
    v5.5.0 B6：`dcf.wacc` 与国债距离超参考带 +2pct → 软告警——**WACC sanity 粗筛**，不是
    股权成本 r 带的执法（真正的 r 带是写作侧人工口径：DDM 的 r 无落盘字段，机器无可核；
    同报告多个折现率的口径说明也只能人工写；见 scoring.md DDM 节）。"""
    d = fill.get("dcf")
    if not isinstance(d, dict) or not d:
        st = str(fill.get("stock_type") or "")
        # v5.8.2：分型+生效层解析收敛 _resolve_type_tier 单源（本处静默口径：缺 tier 按 mid 兜底，
        # 「!= high」判定与原 None 等价）
        std, tier, _legacy = _resolve_type_tier(fill)
        if std == "成长型" and tier != "high":
            warns.append("dcf 字段未填：成长型（中速层 / 未声明 high）分型 DCF 强制三行由 dcf 字段"
                         "承载（v4.11.3 起；原「稳健成长」改名后于 v5.4.1 重新对齐；"
                         "value/fcf0/growth_5y/g_perp/wacc/net_cash/implied_g/verdict 八键，"
                         "现价比价脚本算，valuation_html 不再手写 DCF 表）")
        elif std == "成熟/停滞":
            warns.append("dcf 字段未填：成熟/停滞分型 DCF 强制三行由 dcf 字段承载"
                         "（与成长型·中速层、稳定价值（非金融）同口径；"
                         "value/fcf0/growth_5y/g_perp/wacc/net_cash/implied_g/verdict 八键）")
        elif std == "稳定价值" and not _fin_subclass(st):
            # v5.1.5（热核 P0-6，用户拍板补校验）：fill-schema/SKILL 承诺「稳定价值（非金融）
            # 必填」此前零执行——与成长型·中速层同态（软告警）；金融类稳定价值股豁免
            # （银行/保险走 PB-ROE/DDM，见 scoring.md）——子类判定与 B6 参考带共用 _fin_subclass
            warns.append("dcf 字段未填：稳定价值（非金融）分型 DCF 双卡由 dcf 字段承载"
                         "（v5.1.5 起；金融类稳定价值股豁免）")
        return
    # v5.5.0 B6：WACC sanity 粗筛（与国债距离超参考带 +2pct 才告警；非股权成本 r 带执法）
    wacc = _num(d.get("wacc"))
    rf = _num((fill.get("valuation_inputs") or {}).get("risk_free"))
    cap = _discount_premium_cap(fill)
    if wacc is not None and rf is not None and cap:
        if wacc > rf + cap[1] + 2:
            warns.append(f"dcf.wacc {wacc:g}% 与国债 {rf:g}% 的距离（{wacc - rf:.1f}pct）超"
                         f"{cap[0]} 参考带 +2pct 容差（上限 {cap[1] + 2 + rf:.2f}%）："
                         f"WACC 与国债距离超参考带（sanity 粗筛）——WACC 是加权口径、天然低于股权成本 r，"
                         f"离国债这么远请核对折现率口径与假设；股权成本 r 的参考带须写作侧自查"
                         f"（scoring.md DDM 节；同报告多个折现率的口径说明为人工义务，非机械校验）")
    missing = [k for k in ("value", "fcf0", "growth_5y", "g_perp", "wacc", "net_cash",
                           "implied_g", "verdict") if not str(d.get(k) or "").strip()]
    if missing:
        warns.append(f"dcf 缺键 {missing}：八键应齐全（value/implied_g/verdict 缺一时整卡不生成）")
    for k in ("value", "implied_g"):
        raw = str(d.get(k) or "").strip()
        if raw and _num(raw) is None:
            warns.append(f"dcf.{k}「{raw}」非空但不可解析为数值：渲染要求数值，"
                         "否则双卡整体不生成（v5.1.2——此前校验只查非空，整卡静默消失）")
    # v5.5.0 P1：参数型三键的非空不可解析同样告警（对齐 value/implied_g 的 v5.1.2 先例）；
    # 「—」占位（口径注/数据不可得）仍跳过，不打扰
    for k in ("wacc", "growth_5y", "g_perp"):
        raw = str(d.get(k) or "").strip()
        if raw and raw != "—" and _num(raw) is None:
            warns.append(f"dcf.{k}「{raw}」非空但不可解析为数值：卡面参数与复核都依赖数值，"
                         "请照抄参数字面值（如 wacc 写 8.5%）（v5.1.2 先例，v5.5.0 扩到三键）")
    if wacc is not None and 0 < wacc < 1:
        warns.append(f"dcf.wacc {wacc:g} < 1：疑为小数口径（WACC 应写百分数，如 8.5% 而非 0.085）"
                     "——卡面原样显示，请核对口径后重渲")
    verdict_len = len(_plain_text(str(d.get("verdict") or "")).strip())
    if 0 < verdict_len < 40:
        warns.append(f"dcf.verdict {verdict_len} 字 < 40：判词须含隐含 g 对照与互证结论"
                     "（与现价比价由脚本算后自动拼接，不用手写）")
    vh = fill.get("valuation_html") or ""
    if "<table" in vh and re.search(r">[^<]*DCF", vh):
        warns.append("valuation_html 仍含手写 DCF 表：v4.11.3 起 DCF 由 dcf 字段承载，请删除手写表")
