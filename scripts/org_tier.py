#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""org_tier.py — 头部/外资券商清单与机构名归一化（v5.9.0 自 charts_gap.py 搬出单源）。

v5.9.0 起数据层（em_owner gap_history 排序）与渲染层（charts_gap 降级面板选取/
机构名着色）共用，此前清单位于 charts_gap.py 仅供渲染层。
"""


def norm_org(org: str) -> str:
    """机构名归一化（v5.8.1）：tushare org_name 存在「中金/中金公司」口径漂移，
    rows 与 tp_reports 同机构名可能不一致——去尾部公司后缀后比对（宁德 300750 复盘
    实证：归一前降级面板单点落行外补列）。括号注（如 (香港)）保留，区分境内外主体。"""
    s = org.strip()
    for suf in ("证券股份有限公司", "股份有限公司", "有限责任公司", "有限公司", "公司", "证券"):
        if s.endswith(suf):
            s = s[:-len(suf)]
            break
    return s


# 头部/外资券商清单（norm_org 归一化后精确匹配）：gap_history 行排序与目标价降级面板
# 行外券商独立行的选取优先级——大券商目标价参考价值高于小券商（宝丰能源复盘实证：
# 中金/中信建投单份研报目标价沉右下小字补列，用户拍板大券商优先列示）
TIER1_ORGS = frozenset((
    # 外资
    "高盛", "摩根士丹利", "摩根大通", "瑞银", "花旗", "汇丰", "野村", "美银", "巴克莱",
    "杰富瑞", "麦格理", "大和",
    # 头部内资
    "中信", "中金", "中信建投", "华泰", "国泰海通", "国泰君安", "招商", "广发",
    "申万宏源", "国信", "兴业", "东方", "光大", "平安"))


def is_tier1(org: str) -> bool:
    """归一化命中头部/外资清单。"""
    return norm_org(org) in TIER1_ORGS
