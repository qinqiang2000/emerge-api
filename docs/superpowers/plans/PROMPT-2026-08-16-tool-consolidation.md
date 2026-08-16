# Plan-input prompt — 工具收敛（Cowork remote MCP P4）

> **这个文件是什么。** 喂给新会话的 **briefing**，由它先产出正式 plan
> (`docs/superpowers/plans/2026-08-16-tool-consolidation.md`)，用户签字后再按
> `feedback_default_execution_mode`（subagent-driven）执行。
>
> **不要照着这个文件直接改代码。** 里面有结论，也有需要你自己量的数——写
> plan 的第一步是量数据，不是抄这里的分组。

---

## 1. 背景：为什么现在做

2026-08-14 prod 事故复盘（见 INSIGHTS「A per-item read model with no set
projection」）之后，用户问了一句要害的话：**"是不是要有个通用点的接口，否则永远
有补不完的工具？"**

结论已经落地了一半：那次的缺口是 **投影**（`tools/doc_status.py` +
`get_surface_state` 集合形式，commit `76f56b2`），不是通用性——通用面已经有两个
（in-session 的 Bash / 远程的 `ws_*`）。判据写进了 CLAUDE.md：

> 已有名词的新问法 → 扩投影；新名词或新副作用 → 才加 typed tool；只读且形状
> 不可预知 → `ws_*` / Bash。**只回答单个元素的读模型是不完整的读模型。**

剩下的一半是本 milestone：**工具数量本身**。`app/tools/__init__.py` 现在有
**78 个 `@tool`**（CLAUDE.md 曾写 ~35，已改）。ROADMAP 里
`2026-06-08-cowork-remote-mcp.md` 的 **P4「工具收敛(38→~10 + per-tool
policy)」** 就是这件事——但那个 38 和 ~10 都是 6 月的数字，**已过期，先自己数**。

## 2. 目标

按**名词**归并成更少、更连贯的工具族，并让 policy 能按 `(noun, op)` 表达。
不是减少能力，是减少**表面**。

**非目标（写进 plan 的 non-goals，别漂移）：**

- ❌ 不做 mega-tool，不做通用 exec / query DSL。**动词可见性 = 能力可发现性**：
  模型看不见动词就想不起来有这个能力。已经有两个通用面了，第三个只会让同一件事
  有三种做法。
- ❌ 不并跨名词的东西。只并**同名词、同输入形状、同 policy**的。
- ❌ 不趁机改语义。这一轮是纯表面重构，任何行为变化单独立项。

## 3. 先量数据，再定分组

写 plan 之前必须拿到这三个数，plan 里要引用：

1. **真实调用频次**。prod 上有 28+ 项目的真实历史，本地 `backend/workspace` 也是
   真实租户数据（memory `project_local_workspace_is_real_tenant_data`）。扫
   `**/chats/*.jsonl` 统计 `tool_name` 频次 → 哪些工具从来没被调用过、哪些是主
   干。**该并谁、该删谁，是数据问题，不是审美问题。** prod 只读扫描，别写。
2. **当前各表面的实际大小**：in-session（全量 − `_HEADLESS_EXCLUDE`）、remote
   minimal（`app/mcp_server.py::_MINIMAL_SURFACE`）、full。
3. **每个工具的 policy 四元组**：它在 `_READ_ONLY` / `_DESTRUCTIVE` /
   `_IDEMPOTENT` / `_TOUCHES_PROVIDER` 里各占哪一格（`app/tools/__init__.py`
   顶部）。

一眼可见的候选族（**当作假设去验证，不是答案**）：
`set_{labeler,proposer,translate}_model` → `set_model(role=)`；
`score{,_audit,_match}`；`save_reviewed{,_audit,_match}`；
`history_{log,diff,restore}`；`{start,get,pause,resume,cancel}_job`；
`ui_{open_review,goto_page,set_active_*}`；
`{create,delete,rename,fork,list}_project`；`{list_trash,restore_from_trash}`。
`ws_*` **不要并**——它是仿 Bash/Read/Write 的通用总线，模型对这套动词已有先验，
并成 `ws(op=)` 是净损失。

## 4. 硬约束 / 一定会咬人的地方

**这一节是这个文件存在的理由。逐条在 plan 里给出对策，别靠现场发挥。**

