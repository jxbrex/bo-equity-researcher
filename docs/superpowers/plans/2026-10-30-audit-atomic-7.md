# 热核审计第 7 项部署与归档可恢复改造计划

> **执行要求：** 使用 superpowers:executing-plans 在当前目录按任务执行。不得自动 commit、push、tag、release 或部署。

**目标：** 部署失败可恢复旧版本，归档失败不丢源文件且可重跑；所有变更均在临时目录完成故障注入验证。

**架构：** 部署采用“原目录改名备份 → 镜像新目录 → 失败恢复/成功清理”；归档采用“复制到临时文件 → 提交归档与索引 → 最后删除源文件”。

**技术栈：** PowerShell 5.1+、Python 3.9+ 标准库、pytest、robocopy。

**设计依据：** 用户已批准“备份恢复 + 复制后提交”方案，不引入事务框架。

## 全局约束

- 不访问真实部署目录，不执行正式部署，不改公开 fill 契约或正常归档布局。
- 保留部署预览 /MIR /L、额外文件提示、旧目录退休和 UTF-8 BOM；robocopy rc>=8 必须恢复。
- 归档仍使用 `_archive/_index.jsonl`，正常 HTML、文件名、索引行和告警顺序不变。
- 每项先写失败测试并确认原因，再做最小实现与域回归。
- 最后更新 CHANGELOG 未发布记录，不提升版本号，不自动提交或发布。

## 复核重点

- 部署已有目录：失败必须恢复原目录，不得留下半成品；成功才删除备份。
- 首次部署：失败后不得留下部分新目录；备份已存在时必须拒绝且不动原目录。
- 归档复制失败：源 fill/quote/timing 必须保留，索引不得新增。
- 索引替换失败：源文件必须保留并可重跑成功；成功后才允许删除源文件。
- 所有路径：目标部署目录恢复只读，deploy.ps1 保持 UTF-8 BOM。

---

### Task 1：部署目录备份、失败恢复与只读收口

**文件：** `scripts/deploy.ps1`、`scripts/test_deploy_meta.py`

**接口：** 新增 `Invoke-MirroredDeployment -Repo -Dest`，封装备份、robocopy、失败恢复和只读恢复；-Go 只调用一次，预览路径不变。

- [ ] 写故障注入测试：提取完整 PowerShell 函数到临时脚本，以函数形式替换 robocopy/attrib。rc=8 时先制造部分新文件，断言原 marker 恢复、partial 不存在、备份清理、+R 被调用；rc=1 时断言新文件存在且备份删除；备份已存在时断言拒绝且原目录不变。
- [ ] 运行测试，预期当前直接 /MIR 的实现没有该函数或失败恢复而失败。
- [ ] 实现备份改名、镜像、失败删除半成品并恢复、成功清理备份、finally 恢复只读。备份移动失败不得删除原目录。
- [ ] 跑故障注入、全部 `test_deploy_meta.py` 和 `git diff --check`，预期全绿且 BOM 保留。

### Task 2：归档复制提交与源文件最后清理

**文件：** `scripts/render_report.py`、`scripts/test_render_gate_core.py`、`test_render_e2e.py`

**接口：** `_archive_artifacts` 先收集 (src,dst)，使用 `shutil.copy2` 写归档临时文件；归档文件与索引提交成功后才删除源文件。

- [ ] 写复制失败测试：第一次 copy2 抛 OSError，断言三个源文件都存在且 `_index.jsonl` 未生成。
- [ ] 写索引失败并重跑测试：仅替换 `_index.jsonl` 时抛 OSError，断言源文件保留；恢复真实 replace 后重跑，断言索引成功且源文件按成功路径清理。
- [ ] 运行测试，预期当前实现先 move 导致源文件缺失而失败。
- [ ] 用表驱动 pending 列表替换三段重复移动；保留索引更新、文件名和成功输出。失败临时文件 best-effort 清理，清理失败与归档失败分开报告。
- [ ] 跑定向测试、全部 render gate、e2e 和 golden，预期正常归档输出零漂移。

### Task 3：整体验收与未发布记录

**文件：** `CHANGELOG.md`

- [ ] 运行完整 `PYTHONDONTWRITEBYTECODE=1 python -m pytest scripts/ -q -p no:cacheprovider`，预期全部通过。
- [ ] 重跑部署 rc=1/rc=8、归档复制失败和索引失败重跑反例；检查 `git diff --check` 与 `git status --short`。
- [ ] 在 CHANGELOG 顶部记录可恢复改造与实测结果，标明未发布；不修改 RENDERER_VERSION，不执行 git 写操作。
