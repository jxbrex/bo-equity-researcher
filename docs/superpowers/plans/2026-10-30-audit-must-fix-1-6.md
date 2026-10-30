# 热核审计第 1–6 项修复实施计划

> **执行要求：** 使用 superpowers:subagent-driven-development 或 superpowers:executing-plans，按任务顺序执行；步骤用复选框跟踪。不得执行 git commit、push、tag、release 或部署。

**目标：** 消除负 PE 错分、429 静默降级、同日底稿错配、重述报表遗漏、非有限数值坏图和校验模块循环导入，同时保持正常输入的报告行为不变。

**架构：** 每个缺陷先以现有测试框架复现，再做最小根因修复。数值有限性收在共享 `_num` 边界；校验公共工具移到无反向依赖的 `validate_common.py`，`validate.py` 只保留调度入口。

**技术栈：** Python 3.9+ 标准库、pytest、现有 HTML/SVG 渲染与 golden 快照。

**设计依据：** 本会话 2026-10-30 已批准的三批设计（聊天版；按仓库偏好不另建设计文档）。

## 全局约束

- 不改评分阈值、公开 fill 字段契约或正常输入的渲染结果。
- 不处理审计第 7–15 项，不扩大为部署、归档或其他冗余重构。
- 不访问部署目录，不执行真实网络取数，不新增第三方依赖。
- 每个任务必须完成“定向测试先红 → 最小修复 → 定向测试转绿 → 相关域回归”。
- 最后更新 `CHANGELOG.md` 为未发布记录；不提交、不推送、不发布、不部署。

## 复核重点

- `pe_ttm` 为 0 或负数：必须不可评分，不能进入“越低越便宜”分支，归任务 1 测试。
- 东财 429：必须穿透，且无风险利率失败后不得缓存失败值，归任务 2 测试。
- 同代码同日期的多目录 HTML/fill：只能绑定同报告目录的可靠组合，归属不明必须冲突，归任务 3 测试。
- 同期原始与调整财务报表：较晚公告的调整行必须胜出，归任务 4 测试。
- NaN、正负 Infinity：共享数值边界必须返回无有效数，图表不得输出非有限坐标，归任务 5 测试。

---

### Task 1：负 PE 不得产生合理倍数分

**文件：**
- 修改：`scripts/scoring.py:345-369`
- 测试：`scripts/test_render_gate_core.py`

**接口：**
- 消费：现有 `compute_valuation_score(calc: dict, inputs: dict, gap_tier=None) -> dict | None`。
- 产出：`pe_ttm <= 0` 时返回 `None`，由现有渲染路径转为友好的“估值分无法计算”错误。

- [ ] **步骤 1：写失败测试**
  新增 `test_nonpositive_pe_ttm_cannot_score_as_cheap`：以 `minimal_fill()` 分别设置 `pe_ttm=0` 和 `-5`，`pe_band=[14.5,15.5]`，断言 `compute_valuation_score(compute_valuation(fill), inputs) is None`。

- [ ] **步骤 2：确认测试先红**
  运行：`python -m pytest scripts/test_render_gate_core.py -q -p no:cacheprovider -k nonpositive_pe_ttm`
  预期：当前两种输入都返回字典，测试失败。

- [ ] **步骤 3：实现最小守卫**
  在 `compute_valuation_score` 现有 `pe_ttm is None` 守卫中增加 `pe_ttm <= 0`；不改 `_map_warranted` 阈值。

- [ ] **步骤 4：验证修复与域回归**
  运行上述定向测试及整个 `test_render_gate_core.py`；预期全部通过。

### Task 2：东财 429 全路径穿透且失败不缓存

**文件：**
- 修改：`scripts/em_market.py:195-215`
- 修改：`scripts/em_finance.py:306-313`、`scripts/em_finance.py:535-563`、`scripts/em_finance.py:601-618`
- 测试：`scripts/test_em_fetch.py`

**接口：**
- 消费：现有 `em_core.RateLimitError`、`memo(cache, key, loader)`。
- 产出：四处遇到 `RateLimitError` 均向外抛出；`fetch_risk_free()` 的 429 不写 `_RF_CACHE[today]`，后续调用可重试。

- [ ] **步骤 1：写四个失败测试**
  - 月线缩放校准的 `fetch_quote` 抛 429，断言 `_em_kline_monthly` 抛错而非返回未校准序列。
  - `_em_f10` 抛 429，断言 `fetch_dupont_factors` 抛错而非返回 `{}`。
  - `_em_dc` 抛 429，断言 `_em_hkf10_annual_rows` 抛错而非返回 `[]`。
  - 无风险利率第一次请求抛 429、第二次返回有效行；断言第一次抛错、缓存无当日键、第二次成功且实际请求两次。

