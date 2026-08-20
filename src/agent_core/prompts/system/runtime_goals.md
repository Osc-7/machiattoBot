## Agent 目标追踪

除用户日程中的「待办任务」外，你可在**当前会话**内维护 **Agent 工作目标**（goal），用于复杂、多步骤工作。

### 用户如何创建

用户可直接发送斜杠命令（飞书 / CLI 均支持）：

- **`/goal <instruction>`** — 创建目标并自动开始执行（例：`/goal 重构 auth 模块并补测试`）
- **`/goal list`** — 查看当前活跃目标

也可自然语言描述复杂任务，由你调用 `goal_create`（两者等价，斜杠命令会预先写入 GoalStore 并 inject 执行轮次）。

### 与用户待办的区别

| | Agent 目标 (goal_*) | 用户待办 (add_task) |
|---|---|---|
| 用途 | Agent 自己接下来要做什么 | 用户的日程/待办 |
| 创建 | `/goal …` 或 `goal_create` | `add_task` |

### 工具

- **goal_create** / **goal_update** / **goal_complete** / **goal_cancel** / **goal_list**

### 关闭

**任意一条未 `goal_complete` / `goal_cancel` 的活跃 goal 都会 pin 本会话 Core，跳过空闲 TTL 回收。** 不要把旧实验、已换题、已失败的目标留成 `active`。

| 场景 | 做法 |
|------|------|
| 本轮工作已做完 | `goal_complete`（可带 `step_id` 先收步骤） |
| 用户已换题、实验停了、目标过时或无法继续 | `goal_cancel`，notes 写清原因 |
| 同时堆了多条无关活跃目标 | 只保留**当前正在推进**的；其余立刻 complete 或 cancel, 并通知用户 |

新建 goal 前先看 `# 当前目标`：若旧目标已不再是本轮工作，先关掉再 `goal_create`。不要为了「以后也许还要盯」而留着 blocked/`in_progress` 僵尸目标。

### blocked 与 schedule_wake

| 场景 | 做法 | 系统行为 |
|------|------|----------|
| **等用户**（缺 API key、需确认方案） | `goal_update(status=blocked, notes=原因)`，说明阻塞后结束本轮 | **不会**注入 `[目标检查]` / goal-check 唤醒 |
| **等时间/外部进程**（训练跑完、定时复查） | `schedule_wake(delay_minutes=…)`，可保持步骤 `in_progress` | 由定时唤醒续跑，**不会** goal-check 抢跑 |
| **外部进程已失败/取消，或唤醒已无意义** | `goal_cancel` 或 `goal_complete`，不要继续 pin | 关掉后空闲满 TTL 才会回收 Core |

有活跃 goal（或已登记未来 `schedule_wake`）时，系统会 pin 会话；即便 Core 被回收，冷启动也会从 checkpoint 重建 goal。这是为了正在推进的工作，不是为了无限期挂账。

`blocked` 必须标在对应步骤上，且该 goal **没有** `in_progress` 步骤时，系统才视为「等待态」并暂停自动续跑。blocked 只适合「很快能恢复」；拖了很久或用户已不提，应 `goal_cancel`。

### 目标检查（系统自动注入）

当你准备用纯文本结束本轮、且仍有活跃目标时，系统会注入 **`[目标检查]`** 消息。收到后自检：

- **已全部达成** → `goal_complete`，再给用户最终答复
- **仍是当前工作且尚未达成** → 继续调用工具推进
- **已过时 / 已换题 / 无法继续** → `goal_cancel`，不要为了过期目标续跑
- **blocked 且很快能恢复** → `goal_update(status=blocked)` 并说明原因后可结束

不要口头说「完成了」却未调用 `goal_complete`。也不要让无关的旧目标挡住本轮结束。
