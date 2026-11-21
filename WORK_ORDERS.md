# 按当班工位开单与核销

沿用 README.md 中的站内发布、离线接纳和离线库初始化。新增开单只使用已接纳的 V1 分析件，在源库关闭后办理。工位槽的独占范围是一份工作单。

## 开单

新增 `review.decisions.issue_work_order(conn, requirements, open_slots, compatibility, *, analysis_id)`。

- `analysis_id` 指定一份已经接纳的分析。`requirements` 沿用 `review_plan` 的段号到处置映射或二元组序列，可以为空。
- `open_slots` 是开放槽号序列，可为空。槽号沿用项目的具名标识规则，即非空、可打印且首尾无空白的字符串。槽号在清单中不得重复。
- `compatibility` 是 `(segment_id, disposition, slot_id)` 三元组序列。段必须公开，处置只能是 `release` 或 `retest`，槽必须在开放清单中。三元组不得重复，未列三元组不可用。多个段可以登记同一个候选槽。两个序列及其中的三元行均可用列表或元组传入。

只有同一份完整指派符合全批最低工时证据、指定处置和工位兼容，且每槽至多用一次，才可获准。分析件中的强制项和全部蕴含均适用。每个公开段恰有一项指派，多解任选。

返回对象有 `report_id`、`analysis_id`、`request`、`open_slots`、`compatibility`、`status` 和 `assignment` 属性。`request` 沿用 `ReviewRequest`。`open_slots` 和 `compatibility` 固定输入内容及顺序，以元组保存，兼容行也是元组。`status` 为 `approved` 或 `infeasible`。获准时 `assignment` 为原公开段序的 `(segment_id, disposition, slot_id)` 元组序列。合法不可行也保存报告，`assignment` 为 `None`。空公开清单的获准指派是 `()`。

## 核销及领取

新增 `execution.closeout.close_work_order(conn, report_id, actuals)`。`report_id` 指定一份获准的工位工作单。`actuals` 是 `(segment_id, disposition, slot_id)` 行组成的列表或元组，行也可用列表或元组表示。实际可以为空，同段不得重复，段须在原指派中，处置和槽名按开单时的类型校验。实际槽可以在原开放清单外，两个段报同一实际槽时照录事实。

返回对象有 `closeout_id`、`report_id`、`actuals` 和 `findings` 属性。`actuals` 按提交顺序保存为三元组的元组。`findings` 是 `(segment_id, kind)` 二元组的元组，按原指派段序排列。未报段只记 `missing`，已报段在处置不符时记 `disposition`，槽不符时记 `slot`。两差并存时同段先记 `disposition` 再记 `slot`。无差异时为 `()`。只和原工作单实际签出的指派核对。即使另一工位兼容，也以原指派判差。

沿用 `review.reports.read_result(conn, result_id, *, report_id=None)` 领取新旧报告和核销。给核销读回指定父报告号时，关联不符报 `LookupError`。重开后读回已存输入、指派、实际和偏差。V1 的分析件、处置报告、核销和入口继续可读写。原处置报告经 `close_execution` 核销，工位工作单经 `close_work_order` 核销。以已知报告调用另一类核销入口，或试图核销不可行工作单，均报 `ValueError`。

非法输入报 `ValueError`，未知固定号报 `LookupError`。调用写入入口时提供空闲连接。开单和核销各自原子提交，提交失败回滚本次成果，SQLite 错误原样传回，可重新调用。

## 样例与运行

`samples/slot_shift.json` 给出三组槽输入。`shared` 和 `alternate` 可用 `tests.test_workflow.put_bridge` 在已初始化的站库登记批次，按 `line-v1` 签发，关闭站库后用 `accept_analysis` 接纳。该件公开段序为 A、B，最低工时为 0，A 复测蕴含 B 复测。

设 `case` 是从样例文件读取的 `shared`，`accepted` 是 `accept_analysis` 的返回值，`offline` 是依 README.md 初始化的离线连接。新增入口的调用和手算值如下。

```python
from execution.closeout import close_work_order
from review.decisions import issue_work_order
from review.reports import read_result

order = issue_work_order(
    offline, {}, case['open_slots'], case['compatibility'],
    analysis_id=accepted.analysis_id,
)
assert order.status == 'approved'
assert order.assignment == (('A', 'release', 'L1'), ('B', 'retest', 'R1'))
closed = close_work_order(offline, order.report_id, case['actuals'])
assert closed.findings == (('A', 'slot'), ('B', 'missing'))
assert read_result(offline, closed.closeout_id, report_id=order.report_id) == closed
```

同一 `shared` 输入改为 `{'A': 'retest'}` 时，本来最低工时许可的两段复测会争用 R1，须签出 `infeasible`。`alternate` 可把 A 指派到 L1 或 L2，B 固定复测于 R1。先读 A 的实签槽，再将 A 的放行报在另一兼容槽且不报 B，应有 A 错槽和 B 缺报。若同时把 A 改报复测，A 的两类偏差都应保留。

`reassign` 的站内段序为 C、A、H-internal、B，公开段为 C、A、B。以 `put_bridge` 的同两条有向换序计时登记，基本工时仅 C 复测为 1，其余均为 0。最低工时为 0，额外强制 C 放行。空申请的唯一获准指派是 C 放行于 L2、A 放行于 L1、B 复测于 R1。撤下 L2 并删除其兼容行后，工作单不可行。

原运行清单的核验入口通过 `check_project.py` 发现原回归和新增测试，任一失败以非零状态退出。演示入口要实际展示断源开单、核销及重开领取。可沿用 `tests.test_workflow.refuse_commit` 模拟提交失败，例如在 `with refuse_commit(offline):` 内调用写入入口并检查其抛出的 `sqlite3.DatabaseError`，退出后核对成果并重试。
