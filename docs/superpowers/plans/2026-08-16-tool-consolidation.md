# 工具收敛（Cowork remote MCP P4）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 emerge 的工具表面按**名词**归并成更少、更连贯的族，同时补上「装了但没接线」的 9 个工具，并让「注册」而非「源码文本」成为对称契约的度量基准。

**Architecture:** 三段。① 先修 bug：9 个 `@tool` 有 HTTP 路由、有测试、有 skill 文本，却从未进 `create_sdk_mcp_server(tools=...)` 的列表——对任何 agent 都不存在；顺手把 `test_symmetry_invariant.py` 的 `_discover_tools()`（正则扫源码）换成扫**实际注册**，这正是漏检的根因。② 再按 8 个族做纯表面归并，每族一 commit，全部满足「同名词 + 同输入形状 + 同 policy + 成员里没有破坏性 op」。③ 别名只做**渲染侧**（前端读历史 jsonl），服务端不收旧名（沿用 `pre_label` 的先例：no deprecated alias）。

**Tech Stack:** Python 3.12 / FastAPI / `claude_agent_sdk` `@tool` / `mcp` 1.27.2 / pytest；前端 Vite + React 19 + TS + Zustand + vitest。

**Spec:** `docs/superpowers/plans/PROMPT-2026-08-16-tool-consolidation.md`（briefing）+ `docs/superpowers/plans/2026-06-08-cowork-remote-mcp.md` §P4。

---

## 0. 量到的数（本 plan 的全部论据）

三个数在动手前实测过，脚本见 `scratchpad/{measure_surfaces,scan_freq,combine}.py`（一次性，不入库）。

### 0.1 表面大小 —— 「78」是源码数，不是可达数

| 口径 | 数 | 怎么来的 |
|---|---|---|
| 源码里的 `@tool(` | **78** | `grep -c '^    @tool('` |
| **实际注册**（headless） | **69** | 真起 server 后 `tools/list` |
| 实际注册（浏览器 chat） | 59 | 同上，`headless=False` |
| headless full **listed** | 63 | 69 − 6 个 `_HEADLESS_EXCLUDE` |
| headless **minimal** listed | **41** | `_MINIMAL_SURFACE` 过滤后（remote 默认） |

**9 个工具装了 `@tool` 但从未进 `_tools` 列表**，因此对 chat / stdio / remote **三个面全部不存在**：

```
delete_doc  rename_doc  rename_project  list_trash  restore_from_trash
forget_memory  history_log  history_diff  history_restore
```

它们**每一个都有活的 HTTP 路由**（在 `_TOOL_HTTP_MAP` 里，见 §0.4），也有单测——但单测直接 import `app.tools.docs.delete_doc` 这样的模块函数，绕过了 MCP 注册。`test_symmetry_invariant.py::_discover_tools()` 用正则扫 `__init__.py` **源码文本**，所以 78 个装饰器全过，注册缺失完全隐形。

这不是新失败模式：`test_tool_registration.py::test_delete_project_registered` 的 docstring 写着 delete_project「its `@tool` decorator slipped past both the `tools=[...]` list … M11 T14's symmetry invariant surfaced the omission」——当时只给 `delete_project` 钉了一颗单点钉子，没升级成通用不变量，于是同样的事又发生了 9 次。

其中 4 个的缺席直接踩 INSIGHTS 红线：`delete_doc` / `rename_doc` / `rename_project` 是「读起来像 rm/mv 但不是」的三件（一个 doc 的 filename 是另外四份产物的主键），`forget_memory` 是第三件同类（退休一条 memory 必须同时移进 `_trash/` 且摘掉 `MEMORY.md` 那行）。它们不在表面上 = agent 只能用 Bash `rm`/`mv`，也就是 INSIGHTS 专门写条目防止的那个动作。`list_trash`/`restore_from_trash` 是「绝不物理删除」红线的恢复半边，缺席等于回收站是黑洞。

### 0.2 真实调用频次 —— 587(prod) + 177(local) chat 调用 + 145 MCP 调用

- **prod** `43.166.182.9:/root/emerge/backend/workspace`：47 个 chat jsonl，587 次 tool_call（只读扫描，未写盘）。注意 chat 落在**两处**：`_chats/`（未绑定）和 `{project}/chats/`（已绑定）——只扫 `_chats/` 会漏掉 39/47。
- **local** `backend/workspace`：28 个 chat，177 次。
- **MCP usage log**（`_usage/calls.jsonl`，只记 headless/remote，正是为 P4 埋的）：prod 133 + local 12 = 145 次，时间窗 **2026-06-09 → 06-12**（Cowork dogfood 那几天），22 个 distinct。样本窄，当**存在性证据**用，不当频次分布用。

合计 emerge 自家工具被调用 588 次。头部：

```
extract_one 147 · promote_attachment_to_docs 82 · extract_with_experiment 53
read_audit_report 30 · read_skill 29 · run_audit 27 · ws_list 26 · read_doc_image 25
write_schema 24 · create_experiment 15 · write_audit_rules 15 · create_project 14
```

**最重要的一行数据不是 emerge 工具：`Bash` 260 次，全场第一**（`Read` 42，`ws_*` 合计 44）。通用面已经在扛长尾——这是「不做第三个通用面」这条 non-goal 的实测依据，不是审美偏好。

**从未被调用：34/78。** 但这 34 个必须分三类读，混在一起就会犯 6 月那次的错：

| 类 | 数 | 例子 | 含义 |
|---|---|---|---|
| A. 不可达所以没人调 | 9 | `delete_doc` `forget_memory` `history_*` | **不是没人要，是叫不出来**（§0.1）→ Task 1 修 |
| B. 罕见但正确的 op | ~15 | `promote_experiment` `cancel_job` `switch_active_prompt` `run_experiment_eval` | 低频是它该有的样子；砍掉 = 能力消失 |
| C. 真·重复表面 | ~10 | `set_labeler_model` `set_proposer_model` `set_translate_model` `get_labeler_config` `ui_set_active_*` | 归并的正当目标 |

**「零调用」只对 C 类构成证据。** 6 月那次「按 suite 砍」正是把 B 当 C 处理，几小时内 agent 在真实 audit 请求下无合法路径，改用 `read_doc_image` 自己当裁判——踩 agent self-audit 红线（`_MINIMAL_SURFACE` 的注释是它的墓志铭）。

### 0.3 policy 四元组现状

`_READ_ONLY` 19 · `_DESTRUCTIVE` 5 · `_IDEMPOTENT` 17 · `_TOUCHES_PROVIDER` 13 · **无标注 19**。破坏性只有 5 个：`delete_project` `delete_doc` `freeze_version` `issue_api_key` `promote_experiment`。

### 0.4 耦合面（改名的爆炸半径）

| 位置 | 量 | 性质 |
|---|---|---|
| `app/skills/*.md` | **182 处**提名、50 个 distinct 名字（`emerge_extractor.md` 独占 131） | 名一改 agent 就叫不出来，必须同 PR 改 |
| `frontend/src/stores/chat.ts` | 34 处 `mcp__emerge_tools__*` 常量做 store 失效分派 | 其中 5 个已是**死常量**（`delete_experiment` `archive_experiment` `write_prompt` `upload_doc` `accept_candidate` 都已不存在） |
| `frontend/src/lib/toolHint.ts` | 21 个 `case` 出标签/摘要 | 按 bare name switch |
| `frontend/src/lib/groupChatEvents.ts` | `HOISTED_TOOL_NAMES` 8 个 | 卡片上浮 |
| `tests/unit/test_symmetry_invariant.py` | `_TOOL_HTTP_MAP` 72 + `_HTTP_EXEMPT` 6 = 78 | 正好等于源码装饰器数（= 它在量源码） |
| prod/local chat jsonl | 764 条 tool_call 存的是**旧名原文** | 只能靠渲染侧别名兜底 |

---

## Global Constraints

从 CLAUDE.md / briefing 逐字搬来，每个 task 都隐含这些要求：

- **Non-goal 1：不做 mega-tool / 通用 exec / query DSL。** 动词可见性 = 能力可发现性。已有两个通用面（in-session `Bash`、远程 `ws_*`），第三个只让同一件事有三种做法。
- **Non-goal 2：不并跨名词的东西。** 只并**同名词、同输入形状、同 policy**的。
- **Non-goal 3：不趁机改语义。** 纯表面重构；任何行为变化单独立项。本 plan 唯一的行为增量是 Task 1 的「让不可达变可达」和 Task 5 的 `env_default` 补字段，两处都显式标注。
- **红线 —— 破坏性 op 永不并进多 op 工具。** 见 §Policy 设计。
- **三形对称**：每个 `@tool` 必须有 HTTP 路由或进 `_HTTP_EXEMPT`（带理由），并自动继承进 `mcp_server.py`。**HTTP 侧不跟着并**——REST 天然按资源+方法表达，`DELETE /lab/projects/{slug}` 就是 `project(op='delete')`。map 从「1 工具 ↔ 1 路由」变成「1 (工具, op) ↔ 1 路由」，断言形状跟着改，**不许改松**。
- **Chat 能完成一切**；`ui_*` 在 headless 下叙述代替调用（`→ page N` / `→ focus field_name`），不能静默跳过；skill rendering contract 必须同时写 `browser` 和 `headless` 两个分支。
- **绝不物理删除用户数据**；本 plan 不新增根级 `_` sentinel 目录。
- **`_HEADLESS_EXCLUDE` + `_MINIMAL_SURFACE` 都按 bare name**，跟着改。
- 测试基线：`cd backend && uv run pytest -q -n 4 --timeout=120` → **1798 passed**；前端 `npx tsc -b --noEmit` + `npx vitest run`（`FSSpine-*` 11 个失败是既有的，与本次无关）。
- 中文注释/文案沿用仓库风格；错误响应 `{error_code, error_message_en}`。

---

## 实测约束：jsonschema 在 handler 之前跑（Task 4 暴露，约束 T7–T10）

MCP SDK 在把参数交给 handler **之前**就按声明的 inputSchema 校验一遍。实测：

```
set_model(role="agent_brain")
→ "Input validation error: 'agent_brain' is not one of ['extract','labeler','proposer','translate']"
```

handler 里那句 `if role not in _MODEL_ROLES: return _error_envelope("model_role_unknown", …)`
**永远走不到**，测它的用例也必然失败。两个选择，本 plan 选后者：

- ❌ schema 去掉 `enum`，留 handler 守卫 —— 为了一条更好看的错误信息，把**模型能看见的
  合法取值**从 `tools/list` 里删掉。schema 里的 enum 是**预防**（模型压根不会发错），
  handler 守卫只是**事后报告**。拿预防换报告是坏交易。
- ✅ **留 enum，删掉不可达的守卫，测试改为断言 schema 层的拒绝。**

**因此 T7/T8/T9/T10 一律遵守：**

| 守卫 | 可达? | 怎么办 |
|---|---|---|
| `score_kind_unknown`、`job_action_unknown`、`ui_target_unknown` | ❌ enum 已挡 | 不要写；测试断言 `Input validation error` |
| `board_kind_required` | ❌ `required` 已挡 | 同上 |
| `score_kind_arg_unsupported`（`use_llm_judge` 配非 extract kind） | ✅ | 保留 —— 「两个参数的组合非法」schema 表达不了 |
| `ui_value_invalid`（`value` 类型与 `target` 不匹配） | ✅ | 保留 —— 同上，`value` 声明成 `["string","integer"]`，按 target 的转型只能在代码里 |

判据一句话：**单个参数的取值能被 schema 表达 → 交给 schema，别写守卫；跨参数的组合约束
schema 表达不了 → 才写守卫。**

---

## Policy 设计（我的判断，不拿去签字）

briefing 假设「policy 必须能按 `(noun, op)` 表达」。**量完之后这个假设不成立，而且按它做会更差。** 理由：

1. **MCP annotation 是 per-tool-name 的。** 客户端（Cowork「Tool policy」、Desktop、claude.ai）的 auto-approve / gate **只能按工具名**。`project(op='delete')` 一旦存在，客户端只能整个 `project` 放行或整个拦——服务端再精细的 `(noun, op)` 表也**传不过去**。这不是「合并后要补一张表」，是**合并本身会结构性摧毁我们在 MCP best-practices pass 里刚立起来的 annotation 契约**。
2. `always_allow`（`chat/permissions.py::mark_always_allow`，进程内、按 `tool_name`、不落盘）同理：合并后一次「总是允许」会顺带盖住破坏性 op。

所以规则不是「让 policy 支持 (noun, op)」，而是**更强的一条**：

> **多 op 工具的所有 op 必须落在同一个 policy 桶里，且成员中不得有 `_DESTRUCTIVE` 成员。**

本 plan 选的 8 个族**全部天然满足**——这不是巧合，是「同 policy」那条准则在起作用。5 个破坏性工具全部保持独立单名。于是四个 frozenset 保持按名字，零改动，`always_allow` 按构造安全。落地为 Task 2 的一个不变量测试，比 `(noun, op)` 矩阵简单也强得多。

**Alias 策略（同样不签字）：渲染侧别名，服务端不收旧名。**

- 服务端：仓库先例是 no deprecated alias（`test_label_docs_tools_are_registered` 明写「Legacy `pre_label` must be gone — no deprecated alias」）。旧名直接消失。代价是一个**连着的** Cowork session 手里握着过期 tool list 会拿到 unknown tool——MCP 客户端会重新 `initialize`，是瞬时且可自愈的，写进发版说明即可。
- 前端：764 条历史 tool_call 存的是旧名，**必须**能渲染。做一个 `legacyToolName(bare) → bare` 归一化映射，`toolHint.ts` / `groupChatEvents.ts` / `stores/chat.ts` 三个消费点在入口处过一次。Task 3 先建，后续每族只往表里加一行。

---

## 分组决策表（Task 4–11 的施工图）

**合并（8 族，−14）**