- [ ] **步骤 2：确认测试先红**
  运行：`python -m pytest scripts/test_em_fetch.py -q -p no:cacheprovider -k "rate_limit and (monthly or dupont or hkf10 or risk_free)"`
  预期：当前四处均静默返回降级值，测试失败。

- [ ] **步骤 3：实现穿透**
  在四处泛型 `except Exception` 前增加 `except RateLimitError: raise`。保留其他异常的既有降级行为，不改 `memo`。

- [ ] **步骤 4：验证修复与取数回归**
  运行上述定向测试及 `python -m pytest scripts/test_em_fetch.py -q -p no:cacheprovider`；预期全部通过。

### Task 3：同日 HTML 与 fill 可靠成组绑定

**文件：**
- 修改：`scripts/score_dist.py:159-166`、`scripts/score_dist.py:189-227`、`scripts/score_dist.py:437-457`
- 测试：`scripts/test_score_dist.py`

**接口：**
- 消费：现有 `_attach_fill(rows, fills)`、`_arbitrate(rows, preferred)` 与归档布局 `<报告目录>/_archive/fill_*.json`。
- 产出：优先绑定与 HTML 同报告目录的唯一 fill；多重归属无法确定时将行标为 `status="conflict"`、`canonical=False`，不得按路径排序猜选。

- [ ] **步骤 1：写错配复现测试**
  新增同日双目录用例：`a` 放非首选 HTML/fill，`z` 放索引首选 HTML/fill，分别带 `lineage_marker=WRONG-A/RIGHT-Z`。调用真实 `scan_reports` 后，断言 canonical 行来自 `z`，且 `fill_path` 与 `lineage_marker` 也属于 `z`。

- [ ] **步骤 2：写归属不明测试**
  同一代码日期存在多个候选且无法唯一定位到报告目录时，断言结果冲突且不进入评分，不采用字母排序结果。

- [ ] **步骤 3：确认测试先红**
  运行：`python -m pytest scripts/test_score_dist.py -q -p no:cacheprovider -k "same_day or ambiguous"`
  预期：首选 HTML 绑定 `WRONG-A`，测试失败。

- [ ] **步骤 4：实现可靠绑定**
  用绝对路径比较 `dirname(dirname(fill_path)) == dirname(html_path)`；唯一同目录候选或全局唯一候选才可绑定。删除无效的文件名 `endswith` 猜测，多重归属保留冲突标记并由 `scan_reports` 排除评分。

- [ ] **步骤 5：验证修复与台账回归**
  运行定向测试及整个 `test_score_dist.py`；预期既有去重、索引仲裁和人工仲裁用例全部通过。

### Task 4：重述财务报表进入最新公告选择

**文件：**
- 修改：`scripts/quality_inputs.py:27-39`
- 测试：`scripts/test_quality_inputs.py`

**接口：**
- 消费：现有 `_stmt(code, api, as_of, annual=True)`、`_visible`、`_pick_latest_per_period`。
- 产出：income/balancesheet 的 `report_type` 1 与 4 均保留，较晚 `ann_date` 的调整行最终胜出。

- [ ] **步骤 1：写失败测试**
  新增同期原始行 `report_type=1, ann_date=20260320, total_revenue=100` 与调整行 `report_type=4, ann_date=20260410, total_revenue=80`；经真实 `_stmt → _visible → _pick_latest_per_period` 后断言选中类型 4、数值 80。

- [ ] **步骤 2：确认测试先红**
  运行：`python -m pytest scripts/test_quality_inputs.py -q -p no:cacheprovider -k restated`
  预期：类型 4 被过滤，实际选中类型 1、数值 100。

- [ ] **步骤 3：放宽过滤并复用既有去重**
  将 income/balancesheet 过滤条件改为 `report_type in {"1","4"}`，不新增第二套同期选择逻辑。

- [ ] **步骤 4：验证修复与机械输入回归**
  运行定向测试及整个 `test_quality_inputs.py`；预期全部通过。

### Task 5：共享数值边界拒绝非有限数

**文件：**
- 修改：`scripts/scoring.py:116-123`
- 测试：`scripts/test_render_charts.py`

**接口：**
- 消费：全项目共享 `_num(value) -> float | None`。
- 产出：NaN、Infinity、-Infinity 均返回 `None`；有限 int/float 和既有字符串解析完全不变。所有已使用 `_num` 的图族自动获得同一守卫，不新增 `_fnum` 平行助手。

