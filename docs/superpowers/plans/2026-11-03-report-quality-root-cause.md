# 报告质量系统性根因整改 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让历史严重报告问题成为可重复的回归测试，在写盘前检查最终 HTML，并消除次年利润增长链的重复手填。

**Architecture:** 在现有 fill→render 流程中增加规范化 fill 视图，由明确的情景利润年份和实际利润基数派生可计算的字段。将完整内存渲染提取为预检、正式渲染和真实语料审计共用入口，最终 HTML 与 SVG 在写盘前验收。真实事故通过独立清单脚本隔离运行，不改变正式报告或证据文件。

**Tech Stack:** Python 标准库、既有 pytest、现有 HTML/SVG 渲染器、JSON 清单；不新增依赖。

**Spec:** `docs/superpowers/specs/2026-11-03-report-quality-root-cause-design.md`

## Global Constraints

- 不重写全部软告警，不把风格提示一概升级为拒渲染；只拦截事实矛盾、必要内容缺失和静默减配。
- 不批量重渲或重评历史报告，不改变既有 3A 评分阈值、行业权重、PE 带和估值方法。
- 次年且实际归母净利为正时才自动计算单年增速；隔年、累计增速、非正分母不得猜测或拿卖方一致预期补洞。
- 新报告仍可自动计算的字段若被手填，直接拒渲染；不静默覆盖，不因碰巧一致而放行。旧 fill 保持兼容。
- 真实报告、会话和 `_archive/` 原件只读；所有生成物写入 `artifacts/_quality_root_cause/`。
- 不读写部署目录；未经用户确认，不 commit、push、tag、release 或 deploy，因此本计划不含提交步骤。

## Review Focus

- 隔年情景或累计增速：不得把两年累计增速当成单年增速；由任务 1 的隔年反例覆盖。
- 非正实际利润、缺实际年表或市值口径：自动计算必须跳过或给出明确错误，不能产生伪百分比；由任务 1 的边界参数化测试覆盖。
- 规范化被 `_preflight`、`compute_scores` 重复调用：第二次不得把脚本派生值误判成手填；由任务 1 的幂等测试覆盖。
- 预检后 SVG 被模板删除、重复或内容改变：最终组件计数必须发现；由任务 2 的最终 SVG 反例覆盖。
- 真实语料中的“应拒绝”和“应通过”：结果不得混淆，且失败时不得写报告或移动证据；由任务 3 的清单运行器测试覆盖。

---

### Task 1: 增长链规范化与重复手填门禁

**Files:**
- Modify: `scripts/scoring.py:480-570`
- Modify: `scripts/render_report.py:962-999`
- Modify: `scripts/validate_audit.py:642-841`
- Test: `scripts/test_render_gate_validate.py`
- Test: `scripts/test_quality_rules.py`

**Interfaces:**
- Produces: `normalize_growth_fill(fill: dict) -> dict`，返回深拷贝的规范化 fill，不改输入对象。
- Consumes: `valuation.profit_year`、`fin_trend` 最近实际归母净利、`valuation.scenarios` 和现有 `score_inputs/growth_plot/gap_plot`。
- Internal: 规范化视图用运行时 `_growth_derived` 路径清单标记脚本派生字段，保证幂等；该键不写入归档或 HTML。
- Contract: `date >= "2026-11-04"` 的利润口径 v2 报告必须有 `valuation.profit_year`。仅 `profit_year == 最近实际年 + 1` 且实际归母净利 `>0` 时派生 3A 与该年 `growth_plot` 增速；任何可派生字段的原始手填均拒绝。匹配年份的 `gap_plot` 本文净利始终可由基础情景利润派生。

- [ ] **Step 0: 记录修改前全量基线**

Run: `python -m pytest scripts/ -q -p no:cacheprovider`
Run: `python scripts/test_golden.py`

Expected: 记录实际通过数与任何既有失败；后续不得把既有失败误算为本次回归。

- [ ] **Step 1: 写次年单年派生与联动失败测试**

新增 `test_growth_view_derives_next_year_single_source`：使用 2025 实际归母净利 16.78 亿，2026 三情景利润 17.5/18.9/19.6 亿，`profit_year=2026`，删除 3A 的 `growth_lo/growth_hi`、2026E 的 `np_lo/np_hi` 和该年 `gap_plot.ours`。断言规范化后 3A 与图区间均约为 `[4.2908,16.8057]`，`gap_plot.ours=18.9`，输入 fill 未改变。