| # | 旧工具 | → 新形状 | policy | Δ |
|---|---|---|---|---|
| 1 | `set_labeler_model` `set_proposer_model` `set_translate_model` `switch_active_model` | `set_model(slug, role, model_id)` role∈{extract,labeler,proposer,translate} | 全 idem | −3 |
| 2 | `get_labeler_config` `get_project_config` | `get_project_config(slug)`（已是超集，补 `env_default`） | 全 read | −1 |
| 3 | `extract_one` `extract_with_experiment` | `extract(slug, filename, experiment_id?)` | 全 prov | −1 |
| 4 | `score` `score_audit` `score_match` | `score(slug, kind, use_llm_judge?)` kind∈{extract,audit,match} | 全 prov | −2 |
| 5 | `pause_job` `resume_job` `cancel_job` | `control_job(job_id, action)` | 全 idem | −2 |
| 6 | `ui_goto_page` `ui_set_active_field` `ui_set_active_tab` `ui_set_active_entity` | `ui_focus(slug, filename, target, value)` target∈{page,field,tab,entity} | 全 idem | −3 |
| 7 | `render_audit_board` `render_review_board` | `render_board(slug, kind)` kind∈{audit,review} | 全 read | −1 |
| 8 | `history_log` `history_diff` | `history(op)` op∈{log,diff} | 全 read | −1 |

四条准则的逐族核对（每族的输入 schema 是实测的，不是估的）：

- ①：四个签名**逐字相同** `(slug*, model_id*)`，四个都 idem，四个都 0 调用。全表最干净的一并。
- ②：`get_project_config` 返回 `{active_prompt_id, extract, labeler, proposer, translate, agent_brain}`，每角色带 `{override, resolved, source}`，是 `get_labeler_config` 的 `{override, env_default, resolved, source}` 的超集**减一个 `env_default`**——并的时候补上，是本 plan 仅有的两处行为增量之一。
- ③：`(slug*, filename*)` vs `(slug*, experiment_id*, filename*)`，差一个可选参数——风险最低的一类并法。但它俩是全场最热（147+53），skill / FE 改动最多。
- ④：`(slug*, use_llm_judge?)` / `(slug*)` / `(slug*)`。返回 shape 不同，但准则约束的是**输入**形状。
- ⑤：三个签名逐字相同 `(job_id*)`，全 idem。`start_job`(prov, 不同 shape) / `get_job`(read) 留下。
- ⑥：四个都是 `(slug*, filename*, <单个值>)`，全 idem，全在 `_HEADLESS_EXCLUDE`。副产品：headless 叙述契约从四处收敛成一处。`ui_open_review` 是模式切换（且被调用过），留下。
- ⑦：都是 `(slug*)`，都零 LLM。`render_review_board` 的 description 自称「This is the structured-data twin of `render_audit_board`'s page-image circling」——是同一个名词的两种介质。**kind 显式传，不做按项目类型自动派发**（那是改语义）。
- ⑧：两个都 read-only。`history_restore` 是 mutate，**不并**（违反同 policy）。这族当前不可达，所以别名成本和历史成本都是零。

**明确不并（表里要有的「不并的理由」列）**

| 不并的 | 理由 |
|---|---|
| `save_reviewed` / `save_reviewed_audit` / `save_reviewed_match` | **输入形状分叉**：`entities:array` vs `expected:object` vs `expected+anchor_doc`。并了就是一个 union schema，模型得猜分支。同名词同 policy 但输入形状不同 → 准则说不并 |
| `delete_project` `delete_doc` `freeze_version` `issue_api_key` `promote_experiment` | 破坏性。客户端 gate 按名字，合并 = 安全回归（见 Policy 设计） |
| `create_project` / `create_match_project` / `fork_project` / `promote_chat_to_project` | 输入形状各不相同（`name` vs `name+anchor+sources` vs `src_slug+name` vs `chat_id+name`），语义也不同（新建/派生/收养）。且 `create_project` 是第一入口动词，藏进 `op=` 是纯损失 |
| `ws_*` 六件 | briefing 明令。它是仿 Bash/Read/Write 的通用总线，模型对这套动词有先验，并成 `ws(op=)` 是净损失 |
| `run_audit` / `run_match` / `run_experiment_eval` / `label_docs` | 名词不同（audit / match / experiment / labels），shape 也不同 |
| `readiness_check` / `contract_diff` / `bench_view` | shape 都是 `(slug)`，但是三个不同的读，输出不同。同形状 ≠ 同名词 |
| `write_schema` / `write_audit_rules` / `write_match_prompt` | 名词不同（字段表 / 审单规则 / 匹配 prompt） |
| `extract_textlayer` / `translate_page` | 页级派生，两个不同名词 |
| `read_doc_image` / `pdf_render_page` | 一个返回 inline image blocks（doc vision pull 红线），一个返回**路径**。消费者不同 |
| `list_trash` + `restore_from_trash`；`history_restore` | 族内 policy 混合（read + mutate）。先修可达性，攒到数据再判 |

**砍掉 / 不再 list**：**本轮不新增任何 cut。** 现有 `_MINIMAL_SURFACE` 已经把 remote 面从 63 压到 41，那是**便宜杠杆**（只改 listing，不改名、不要别名、不碎历史）。再往下砍就要碰 §0.2 的 B 类，而 B 类正是 6 月出事的地方。Task 12 只做**重算**：把 8 族的新名替换进去，并给 Task 1 复活的 9 个定 listing（`delete_doc`/`rename_doc`/`forget_memory` 进 minimal——它们是 Bash 会做错的那三件；`list_trash`/`restore_from_trash`/`rename_project`/`history` 只进 full）。

**目标数**

| 口径 | 现在 | Task 1 后 | 收敛后 |
|---|---|---|---|
| 源码 `@tool` | 78 | 78 | **64** |
| **实际可达** | **69** | **78** | **64** |
| 浏览器 chat listed | 59 | 68 | **54** |
| headless full listed | 63 | 72 | **61** |
| **headless minimal listed（Cowork 实际看见）** | **41** | 44 | **41** |

> minimal 面**净不变**，这不是算错：8 族里只有 3 族的成员真的同时躺在 minimal 里
> （`extract_one`+`extract_with_experiment` −1、`score`+`score_audit`+`score_match`
> −2），其余族的成员大多本来就没 list；再加上 Task 1 复活的三件红线工具
> （`delete_doc`/`rename_doc`/`forget_memory`）+3。**41 − 3 + 3 = 41。**
> 这恰恰是本 plan 的论点本身：**归并省的是 chat 面和 full 面的表面，remote 面
> 的 context 税早就被 listing 收走了。** 想再压 remote 面只有继续 cut 一条路，
> 而那条路上站着 6 月的墓碑。

> **必须坦白的一句：这不是 6 月写的「38 → ~10」。** 那个目标当时就基于错的数（38 是彼时的 listed 数），而且量完之后它是**错的目标**：Bash 260 次已经在扛长尾，remote 面早被 listing 压到 41，唯一一次照「~10」的方向硬砍（按 suite）几小时内就砍没了唯一合法路径。真实可收的表面重复只有 14 个，其余「多」出来的是罕见但正确的动词。**本 milestone 的大头其实是那 9 个不可达工具和那条量错东西的不变量，归并是小头。** ROADMAP 的 P4 描述要跟着改（Task 12）。

---

## File Structure

| 文件 | 责任 | 变更 |
|---|---|---|
| `backend/app/tools/__init__.py` | 全部 `@tool` 定义 + policy 四集合 + `_tools` 注册列表 | 每族改；Task 1 补 9 个注册 |
| `backend/app/tools/_merged.py` | **新建**。`_MERGED_TOOLS: dict[str, tuple[str, ...]]` 声明「新名 → 它吃掉的旧名」，单一真相，被 policy 不变量、symmetry map、前端别名生成三方读 | 新建 + 每族加一行 |
| `backend/app/mcp_server.py` | `_HEADLESS_EXCLUDE` / `_MINIMAL_SURFACE` | 跟着改名；Task 12 重算 |
| `backend/tests/unit/test_symmetry_invariant.py` | 三形对称 | `_discover_tools()` 改扫注册；`_TOOL_HTTP_MAP` 改 `(tool, op) → route` |
| `backend/tests/unit/test_tool_registration.py` | 注册不变量 | 加通用不变量（装饰器 ⊆ 注册） |
| `backend/tests/unit/test_tool_policy.py` | **新建**。policy 不变量 | 多 op 工具同桶 + 无破坏性成员 |
| `backend/app/skills/*.md` | 4 个 skill，182 处提名 | 每族同 PR 改 |
| `frontend/src/lib/legacyToolName.ts` | **新建**。旧名 → 新名归一化 | 新建 + 每族加行 |
| `frontend/src/lib/toolHint.ts` / `groupChatEvents.ts` / `stores/chat.ts` | 三个消费点 | 入口处过归一化；清 5 个死常量 |
| `docs/superpowers/INSIGHTS.md` | trap notes | 追加收敛 taxonomy 判据 |
| `docs/superpowers/plans/ROADMAP.md` | milestone 表 | P4 独立成行 |

---

### Task 1: 注册不变量 + 复活 9 个不可达工具

**这个 task 必须第一个做**：它改的是后面每个 task 的分母，而且在此之前 `_discover_tools()` 量的是源码文本，任何「工具还在吗」的断言都不可信。

**Files:**
- Modify: `backend/app/tools/__init__.py:2549-2614`（`_tools` 列表）
- Modify: `backend/tests/unit/test_symmetry_invariant.py:194-208`（`_discover_tools`）
- Modify: `backend/tests/unit/test_tool_registration.py`
- Test: `backend/tests/unit/test_tool_registration.py`

**Interfaces:**
- Produces: `app.tools.registered_tool_names(headless: bool = True) -> frozenset[str]` —— 真起一次 `build_emerge_mcp` 并读 `tools/list`，返回 bare 名字集合。后续所有 task 和 `test_symmetry_invariant` 都用它，不再用正则。

- [ ] **Step 1: 写失败的测试 —— 装饰器必须等于注册**

在 `backend/tests/unit/test_tool_registration.py` 末尾追加：

```python
async def test_every_decorated_tool_is_actually_registered() -> None:
    """A `@tool` decorator that never lands in the `tools=[...]` list passed to
    `create_sdk_mcp_server` is invisible to EVERY surface — chat, stdio, remote —
    while still satisfying the symmetry invariant (which used to scan source
    text). That is how nine tools with live HTTP routes, unit tests and skill
    prose ended up unreachable. `test_delete_project_registered` pinned exactly
    one name against this; this is the general form."""
    import re
    from pathlib import Path

    import app.tools as tools_pkg
    from app.tools import registered_tool_names

    src = Path(tools_pkg.__file__).resolve().read_text(encoding="utf-8")
    decorated = set(re.findall(r'@tool\(\s*"([a-z_][a-z0-9_]*)"', src))
    registered = registered_tool_names(headless=True)

    missing = decorated - registered
    assert not missing, (
        f"@tool decorated but never registered (invisible to every agent): "
        f"{sorted(missing)}. Append the t_* function to the `_tools` list in "
        f"build_emerge_mcp."
    )
```

- [ ] **Step 2: 跑，确认它失败**

```bash
cd backend && uv run pytest tests/unit/test_tool_registration.py::test_every_decorated_tool_is_actually_registered -v
```

Expected: FAIL — 先是 `ImportError: cannot import name 'registered_tool_names'`。

- [ ] **Step 3: 加 `registered_tool_names()` helper**

在 `backend/app/tools/__init__.py` 底部，`_emerge_tool_names()` 旁边加：

```python
def registered_tool_names(*, headless: bool = True) -> frozenset[str]:
    """Bare names of the tools ACTUALLY handed to ``create_sdk_mcp_server``.

    The contract-checking tests must measure registration, not source text: a
    `@tool` decorator that never reaches the `tools=[...]` list is invisible to
    every agent while still matching a source-scanning regex. Builds a throwaway
    server with dummy collaborators — no tool body runs, so the stubs are never
    touched.
    """
    import asyncio
    import tempfile

    from mcp.types import ListToolsRequest

    cfg = build_emerge_mcp(
        workspace=Path(tempfile.gettempdir()),
        provider=cast(Any, object()),
        job_runner=cast(Any, object()),
        headless=headless,
    )
    handler = cfg["instance"].request_handlers[ListToolsRequest]
    result = asyncio.run(handler(ListToolsRequest(method="tools/list")))
    return frozenset(
        t.name.removeprefix(SERVICE_PREFIX) for t in result.root.tools
    )
```

文件顶部 import 补 `cast`（`from typing import Any, cast`，按现有 import 行改）。

- [ ] **Step 4: 再跑，确认失败换成了真正的断言失败**

```bash
cd backend && uv run pytest tests/unit/test_tool_registration.py::test_every_decorated_tool_is_actually_registered -v
```

Expected: FAIL，列出 9 个名字：`['delete_doc', 'forget_memory', 'history_diff', 'history_log', 'history_restore', 'list_trash', 'rename_doc', 'rename_project', 'restore_from_trash']`

- [ ] **Step 5: 把 9 个补进 `_tools`**

`backend/app/tools/__init__.py` 的 `_tools = [...]`（约 2549 行），在 `t_delete_project,` 之后插入：

```python
            # Reachability restored 2026-08-16 (P4 Task 1). These nine carried
            # `@tool`, a live HTTP route and unit tests, but never reached this
            # list — invisible to chat, stdio and remote alike. The first four
            # are the "reads like an rm/mv wrapper but isn't" family INSIGHTS
            # warns about: a doc's filename is the primary key of four other
            # artifacts, a project's folder name is mirrored in project.json +
            # the pid index, and retiring a memory must trash the body AND drop
            # its MEMORY.md line in one step — Bash gets all four wrong.
            t_delete_doc,
            t_rename_doc,
            t_rename_project,
            t_forget_memory,
            # Recovery half of the never-physically-delete red line; without
            # them `_trash/` is a black hole.
            t_list_trash,
            t_restore_from_trash,
            # Schema version history (log/diff read-only, restore mutates).
            t_history_log,
            t_history_diff,
            t_history_restore,
```

- [ ] **Step 6: 跑，确认通过**

```bash
cd backend && uv run pytest tests/unit/test_tool_registration.py -v
```

Expected: PASS（含新不变量）。

- [ ] **Step 7: 把 `_discover_tools()` 从扫源码改成扫注册**

`backend/tests/unit/test_symmetry_invariant.py`，替换 `_discover_tools`（194-208 行）：

```python
def _discover_tools() -> set[str]:
    """Tools ACTUALLY registered on the MCP server.

    Was: a regex over `__init__.py` source text. That measured the wrong thing —
    nine tools kept their `@tool` decorator (so the regex matched) while never
    reaching the `tools=[...]` list, so they had HTTP twins mapped here for
    functions no agent could call. Registration is the contract; source text is
    not. See test_tool_registration::test_every_decorated_tool_is_actually_registered.
    """
    from app.tools import registered_tool_names

    return set(registered_tool_names(headless=True))
```