1. **工具名是历史数据的一部分。** `chats/*.jsonl` 里存着 `tool_name` 原文。前端
   `lib/toolHint.ts` 按 bare name `switch` 出标签/摘要，`stores/chat.ts` 有 **34
   处** `mcp__emerge_tools__*` 常量做 store 失效分派。改名 = 历史会话渲染成未知
   工具 + 旧 chat 的失效逻辑失灵。**必须有 alias / legacy 映射层**，并且要有测试
   钉住"老名字仍能渲染"。
2. **policy 不能跟着名字一起融化。** 现在 `_DESTRUCTIVE` 等四个集合按工具名。
   `project(op='delete')` 若继承了 `project(op='list')` 的 read-only 注解，客户端
   就不再 gate 破坏性操作了 —— **这是安全回归，不是重构细节。** policy 必须能按
   `(noun, op)` 表达，且默认从严。
3. **`always_allow` 是按 tool_name 记的**（`chat/permissions.py::mark_always_allow`）。
   合并后用户点一次"总是允许 project 工具" = 顺带允许了 `delete_project`。要么
   按 `(noun, op)` 记，要么对破坏性 op 直接禁用 always。
4. **`test_symmetry_invariant.py` 会挡你。** 每个 `@tool` 必须有 HTTP 对应或进
   `_HTTP_EXEMPT`（带理由）。注意：**HTTP 侧不要跟着并**——REST 天然按资源+方法
   表达，`DELETE /lab/projects/{slug}` 就是 `project(op='delete')`，不需要 `op`
   参数化。所以 map 会从「1 工具 ↔ 1 路由」变成「1 (noun,op) ↔ 1 路由」，测试的
   断言形状要跟着改，别把它改松。
5. **skill markdown 成篇按名字讲工具**（`app/skills/emerge_extractor.md` 等，含
   §"这些工具 Bash 模仿不了"清单、remote minimal 的降级指引）。名字一改，agent 就
   叫不出新名字。skill 文本必须同 PR 改完，并且 dogfood 验证。
6. **上一次收敛已经出过事故，读它的墓志铭再动手。** `_MINIMAL_SURFACE` 的注释记
   着：第一版"按 suite 砍"是错的 taxonomy，几小时内就让 agent 在一个真实 audit
   请求下无合法路径可走，于是它用 `read_doc_image` 自己当裁判——踩了 agent
   self-audit 红线。**"少"如果砍掉的是唯一路径，那不是收敛是能力消失。**
7. **Chat 能完成一切 / 三形对称**（CLAUDE.md 人格红线）：合并后仍然要
   tool ↔ HTTP ↔ MCP 三形齐全，headless 可达。
8. **`_HEADLESS_EXCLUDE` + `_MINIMAL_SURFACE` 都按 bare name**，跟着改。

## 5. 交付物

- `docs/superpowers/plans/2026-08-16-tool-consolidation.md`（正式 plan，含上面的
  数据、分组决策表、alias 策略、policy 表设计、分阶段切分）。
- ROADMAP 加一行（P4 从 `2026-06-08-cowork-remote-mcp.md` 里独立出来）。
- 实现按**族**切 commit，一族一测，绝不一把梭。每族至少：新形状测试 + 老名字
  alias 测试 + policy 断言（破坏性 op 仍被标成破坏性）。
- INSIGHTS 追加一条：收敛的 taxonomy 判据（什么可以并、什么并了会丢能力），把
  `_MINIMAL_SURFACE` 那次事故和这次的结论收在一处。
- 全量测试绿：`cd backend && uv run pytest -q -n 4 --timeout=120`（当前基线
  1798 passed）；前端 `npx tsc -b --noEmit` + `npx vitest run`（`FSSpine-*` 的
  11 个失败是既有的，与本次无关）。

## 6. 开工顺序

1. 读 `CLAUDE.md`、`docs/superpowers/INSIGHTS.md`（尤其末尾两条 2026-08 的）、
   `docs/superpowers/plans/ROADMAP.md`、`2026-06-08-cowork-remote-mcp.md` §P4。
2. 量第 3 节的三个数。
3. 用 `superpowers:writing-plans` 产出 plan，**给用户签字**。
4. 签字后按 `superpowers:subagent-driven-development` 执行（用户默认，不用问）。
5. 发版走 `./deploy.sh`；停在 live browser smoke 之前交回人手 dogfood
   （memory `feedback_milestone_dogfood_handoff`）。