新增 `test_growth_view_scenario_changes_update_derived_consumers`：一个子例只把悲观情景 17.5 改为 17.6，断言评分与增长图下限自动变化；另一个子例只把基础情景 18.9 改为 19.0，断言 `gap_plot.ours` 自动变化。不得断言基础情景变化会改变由悲观/乐观边界决定的区间。

- [ ] **Step 2: 写重复手填、幂等与旧版兼容失败测试**

新增 `test_growth_view_rejects_manual_derived_fields_for_new_report`：在新日期 fill 中分别手填一个可派生字段，即使数值与计算结果完全相同，也必须抛出包含该字段路径和“删除重复字段”的 `ValueError`。

新增 `test_growth_view_normalization_is_idempotent`：对同一新 fill 连续规范化两次，第二次不得误拒，结果一致。

新增 `test_growth_view_legacy_manual_fields_remain_supported`：旧日期、已有手填值保持原值，由现有对账校验处理，不得被静默覆盖。

- [ ] **Step 3: 写隔年、非正分母和缺年份失败测试**

新增参数化测试：2027 情景利润而实际年表止于 2025 时，不生成 2027 单年增速，原有单年/累计写法保留；实际利润为 0 或负数时不生成数字增速；市值口径不要求 `profit_year`；新日期利润口径缺 `profit_year` 时给出明确错误。

- [ ] **Step 4: 运行定向测试确认 RED**

Run: `python -m pytest scripts/test_render_gate_validate.py scripts/test_quality_rules.py -q -p no:cacheprovider -k "growth_view or growth_score"`

Expected: 新测试因 `normalize_growth_fill` 不存在或派生/拒绝行为未实现而失败；既有失败单独记录，不与新反例混淆。

- [ ] **Step 5: 实现最小规范化并接入评分与预检**

在 `scripts/scoring.py` 实现 `normalize_growth_fill`，复用现有 `_num`、情景查找和有限数值语义。`_preflight` 在 `_load_fill` 后立即规范化；`compute_scores` 对 v2 同样调用，利用 `_growth_derived` 保证重复入口幂等。

让 `_check_growth_consistency` 优先消费明确的 `profit_year`，保留旧 fill 的原有推断。不得新增另一套年份推断或数字解析。

- [ ] **Step 6: 运行定向测试确认 GREEN**

Run: `python -m pytest scripts/test_render_gate_validate.py scripts/test_quality_rules.py -q -p no:cacheprovider -k "growth or quality_profile"`

Expected: 新增与既有相关测试全部通过；不得通过删除预测、合并年份或放宽既有硬门禁转绿。

### Task 2: 最终 HTML 与 SVG 的共用预检门禁

**Files:**
- Modify: `scripts/render_report.py:524-535,962-1078`
- Modify: `scripts/validate_html.py:444-544`
- Modify: `scripts/validate_charts.py:192-275`
- Test: `scripts/test_render_gate_core.py`
- Test: `scripts/test_render_gate_validate.py`
- Test: `scripts/test_golden.py`

**Interfaces:**
- Consumes: 任务 1 的 `normalize_growth_fill` 与规范化 fill。
- Produces: `CompleteRender = namedtuple("CompleteRender", ["html", "repl", "fill", "sc", "valuation", "prev", "date", "target_range"])`。
- Produces: `render_document(fill_path: str) -> CompleteRender`，完成全部内存构建与最终校验，不写盘、不归档。
- Produces: `check_final_dimensions(html: str, fill: dict, sc: dict) -> None` 与 `_check_final_charts(html: str, repl: dict) -> None`。

- [ ] **Step 1: 写最终渲染后才出现的错误测试**

新增 `test_check_fill_runs_final_html_gates_without_writing`：构造预检可接受、图表构建时才产生非法来源注的 fill。旧行为下 `check_fill` 不构建图表；新行为必须抛出同一最终错误，并断言目标 HTML、归档文件均不存在，原 fill/quote/timing 路径未移动。

- [ ] **Step 2: 写最终九维与 SVG 保真失败测试**

新增 `test_final_dimensions_reuse_four_element_contract`：在最终注入后的 HTML 中缺少任一“判词/论据/对比/评分”或重复标签时，`check_final_dimensions` 必须点名维度；合法四段不重复内容时通过。

新增 `test_final_svg_multiset_matches_rendered_repl`：从 `repl` 各值提取完整 `<svg>...</svg>`，与最终 HTML 的 SVG 多重集合比较；少一张、重复一张或同图内容被替换均拒绝，合法报告通过。

