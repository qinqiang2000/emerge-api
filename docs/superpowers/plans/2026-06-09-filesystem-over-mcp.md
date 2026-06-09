# 2026-06-09 — Filesystem over MCP（把"文件系统总线"暴露给远程客户端）

> **Status**: ✅ P0 (read 三件 ws_list/ws_read/ws_grep) + P1 关键部分 (add_model typed 工具 + skill interface-aware FS 分支) shipped & deployed prod (2026-06-09)；P1 的通用 ws_write/ws_edit/ws_move **deferred**（model 注册已被 add_model 闭合；raw 文件写是最险面，按 dogfood 需求再加）；P2 收敛 + Tier-2 code-exec planned。**Pending**: Cowork 重连重跑「增加 gemini-2.5-flash 然后提取」登录式 dogfood。
> **Closes**: 远程 MCP 客户端（Cowork/Desktop）"大量能力不可用或不好用"的根因——`emerge_extractor.md` 把"文件系统 = API"硬编码，而远程客户端的 Bash 在自己的云沙箱，看不到服务器磁盘。
> **Supersedes**: `2026-06-08-cowork-remote-mcp.md` 的 **P1.6**（逐个 reconcile Step B 砍的工具）——本 plan 用一个文件系统面**一次性**恢复，而非逐点补 typed 工具。
> **Reframes**: 该 plan 的 **P4**（工具收敛）——headless 面收敛成"~6 个 `ws_*` + 少数 typed 不变量动词"，自然 ~15 而非 38。
> **Inputs**: dogfood 实锤（截图：agent 想"加 model→用它"，9 步反复撞墙，因为 MCP 面无 `list_models`/`add_model` 且 `cat project.json` 不到）+ 研究（Anthropic code-execution-with-MCP、官方 filesystem MCP server + Roots、filesystem path-traversal advisory）

---

## 根因（固化）

`emerge_extractor.md` §"Workspace is your filesystem"（行 63-92）白纸黑字：

> emerge intentionally has no `list_docs`/`rename_project`/`delete_*` tools — **paths are the API.** "List projects" → `Bash ls {WORKSPACE_ROOT}/`；Copy/move → `Bash cp`/`mv`；List/search → `Glob`/`Grep`；读 PDF/图 → `Read`。

本地（emerge 自家 chat 的 agent brain cwd=工作区；或本地 Claude Code）**共享工作区 FS**，这套极灵活。**远程不成立**：Cowork 的 Bash 在它自己的云沙箱，`WORKSPACE_ROOT` 在那不存在。Step B（SDK reframe）砍 23 个 filesystem-wrapper 工具时，赌注是"agent 用内置 Bash 操作工作区"——**只在共享 FS 时成立**。截图里 agent 完全照 skill 做了（"让我看看 project.json 结构"→"文件系统里找不到项目文件"），是前提为假，不是 agent 犯错。

## 统一洞察

emerge 核心对象**本来就是文件**（`project.json` / `models/{id}.json` / `prompts/{id}.json` / `predictions/*.json`）。所以**把 team 工作区的文件系统作为 MCP 暴露 = 一次把每个核心对象的全套 CRUD 暴露**——不是逐个补 `list_models`/`get_prediction`… 23 个 typed 工具（那是"解决点"）。skill 说"paths are the API"，远程就**把同样六个动词（list/read/write/edit/glob/grep）做成 MCP 工具**指向服务器的 team 工作区——**同一份 skill 一字不改重新成立**。

## 架构决策

1. **auth-scoped roots（比官方 filesystem-server 更优雅）**。官方 server 靠客户端 Roots 或命令行参数定 scope。emerge **不需要**——team 工作区**已由 auth token 每请求解析**（P1 的 `_authenticate`→`_resolve_team_workspace`）。root = 认证出的 team 目录，**客户端零配置、物理上逃不出本 team**。这是 zero-config 多租户文件系统 over MCP。
2. **混合按操作语义分（这才是"面"，不是按名词分）**：
   - **读 + 纯文件移动** → 通用 `ws_*` 文件系统工具（安全；一招恢复全部发现/读取/cp）。
   - **带不变量/副作用的写** → 保留 typed 工具：`delete_project`（tombstone 抢在 chat-log writer 前——见 skill 行 92）、`write_schema`（原子 prompt 版本化）、`extract_*`/`score`/`*_experiment`（LLM 调用）、`freeze_version`/`issue_api_key`（真实根 keystore）。这些**不是单纯文件操作**，手搓 JSON 会破不变量（截图里 agent 正想手改 project.json 注册 model = 危险）。