`import re` 若无其他使用者一并删掉。

- [ ] **Step 8: 跑对称测试**

```bash
cd backend && uv run pytest tests/unit/test_symmetry_invariant.py -v
```

Expected: PASS 全部。（9 个工具的 `_TOOL_HTTP_MAP` 条目原本就在，现在从「映射了一个不存在的工具」变成「映射了一个真工具」。）

- [ ] **Step 9: 补一条断言，钉住「这 9 个在 headless 面上」**

追加到 `test_tool_registration.py`：

```python
async def test_filesystem_lookalike_tools_are_reachable() -> None:
    """delete_doc / rename_doc / rename_project / forget_memory read like rm/mv
    wrappers but aren't (INSIGHTS: filename is the primary key of four sibling
    artifacts; MEMORY.md index and note body must move together). If they leave
    the surface again the agent falls back to Bash rm/mv and silently corrupts
    the set — the exact failure those tools exist to prevent."""
    from app.tools import registered_tool_names

    names = registered_tool_names(headless=True)
    for n in (
        "delete_doc", "rename_doc", "rename_project", "forget_memory",
        "list_trash", "restore_from_trash",
        "history_log", "history_diff", "history_restore",
    ):
        assert n in names, f"{n} fell off the registration list again"
```

- [ ] **Step 10: 跑后端全量，确认零回归**

```bash
cd backend && uv run pytest -q -n 4 --timeout=120
```

Expected: 1798 + 2 passed（基线 1798，新增 2 个测试），0 failed。

- [ ] **Step 11: Commit**

```bash
git add backend/app/tools/__init__.py backend/tests/unit/test_tool_registration.py backend/tests/unit/test_symmetry_invariant.py
git commit -m "$(cat <<'EOF'
fix(tools): 九个工具装了但没接线 —— 不变量改量注册，别量源码文本

@tool 装饰器 ⊄ create_sdk_mcp_server(tools=[...])。delete_doc / rename_doc /
rename_project / forget_memory / list_trash / restore_from_trash / history_*
九个有 HTTP 路由、有单测、skill 里也写着，却对 chat/stdio/remote 三个面
全部不存在。单测直接 import 模块函数绕过了注册；symmetry invariant 用正则
扫源码文本，78 个装饰器全过。

_discover_tools() 改为真起 server 读 tools/list；加通用不变量把
test_delete_project_registered 那颗单点钉子升级成全集。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 合并声明表 + policy 不变量

**Files:**
- Create: `backend/app/tools/_merged.py`
- Create: `backend/tests/unit/test_tool_policy.py`

**Interfaces:**
- Produces: `app.tools._merged.MERGED_TOOLS: dict[str, tuple[str, ...]]` —— `{新名: (被吃掉的旧名, ...)}`，Task 4–11 每族加一行。被 policy 不变量、`_TOOL_HTTP_MAP` 形状测试、前端别名表三方消费，是「哪些名字并去了哪」的唯一真相。
- Produces: `app.tools._merged.MERGED_POLICY: dict[str, frozenset[str]]` —— `{新名: 该族共有的 policy profile}`，取值是 `{"read_only","destructive","idempotent","touches_provider"}` 的子集。**必须有这张表**：合并落地后旧名已从四个 frozenset 里删掉了，`_profile("set_labeler_model")` 会返回空集，「成员同桶」变成永远真的空断言。把共有 profile 显式声明出来，「同 policy」这条准则才是永久可查的。
- Produces: `app.tools._merged.legacy_alias() -> dict[str, str]` —— 反向展开 `{旧名: 新名}`。
- Produces: `app.tools._error_envelope(code: str, message: str) -> dict[str, Any]` —— 仓库里**没有**通用错误信封 helper（只有 `_chat_not_bound_error` / `_extract_provider_error` 两个专用的，其余 ~15 处是内联字面量）。Task 4–11 的新工具都要报 `*_unknown` / `*_unsupported`，统一走它。**只给新工具用，不回头改那 15 处内联** —— 那是另一件事。

- [ ] **Step 0: 加通用错误信封 helper**

`backend/app/tools/__init__.py`，紧跟 `_chat_not_bound_error` 之后：

```python
def _error_envelope(code: str, message: str) -> dict[str, Any]:
    """The house `{ok, error:{error_code, error_message_en}}` shape, as a tool
    result. Introduced with the P4 merges: a multi-op tool has to reject an
    unknown or inapplicable op, and inlining that dict at every new call site
    is how the shape drifts. Existing inline sites are deliberately left alone.
    """
    return {
        "content": [{
            "type": "text",
            "text": _json.dumps(
                {"ok": False, "error": {
                    "error_code": code, "error_message_en": message,
                }},
                ensure_ascii=False,
            ),
        }]
    }
```

- [ ] **Step 1: 建 `_merged.py`（先只放空表 + 两个函数）**

```python
"""Single source of truth for P4 tool consolidation: which old tool names were
folded into which new one.

Three consumers read this and MUST NOT keep their own copies:
- ``tests/unit/test_tool_policy.py`` — every op of a merged tool shares one
  policy bucket, and no merged tool may swallow a destructive op.
- ``tests/unit/test_symmetry_invariant.py`` — a merged tool maps
  ``(tool, op) -> route``, because REST already expresses ops as resource+verb
  and the HTTP side deliberately does NOT merge.
- ``frontend/src/lib/legacyToolName.ts`` — 764 historical tool_call records in
  chats/*.jsonl store the OLD names; they still have to render.

The server does NOT accept old names (no deprecated alias — same posture as
`pre_label`). Aliasing here is a RENDERING concern only.
"""
from __future__ import annotations

MERGED_TOOLS: dict[str, tuple[str, ...]] = {}

# The policy profile the whole family shared, declared per merged tool.
# Declared rather than derived: once a merge lands, the old names are gone from
# the four frozensets, so deriving "did the members agree?" from them would be a
# vacuously-true check over empty sets. Keys must match MERGED_TOOLS exactly.
MERGED_POLICY: dict[str, frozenset[str]] = {}


def legacy_alias() -> dict[str, str]:
    """``{old_name: new_name}`` — the flattened inverse of ``MERGED_TOOLS``."""
    return {
        old: new for new, olds in MERGED_TOOLS.items() for old in olds
    }
```

- [ ] **Step 2: 写 policy 不变量测试（现在为空表，必然通过；下一步用假数据验证它真的会失败）**

`backend/tests/unit/test_tool_policy.py`：

```python
"""Policy invariants for merged (multi-op) tools.

The briefing assumed policy would have to become expressible per ``(noun, op)``.
It must not: MCP tool annotations are per tool NAME, and that is the only thing
a client's auto-approve / destructive-gate can key on. A server-side
``(noun, op)`` table cannot be transmitted, so ``project(op='delete')`` would
leave Cowork able only to allow or block the whole tool. `always_allow`
(chat/permissions.py, keyed by tool_name) has the same shape.

So the rule is stronger and simpler than a matrix: every op of a merged tool
shares one policy bucket, and a merged tool never swallows a destructive op.
"""
import pytest

from app.tools import (
    _DESTRUCTIVE,
    _IDEMPOTENT,
    _READ_ONLY,
    _TOUCHES_PROVIDER,
    registered_tool_names,
)
from app.tools._merged import MERGED_POLICY, MERGED_TOOLS, legacy_alias

_BUCKETS = {
    "read_only": _READ_ONLY,
    "destructive": _DESTRUCTIVE,
    "idempotent": _IDEMPOTENT,
    "touches_provider": _TOUCHES_PROVIDER,
}

# The five irreversible / outward-facing verbs. Each must keep a standalone
# name: an MCP client's destructive-gate keys on the tool name, so any of these
# folded into a multi-op tool becomes un-gateable from the client side.
_MUST_STAY_STANDALONE = frozenset({
    "delete_project", "delete_doc",
    "freeze_version", "issue_api_key", "promote_experiment",
})


def _profile(name: str) -> frozenset[str]:
    return frozenset(b for b, s in _BUCKETS.items() if name in s)


def test_destructive_tools_stay_standalone() -> None:
    """A client gates on the tool NAME. Folding delete_* into a multi-op tool
    silently un-gates it — a safety regression, not a refactoring detail."""
    assert _MUST_STAY_STANDALONE <= _DESTRUCTIVE, (
        "a verb left _DESTRUCTIVE without this list being revisited: "
        f"{sorted(_MUST_STAY_STANDALONE - _DESTRUCTIVE)}"
    )
    live = registered_tool_names(headless=True)
    assert _MUST_STAY_STANDALONE <= live, (
        f"destructive verb missing from the surface: "
        f"{sorted(_MUST_STAY_STANDALONE - live)}"
    )
    swallowed = sorted(
        old for olds in MERGED_TOOLS.values() for old in olds
        if old in _MUST_STAY_STANDALONE
    )
    assert not swallowed, (
        f"destructive op(s) folded into a multi-op tool: {swallowed}"
    )


def test_no_merged_tool_is_destructive() -> None:
    for new in MERGED_TOOLS:
        assert new not in _DESTRUCTIVE, (
            f"{new!r} is a merged multi-op tool and must not be destructive: a "
            f"client can only allow or block the whole name."
        )
        assert "destructive" not in MERGED_POLICY.get(new, frozenset())


def test_merged_tool_matches_its_declared_policy_profile() -> None:
    """'Same policy' is one of the four merge criteria. Declared, not derived:
    after a merge the old names are gone from the four frozensets, so deriving
    "did the members agree?" would be a vacuous check over empty sets."""
    assert set(MERGED_POLICY) == set(MERGED_TOOLS), (
        f"MERGED_POLICY and MERGED_TOOLS disagree on which tools are merged: "
        f"only in MERGED_TOOLS {sorted(set(MERGED_TOOLS) - set(MERGED_POLICY))}, "
        f"only in MERGED_POLICY {sorted(set(MERGED_POLICY) - set(MERGED_TOOLS))}"
    )
    for new, declared in MERGED_POLICY.items():
        unknown = declared - set(_BUCKETS)
        assert not unknown, f"{new!r} declares unknown bucket(s) {sorted(unknown)}"
        assert _profile(new) == declared, (
            f"{new!r} is annotated {sorted(_profile(new))} but its family's "
            f"declared shared profile is {sorted(declared)}."
        )


def test_old_names_are_gone_from_the_server() -> None:
    """No deprecated alias on the wire (same posture as `pre_label`). The alias
    lives only in the frontend's history renderer."""
    live = registered_tool_names(headless=True)
    lingering = sorted(set(legacy_alias()) & live)
    assert not lingering, (
        f"Old tool names still registered: {lingering}. Remove the old @tool "
        f"definitions; history rendering is handled in legacyToolName.ts."
    )


def test_merged_targets_are_registered() -> None:
    live = registered_tool_names(headless=True)
    missing = sorted(set(MERGED_TOOLS) - live)
    assert not missing, f"MERGED_TOOLS names a tool nobody registered: {missing}"
```

- [ ] **Step 3: 用一条假数据验证不变量真的会失败**

一个不变量在空表下通过什么都没证明。临时改成：

```python
MERGED_TOOLS = {"project": ("create_project", "delete_project")}
MERGED_POLICY = {"project": frozenset({"idempotent"})}
```

```bash
cd backend && uv run pytest tests/unit/test_tool_policy.py -v
```

Expected: `test_destructive_tools_stay_standalone` FAIL（`destructive op(s) folded into a multi-op tool: ['delete_project']`）、`test_merged_tool_matches_its_declared_policy_profile` FAIL（`project` 没被注册所以 profile 是空集 ≠ `{idempotent}`）、`test_merged_targets_are_registered` FAIL、`test_old_names_are_gone_from_the_server` FAIL。**四个都失败才算这层网是活的**；只要有一个意外通过，先查那个测试是不是写空了。确认后把两张表都改回 `{}`。

- [ ] **Step 4: 跑，确认空表下全绿**

```bash
cd backend && uv run pytest tests/unit/test_tool_policy.py -v
```

Expected: 5 passed。

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/_merged.py backend/app/tools/__init__.py backend/tests/unit/test_tool_policy.py
git commit -m "$(cat <<'EOF'
chore(tools): 合并声明表 + policy 不变量 —— 破坏性 op 永不并进多 op 工具

briefing 假设 policy 要按 (noun, op) 表达。不成立：MCP annotation 按工具名，
客户端 gate 只能按名字，(noun,op) 表根本传不过去。always_allow 同理。
所以规则更强也更简单——多 op 工具的所有 op 同桶、且不含破坏性成员，
四个 frozenset 保持按名字零改动。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 前端历史渲染别名层

764 条历史 `tool_call` 存的是旧名。服务端不收旧名，但前端**必须**能渲染它们。

**Files:**
- Create: `frontend/src/lib/legacyToolName.ts`
- Create: `frontend/src/lib/legacyToolName.test.ts`
- Modify: `frontend/src/lib/toolHint.ts:29`（`const bare = ...`）
- Modify: `frontend/src/lib/groupChatEvents.ts`
- Modify: `frontend/src/stores/chat.ts`

**Interfaces:**
- Produces: `canonicalToolName(toolName: string): string` —— 剥 `mcp__emerge_tools__` / `emerge_` 前缀并把旧名映射到新名，返回 bare 新名。
- Produces: `LEGACY_TOOL_NAMES: Record<string, string>` —— 与 `_merged.py::MERGED_TOOLS` 手工对齐，Task 4–11 每族加行。

- [ ] **Step 1: 写失败的测试**

`frontend/src/lib/legacyToolName.test.ts`：

```ts
import { describe, expect, it } from 'vitest'
import { canonicalToolName, LEGACY_TOOL_NAMES } from './legacyToolName'