新增 `test_final_review_chart_gap_uses_existing_reason_rules`：复用 `_prev_chart_facts` 和 `_review_chart_note`，新日期报告旧图减少且无同句原因时拒绝，有合理缺席说明时通过，旧日期只保留原告警。

- [ ] **Step 3: 运行定向测试确认 RED**

Run: `python -m pytest scripts/test_render_gate_core.py scripts/test_render_gate_validate.py -q -p no:cacheprovider -k "final_ or check_fill_runs"`

Expected: 新测试因最终检查不存在或 `check_fill` 尚未执行完整渲染而失败。

- [ ] **Step 4: 提取完整内存渲染并接入最终检查**

将当前 `render()` 中图表构建、`RenderContext`、`repl`、模板合成、`_check_leftover` 和 `_check_source_spans` 收入 `render_document`。正式 `render()` 只负责调用它、写 HTML、既有后检查与归档；`check_fill()` 调用同一 `render_document`，成功才打印通过。

最终维度判定与现有 `_check_dim_blocks` 共用提取/判空辅助函数。最终 SVG 使用 `collections.Counter` 比较完整字符串，不另建图名映射。复盘减配复用现有检查函数产生的原因列表，新日期升级为错误，不重写原因识别规则。

- [ ] **Step 5: 运行定向与 golden 测试确认 GREEN**

Run: `python -m pytest scripts/test_render_gate_core.py scripts/test_render_gate_validate.py -q -p no:cacheprovider -k "final_ or check_fill or dim_blocks or prev_charts"`
Run: `python scripts/test_golden.py`

Expected: 全部通过；任何快照差异必须逐行解释，不为消红直接重建。

### Task 3: 真实事故清单与隔离整案验收

**Files:**
- Create: `scripts/audit_corpus.py`
- Test: `scripts/test_audit_corpus.py`
- Create: `artifacts/_quality_root_cause/manifest.json`
- Create: `artifacts/_quality_root_cause/sources/`（从事发证据复制，不修改原件）
- Create: `artifacts/_quality_root_cause/results/`（运行产物，不入库）

**Interfaces:**
- Consumes: 任务 2 的 `render_document(fill_path)` 和 `CompleteRender.html`。
- Produces: `run_manifest(manifest_path: str, out_dir: str) -> list[dict]`；每项结果为 `{name, expected, actual, ok, detail}`。
- Produces: `extract_reader_text(html: str) -> str`，使用标准库 `HTMLParser` 跳过 `script/style/svg`，供轻量终检阅读。
- CLI: `python scripts/audit_corpus.py <manifest.json> --out <结果目录>`；任一案例不符预期返回非零。

- [ ] **Step 1: 写清单运行器失败测试**

用一个应通过的最小 fill 和一个应拒绝的非法 fill，断言 `run_manifest` 分别报告 pass/reject；应拒绝案例不得输出 HTML，原证据路径不变；应通过案例输出 HTML 与不含 CSS/SVG 的 `.txt` 正文。再构造“预期拒绝但实际通过”的案例，断言 `ok=False` 且 CLI 非零。

- [ ] **Step 2: 运行测试确认 RED 后实现最小运行器**

Run: `python -m pytest scripts/test_audit_corpus.py -q -p no:cacheprovider`

Expected: 初次 RED；实现清单解析、相对路径解析、结果 JSON、HTML/正文输出和退出码后 GREEN。清单只支持 `name/fill/expect/contains` 四键，`expect` 为 `pass` 或 `reject`，不增加未要求的配置能力。

- [ ] **Step 3: 恢复六家事故证据并登记不变量**

定位并只读检查以下原始报告会话：比亚迪 `feff8875-5825-4639-b26f-d2429bb7596d`、中免 `94db749f-b622-4143-8faf-c0fa13ada5d1`、益丰 `cd53458a-844e-4160-a1d8-08678b63c6ec`、工业富联 `b3f60e90-5ab1-4b35-aceb-60720bf8d461`、金诚信 `3a898a8d-e2a0-453c-9d44-5ab768ae8ddc0`、中国船舶 `1e789fe9-eae3-4e41-90c5-c275bbf10698`。

从事发 transcript/file-history 恢复坏 fill 或 HTML 到 `sources/`，从 `_archive/` 复制已修正版本及必需 quote/timing。六家均在结果台账写明症状、不变量、漏检层和本次拦截层；无法完整恢复的明确标为最小反例，不冒充整案。

- [ ] **Step 4: 先运行事故清单，确认检测盲区再补反例**

Run: `python scripts/audit_corpus.py artifacts/_quality_root_cause/manifest.json --out artifacts/_quality_root_cause/results`