3. **headless-only**。`ws_*` 只在 `build_emerge_mcp(headless=True)` 注册（stdio + remote）。emerge 自家 chat（`headless=False`）继续用内置 Bash/Read/Write——它**共享 FS**，加 `ws_*` 是噪音。这是 P1.5 发现三件套的扩展（同一 `if headless` 门）。
4. **containment 即 secret 防护（关键简化）**：所有 secret 都在**真实根**（`_auth`/`_keys.json`/`_published`）或 backend 根（`.env`）——**都在 team 工作区之外**。所以"路径必须 resolve 进 team 根内"这一条**天然挡住每一个 secret**。仍保留显式 denylist 作 defense-in-depth（INSIGHTS #1 的 `.env` 泄露教训：硬 block 必须服务端强制，不靠 prompt）。
5. **删除走 trash 不走 rm**（红线：绝不物理删用户数据）。不暴露通用 `ws_delete`；删整项目仍走 typed `delete_project`；其余删除（如清 `predictions/_draft`）走 `workspace/trash.py::trash()`。

---

## Phases

### P0 — 读侧文件系统工具（最小修复，直接解掉截图）

**In:**
- `app/tools/workspace_fs.py`（新）：`_safe_ws_path(workspace, rel) -> Path`——`(workspace/rel).resolve()` 后断言 `is_relative_to(workspace.resolve())`，拒 symlink 逃逸 + 拒 denylist（`.env*`/`*.key`/`*.pem`/含 `secret`/`_auth`/`_keys`）。复用 `api/routes/_safety.py` 的 sanitizer 风格。
- 三个 `@tool`（headless-only，注册进 `build_emerge_mcp` 的 `if headless` 块）：
  - `ws_list(path=".", recursive=False)` → 目录列表（替 `Bash ls` + `list_projects`/`list_docs`/`list_prompts`/`list_models`/`list_experiments`/`list_reviewed`）。默认浅列；`recursive` 出 tree。skip dotfiles + `_`-前缀 sentinel（与项目扫描器一致）。
  - `ws_read(path, max_bytes=…)` → 读 UTF-8 文本/JSON（替 `cat` + `read_prompt`/`get_prediction`/`get_reviewed`/`get_pending`）。大文件截断 + 提示。**PDF/图不走这里**——保留现有 vision-pull 工具 `read_doc_image`/`pdf_render_page`（红线：doc vision is pulled）。
  - `ws_grep(pattern, path=".", glob=None)` → 递归内容搜索（替 `Grep`/`Glob`）。
- rendering contract：headless → 紧凑文本（目录树/文件内容/命中行）；browser → 一句摘要（UI 兜底，虽然 `ws_*` 实际只在 headless 出现，契约仍双写以防误用）。
- `_TOOL_HTTP_MAP` 对称：`ws_list`/`ws_read`/`ws_grep` 配 HTTP twin（`GET /lab/ws/list` · `.../read` · `.../grep`，team-scoped via `current_ws()`）或写入 `_HTTP_EXEMPT` 注明理由（倾向给 twin——保持对称契约 + 让 CLI 可达）。

**Tests:** `test_workspace_fs.py`——containment（`../` 逃逸→拒、symlink→拒、`.env`→拒、跨 team→拒）、`ws_list` 列出 models/ 含真实 model 文件、`ws_read` 出 project.json、headless-only 注册（chat 面无泄漏）、symmetry 3 passed。

**Verified（live remote）:** 重跑截图场景——"增加 gemini-2.5-flash 然后提取一个文件"：agent `ws_list("models/")`→见真实 model 文件→`ws_read` 确认 provider_model_id→不再瞎蒙 id。

### P1 — 写侧 + skill interface-aware

**In:**
- `ws_write(path, content)` → 建/覆盖文本文件（替 `Write` + `create_prompt`/`write_model`/`import_prompt` 的"手写 JSON"路径）。**写后副作用**：落 `docs/` 的 sidecar 仍 lazy-rebuild（skill 行 90"no register tool needed after cp"）；写 `models/`/`prompts/` 后**不**自动 wire `active_*`——那是 typed 工具的活，skill 明示"注册 model 用 `switch_active_model`/写 project.json 用 typed 工具"。
- `ws_edit(path, old, new)` → 定点替换（替 `Edit`）。
- `ws_move(src, dst)` → workspace 内 cp/mv（替 `Bash cp`/`mv`）。**不暴露 `ws_delete`**——删走 trash/typed。
- `emerge_extractor.md` 加 **interface-aware "Workspace access" 分支**（扩展现有 browser/headless rendering contract 模式）：
  - **browser/local**（`interface: browser` 或共享 FS）：现状不变——Bash/Glob/Grep/Read/Write/Edit on `WORKSPACE_ROOT`。
  - **headless-remote**（`interface: headless`）：同样的 paths-are-the-API 心智，但用 `ws_list`/`ws_read`/`ws_grep`/`ws_write`/`ws_edit`/`ws_move`；"List projects" → `ws_list(".")`；"读 project.json" → `ws_read("{slug}/project.json")`。**一个心智模型、一份 skill、transport 路由。**
- skill 顺带补：headless 下"注册新 model"= `ws_write("models/{id}.json", …)` + `switch_active_model`（截图那个具体卡点的正解写进 skill）。