describe('canonicalToolName', () => {
  it('strips the chat-surface prefix', () => {
    expect(canonicalToolName('mcp__emerge_tools__extract_one')).toBe('extract_one')
  })

  it('strips the headless service prefix', () => {
    expect(canonicalToolName('emerge_ws_list')).toBe('ws_list')
  })

  it('leaves SDK built-ins alone', () => {
    expect(canonicalToolName('Bash')).toBe('Bash')
    expect(canonicalToolName('Read')).toBe('Read')
  })

  it('passes unknown names through unchanged', () => {
    expect(canonicalToolName('mcp__emerge_tools__some_future_tool'))
      .toBe('some_future_tool')
  })

  it('maps every legacy entry to a different, non-empty name', () => {
    for (const [oldName, newName] of Object.entries(LEGACY_TOOL_NAMES)) {
      expect(newName).toBeTruthy()
      expect(newName).not.toBe(oldName)
      expect(canonicalToolName(`mcp__emerge_tools__${oldName}`)).toBe(newName)
    }
  })
})
```

- [ ] **Step 2: 跑，确认失败**

```bash
cd frontend && npx vitest run src/lib/legacyToolName.test.ts
```

Expected: FAIL — `Failed to resolve import "./legacyToolName"`。

- [ ] **Step 3: 实现**

`frontend/src/lib/legacyToolName.ts`：

```ts
/**
 * Historical chats store the tool name that was live when the turn ran — 764
 * of them across prod + local as of 2026-08-16. P4 folded several tools into
 * multi-op ones and the server no longer answers to the old names, so the
 * renderer is the only thing that can still make old transcripts legible.
 *
 * Keep in sync with `backend/app/tools/_merged.py::MERGED_TOOLS` (one entry per
 * swallowed old name). This map is RENDER-ONLY — never send these names back
 * to the server.
 */
export const LEGACY_TOOL_NAMES: Record<string, string> = {
  // filled in per family by P4 Tasks 4-11
}

const CHAT_PREFIX = 'mcp__emerge_tools__'
const SERVICE_PREFIX = 'emerge_'

/** Bare, current-generation tool name for any recorded tool_name. */
export function canonicalToolName(toolName: string): string {
  let bare = toolName
  if (bare.startsWith(CHAT_PREFIX)) bare = bare.slice(CHAT_PREFIX.length)
  else if (bare.startsWith(SERVICE_PREFIX)) bare = bare.slice(SERVICE_PREFIX.length)
  return LEGACY_TOOL_NAMES[bare] ?? bare
}
```

- [ ] **Step 4: 跑，确认通过**

```bash
cd frontend && npx vitest run src/lib/legacyToolName.test.ts
```

Expected: PASS (5)。

- [ ] **Step 5: 接进 `toolHint.ts`**

把 `unsafeToolInputHint` 里的
```ts
const bare = toolName.replace(/^mcp__emerge_tools__/, '')
```
换成
```ts
const bare = canonicalToolName(toolName)
```
`unsafeToolShortHint` 里同样的一行也换掉，文件顶部加 `import { canonicalToolName } from './legacyToolName'`。

- [ ] **Step 6: 接进 `groupChatEvents.ts`**

`HOISTED_TOOL_NAMES` 从存全名改成存 bare 新名，比较处过归一化：

```ts
import { canonicalToolName } from './legacyToolName'

