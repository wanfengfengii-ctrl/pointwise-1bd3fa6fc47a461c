# 海岚带材复检台账

海岚冷轧带材厂的白班质控员按分卷清单和原计时核算复检工时。夜班领班断开站库后，凭指定分析办理现场处置要求。次班核销员按作业员实际采用的原报告查漏报和误放行。项目使用 Python 3.11 标准库及 SQLite。

## 运行

```sh
python3 -B check_project.py
python3 -B -m unittest discover -s tests -t .
python3 -B demo.py
```

控制台物化时提供 `check_project.py`。演示读取 `samples/` 下的两份样例，在临时目录开站库与离线库。它依次登记分卷、提交计时更正、核对工时、冻结分析、关闭站库、办理现场申请、核销实际处置并重开离线库读取旧成果。输出中的 `POINTWISE_SCENARIO` 记录手算预期和实际结果。

## 站内接口

在空闲的 `sqlite3.Connection` 上依次调用 `BatchStore(conn).initialize()` 和 `AnalysisArchive(conn).initialize()`。初始化可以重复，已有修订和成果均会保留。站库与离线库使用各自的库文件。

- `batches.intake.put_batch(conn, batch_id, segments, public_segments, base_timings, changeovers=(), *, parent_revision_id=None)` 返回新修订号。`segments` 为有序 `Segment(segment_id)` 序列，公开范围按段号选取并沿用原序。每段须登记两条 `BaseTiming(timing_id, segment_id, disposition, amount, unit='work')`。`ChangeoverTiming(timing_id, start_segment, end_segment, amount, unit='work')` 保留原方向。时间记录号在修订中唯一，金额须为非负整数。省略父号时沿用该批当前修订，显式父号须属同批。`BatchStore.load_revision` 和 `load_current` 分别读固定号和当前修订。
- `costs.ledger.score_batch(conn, revision_id, policy_version, plan)` 接收覆盖全部站内段的 `{段号: 处置}`，返回 `ScoreResult`，其中 `total_work` 为整笔工时，`entries` 按原记录提供计分出处。处置取 `retest` 或 `release`。`work` 按原值计量。`line-v1` 的 `tick` 和 `cycle` 分别折为 2、5 工时单位，`bench-v1` 分别折为 3、5。未知口径或单位在建立计分依据时拒绝。附加只在起段复测且止段放行时计入。
- `analysis.publish.publish_analysis(conn, revision_id, policy_version)` 提交冻结和签发，返回带 `analysis_id`、`minimum_work` 和 JSON `artifact` 的 `SavedAnalysis`。`AnalysisArchive.load_analysis` 按固定号读回，后续更正可以另行发布。

## 离线接口

在另一份空闲连接上依次调用 `ReviewStore(conn).initialize()` 和 `ExecutionStore(conn).initialize()`。

- `review.imports.accept_analysis(conn, artifact)` 可以先接纳完整件。同号同内容可复用，键顺序和证据列表的排列不影响内容比较。同号异件拒绝。
- `review.decisions.review_plan(conn, requirements, *, analysis_id=None, artifact=None)` 须给定其中一种分析来源。`requirements` 可为段号到处置的映射或具名二元组序列，可以为空。每段至多指定一次。返回 `DecisionReport`，状态为 `approved` 或 `infeasible`。获准时 `plan` 是按原公开段序排列的完整二元组序列，不可行时 `plan` 为 `None`。空公开范围的获准计划是 `()`。
- `execution.closeout.close_execution(conn, report_id, actuals)` 使用获准报告和 `ActualDisposition(segment_id, disposition)` 序列。实际可以为空，按段号登记且不得重复。返回的 `ExecutionCloseout` 保存实际事实和按原计划顺序排列的 `findings`。缺报记为 `missing`，实际与计划不同记为 `different`。
- `review.reports.read_result(conn, result_id, *, report_id=None)` 按固定号读回报告或核销。读取核销时可指定父报告号，关联不符按缺件处理。同一报告可产生多份独立核销。

V1 JSON 分析件的外层字段为 `version`、`analysis_id`、`batch_id`、`revision_id`、`policy_version`、`minimum_work`、`public_segments` 和 `evidence`。当前证据使用 `forced_retest`、`forced_release` 和 `implications` 三个列表。蕴含条目 `[u, v]` 表示复测 u 要求复测 v。段号与顺序从原公开清单取得，最低工时是全批的结果。空公开清单允许唯一的空安排。外来件的生产方负责其与源台账的一致性，离线端可独立检查格式、端点及证据内部的一致性。

输入错误抛出 `ValueError`，未知固定号或关联抛出 `LookupError`。合法业务不可行返回固定决定。写入 API 管理自己的事务，调用时提供空闲连接。数据库错误由 SQLite 报出，提交失败时回滚本次写入。包和报告号用于关联，处置选择、工时及差异顺序由固定输入决定。