Expected: 应拒绝的原始坏样本被点名，已修正样本通过。若原始事故仍能通过，回到任务 1 或 2 添加最小失败测试并修复；不得修改预期来放行。

- [ ] **Step 5: 完成至少三份真实整案验收**

至少覆盖比亚迪、中免、益丰：检查最终 HTML、九维正文、预期组件和增长口径；为终检生成去 CSS/SVG 正文。比亚迪的隔年/累计增速保持原语义，益丰的次年单年增速必须可复算，中免年报验证不得重新出现在催化剂清单。

### Task 4: 流程契约、独立终审与全量交付验证

**Files:**
- Modify: `references/fill-schema.md`
- Modify: `SKILL.md`
- Modify: `tasks/lessons.md`
- Modify: `CHANGELOG.md`
- Modify: `scripts/render_report.py:65-67`
- Create: `handoffs/v0.14.0-handoff.md`

**Interfaces:**
- Consumes: 任务 1–3 的实际代码与真实运行结果。
- Produces: 后续报告可执行的 `profit_year`、派生字段禁填、最终预检和真实事故验收契约；版本 `v0.14.0`。

- [ ] **Step 1: 更新字段契约与报告流程**

明确 `profit_year` 的年度含义、次年自动计算的适用条件、隔年/非正分母不自动计算、重复手填拒绝和旧版迁移。将交付完成条件改为最终 HTML 预检、相关真实事故回归和轻量独立终检同时完成，不再以测试数量或视觉通过代替内容验收。

- [ ] **Step 2: 更新教训、版本与交接文档**

记录三要素/四要素口径漂移、合成快照边界、派生值多头手填和反向消警的共同根因。只写已经运行的测试与整案结果；未恢复或未执行的样本明确挂账。`RENDERER_VERSION` 升为 `v0.14.0`，旧 handoff 的未决事项按仓库制度承接。

- [ ] **Step 3: 运行标准全量回归**

Run: `python -m pytest scripts/ -q -p no:cacheprovider`
Run: `python scripts/test_golden.py`

Expected: 全量通过；快照有意变化已逐行审核。若出现与本次无关的既有失败，单独报告，不顺手修无关问题。

- [ ] **Step 4: 真实成品与视觉验收**

重新运行任务 3 清单；对比亚迪、中免、益丰输出 HTML 运行 `scripts/visual_check.py`，核对最终文本、SVG 数量、版本标记和无占位符。原正式报告不被覆盖。

- [ ] **Step 5: 默认次一级子智能体独立终审**

省略 `model` 参数，提供三份去 CSS/SVG 正文、验收清单和必要结构化字段；只读一轮、最多 5 条带证据问题，不重新取数、不做风格润色。主会话逐条复现重要发现，复核期间冻结受审文件。

- [ ] **Step 6: 最终差异与临时产物检查**

Run: `git diff --check`
Run: `git status --short`

Expected: 只包含本计划源代码、测试、契约和文档；`artifacts/` 为隔离运行产物，不进入提交。没有测试日志或临时文件散落仓库根目录。未经用户确认不提交、不发布、不部署。

## Verification

完成必须同时满足：

1. 新增反例均先 RED 后 GREEN，原始坏样本不能靠改预期通过。
2. 次年单年情形中，边界情景利润变化自动更新评分与增长图，基础情景利润变化自动更新预期差；隔年/累计与非正分母不被误算。
3. `--check` 与正式渲染执行同一个最终 HTML 门禁，失败零写盘、零归档副作用。
4. 比亚迪、中免、益丰至少三份真实整案完成最终内容检查，六家事故都有明确台账。
5. 全量 pytest、官方 golden、真实清单和三份代表性报告双视口通过，独立轻量终审的重要发现已核实。
6. CHANGELOG 与 handoff 只记录真实完成事项；工作区没有非计划改动，未执行任何发布操作。

## Assumptions

- 新增长契约从 `2026-11-04` 的报告日期起生效，给当前日期为 2026-11-03 的存量报告保留迁移边界。
- 只有次年且正实际利润的 3A/增长图可自动派生；隔年或累计情形不扩展新输入，也不借自动化改变评分语义。
- `_growth_derived` 只是运行时幂等标记，不是新写作字段，不进入归档或最终 HTML。
- 真实整案使用隔离副本，不能把原始坏样本必须拒绝误写成必须渲染成功。
- 采用哪种子代理执行方式由用户在计划审阅后决定；终审模型仍使用 Kimi Code 默认次一级子智能体。