const HOISTED_TOOL_NAMES = new Set([
  'start_job', 'readiness_check', 'issue_api_key', 'score',
  'save_reviewed', 'run_audit', 'render_review_board',
])
// …
if (HOISTED_TOOL_NAMES.has(canonicalToolName(e.tool_name))) {
```
（`score_audit` 原本单列，Task 7 并进 `score` 后由归一化自动覆盖；本步先保持行为等价——把 `score_audit` 也放进集合。）

- [ ] **Step 7: 接进 `stores/chat.ts` 并清掉 5 个死常量**

store 失效分派处的 `mcp__emerge_tools__X` 字面量改为对 `canonicalToolName(toolName)` 的 bare 比较。同时删掉已不存在的工具的分支：`delete_experiment` `archive_experiment` `write_prompt` `upload_doc` `accept_candidate`（这 5 个工具在 Step B 就被砍了，分支是死代码）。

- [ ] **Step 8: 跑前端测试 + 类型**

```bash
cd frontend && npx tsc -b --noEmit && npx vitest run
```

Expected: tsc 干净；vitest 除既有的 11 个 `FSSpine-*` 失败外全绿。

- [ ] **Step 9: Commit**

```bash
git add frontend/src/lib/legacyToolName.ts frontend/src/lib/legacyToolName.test.ts \
        frontend/src/lib/toolHint.ts frontend/src/lib/groupChatEvents.ts frontend/src/stores/chat.ts
git commit -m "$(cat <<'EOF'
feat(chat): 历史会话的旧工具名仍渲染 —— 靠一层归一化，不靠服务端收旧名

764 条历史 tool_call 存的是当时的工具名。服务端沿用 pre_label 的先例不收
旧名，所以别名只做渲染侧：canonicalToolName 剥前缀 + 查 LEGACY_TOOL_NAMES，
toolHint / groupChatEvents / stores.chat 三个消费点在入口处过一次。
顺手清掉 Step B 砍完就没人删的 5 个死常量。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 族① `set_model(role=)` —— 吃掉 4 个

全表签名最一致、调用量为零、前端无卡片的一族，先做它把整条流水线走通。

**Files:**
- Modify: `backend/app/tools/__init__.py`（删 `t_set_labeler_model` / `t_set_translate_model` / `t_set_proposer_model` / `t_switch_active_model`，加 `t_set_model`；`_IDEMPOTENT` 换名；`_tools` 换名）
- Modify: `backend/app/tools/_merged.py`
- Modify: `backend/tests/unit/test_symmetry_invariant.py`（`_TOOL_HTTP_MAP` 改 `(tool, op)` 键）
- Modify: `backend/app/skills/emerge_extractor.md`, `emerge_pre_label_runner.md`
- Modify: `frontend/src/lib/legacyToolName.ts`
- Test: `backend/tests/unit/test_tool_set_model.py`（新建）

**Interfaces:**
- Consumes: `MERGED_TOOLS`（Task 2）、`registered_tool_names`（Task 1）、`LEGACY_TOOL_NAMES`（Task 3）
- Produces: 工具 `set_model(slug: str, role: "extract"|"labeler"|"proposer"|"translate", model_id: str)`。`role="extract"` 走 `models_mod.switch_active_model`，其余三个走 `pre_label_mod.set_{role}_model` 家族。返回 `{"role": role, "model_id": model_id}` 的 JSON 文本。
- Produces: `_TOOL_HTTP_MAP` 的键类型变成 `tuple[str, str | None]`（`(tool_name, op)`，`op=None` 表示单 op 工具）。

- [ ] **Step 1: 写失败的测试**

`backend/tests/unit/test_tool_set_model.py`：

```python
"""set_model(role=) folds the four identical `(slug, model_id)` setters.

They had byte-identical input schemas, all idempotent, all non-destructive,
and zero recorded calls across 764 chat tool_calls + 145 remote MCP calls —
the textbook case for the four merge criteria (same noun, same input shape,
same policy, no destructive member)."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tools import build_emerge_mcp, registered_tool_names
from app.tools.projects import create_project


async def _call(server, name: str, args: dict):
    from mcp.types import CallToolRequest, CallToolRequestParams

    handler = server["instance"].request_handlers[CallToolRequest]
    return await handler(
        CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=name, arguments=args),
        )
    )


@pytest.mark.parametrize(
    "role", ["extract", "labeler", "proposer", "translate"],
)
async def test_set_model_writes_the_role(
    workspace: Path, stub_provider: AsyncMock, role: str,
) -> None:
    import json

    from app.tools.project_config import get_project_config

    slug = (await create_project(workspace, name="p"))["slug"]
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    await _call(server, "set_model", {
        "slug": slug, "role": role, "model_id": "m_test",
    })
    cfg = await get_project_config(workspace, slug)
    assert cfg[role]["resolved"] == "m_test" or cfg[role]["override"] == "m_test"


async def test_set_model_rejects_unknown_role(
    workspace: Path, stub_provider: AsyncMock,
) -> None:
    slug = (await create_project(workspace, name="p"))["slug"]
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    res = await _call(server, "set_model", {
        "slug": slug, "role": "agent_brain", "model_id": "m",
    })
    text = res.root.content[0].text
    assert "Input validation error" in text and "agent_brain" in text


def test_the_four_old_setters_are_gone() -> None:
    live = registered_tool_names(headless=True)
    for old in (
        "set_labeler_model", "set_proposer_model",
        "set_translate_model", "switch_active_model",
    ):
        assert old not in live, f"{old} should have been folded into set_model"
    assert "set_model" in live
```

- [ ] **Step 2: 跑，确认失败**

```bash
cd backend && uv run pytest tests/unit/test_tool_set_model.py -v
```

Expected: FAIL — `set_model` 未注册。

- [ ] **Step 3: 实现 `set_model`**

在 `backend/app/tools/__init__.py` 里，用一个 `t_set_model` 替换掉 `t_set_labeler_model` / `t_set_proposer_model` / `t_set_translate_model` / `t_switch_active_model` 四个定义：

```python
    _MODEL_ROLES = ("extract", "labeler", "proposer", "translate")

    @tool(
        "set_model",
        "Point one of this project's four tunable LLM roles at a model. "
        "`role`: 'extract' (the model that produces predictions — writes "
        "active_model_id), 'labeler' (label_docs), 'proposer' (AutoResearch), "
        "'translate' (review-pane translation). The last three write a "
        "project.json override; null there is the NORMAL state and means the "
        "role falls through to its env default. DO NOT call this just because "
        "an override is null — call `get_project_config` to see what each role "
        "actually resolves to. `agent_brain` is system-level and NOT settable. "
        "No risk gate; every role is recoverable by setting it again.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "role": {"type": "string", "enum": list(_MODEL_ROLES)},
                "model_id": {"type": "string"},
            },
            "required": ["slug", "role", "model_id"],
        },
    )
    async def t_set_model(args: dict[str, Any]) -> dict[str, Any]:
        role, slug, model_id = args["role"], args["slug"], args["model_id"]
        if role not in _MODEL_ROLES:
            return _error_envelope(
                "model_role_unknown",
                f"Unknown role {role!r}. Expected one of "
                f"{', '.join(_MODEL_ROLES)}. agent_brain is system-level and "
                f"cannot be set per project.",
            )
        await _MODEL_SETTERS[role](workspace, slug, model_id)
        return {
            "content": [{
                "type": "text",
                "text": _json.dumps({"role": role, "model_id": model_id}),
            }]
        }
```

`_error_envelope(...)` 是 Task 2 Step 0 加的通用信封 helper —— 仓库原本没有通用版，别再内联字面量。

**别新建跨模块 helper。** 四个 setter 实测住在**四个不同模块**里，让 `pre_label`
去 import `jobs.autoresearch` 是坏分层。就在 `build_emerge_mcp` 里放一张调用表，
和原来四个 tool body 各自做的事逐字一致：

```python
    from app.jobs.autoresearch import set_proposer_model as _set_proposer

    _MODEL_SETTERS = {
        "extract": model_mod.switch_active_model,
        "labeler": pre_label_mod.set_labeler_model,
        "proposer": _set_proposer,
        "translate": translate_mod.set_translate_model,
    }
```

四个都是 `async (workspace, slug_or_pid, model_id) -> None`。`model_mod` /
`pre_label_mod` / `translate_mod` 在文件顶部已经 import 好了；`set_proposer_model`
原本就是在 tool body 里局部 import 的（`app/jobs/autoresearch.py:177`），保持
局部 import 避免顶层循环依赖。

- [ ] **Step 4: 更新 `_IDEMPOTENT` 与 `_tools`**

`_IDEMPOTENT` 里把 `"set_labeler_model", "set_translate_model", "set_proposer_model"` 和 `"switch_active_model"` 四项替换成 `"set_model"`。`_tools` 列表里四个 `t_*` 换成一个 `t_set_model`。

- [ ] **Step 5: 登记进 `MERGED_TOOLS`**

```python
MERGED_TOOLS: dict[str, tuple[str, ...]] = {
    # Byte-identical `(slug, model_id)` schemas, all idempotent, zero calls.
    "set_model": (
        "set_labeler_model", "set_proposer_model",
        "set_translate_model", "switch_active_model",
    ),
}

# …and the same key in MERGED_POLICY — the family's shared profile:
    "set_model": frozenset({"idempotent"}),
```

- [ ] **Step 6: 改 `_TOOL_HTTP_MAP` 的键形状**

`backend/tests/unit/test_symmetry_invariant.py`：键从 `str` 改成 `tuple[str, str | None]`。四条旧行变成：

```python
_TOOL_HTTP_MAP: dict[tuple[str, str | None], tuple[str, str]] = {
    # …
    # REST already expresses the op as the resource, so the HTTP side does NOT
    # merge: one (tool, op) pair per route, never an `op` query parameter.
    ("set_model", "labeler"): ("POST", r"^/lab/projects/\{slug\}/labeler_model$"),
    ("set_model", "translate"): ("PUT", r"^/lab/projects/\{slug\}/translate_model$"),
    ("set_model", "proposer"): ("PUT", r"^/lab/projects/\{slug\}/proposer_model$"),
    ("set_model", "extract"): ("PUT", r"^/lab/projects/\{slug\}/models/active$"),
    # …其余单 op 工具键写成 (name, None)
}
```

`test_every_tool_has_http_or_is_exempt` 里 `mapped = set(_TOOL_HTTP_MAP)` 改成 `mapped = {t for t, _op in _TOOL_HTTP_MAP}`；`test_declared_routes_exist` 的循环解包改成 `for (tool_name, op), (method, pattern) in _TOOL_HTTP_MAP.items():`，错误信息带上 op。**断言强度不许降**：仍然要求每个注册工具被覆盖、每条 map 都命中活路由、无 stale 条目。

再加一条形状测试：

```python
def test_merged_tools_map_every_op_to_its_own_route() -> None:
    """A merged tool must not lose route coverage: each op it swallowed keeps a
    distinct route, because REST expresses ops as resource+method and the HTTP
    side deliberately did not merge."""
    from app.tools._merged import MERGED_TOOLS

    for new, olds in MERGED_TOOLS.items():
        ops = {op for (tool, op) in _TOOL_HTTP_MAP if tool == new}
        assert len(ops) == len(olds), (
            f"{new!r} swallowed {len(olds)} ops but maps {len(ops)} routes: "
            f"{sorted(ops)}"
        )
```

- [ ] **Step 7: 前端别名加行**

`LEGACY_TOOL_NAMES` 加：
```ts
  set_labeler_model: 'set_model',
  set_proposer_model: 'set_model',
  set_translate_model: 'set_model',
  switch_active_model: 'set_model',
```

- [ ] **Step 8: 改 skill 文本**

```bash
cd backend && grep -rn "set_labeler_model\|set_proposer_model\|set_translate_model\|switch_active_model" app/skills/
```
逐处改写成 `set_model(role=…)`。`emerge_pre_label_runner.md` 里 `set_labeler_model` 的段落改成 `set_model(role='labeler')`；`emerge_extractor.md` 里 `switch_active_model` 改成 `set_model(role='extract')`。**只改名，不改叙述逻辑。**

- [ ] **Step 9: 跑三层测试**

```bash
cd backend && uv run pytest tests/unit/test_tool_set_model.py tests/unit/test_tool_policy.py tests/unit/test_symmetry_invariant.py tests/unit/test_tool_registration.py -v
cd ../frontend && npx vitest run src/lib/legacyToolName.test.ts && npx tsc -b --noEmit
```

Expected: 全 PASS。

- [ ] **Step 10: 跑后端全量**

```bash
cd backend && uv run pytest -q -n 4 --timeout=120
```

Expected: 0 failed。旧 setter 的既有单测若直接测模块函数则不受影响；若测的是工具名，改成 `set_model`。

- [ ] **Step 11: Commit**

```bash
git add -A && git commit -m "$(cat <<'EOF'
refactor(tools): 四个 model setter 并成 set_model(role=) —— 签名本来就一模一样

set_labeler/proposer/translate_model + switch_active_model 四个工具的输入
schema 逐字相同 (slug, model_id)，四个都 idempotent，764 次 chat 调用 +
145 次 remote 调用里一次都没出现过。HTTP 侧不并：REST 用资源表达 role，
_TOOL_HTTP_MAP 改成 (tool, op) -> route，四条路由原样保留。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: 族② `get_project_config` 吃掉 `get_labeler_config`

**Files:**
- Modify: `backend/app/tools/__init__.py:671-696`（删 `t_get_labeler_config`）
- Modify: `backend/app/tools/project_config.py`（每个角色补 `env_default`）
- Modify: `backend/app/tools/_merged.py`, `backend/tests/unit/test_symmetry_invariant.py`
- Modify: `backend/app/skills/emerge_pre_label_runner.md`, `emerge_extractor.md`
- Modify: `frontend/src/lib/legacyToolName.ts`
- Test: `backend/tests/unit/test_tool_config.py`（既有文件，追加）

**Interfaces:**
- Produces: `get_project_config(slug)` 每个 role 的字典从 `{override, resolved, source}` 变成 `{override, env_default, resolved, source}`。**这是本 plan 仅有的两处行为增量之一**——不加这个字段，`get_labeler_config` 的调用者会丢信息，就不是纯表面重构了。

- [ ] **Step 1: 写失败的测试**

追加到 `backend/tests/unit/test_tool_config.py`：

```python
async def test_project_config_carries_env_default_per_role(
    workspace: Path, monkeypatch,
) -> None:
    """get_labeler_config folded into get_project_config, which returned
    {override, resolved, source} — a superset of the labeler view MINUS
    env_default. Dropping that field would turn a surface merge into an
    information loss, so the merge adds it for all four roles."""
    from app.tools.project_config import get_project_config
    from app.tools.projects import create_project

    monkeypatch.setenv("EMERGE_DEFAULT_LABELER_MODEL", "m_env_labeler")
    slug = (await create_project(workspace, name="p"))["slug"]
    cfg = await get_project_config(workspace, slug)
    for role in ("labeler", "proposer", "translate"):
        assert "env_default" in cfg[role], f"{role} lost env_default"
    assert cfg["labeler"]["env_default"] == "m_env_labeler"


def test_get_labeler_config_is_gone() -> None:
    from app.tools import registered_tool_names

    assert "get_labeler_config" not in registered_tool_names(headless=True)
```

- [ ] **Step 2: 跑，确认失败**

```bash
cd backend && uv run pytest tests/unit/test_tool_config.py -v -k "env_default or labeler_config_is_gone"
```

Expected: FAIL。

- [ ] **Step 3: `project_config.py` 补 `env_default`**

在组装每个 role 字典的地方（`get_project_config` 内），把已经算出来的 env 默认值一并放进返回值：

```python
        role_view = {
            "override": override,
            "env_default": env_default,   # merged in from get_labeler_config
            "resolved": resolved,
            "source": source,
        }
```
`extract` 角色若无 env 概念，写 `"env_default": None` 并在 docstring 里说明。

- [ ] **Step 4: 删 `t_get_labeler_config`，更新 description / `_READ_ONLY` / `_tools`**

`get_project_config` 的 description 里把返回值改成 `{override, env_default, resolved, source}`，并把 `get_labeler_config` 那句「Call this whenever you would otherwise inspect project.json directly」的告诫**搬进来**（那是它存在的理由，不能随工具一起消失）。`_READ_ONLY` 去掉 `"get_labeler_config"`，`_tools` 去掉 `t_get_labeler_config`。

- [ ] **Step 5: 登记 + 路由 + 别名 + skill**

```python
    # get_project_config already returned a superset per role; the merge adds
    # the one field it lacked (env_default).
    "get_project_config": ("get_labeler_config",),


# …and the same key in MERGED_POLICY — the family's shared profile:
    "get_project_config": frozenset({"read_only"}),
```
`_TOOL_HTTP_MAP`：
```python
    ("get_project_config", "config"): ("GET", r"^/lab/projects/\{slug\}/config$"),
    ("get_project_config", "labeler"): ("GET", r"^/lab/projects/\{slug\}/labeler_config$"),
```
`LEGACY_TOOL_NAMES` 加 `get_labeler_config: 'get_project_config',`。skill 里 `get_labeler_config` 全改 `get_project_config`。

- [ ] **Step 6: 跑测试**

```bash
cd backend && uv run pytest tests/unit/test_tool_config.py tests/unit/test_tool_policy.py tests/unit/test_symmetry_invariant.py -v
```

Expected: PASS。

- [ ] **Step 7: 全量 + Commit**

```bash
cd backend && uv run pytest -q -n 4 --timeout=120
cd .. && git add -A && git commit -m "$(cat <<'EOF'
refactor(tools): get_labeler_config 并进 get_project_config —— 顺手把 env_default 补回来

get_project_config 每个角色返回 {override, resolved, source}，正好是
get_labeler_config 的超集减一个 env_default。并的时候补上，否则表面重构
就变成了信息丢失。"别直接读 project.json，会漏 env fallback" 那句告诫
随字段一起搬进新 description。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 族③ `extract(experiment_id?)`

全场最热的两个工具（147 + 53 次），skill 与前端改动最多，所以放在流水线跑顺之后。

**Files:**
- Modify: `backend/app/tools/__init__.py`（`t_extract_one` + `t_extract_with_experiment` → `t_extract`；`_TOUCHES_PROVIDER`；`_tools`；`_MINIMAL_SURFACE`）
- Modify: `backend/app/tools/_merged.py`, `backend/tests/unit/test_symmetry_invariant.py`
- Modify: `backend/app/skills/emerge_extractor.md`, `emerge_autoresearch.md`
- Modify: `frontend/src/lib/legacyToolName.ts`, `frontend/src/lib/toolHint.ts`
- Test: `backend/tests/unit/test_tool_extract.py`（新建）

**Interfaces:**
- Produces: `extract(slug: str, filename: str, experiment_id: str | None = None)`。`experiment_id` 缺省 → 走 active prompt/model 写 `predictions/_draft`；给了 → 走该 experiment 写 `experiments/{id}/predictions/`。**两条路径的实现原样保留，只是入口合一。**

- [ ] **Step 1: 写失败的测试**

`backend/tests/unit/test_tool_extract.py`：

```python
"""extract(experiment_id?) folds the two hottest tools in the system
(extract_one 147 calls, extract_with_experiment 53). They differ by exactly one
optional argument — the lowest-risk shape of merge — and both are provider-
touching, so the policy profile is uniform."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from app.tools import build_emerge_mcp, registered_tool_names
from app.workspace.paths import experiment_prediction_path, prediction_draft_path


async def _call(server, name: str, args: dict):
    from mcp.types import CallToolRequest, CallToolRequestParams

    handler = server["instance"].request_handlers[CallToolRequest]
    return await handler(
        CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=name, arguments=args),
        )
    )


async def test_extract_without_experiment_writes_the_draft(
    workspace: Path, stub_provider: AsyncMock, seeded_project,
) -> None:
    slug, filename = seeded_project
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    await _call(server, "extract", {"slug": slug, "filename": filename})
    assert prediction_draft_path(workspace, slug, filename).exists()


async def test_extract_with_experiment_writes_that_experiments_prediction(
    workspace: Path, stub_provider: AsyncMock, seeded_project_with_experiment,
) -> None:
    slug, filename, exp_id = seeded_project_with_experiment
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    await _call(server, "extract", {
        "slug": slug, "filename": filename, "experiment_id": exp_id,
    })
    assert experiment_prediction_path(workspace, slug, exp_id, filename).exists()
    assert not prediction_draft_path(workspace, slug, filename).exists()


def test_old_extract_names_are_gone() -> None:
    live = registered_tool_names(headless=True)
    assert "extract_one" not in live
    assert "extract_with_experiment" not in live
    assert "extract" in live
```

`seeded_project` / `seeded_project_with_experiment` 两个 fixture：先在 `tests/unit/test_tool_extract.py` 本地定义（用 `create_project` + `upload_doc` + `write_schema` + `create_experiment`，照 `tests/unit/test_tool_experiments.py` 现有 setup 抄），若 `conftest.py` 已有同名 fixture 则直接用。

- [ ] **Step 2: 跑，确认失败**

```bash
cd backend && uv run pytest tests/unit/test_tool_extract.py -v
```

Expected: FAIL — `extract` 未注册。

- [ ] **Step 3: 实现**

把 `t_extract_one` 与 `t_extract_with_experiment` 换成：

```python
    @tool(
        "extract",
        "Run extraction on ONE document and persist the prediction. Omit "
        "`experiment_id` to use the project's ACTIVE prompt + model and write "
        "predictions/_draft (this is what the review pane reads). Pass "
        "`experiment_id` to run that experiment's prompt/model instead and "
        "write under experiments/{id}/predictions/ — the active draft is left "
        "untouched, which is what makes A/B comparison safe. Costs one provider "
        "call per document; for a whole folder use start_job.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "filename": {"type": "string"},
                "experiment_id": {"type": "string"},
            },
            "required": ["slug", "filename"],
        },
    )
    async def t_extract(args: dict[str, Any]) -> dict[str, Any]:
        exp_id = args.get("experiment_id") or None
        try:
            if exp_id:
                out = await experiments_mod.extract_with_experiment(
                    workspace, provider, args["slug"], exp_id, args["filename"],
                )
            else:
                out = await extract_mod.extract_one(
                    workspace, provider, args["slug"], args["filename"],
                )
        except Exception as exc:
            return _extract_provider_error(exc)
        return {"content": [{"type": "text", "text": _json.dumps(out, ensure_ascii=False)}]}
```
（两个分支的 body 从原来的两个 `t_*` 里原样搬，包括各自的错误处理 —— 若原来两个的错误信封不同，保留各自的，不要统一，那是改语义。）

- [ ] **Step 4: 更新集合**

`_TOUCHES_PROVIDER`：`"extract_one", "extract_with_experiment"` → `"extract"`。`_tools`：两个 `t_*` → 一个 `t_extract`。`app/mcp_server.py::_MINIMAL_SURFACE`：`"extract_one"` → `"extract"`，删 `"extract_with_experiment"`。

- [ ] **Step 5: 登记 + 路由 + 别名**

```python
    # One optional argument apart; both provider-touching. The two hottest
    # tools in the system (147 + 53 recorded calls).
    "extract": ("extract_one", "extract_with_experiment"),


# …and the same key in MERGED_POLICY — the family's shared profile:
    "extract": frozenset({"touches_provider"}),
```
```python
    ("extract", "active"): ("POST", r"^/lab/projects/\{slug\}/extract$"),
    ("extract", "experiment"): (
        "POST",
        r"^/lab/projects/\{slug\}/experiments/\{experiment_id\}/predictions/\{filename:path\}$",
    ),
```
`LEGACY_TOOL_NAMES` 加 `extract_one: 'extract', extract_with_experiment: 'extract',`。

- [ ] **Step 6: `toolHint.ts` 的 case 改名**

`case 'extract_one':` → `case 'extract':`（该 case 与 `label_docs`/`save_reviewed` 共用一个分支，只改字面量）。

- [ ] **Step 7: 改 skill 文本（本族最重）**

```bash
cd backend && grep -rn "extract_one\|extract_with_experiment" app/skills/
```
`emerge_extractor.md` 是重灾区。规则：`extract_one(slug, filename)` → `extract(slug, filename)`；`extract_with_experiment(slug, exp, filename)` → `extract(slug, filename, experiment_id=exp)`。**「这些工具 Bash 模仿不了」清单和 remote minimal 降级指引里的名字也要改。** 改完通读一遍受影响段落，确认叙述仍然通顺（不是机械替换后语义走样）。

- [ ] **Step 8: 跑测试**

```bash
cd backend && uv run pytest tests/unit/test_tool_extract.py tests/unit/test_tool_policy.py tests/unit/test_symmetry_invariant.py -v
cd ../frontend && npx vitest run && npx tsc -b --noEmit
```

Expected: PASS（前端除既有 11 个 `FSSpine-*`）。

- [ ] **Step 9: 全量 + Commit**

```bash
cd backend && uv run pytest -q -n 4 --timeout=120
cd .. && git add -A && git commit -m "$(cat <<'EOF'
refactor(tools): extract_one / extract_with_experiment 合成 extract(experiment_id?)

全场最热的两个工具(147+53 次)，差别只有一个可选参数，都 provider-touching。
两条实现路径原样保留，只是入口合一：不传 experiment_id 走 active prompt
写 _draft，传了走该实验写 experiments/{id}/predictions/。
skill 里 emerge_extractor.md 是改名重灾区，含"Bash 模仿不了"清单。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 族④ `score(kind=)`

**Files:**
- Modify: `backend/app/tools/__init__.py`（三个 `t_score*` → `t_score`；`_TOUCHES_PROVIDER`；`_tools`；`_MINIMAL_SURFACE`）
- Modify: `backend/app/tools/_merged.py`, `backend/tests/unit/test_symmetry_invariant.py`
- Modify: `backend/app/skills/emerge_extractor.md`（含 audit / match 两个 domain 段）
- Modify: `frontend/src/lib/legacyToolName.ts`, `frontend/src/lib/groupChatEvents.ts`
- Test: `backend/tests/unit/test_tool_score.py`（新建）

**Interfaces:**
- Produces: `score(slug: str, kind: "extract"|"audit"|"match" = "extract", use_llm_judge: bool | None = None)`。`use_llm_judge` 只对 `kind="extract"` 有意义，其余 kind 传了就返回 `score_kind_arg_unsupported` 错误信封（不静默忽略）。三种 kind 的返回 shape 各不相同 —— 这没问题，准则约束的是输入形状。

- [ ] **Step 1: 写失败的测试**

`backend/tests/unit/test_tool_score.py`：

```python
"""score(kind=) folds the three scoring verbs. Inputs were (slug, use_llm_judge?)
/ (slug) / (slug) — same noun, same policy (all provider-touching), compatible
shapes. Return shapes differ per kind and that is fine: the merge criterion
constrains INPUT shape."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tools import build_emerge_mcp, registered_tool_names


async def _call(server, name: str, args: dict):
    from mcp.types import CallToolRequest, CallToolRequestParams

    handler = server["instance"].request_handlers[CallToolRequest]
    return await handler(
        CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=name, arguments=args),
        )
    )


async def test_score_defaults_to_extract_kind(
    workspace: Path, stub_provider: AsyncMock, scored_project,
) -> None:
    slug = scored_project
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    res = await _call(server, "score", {"slug": slug})
    assert "field_accuracy" in res.root.content[0].text


async def test_score_rejects_llm_judge_flag_for_non_extract_kinds(
    workspace: Path, stub_provider: AsyncMock, scored_project,
) -> None:
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    res = await _call(server, "score", {
        "slug": scored_project, "kind": "audit", "use_llm_judge": False,
    })
    text = res.root.content[0].text
    assert "score_kind_arg_unsupported" in text


async def test_score_rejects_an_unknown_kind_at_the_schema_layer(
    workspace: Path, stub_provider: AsyncMock, scored_project,
) -> None:
    """The enum is the guard. Asserted here so that deleting it from the schema
    to "simplify" the tool shows up as a failure rather than as a silently
    wider surface."""
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    res = await _call(server, "score", {"slug": scored_project, "kind": "audti"})
    assert "Input validation error" in res.root.content[0].text


def test_old_score_names_are_gone() -> None:
    live = registered_tool_names(headless=True)
    assert "score_audit" not in live
    assert "score_match" not in live
    assert "score" in live
```

`scored_project` fixture：建项目 + 写 schema + 一份 `_draft` 预测 + 一份 `reviewed`，照 `tests/unit/test_tool_score*.py` 现有 setup 抄。

- [ ] **Step 2: 跑，确认失败**

```bash
cd backend && uv run pytest tests/unit/test_tool_score.py -v
```

Expected: FAIL。

- [ ] **Step 3: 实现**

```python
    _SCORE_KINDS = ("extract", "audit", "match")

    @tool(
        "score",
        "Score this project against its human-confirmed ground truth. "
        "`kind='extract'` (default): field + doc accuracy of predictions/_draft "
        "vs reviewed examples via L1 normalize + optional L2 LLM-judge + L3 "
        "presence; persists metrics/eval_{ts}/ and returns the summary. "
        "`kind='audit'`: re-runs the audit with the CURRENT rules and reports "
        "accuracy + precision/recall with 'fail' as the positive class (a judge "
        "'unclear' on a true fail counts as a miss, never a false alarm); the "
        "tune loop is write_audit_rules → score(kind='audit'). `kind='match'`: "
        "re-runs the match and reports per-source precision/recall over "
        "reviewed anchors plus doc_completeness. `use_llm_judge` applies to "
        "kind='extract' only.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "kind": {"type": "string", "enum": list(_SCORE_KINDS)},
                "use_llm_judge": {"type": "boolean"},
            },
            "required": ["slug"],
        },
    )
    async def t_score(args: dict[str, Any]) -> dict[str, Any]:
        # No `kind not in _SCORE_KINDS` guard: the schema enum already rejects
        # that before this handler runs (see "jsonschema 在 handler 之前跑").
        kind = args.get("kind") or "extract"
        if kind != "extract" and "use_llm_judge" in args:
            return _error_envelope(
                "score_kind_arg_unsupported",
                f"use_llm_judge applies to kind='extract' only; kind={kind!r} "
                f"always runs its own judge.",
            )
        # Module aliases + call signatures: copy each branch VERBATIM from the
        # t_score / t_score_audit / t_score_match body it replaces. `score_mod`
        # is imported at the top of the file; the audit/match halves may use a
        # different alias or a local import — keep whatever they already do.
        if kind == "extract":
            out = await score_mod.score(...)      # ← verbatim from t_score
        elif kind == "audit":
            out = ...                             # ← verbatim from t_score_audit
        else:
            out = ...                             # ← verbatim from t_score_match
        return {"content": [{"type": "text", "text": _json.dumps(out, ensure_ascii=False)}]}
```
**三个分支必须从原三个 `t_*` body 逐字搬**（含各自的 `await`、参数名、错误处理和
`_json.dumps` 的 `ensure_ascii` 取值）。已实测顶部 import 有 `score_mod`
（`app/tools/score.py`）；audit / match 两支的模块别名以文件现状为准，别照上面
占位符里的 `audit_mod` / `match_mod` 猜。

- [ ] **Step 4: 更新集合**

`_TOUCHES_PROVIDER` 去掉 `"score_match"` / `"score_audit"`，保留 `"score"`（连同它们各自的行内注释合并成一行 `"score",  # extract/audit/match — the L2 judge may call the LLM in all three`）。`_tools` 三个 → 一个。`_MINIMAL_SURFACE` 删 `"score_audit"` / `"score_match"`。

- [ ] **Step 5: 登记 + 路由 + 别名 + 前端上浮集合**

```python
    # Same noun, same policy, compatible input shapes; return shapes differ,
    # which the criteria do not constrain.
    "score": ("score_audit", "score_match"),


# …and the same key in MERGED_POLICY — the family's shared profile:
    "score": frozenset({"touches_provider"}),
```
```python
    ("score", "extract"): ("POST", r"^/lab/projects/\{slug\}/score$"),
    ("score", "audit"): ("POST", r"^/lab/projects/\{slug\}/audit-score$"),
    ("score", "match"): ("GET", r"^/lab/match/projects/\{slug\}/score$"),
```
`LEGACY_TOOL_NAMES` 加 `score_audit: 'score', score_match: 'score',`。`groupChatEvents.ts` 的 `HOISTED_TOOL_NAMES` 里删掉 `score_audit`（归一化后由 `score` 覆盖）。

- [ ] **Step 6: 改 skill 文本**

```bash
cd backend && grep -rn "score_audit\|score_match\|\bscore\b" app/skills/
```
audit 域段的 tune loop「edit rules via write_audit_rules, then score_audit」改成 `score(kind='audit')`；match 域段同理。

- [ ] **Step 7: 跑测试 + 全量 + Commit**

```bash
cd backend && uv run pytest tests/unit/test_tool_score.py tests/unit/test_tool_policy.py tests/unit/test_symmetry_invariant.py -v
cd backend && uv run pytest -q -n 4 --timeout=120
cd ../frontend && npx vitest run && npx tsc -b --noEmit
cd .. && git add -A && git commit -m "$(cat <<'EOF'
refactor(tools): score/score_audit/score_match 合成 score(kind=)

同名词、同 policy(都 provider-touching)、输入形状兼容 (slug[,use_llm_judge])。
返回 shape 三种各不相同 —— 准则约束的是输入形状，不是输出。
use_llm_judge 只对 kind=extract 有意义，其余 kind 传了显式报
score_kind_arg_unsupported，不静默忽略。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: 族⑤ `control_job(action=)`

**Files:**
- Modify: `backend/app/tools/__init__.py`（三个 `t_*_job` → `t_control_job`；`_IDEMPOTENT`；`_tools`；`_MINIMAL_SURFACE`）
- Modify: `backend/app/tools/_merged.py`, `backend/tests/unit/test_symmetry_invariant.py`
- Modify: `backend/app/skills/emerge_extractor.md`
- Modify: `frontend/src/lib/legacyToolName.ts`
- Test: `backend/tests/unit/test_tool_jobs.py`（既有文件，追加）

**Interfaces:**
- Produces: `control_job(job_id: str, action: "pause"|"resume"|"cancel")`。`start_job`（provider，不同 shape）与 `get_job`（read-only）不动。

- [ ] **Step 1: 写失败的测试**（追加到 `tests/unit/test_tool_jobs.py`）

```python
@pytest.mark.parametrize(
    "action,expected_text",
    [("pause", "paused"), ("resume", "resumed"), ("cancel", "cancelled")],
)
async def test_control_job_dispatches_each_action(
    workspace: Path, stub_provider: AsyncMock, monkeypatch,
    action: str, expected_text: str,
) -> None:
    """The three job-control tools had byte-identical `(job_id)` schemas and
    were all idempotent — same noun, same shape, same policy."""
    from unittest.mock import MagicMock

    from mcp.types import CallToolRequest, CallToolRequestParams

    from app.tools import build_emerge_mcp

    from unittest.mock import AsyncMock

    from app.tools import build_emerge_mcp

    # JobRunner.pause/resume/cancel are async and return None; the tool goes
    # through jobs_mod.{action}_job_impl(job_runner, job_id=...). Patch that
    # layer so the test pins the dispatch, not the runner internals.
    impl = AsyncMock(return_value=None)
    monkeypatch.setattr(f"app.tools.jobs.{action}_job_impl", impl)
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    handler = server["instance"].request_handlers[CallToolRequest]
    res = await handler(CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(
            name="control_job", arguments={"job_id": "j_1", "action": action},
        ),
    ))
    impl.assert_awaited_once()
    assert impl.await_args.kwargs["job_id"] == "j_1"
    # Return text must stay byte-identical to the tool it replaced.
    assert res.root.content[0].text == expected_text


def test_old_job_control_names_are_gone() -> None:
    from app.tools import registered_tool_names

    live = registered_tool_names(headless=True)
    for old in ("pause_job", "resume_job", "cancel_job"):
        assert old not in live
    assert "control_job" in live
    assert {"start_job", "get_job"} <= live, "start/get must NOT be folded in"
```
已实测，不用再查：`JobRunner` 在 `app/jobs/runner.py:35`，`pause`/`resume`/`cancel`
都是 `async` 且返回 `None`；工具侧从不直接调它们，走的是
`jobs_mod.{pause,resume,cancel}_job_impl(job_runner, job_id=...)`。

- [ ] **Step 2: 跑，确认失败**

```bash
cd backend && uv run pytest tests/unit/test_tool_jobs.py -v -k "control_job or job_control_names"
```

- [ ] **Step 3: 实现**

```python
    @tool(
        "control_job",
        "Change a running job's state. `action='pause'` stops after the "
        "in-flight document (resumable); 'resume' continues a paused job; "
        "'cancel' stops it for good — already-written predictions are kept, "
        "nothing is rolled back. Idempotent: re-issuing the same action on a "
        "job already in that state is a no-op. Use get_job to see the current "
        "state first.",
        {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "action": {"type": "string", "enum": sorted(_JOB_ACTIONS)},
            },
            "required": ["job_id", "action"],
        },
    )
    async def t_control_job(args: dict[str, Any]) -> dict[str, Any]:
        # No unknown-action guard: the schema enum rejects it first.
        action = args["action"]
        await getattr(jobs_mod, f"{action}_job_impl")(
            job_runner, job_id=args["job_id"],
        )
        return {"content": [{"type": "text", "text": _JOB_ACTIONS[action]}]}
```

`_JOB_ACTIONS` 同时当枚举和返回值表，**返回文本与旧工具逐字一致**（纯表面重构，
返回值也是表面）：

```python
    _JOB_ACTIONS = {"pause": "paused", "resume": "resumed", "cancel": "cancelled"}
```

实测：`JobRunner.pause/resume/cancel` 是 **async 且返回 `None`**，工具侧走的是
`jobs_mod.{pause,resume,cancel}_job_impl(job_runner, job_id=...)`，旧三个工具各自
返回纯文本 `"paused"` / `"resumed"` / `"cancelled"`。**别把它编成布尔返回。**

- [ ] **Step 4: 集合 + 登记 + 路由 + 别名 + skill**

`_IDEMPOTENT`：`"pause_job", "resume_job", "cancel_job"` → `"control_job"`。`_tools` 三换一。`_MINIMAL_SURFACE`：`"cancel_job"` → `"control_job"`。
```python
    # Byte-identical `(job_id)` schemas, all idempotent. start_job (provider,
    # different shape) and get_job (read-only) deliberately stay out.
    "control_job": ("pause_job", "resume_job", "cancel_job"),


# …and the same key in MERGED_POLICY — the family's shared profile:
    "control_job": frozenset({"idempotent"}),
```
```python
    ("control_job", "pause"): ("POST", r"^/lab/jobs/\{job_id\}/pause$"),
    ("control_job", "resume"): ("POST", r"^/lab/jobs/\{job_id\}/resume$"),
    ("control_job", "cancel"): ("POST", r"^/lab/jobs/\{job_id\}/cancel$"),
```
`LEGACY_TOOL_NAMES` 加三行。skill 里 `pause_job`/`resume_job`/`cancel_job` 改成 `control_job(action=…)`。

- [ ] **Step 5: 跑测试 + 全量 + Commit**

```bash
cd backend && uv run pytest tests/unit/test_tool_jobs.py tests/unit/test_tool_policy.py tests/unit/test_symmetry_invariant.py -v
cd backend && uv run pytest -q -n 4 --timeout=120
cd .. && git add -A && git commit -m "$(cat <<'EOF'
refactor(tools): pause/resume/cancel_job 合成 control_job(action=)

三个签名逐字相同 (job_id)，三个都 idempotent。start_job(provider,不同
shape) 与 get_job(read-only) 留在外面 —— 名词相同但 policy 不同。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: 族⑥ `ui_focus(target=)`

副产品：headless 叙述契约从四处收敛成一处。

**Files:**
- Modify: `backend/app/tools/__init__.py`（四个 `t_ui_set_*`/`t_ui_goto_page` → `t_ui_focus`；`_IDEMPOTENT`；`_tools`）
- Modify: `backend/app/mcp_server.py::_HEADLESS_EXCLUDE`
- Modify: `backend/app/tools/_merged.py`, `backend/tests/unit/test_symmetry_invariant.py::_HTTP_EXEMPT`
- Modify: `backend/app/skills/emerge_extractor.md`（rendering contract 双分支）
- Modify: `frontend/src/lib/legacyToolName.ts`, `frontend/src/lib/toolHint.ts`, `frontend/src/stores/chat.ts`
- Test: `backend/tests/unit/test_tool_ui.py`（既有文件，追加；无则新建）

**Interfaces:**
- Produces: `ui_focus(slug: str, filename: str, target: "page"|"field"|"tab"|"entity", value: str | int)`。`target="page"`/`"entity"` 收整数（字符串数字也接受并转换），`"field"`/`"tab"` 收字符串。`ui_open_review`（模式切换、被调用过）保持独立。

- [ ] **Step 1: 写失败的测试**

```python
"""ui_focus(target=) folds the four "point the UI at X" actions. All four had
shape (slug, filename, <one value>), all idempotent, all browser-only. The
by-product matters as much as the count: the headless narration contract
(`→ page N` / `→ focus field_name`) now lives in ONE place instead of four."""
import pytest

from app.tools import registered_tool_names


@pytest.mark.parametrize(
    "target,value,expect",
    [
        ("page", 3, {"page": 3}),
        ("field", "invoice_no", {"path": "invoice_no"}),
        ("tab", "audit", {"tab_key": "audit"}),
        ("entity", 2, {"idx": 2}),
    ],
)
async def test_ui_focus_emits_the_right_side_channel_event(
    workspace, stub_provider, target, value, expect, monkeypatch,
) -> None:
    from unittest.mock import MagicMock
    from mcp.types import CallToolRequest, CallToolRequestParams

    from app.tools import build_emerge_mcp

    from unittest.mock import AsyncMock

    fn_name = {
        "page": "ui_goto_page", "field": "ui_set_active_field",
        "tab": "ui_set_active_tab", "entity": "ui_set_active_entity",
    }[target]
    spy = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(f"app.tools.ui_actions.{fn_name}", spy)
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    handler = server["instance"].request_handlers[CallToolRequest]
    await handler(CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="ui_focus", arguments={
            "slug": "p", "filename": "a.pdf", "target": target, "value": value,
        }),
    ))
    spy.assert_awaited_once()
    kwargs = spy.await_args.kwargs
    assert kwargs["slug"] == "p" and kwargs["filename"] == "a.pdf"
    for k, v in expect.items():
        assert kwargs[k] == v, f"{target}: expected {k}={v!r}, got {kwargs}"


def test_old_ui_names_are_gone_but_open_review_stays() -> None:
    live = registered_tool_names(headless=False)
    for old in (
        "ui_goto_page", "ui_set_active_field",
        "ui_set_active_tab", "ui_set_active_entity",
    ):
        assert old not in live
    assert "ui_focus" in live
    assert "ui_open_review" in live, "mode switch is a different verb"


def test_ui_focus_is_excluded_from_headless() -> None:
    from app.mcp_server import _HEADLESS_EXCLUDE

    assert "ui_focus" in _HEADLESS_EXCLUDE
    assert not (_HEADLESS_EXCLUDE & {
        "ui_goto_page", "ui_set_active_field",
        "ui_set_active_tab", "ui_set_active_entity",
    }), "stale bare names left in _HEADLESS_EXCLUDE"
```
已实测：四个函数在 `app/tools/ui_actions.py`（模块别名 `ui_actions_mod`），
签名 `async (*, slug, filename, <one kwarg>)`。测试 monkeypatch
`app.tools.ui_actions.ui_goto_page` 这一层，别去 patch 不存在的 `emit_ui_action`。

- [ ] **Step 2: 跑，确认失败**

```bash
cd backend && uv run pytest tests/unit/test_tool_ui.py -v
```

- [ ] **Step 3: 实现**

```python
    @tool(
        "ui_focus",
        "Point the user's review pane at one thing inside a doc. `target`: "
        "'page' (value = 1-based page number), 'field' (value = the field path, "
        "e.g. invoice_no or line_items[2].amount), 'tab' (value = the tab key), "
        "'entity' (value = the 0-based entity index). Browser only — this is an "
        "agent→UI side channel with no server state. In a headless interface "
        "there is no pane to move: NARRATE the move instead of calling this "
        "('→ page 3', '→ focus invoice_no') and never silently skip it.",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "filename": {"type": "string"},
                "target": {"type": "string", "enum": sorted(_UI_TARGETS)},
                "value": {"type": ["string", "integer"]},
            },
            "required": ["slug", "filename", "target", "value"],
        },
    )
    async def t_ui_focus(args: dict[str, Any]) -> dict[str, Any]:
        # No unknown-target guard: the schema enum rejects it first. The value
        # cast below DOES need one — `value` is declared ["string","integer"]
        # and which of the two is legal depends on `target`, a cross-argument
        # constraint jsonschema cannot express.
        target = args["target"]
        caster = _UI_TARGETS[target]
        try:
            value = caster(args["value"])
        except (TypeError, ValueError):
            return _error_envelope(
                "ui_value_invalid",
                f"target={target!r} needs a {caster.__name__} value, got "
                f"{args['value']!r}.",
            )
        fn, key = _UI_DISPATCH[target]
        out = await fn(slug=args["slug"], filename=args["filename"], **{key: value})
        return {"content": [{"type": "text", "text": _json.dumps(out)}]}
```

**不要发明新的 emit helper。** 实测四个 side-channel 函数已经在
`app/tools/ui_actions.py` 里，签名 `async (*, slug, filename, <one kwarg>)`，
`ui_actions_mod` 顶部已 import。直接派发过去，**事件形状按构造就是逐字不变的**
（前端 reducer 在监听它）：

```python
    _UI_DISPATCH = {
        "page":   (ui_actions_mod.ui_goto_page, "page"),
        "field":  (ui_actions_mod.ui_set_active_field, "path"),
        "tab":    (ui_actions_mod.ui_set_active_tab, "tab_key"),
        "entity": (ui_actions_mod.ui_set_active_entity, "idx"),
    }
    _UI_TARGETS = {"page": int, "field": str, "tab": str, "entity": int}
```

- [ ] **Step 4: 集合更新**

`_IDEMPOTENT`：四个 `ui_*` → `"ui_focus"`（`"ui_open_review"` 保留）。`_tools` 四换一。`app/mcp_server.py::_HEADLESS_EXCLUDE`：四个换成 `"ui_focus"`。`_HTTP_EXEMPT`：四条换成一条 `"ui_focus": "ui side-channel; agent→UI only, CLI clients ignore"`。

- [ ] **Step 5: 登记 + 别名 + 前端**

```python
    # Same (slug, filename, <one value>) shape, all idempotent, all browser-only.
    # Collapses the headless narration contract from four places to one.
    "ui_focus": (
        "ui_goto_page", "ui_set_active_field",
        "ui_set_active_tab", "ui_set_active_entity",
    ),


# …and the same key in MERGED_POLICY — the family's shared profile:
    "ui_focus": frozenset({"idempotent"}),
```
`LEGACY_TOOL_NAMES` 加四行。`toolHint.ts` 的 `case 'ui_goto_page':` 改 `case 'ui_focus':`，hint 文案改成读 `target` + `value`。`stores/chat.ts` 里四个 `ui_*` 常量的失效分支合并成一个。

- [ ] **Step 6: 改 skill 的 rendering contract**

`emerge_extractor.md` 里 `ui_*` 的 **`browser` / `headless` 双分支**必须同时改到位——headless 分支保留 `→ page N` / `→ focus field_name` 的叙述形式，只是不再逐工具列举。改完自查：browser 分支一句摘要、headless 分支完整文字输出，两个分支都在。

- [ ] **Step 7: 跑测试 + 全量 + Commit**

```bash
cd backend && uv run pytest tests/unit/test_tool_ui.py tests/unit/test_tool_policy.py tests/unit/test_symmetry_invariant.py -v
cd backend && uv run pytest -q -n 4 --timeout=120
cd ../frontend && npx vitest run && npx tsc -b --noEmit
cd .. && git add -A && git commit -m "$(cat <<'EOF'
refactor(tools): 四个 ui_set_* 合成 ui_focus(target=) —— 叙述契约也从四处收成一处

四个签名都是 (slug, filename, <单个值>)，全 idempotent，全在
_HEADLESS_EXCLUDE。side-channel 事件形状一个字节没改(前端 reducer 在听)。
ui_open_review 是模式切换、且被真实调用过，留独立。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: 族⑦ `render_board(kind=)`

**Files:**
- Modify: `backend/app/tools/__init__.py`（两个 `t_render_*_board` → `t_render_board`；`_READ_ONLY`；`_tools`；`_MINIMAL_SURFACE`）
- Modify: `backend/app/tools/_merged.py`, `backend/tests/unit/test_symmetry_invariant.py`
- Modify: `backend/app/skills/emerge_extractor.md`
- Modify: `frontend/src/lib/legacyToolName.ts`, `groupChatEvents.ts`, `components/Chat/AuditCard.tsx`, `components/Chat/ReviewBoardCard.tsx`
- Test: `backend/tests/unit/test_tool_render_board.py`（新建）

**Interfaces:**
- Produces: `render_board(slug: str, kind: "audit"|"review")`。**kind 必传，不按项目类型自动派发**——自动派发是改语义，本 plan 禁止。

- [ ] **Step 1: 写失败的测试**

```python
"""render_board(kind=) folds the two board renderers. render_review_board's own
description calls itself "the structured-data twin of render_audit_board's
page-image circling" — one noun, two media. Both take (slug), both read-only,
both zero-LLM.

kind is REQUIRED: auto-dispatching on project type would be a semantics change,
and this milestone is a pure surface refactor."""
from app.tools import registered_tool_names


async def test_render_board_audit_returns_images(
    workspace, stub_provider, audited_project,
) -> None:
    ...  # asserts the content list contains an image block, as the old
         # render_audit_board test did — copy that assertion verbatim


async def test_render_board_review_returns_the_text_legend(
    workspace, stub_provider, reconciled_project,
) -> None:
    ...  # copy from the old render_review_board test


async def test_render_board_requires_kind(workspace, stub_provider) -> None:
    """No auto-dispatch on project type — that would change behaviour. `kind` is
    in the schema's `required`, so the rejection comes from the validation layer
    before the handler; assert that text, not a handler-side error envelope."""
    ...  # call render_board with {"slug": …} only; assert the result text
         # contains "Input validation error"


def test_old_board_names_are_gone() -> None:
    live = registered_tool_names(headless=True)
    assert "render_audit_board" not in live
    assert "render_review_board" not in live
    assert "render_board" in live
```
> 前三个测试体从 `tests/unit/` 里现有的 `render_audit_board` / `render_review_board` 测试**逐字搬过来**，只把工具名和参数换掉。不要重写断言——它们钉的是像素/图例的产出形状，重写等于丢覆盖。

- [ ] **Step 2: 跑，确认失败**

```bash
cd backend && uv run pytest tests/unit/test_tool_render_board.py -v
```

- [ ] **Step 3: 实现**

一个 `t_render_board`，`kind` 必填（`"required": ["slug", "kind"]`），两个分支的 body 从原两个 `t_*` 原样搬（含各自的 `audit_no_report` 错误、legend 文本、interactive board deep-link）。description 把两段合并，保留各自的 `Rendering: browser … / headless …` 双分支契约。

- [ ] **Step 4: 集合 + 登记 + 路由 + 别名 + 前端卡片 + skill**

`_READ_ONLY`：两个 → `"render_board"`（把 `render_audit_board` 那条「deliberately NOT in `_TOUCHES_PROVIDER`, plan red line」的注释保留）。`_tools` 两换一。`_MINIMAL_SURFACE`：`"render_audit_board"` → `"render_board"`。
```python
    # render_review_board's own description: "the structured-data twin of
    # render_audit_board's page-image circling". One noun, two media.
    "render_board": ("render_audit_board", "render_review_board"),


# …and the same key in MERGED_POLICY — the family's shared profile:
    "render_board": frozenset({"read_only"}),
```
```python
    ("render_board", "audit"): ("GET", r"^/lab/projects/\{slug\}/audit/board-render$"),
    ("render_board", "review"): ("GET", r"^/lab/projects/\{slug\}/review/board-render$"),
```
`LEGACY_TOOL_NAMES` 加两行。`AuditCard.tsx` / `ReviewBoardCard.tsx` 的工具名匹配改走 `canonicalToolName` + 读 `kind` 区分卡片；`groupChatEvents.ts::HOISTED_TOOL_NAMES` 里 `render_review_board` → `render_board`。skill 里两个名字改成 `render_board(kind=…)`。

- [ ] **Step 5: 跑测试 + 全量 + Commit**

```bash
cd backend && uv run pytest tests/unit/test_tool_render_board.py tests/unit/test_tool_policy.py tests/unit/test_symmetry_invariant.py -v
cd backend && uv run pytest -q -n 4 --timeout=120
cd ../frontend && npx vitest run && npx tsc -b --noEmit
cd .. && git add -A && git commit -m "$(cat <<'EOF'
refactor(tools): 两块白板合成 render_board(kind=) —— 一个名词两种介质

render_review_board 的 description 自称是 render_audit_board 的
"structured-data twin"。都 (slug)、都零 LLM、都 read-only。
kind 必传不自动派发 —— 按项目类型猜是改语义，本轮只动表面。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: 族⑧ `history(op=)`

本族在 Task 1 之前完全不可达，所以**别名成本和历史渲染成本都是零**（没有任何一条历史 jsonl 记过这两个名字）。

**Files:**
- Modify: `backend/app/tools/__init__.py`（`t_history_log` + `t_history_diff` → `t_history`；`_READ_ONLY`；`_tools`）
- Modify: `backend/app/tools/_merged.py`, `backend/tests/unit/test_symmetry_invariant.py`
- Test: `backend/tests/unit/test_tool_history.py`（新建）

**Interfaces:**
- Produces: `history(op: "log"|"diff", ...)`。两者都 read-only。`history_restore`（mutate）**不并** —— 违反同 policy。

- [ ] **Step 1: 写失败的测试**

```python
"""history(op=) folds the two READ halves of schema version history. The third
member, history_restore, mutates — merging it would break the "same policy"
criterion, which is exactly the rule that keeps a destructive/mutating op from
inheriting a read-only annotation."""
from app.tools import _READ_ONLY, registered_tool_names


async def test_history_log_lists_versions(workspace, stub_provider, versioned_project) -> None:
    ...  # copy the assertions from the existing history_log route test


async def test_history_diff_returns_a_field_delta(workspace, stub_provider, versioned_project) -> None:
    ...  # copy from the existing history_diff route test


def test_history_restore_stays_separate() -> None:
    live = registered_tool_names(headless=True)
    assert "history" in live
    assert "history_restore" in live, "restore mutates — must not be folded in"
    assert "history_log" not in live
    assert "history_diff" not in live
    assert "history" in _READ_ONLY
    assert "history_restore" not in _READ_ONLY
```

- [ ] **Step 2: 跑，确认失败**

```bash
cd backend && uv run pytest tests/unit/test_tool_history.py -v
```

- [ ] **Step 3: 实现 + 登记 + 路由**

一个 `t_history`，`op` 必填，两分支 body 原样搬。`_READ_ONLY` 加 `"history"`（`history_log`/`history_diff` 是 Task 1 才注册的，若当时未进 `_READ_ONLY` 则一并补正——它们确实是纯读）。
```python
    # Both read-only halves of schema version history. history_restore mutates
    # and stays out: same noun, different policy.
    "history": ("history_log", "history_diff"),


# …and the same key in MERGED_POLICY — the family's shared profile:
    "history": frozenset({"read_only"}),
```
```python
    ("history", "log"): ("GET", r"^/lab/history$"),
    ("history", "diff"): ("GET", r"^/lab/history/diff$"),
```
前端别名**不加**（历史里不存在这两个名字），但在 `legacyToolName.ts` 顶部注释里说明为什么这族不在表里。

- [ ] **Step 4: 跑测试 + 全量 + Commit**

```bash
cd backend && uv run pytest tests/unit/test_tool_history.py tests/unit/test_tool_policy.py tests/unit/test_symmetry_invariant.py -v
cd backend && uv run pytest -q -n 4 --timeout=120
cd .. && git add -A && git commit -m "$(cat <<'EOF'
refactor(tools): history_log/history_diff 合成 history(op=)

两个都 read-only。history_restore 是 mutate，不并 —— 同名词但不同 policy，
正是"多 op 工具必须同桶"那条不变量要挡住的情况。
这族在 Task 1 之前完全不可达，所以没有任何历史 jsonl 记过旧名，别名表不用加行。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: 重算 minimal surface + skill 全量核对 + INSIGHTS + ROADMAP + 发版

**Files:**
- Modify: `backend/app/mcp_server.py::_MINIMAL_SURFACE`
- Modify: `backend/app/skills/*.md`（4 个，全量核对）
- Modify: `docs/superpowers/INSIGHTS.md`
- Modify: `docs/superpowers/plans/ROADMAP.md`, `docs/superpowers/plans/2026-06-08-cowork-remote-mcp.md`
- Modify: `CLAUDE.md`（工具数 78 → 64）
- Test: `backend/tests/unit/test_mcp_server_surface.py`（既有；无则新建）

- [ ] **Step 1: 写「skill 里不许出现死工具名」的不变量测试**

```python
def test_skill_prose_names_no_dead_tools() -> None:
    """182 tool-name mentions across four skills. A renamed tool that survives
    in skill prose is worse than a missing one: the agent confidently calls a
    name that no longer answers. This is the check that the P4 rename passes
    cannot skip."""
    import re
    from pathlib import Path

    import app.skills as skills_pkg
    from app.tools import registered_tool_names
    from app.tools._merged import legacy_alias

    live = registered_tool_names(headless=True)
    stale = legacy_alias()
    offenders: list[str] = []
    for md in Path(skills_pkg.__file__).resolve().parent.glob("*.md"):
        text = md.read_text(encoding="utf-8")
        for name in sorted(stale):
            if re.search(rf"\b{re.escape(name)}\b", text):
                offenders.append(f"{md.name}: {name} → {stale[name]}")
    assert not offenders, (
        "skill prose still names folded-away tools:\n  " + "\n  ".join(offenders)
    )
    assert live, "sanity: registration probe returned nothing"
```

- [ ] **Step 2: 跑，把它逼绿**

```bash
cd backend && uv run pytest tests/unit/test_mcp_server_surface.py -v
```
失败就按提示逐条改 skill 文本。Task 4–11 每族已改过一轮，这里是兜底扫尾。

- [ ] **Step 3: 重算 `_MINIMAL_SURFACE`**

把 8 族的新名替换进去，并给 Task 1 复活的 9 个定 listing：

```python
    # (b) invariant writes — Bash gets these wrong (filename is the primary key
    # of four sibling artifacts; a memory's body and its MEMORY.md line must
    # move together). Reachable again since 2026-08-16 (P4 Task 1).
    "delete_doc", "rename_doc", "forget_memory",
```
`list_trash` / `restore_from_trash` / `rename_project` / `history` / `history_restore` **只进 full，不进 minimal**——它们是恢复/审计路径，远程队友的日常闭环用不到，且 `ws_*` 读得到 `_trash/` 的内容（但读不到「怎么原样恢复」，所以 full 面必须留着）。

在 `_MINIMAL_SURFACE` 的注释块里补一句本轮的判据：
```python
# 2026-08-16 (P4): this list is the CHEAP lever — it cuts listing without
# renaming anything, so no alias layer, no broken history, no skill rewrite.
# Nothing new was cut this round: everything still listed and uncalled is a
# rare-but-correct verb (promote_experiment, run_experiment_eval, …), not a
# duplicate surface. Cutting those is what went wrong in June.
```

- [ ] **Step 4: 加一条 surface size 的回归钉**

```python
def test_surface_sizes_are_what_the_plan_says() -> None:
    """Sizes are load-bearing: the remote minimal surface is a teammate's
    context tax, and drift there is invisible until a dogfood fails. Update
    these numbers deliberately, never to make a red test green."""
    from app.mcp_server import _HEADLESS_EXCLUDE, _MINIMAL_SURFACE
    from app.tools import registered_tool_names

    headless = registered_tool_names(headless=True)
    chat = registered_tool_names(headless=False)
    listed = headless - _HEADLESS_EXCLUDE

    assert len(headless) == 64, sorted(headless)
    assert len(chat) == 54, sorted(chat)
    assert len(listed) == 61, sorted(listed)
    # Net-unchanged on purpose: merging cost minimal 3 slots and Task 1's three
    # red-line revivals (delete_doc / rename_doc / forget_memory) added 3 back.
    assert len(listed & _MINIMAL_SURFACE) == 41, sorted(listed & _MINIMAL_SURFACE)
    stale = _MINIMAL_SURFACE - headless
    assert not stale, f"_MINIMAL_SURFACE names tools that no longer exist: {sorted(stale)}"
```
> 实施时若实测数与 64/54/61/35 有出入，**先查是不是漏改了某一族**；确认无误后把真实数写进来，并同步更新本 plan §分组决策表的目标数表和 CLAUDE.md。

- [ ] **Step 5: INSIGHTS 追加一条**

在 `docs/superpowers/INSIGHTS.md` 的 "When to add an entry here" 之前插入：

````markdown
## 收敛工具表面：可并的四个条件，和「少」什么时候等于能力消失

**Where:** `backend/app/tools/_merged.py`（声明表）、`tests/unit/test_tool_policy.py`（不变量）、`app/mcp_server.py::_MINIMAL_SURFACE`（listing 杠杆）。

**两次教训，一个结论。** 2026-06-10：第一版 minimal surface「按 suite 砍」，
几小时内一个真实 audit 请求让 agent 无合法路径可走，它改用 `read_doc_image`
自己当裁判——踩 agent self-audit 红线。2026-08-16 量数据时发现的第二件事：
**9 个 `@tool` 装了但从没进 `create_sdk_mcp_server(tools=[...])`**，对 chat /
stdio / remote 三个面全部不存在，而 `test_symmetry_invariant::_discover_tools()`
正则扫的是**源码文本**，78 个装饰器全过。

两件事看起来无关，其实是同一个错误的两面：**把「表面上有几个名字」当成了
「有几种能力」。** 前者砍掉了唯一路径还以为在减负，后者数了 78 个名字而真实
可达只有 69。

**可并的四个条件，缺一不可：** 同名词 · 同输入形状 · 同 policy · **成员里没有
破坏性 op**。第四条不是保守，是硬约束：**MCP annotation 是 per-tool-name 的，
客户端的 auto-approve / gate 只能按名字**。`project(op='delete')` 一旦存在，
Cowork 就只能整个放行或整个拦——服务端再精细的 `(noun, op)` policy 表**传不
过去**。`always_allow`（按 `tool_name` 记）同理。所以正确的做法不是「让 policy
支持 (noun, op)」，而是**让多 op 工具的所有 op 天然同桶**，破坏性动词永远保持
独立单名。

**「零调用」只对一类构成证据。** 588 次真实调用里 34/78 从未出现，但要分三类
读：(A) 不可达所以没人调 —— 是 bug，不是冗余；(B) 罕见但正确的 op
（`promote_experiment` / `cancel_job`）—— 低频是它该有的样子，砍掉是能力消失；
(C) 真·重复表面（四个签名逐字相同的 model setter）—— 只有这类该并。6 月那次
正是把 B 当 C 处理。

**便宜的杠杆先用完再考虑贵的。** `_MINIMAL_SURFACE` 只改 listing：不改名、不
需要别名层、不碎历史渲染、不用重写 182 处 skill 文本。它已经把 remote 面从 63
压到 41。归并才是贵的那个。**先问「能不能只是不 list」，再问「要不要并」。**

**还有一个数不该忘：`Bash` 260 次，全场第一**（`ws_*` 合计 44，最热的自家工具
`extract` 147）。通用面已经在扛长尾——这是「不做第三个通用面」的实测依据。
````

- [ ] **Step 6: ROADMAP + P4 章节 + CLAUDE.md**

ROADMAP 里 P4 从 `2026-06-08-cowork-remote-mcp.md` 独立成行，指向本 plan，状态填实施结果；描述里把「38→~10」改成实测口径（78 源码 / 69 可达 → 64，remote minimal 41 → 35），并注明「6 月的 38 与 ~10 均已过期」。`2026-06-08-cowork-remote-mcp.md` §P4 加一行指针指向本 plan。`CLAUDE.md` 仓库布局那段 `@tool 函数（78 个）` 改成实测数。

- [ ] **Step 7: 全量绿**

```bash
cd backend && uv run pytest -q -n 4 --timeout=120
cd ../frontend && npx tsc -b --noEmit && npx vitest run
```
Expected: 后端 0 failed；前端仅既有 11 个 `FSSpine-*` 失败。

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "$(cat <<'EOF'
docs(tools): P4 收口 —— 重算 minimal 面、skill 死名不变量、把两次教训收在一处

_MINIMAL_SURFACE 换新名并给复活的九件定 listing(delete_doc/rename_doc/
forget_memory 进 minimal，恢复/审计路径只进 full)。本轮不新增任何 cut：
剩下的零调用工具是罕见但正确的动词，砍它们正是六月出事的地方。
INSIGHTS 记下可并的四个条件 + 破坏性 op 为什么永不能并(annotation 按名字，
policy 表传不过去)。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 9: 发版**

```bash
./deploy.sh
```
部署后只做**非交互冒烟**：`curl` 一次 `/healthz`；用 PAT 对 `/mcp/` 发一次 `tools/list`，确认工具数 = 35（minimal）且含 `extract` / `set_model` / `render_board`。

**发版说明必须写一句**：正连着的 Cowork/Desktop session 手里可能还握着旧 tool list，第一次调用旧名会拿到 unknown tool；重连（客户端会重新 `initialize`）即恢复。这是本 plan「服务端不收旧名」的已知且可自愈的代价。

- [ ] **Step 10: 停在这里，交回人手 dogfood**

**不要**自己开浏览器做 live smoke。按 `feedback_milestone_dogfood_handoff`，把下面这份清单交回给人：
1. 浏览器 chat：跑一次 extract → review → `save_reviewed`，确认卡片正常、`extract` 新名的 hint 显示对。
2. 打开一个**旧 chat**（prod 上 `百胜audit1` 有 8 个），确认历史里的 `extract_one` / `score_audit` 仍渲染成正常卡片而不是「未知工具」。
3. Cowork/Desktop connector 重连一次，问「这个项目用的什么模型」（走 `get_project_config`）+ 让它 `set_model(role='labeler')`。
4. 让 agent 删一个测试 doc —— 确认它调 `delete_doc` 而不是 Bash `rm`（这是 Task 1 的验收点）。

---

## Self-Review

**1. Spec coverage.** briefing 六节逐条对：§3 三个数 → §0（含 briefing 没预料到的第四个发现：9 个不可达）；§4 八条硬约束 → alias(#1)=Task 3 / policy(#2)=Task 2 + Policy 设计 / always_allow(#3)=Task 2 不变量 / symmetry(#4)=Task 4 Step 6 的 `(tool, op)` 键 / skill(#5)=每族 + Task 12 Step 1 不变量 / 墓志铭(#6)=§0.2 的 ABC 三类 + Task 12 Step 3 注释 + INSIGHTS / 三形对称(#7)=每族 / `_HEADLESS_EXCLUDE`+`_MINIMAL_SURFACE`(#8)=Task 9 + Task 12；§5 分组表 → §分组决策表；§6 四项交付物 → plan(本文) + ROADMAP(T12 S6) + 一族一 commit(T4–11) + INSIGHTS(T12 S5) + 全量绿(T12 S7)；§7 开工顺序 → 已按序执行。

**2. Placeholder scan.** Task 10/11 的三处测试体写的是「从既有测试逐字搬」而非贴代码 —— 这是刻意的：那些断言钉的是像素/图例/版本 diff 的产出形状，重写等于丢覆盖，指明来源比抄一份走样的更可靠。其余步骤均含可直接执行的代码或命令。三处「以现有实现为准先读一眼」（`_error` 的实际名字、`JobRunner` 的方法名、`emit_ui_action` 的签名）是诚实的接口不确定性，已标明在哪读。

**3. Type consistency.** `registered_tool_names(headless=)`（T1 产出）被 T2/T4–T12 一致消费；`MERGED_TOOLS: dict[str, tuple[str, ...]]`（T2）在 T4–T11 逐族追加、T12 Step 1 反查；`legacy_alias() -> dict[str, str]`（T2）被 T12 Step 1 用；`canonicalToolName`/`LEGACY_TOOL_NAMES`（T3）被 T4/T6/T7/T9/T10 追加；`_TOOL_HTTP_MAP` 的键在 T4 Step 6 一次性改成 `tuple[str, str | None]`，此后所有族按该形状写。
