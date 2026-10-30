# 热核审计第 12–14 项结构精简与快照补网计划

> **执行要求：** 使用 superpowers:executing-plans 在当前目录按任务执行。不得自动 commit、push、tag、release 或部署。

**目标：** v2 评分只计算一次，3B 两种输入共用一套评分引擎，快照覆盖四个缺漏组件且所有快照均参与变异自证。

**架构：** 用 `PreflightResult` 显式传递预检产物；3B 先规范化输入再执行共同引擎；用参数化快照注册表统一比对与变异测试，新增带真实落盘证据的视觉夹具。

**技术栈：** Python 3.9+ 标准库、pytest、namedtuple、现有 golden 快照。

**设计依据：** 用户已批准“行为不变的三小步”方案。

## 全局约束

- 正常输入的分数、rule_steps、告警、HTML/SVG 输出不得改变；既有 8 份快照不得漂移。
- 不处理第 7 项及其他未列事项，不新增依赖，不访问部署目录。
- 每项先写失败测试并确认原因，再做最小结构修复与域回归。
- 新快照只通过官方 `GOLDEN_UPDATE=1 python scripts/test_golden.py` 直跑生成，并核对旧快照零 diff。
- 最后更新 CHANGELOG 未发布记录，不提升版本号，不自动提交或发布。

## 复核重点

- v2 预检和正式渲染：`compute_scores` 只能调用一次，风险登记与维度注入使用同一终态，归任务 1。
- projects/visibility 的空值、主来源、组合主来源、缺权重、数值缺失和加权：结果与旧实现一致，归任务 2。
- gap_plot A/B、gap_history、timing_facts、dupont 的最终 HTML 装配：必须有快照，归任务 3。
- period_q1/q3/annual 及新增 visual_fill：变异后必须偏离基线，归任务 3。
- 既有快照：更新命令后不得出现内容差异，归任务 3。

---

### Task 1：预检产物只生成并消费一次

**文件：** `scripts/render_report.py`、`scripts/test_render_gate_core.py` 或 `test_render_e2e.py`

**接口：**
- 新增私有 `PreflightResult = namedtuple(...)`，携带 fill/calc/sc/valuation/valuation_calc 以及 l1/l3/risk_register 三个渲染产物。
- `build_risk_register(fill, sc=None)` 复用已有 sc；`_build_repl_map` 消费预检产物，不再重复评分、风险登记、图表锚点或维度注入。

- [ ] 写 `test_v2_render_computes_scores_once`：用真实 v2 fill 和证据文件执行完整 render，包装计数 `compute_scores`，断言调用一次且输出仍包含风险登记和九维评分。
- [ ] 运行该测试，预期当前调用三次而失败。
- [ ] 实现 `PreflightResult` 与 `build_risk_register(fill, sc=None)`；render/check_fill 使用字段访问，RenderContext 增加预检产物字段。保持 v1 流程和告警顺序。
- [ ] 跑定向测试、全部 render gate、e2e 和 golden，预期全绿且既有快照零漂移。

### Task 2：3B 共用规范化评分引擎

**文件：** `scripts/quality_rules.py`、`scripts/test_quality_rules.py`

**接口：**
- 新增 `_eval_3b_items(spec, items, marker_key, scores, default_weight, projects_mode)`，统一处理贡献校验、主来源、组合主来源、回退和加权。
- `_eval_3b` 只负责 projects/visibility 的字段选择、分数表、默认权重和空清单语义。

- [ ] 先写共同引擎测试：直接调用尚不存在的 `_eval_3b_items`，两个贡献各 0.5、阶段分 9/7，断言最终分 8、两个规则步骤和 complete 状态；预期 AttributeError/ImportError。
- [ ] 实现共同引擎并迁移两个分支。保留 `PRIMARY_GROUP`、`PRIMARY_FALLBACK`、PROJECT/VISIBILITY 步骤 ID、错误文案、cap 和 visibility 缺 value 降级。
- [ ] 跑共同引擎测试及整个 `test_quality_rules.py`、`test_score_dist.py`；预期全部通过，既有行为零漂移。
- [ ] 用 AST 或行数对照确认重复分支已删除，但不以行数替代行为验收。

### Task 3：参数化快照注册表与真实证据视觉夹具

**文件：** `scripts/conftest.py`、`scripts/test_golden.py`、新增 `scripts/golden/visual_fill.html`

**接口：**
- `visual_fill(**over)` 基于 full_fill，加入 gap_plot（A 档 street）、gap_history、timing_facts、dupont 及对应锚点；另保留无 street 的 B 档变体。
- `render_visual_fill(fill)` 在临时目录写 quote、timing、street 真实 JSON 证据并同步 fill 引用，确保校验与渲染消费同一份数据。
- `_SNAPSHOT_CASES` 统一注册 minimal/full/mcap/v2/period 四态/visual，参数化快照和变异自证共用。

- [ ] 写视觉快照存在性测试：渲染 visual_fill 后断言包含 `gap-notes`、`券商态度变化`、`timing-fact-card`、`dup-chain`，且引用证据均可读；B 档变体包含预期差机构分布图。
- [ ] 先运行测试，确认当前专用夹具/快照不存在而失败。
- [ ] 实现夹具与证据写入；用 `_SNAPSHOT_CASES` 参数化现有 8 个场景并加入 visual，mutation 测试改为遍历同一注册表。保留 v2 特有断言和独立测试 ID。
- [ ] 运行 `GOLDEN_UPDATE=1 python scripts/test_golden.py` 生成 visual 基线；检查 git diff，既有 8 份快照必须零变化，只允许新增 visual_fill.html。
- [ ] 再跑 `python -m pytest scripts/test_golden.py -q -p no:cacheprovider`，预期全部快照和变异自证通过。

### Task 4：整体验收与未发布记录

**文件：** `CHANGELOG.md`

- [ ] 运行完整 `PYTHONDONTWRITEBYTECODE=1 python -m pytest scripts/ -q -p no:cacheprovider`，预期全部通过。
- [ ] 重跑评分调用计数、共同 3B 引擎和视觉快照反例；检查 `git diff --check` 与 `git status --short`。
- [ ] 在 CHANGELOG 顶部记录三项结构整改和实测结果，标明未发布；不修改 RENDERER_VERSION，不执行 git 写操作。
