# 任务规划

agent 处理复杂多步任务时，可以创建执行计划并逐步跟踪进度（PostgreSQL 持久化，重启不丢）。

## 工具

- `create_plan(title, steps[])`：拆解任务为步骤列表，返回 `plan_id`；
- `update_step(plan_id, seq, status)`：标记某步 `pending / in_progress / done / blocked`；
- `get_plan(plan_id)`：查看计划详情与各步骤状态；
- `complete_plan(plan_id)`：整个计划标记完成（未完成步骤一并置为 done）。

## 指令

- `/plan`：进入任务规划模式（系统提示强制"先 create_plan 再执行"），配合下一句任务描述使用；
- `/tasks`：查看进行中的计划与步骤进度；
- `/normal`：退出规划/上线模式。

## 置顶面板

- TUI 版（prompt_toolkit 全屏布局）中，计划面板是**独立的固定顶部窗格**：长输出再多也挤不走，`update_step` 后随重绘实时刷新；
- 面板最多显示 8 步，更多步骤折叠为"共 N 步"，完整进度用 `/tasks` 查看；
- 中间输出区**可滚动**（鼠标滚轮，或绑定 `Keys.ScrollUp/ScrollDown` 调 `Window._scroll_up/_scroll_down`）；
- 无进行中计划时顶部窗格自动收起；输入框上下键仍是历史导航。

## 存储

- `task_plans(id, title, status, created_at)`；
- `task_steps(id, plan_id, seq, description, status, updated_at)`，按 `(plan_id, seq)` 唯一。

## CLI（调试/手工管理）

```bash
python src/planner.py create "标题" 步骤1 步骤2 ...
python src/planner.py list
python src/planner.py show <plan_id>
python src/planner.py update <plan_id> <seq> <status>
python src/planner.py complete <plan_id>
python src/planner.py clear
```

## 说明

- 是否主动规划取决于模型判断；`/plan` 模式会注入强制指令，但个别模型仍可能跳过，**显式要求"先调用 create_plan"最可靠**；
- `update_step` 校验状态与步骤存在性，非法输入会返回错误而不破坏计划；
- 计划完成后退出的 active 列表，`/tasks` 只显示进行中的计划；历史计划可用 CLI `list`（全部）查看。