- [ ] **步骤 1：写共享边界与最终图测试**
  - 参数化断言 `_num` 对三种非有限数返回 `None`。
  - `build_peers_plot` 输入一个非有限点和两个有效点，断言不抛错、结果不含 `nan`/`inf` 坐标且有效点仍绘制。

- [ ] **步骤 2：确认测试先红**
  运行：`python -m pytest scripts/test_render_charts.py -q -p no:cacheprovider -k "nonfinite or non_finite"`
  预期：`_num` 原样透传，散点图出现 `nan` 或对 Infinity 抛错。

- [ ] **步骤 3：实现单一边界修复**
  在 `_num` 的 int/float 分支用现有数学工具增加 `math.isfinite` 判断；不改其他解析分支，不逐图复制守卫。

- [ ] **步骤 4：验证修复与图表回归**
  运行定向测试、整个 `test_render_charts.py` 和 `test_golden.py`；预期全部通过且现有快照零漂移。

### Task 6：解除校验循环依赖并删除再导出层

**文件：**
- 新建：`scripts/validate_common.py`
- 修改：`scripts/validate.py`
- 修改：`scripts/validate_audit.py`、`scripts/validate_charts.py`、`scripts/validate_html.py`、`scripts/validate_typing.py`、`scripts/validate_valuation.py` 的导入
- 修改：`scripts/test_render_gate_source.py`、`scripts/test_render_gate_typing_anchor.py`、`scripts/test_render_gate_period.py` 的内部导入
- 测试：`scripts/test_render_gate_validate.py`
- 文档：`README.md` 的 scripts 目录树

**接口：**
- 产出 `validate_common.py`：拥有 `_HTML_FIELDS`、`_HTML_TABLE_FIELDS`、`_TYPE_ALIASES`、`_is_hk_code`、`_quote_ref`、`_scenario_by_key`、`_normalize_stock_type`、`_resolve_type_tier`、`_anchor_unanchored_type`。
- `validate_audit` 直接从 `charts_gap` 导入 `_gh_sort_key`；其他域模块从 `validate_common` 导入共享工具。
- `validate.py` 仅保留 `validate_content`、`_validate_content_impl` 和实际调度所需导入；`render_report` 的 `validate_content` 调用签名不变。

- [ ] **步骤 1：写独立导入失败测试**
  新增测试用独立 `subprocess` 分别执行 `import validate_audit`、`validate_charts`、`validate_html`、`validate_typing`、`validate_valuation`，工作目录为 `scripts`，断言每个返回码均为 0。

- [ ] **步骤 2：确认测试先红**
  运行：`python -m pytest scripts/test_render_gate_validate.py -q -p no:cacheprovider -k standalone_import`
  预期：当前五个子进程均因 circular import 返回非零。

- [ ] **步骤 3：迁移公共工具并改为单向依赖**
  将公共常量与函数原样移到 `validate_common.py`；五个域模块改从该文件导入。`validate.py` 删除公共工具原文和仅供测试的再导出块，只导入调度清单实际消费的函数。三个测试改从真实拥有者导入。

- [ ] **步骤 4：验证独立导入与校验回归**
  运行定向测试及所有 `test_render_gate_*.py`；预期全部通过，`validate_content` 调用顺序和告警文本不变。

- [ ] **步骤 5：补目录索引**
  在 README 的 scripts 树增加 `validate_common.py`，说明其为校验公共工具层；不新增其他文档。

### Task 7：整体验收与未发布记录

**文件：**
- 修改：`CHANGELOG.md`

**接口：**
- 产出：当前源码的全量回归证据、独立导入证据、定向反例证据和未发布变更记录。

- [ ] **步骤 1：运行完整标准回归**
  运行：`PYTHONDONTWRITEBYTECODE=1 python -m pytest scripts/ -q -p no:cacheprovider`
  预期：全部通过；记录实际数量和时间。

- [ ] **步骤 2：重跑关键原始场景**
  分别验证负 PE 拒绝、四处 429 穿透、同日 `RIGHT-Z` 绑定、重述值 80 胜出、散点图无 `nan`、五个域模块独立导入成功。

- [ ] **步骤 3：检查交付边界**
  运行：`git diff --check` 与 `git status --short`；确认无临时报告、缓存或测试产物，改动只覆盖本计划。

- [ ] **步骤 4：更新未发布记录**
  在 `CHANGELOG.md` 顶部记录六项根因修复和验证结果，标明未发布；不提升 `RENDERER_VERSION`，不修改 handoff，不执行任何 git 写操作。