**Tests:** `ws_write`/`ws_edit`/`ws_move` containment + sidecar lazy-rebuild 触发 + 删除路径不可达（无 `ws_delete`）；skill 渲染契约 lint（browser+headless 双分支齐全）。

### P2 — 收敛（接管旧 P4）

audit headless 面：`ws_*`（6）+ 保留的 typed 不变量动词（`delete_project`/`write_schema`/`extract_*`/`score`/`*_experiment`/`freeze_version`/`issue_api_key`/job 控制）≈ 15 个，给非技术队友清爽。per-tool annotations（已落地）+ skill 引导高危确认。**`emerge_` service 前缀**（best-practice 防撞名）并这里做。

### Tier-2（future，非本期）— code execution / CLI

文件系统总线回来后，叠加 Anthropic [code-execution-with-MCP](https://www.anthropic.com/engineering/code-execution-with-mcp)：`emerge` CLI 或 code-exec 工具，agent 写代码组合 + 在沙箱过滤数据（token 省 ~98%、可组合）。**需沙箱跑 agent 代码 + CLI 装进客户端**——对 Cowork onboarding 重；且它也假设有文件系统。所以 **FS-over-MCP 先、code-exec 后**。等用例攒够再开 plan。

---

## 红线（遵守）

- **lab=prod 一致**：远程 agent 经 `ws_*` 做的 = 本地 agent 经 Bash 做的，只是 transport 路由；工具内绝不递归回 SDK。
- **绝不物理删用户数据**：无通用 `ws_delete`；删走 `trash.py::trash()` / `delete_project`。`_` 前缀 sentinel 目录在 `ws_list` 默认隐藏（与 orphan-sweep 豁免一致，见 INSIGHTS teams/ 事故）。
- **secret 永不可达**：containment-to-team-root 天然挡（secret 全在真实根/backend 根之外）+ 显式 denylist 服务端强制（INSIGHTS #1：不靠 prompt）。
- **doc vision is pulled**：PDF/图不走 `ws_read`；保留 `read_doc_image`/`pdf_render_page`，不给 `ws_read` 加 auto-attach 分支。
- **bbox 永不进 prompt**：`ws_*` 只碰文件字节，不碰 evidence 渲染层。
- **prod 产物落真实根**：`ws_*` scoped 到 team 工作区，够不到 `_published`/`_keys.json`（在真实根）——publish 红线不破。
- **对称契约**：每个 `ws_*` 配 HTTP twin 或 `_HTTP_EXEMPT` 注明（`test_symmetry_invariant.py` 强制）。

## Remote 闭环 dogfood（2026-06-09，computer-use 驱动 Cowork）

接「补 remote 闭环」arc：在 Cowork（原生 Claude app，full tier）续跑 `北方工业` 的 extract→review→eval→compare，驱动方式 = computer-use 真机操作。**结论：闭环在 remote/headless 下全程自助跑通且输出优质，无大洞。**

- ✅ **review→save_reviewed**：一句"存为 ground truth"→ agent 一步 `Save reviewed`，没要路径、没撞墙。
- ✅ **eval→compare**：要求对比 gemini-2.5-flash vs 默认（gemini-3-flash-preview）→ agent 自主编排 `get_project_config`→`create_experiment`(默认模型)→`extract_with_experiment`→两次 `run_experiment_eval`→渲染对比表（flash 90.9% vs preview 81.8% @1.jpg）+ **自诊断** `merchantName` 丢分=两模型都多带括号业态描述、GT 没有 + 建议 prompt 修法。AutoResearch 式洞察自然涌现。
- 🟡 **修掉**：背靠背两次 eval 间 agent 不出文字 → Cowork 渲染成 `(empty placeholder)`（非 emerge bug，是 client 对无文字 turn 的渲染）。skill 补 headless 渲染契约（每次 eval 出一行分）消掉空 turn + 流式反馈。已 deploy。
- 🟡 **client 配置项（非 emerge fix）**：Cowork 默认对**每个** tool call 弹权限确认（含 readOnly 的 `get_project_config`）。已 ship 的 annotations 让用户**可**设 tool-policy 自动放行 readOnly，但默认仍 ask——告诉用户去 Cowork 设 policy 即可。

## Follow-ups

- `ws_read` 大目录/大文件分页（best-practice pagination）。
- 旧 P1.6 列表（`get_prediction`/`list_prompts`/`create_prompt`/`write_model`…）**本 plan 一次性覆盖**——它们都是 `ws_read`/`ws_list`/`ws_write` 的特例，逐个 typed 工具不再需要。
- **archive/delete experiment 远程无 FS 下断**：skill 行 308 用 `Bash mv experiments/{id} ...` 归档，远程客户端 Bash 在沙箱够不到——需 `ws_move`(deferred) 或把 `archive_experiment` 暴露成 typed 工具（dogfood 未撞，低频，留 follow-up）。
- Tier-2 code-exec/CLI 单开 plan。
