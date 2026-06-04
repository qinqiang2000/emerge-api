# emerge

Software 3.0 文档 API 平台。**Slogan**: Documents in. APIs emerge. They get better as you correct them.

## 指引

- **Roadmap**: `docs/superpowers/plans/ROADMAP.md` — 开工前先读，看 milestone 状态
- **Trap notes**: `docs/superpowers/INSIGHTS.md` — 改任何"看起来多余"的代码前先查
- 实施 plan: `docs/superpowers/plans/YYYY-MM-DD-<milestone>.md`，按 ROADMAP 顺序执行

## Collaboration

- 中文叙述、简洁、不要 trailing summary
- 推荐而非菜单；用户是 Karpathy software-3.0 fluent + label-studio veteran
- SSU 原则：体验佳，无须学习，simple and stupid 优先
- Destructive 操作（删文件、force-push、改 spec/schema 结构）先问
- Lab 侧不预算 token / $ — 只 `max_turn` 和 `early_stop_no_improvement` 边界

## Engineering

- **Backend**: FastAPI + `claude_agent_sdk` + 直连 provider HTTP + pydantic v2 + uv。**无 DB**——project = filesystem folder
- **Frontend**: Vite + React 19 + TS + Zustand + Tailwind v3（CSS-var token system）+ Radix + Lucide
- 错误响应 `{error_code, error_message_en}`；不允许 Tailwind 直接 color class，只用语义 token（`paper`/`ink`/`ochre`/`rose`/`moss`，见 `frontend/tailwind.config.js`）
- 测试: `cd backend && uv run pytest -v`
- Schema 真相: `backend/app/schemas/schema_field.py::SchemaField`
- **UI chrome 任务类型无关**：通用动词（`init/run/tune/review/publish/ingest`），不出现 `extract`/`invoice` 等提取专用词；API 路由已固化部分（`/v1/{pid}/extract`）保持现状
- **Tool ↔ HTTP ↔ MCP 三形对称**：每个 `@tool` 必须配 HTTP route（`test_symmetry_invariant.py` 强制）并自动继承进 `mcp_server.py`；无法对称的写入 `_HTTP_EXEMPT` + `_HEADLESS_EXCLUDE` 并注明理由

## 五层 LLM（互不交叉，工具体内绝不递归回 SDK）

| 角色 | 路径 | 配置锚点 |
|---|---|---|
| Agent brain | `claude_agent_sdk.ClaudeSDKClient` | 系统级 env，锁 Anthropic |
| Extract LLM | `provider/*.py` 直连 HTTP | `active_model_id`→`models/{mid}.json`；env 仅 bootstrap seed，改了不影响已有项目 |
| Proposer LLM | 同上 | per-job → project → env → `ProposerNotConfiguredError` |
| Labeler LLM | 同上 | `project.json.labeler_model` → env fallback |
| Translator LLM | 同上 | `project.json.translate_model` → env fallback（默认 gemini-flash-lite） |

## "同事"精神（人格红线）

emerge 是**文档处理能力强的同事**，不是绑在某界面的工具。迭代时守住：

- **Chat 能完成一切**：任何操作 chat 可触达，不能只靠 UI 点击
- **interface-aware 渲染**：skill prompts 的 rendering contract 必须同时写 `browser`（一句摘要，UI 卡片兜底）和 `headless`（完整文字输出）两个分支；只写一个不合格
- **`ui_*` headless 下叙述代替调用**：`→ page N` / `→ focus field_name`，不能静默跳过
- **`interface` 信号透传**：调用 `chat_turn` / `_build_system_prompt` 的新路径必须传 `interface=`，不得硬编码

## Hard rules (red lines)

- **没有 image few-shot**；要教模型只改 `description` / `global_notes`
- **没有 bbox 进 prompt**；坐标只活在 review 渲染层，永不进 extract / labeler / proposer 上下文
- **AutoResearch 永不自动 promote**；user 必须显式 activate
- **Counterexample 永不进 runtime prompt**；仅作 AutoResearch 回归测试集
- **Public API 读 `_published/{pub_xxx}.json`**；`schema.json` 是 lab 编辑态，不得渗入 prod
- **不读取/打印/提交 secrets**（`.env`、provider key、API key 明文等）；runtime 实现见 INSIGHTS #1.5
- **Agent brain ↔ Extract LLM 分离**；tool 内绝不递归回 SDK
- **`schema.json` 只通过 `write_schema` 修改**；autoresearch 只写 `versions/_candidate/`
- **Doc vision is pulled, not pushed**：不要给 `_load_image_blocks` 加 auto-attach 分支
- **绝不物理删除用户数据**（project/experiment 等）；删=`workspace/trash.py::trash()` 移进 `_trash/`（可恢复，保留期后 `cleanup_trash` 才真删）。`rmtree` 只允许打在派生缓存(`predictions/_draft` 即删即重建之类)。新加任何根级 `_` 前缀 sentinel 目录必须进 `orphans._sweep_dir` 的豁免——否则下次重启被当孤儿删（见 INSIGHTS：2026-06-04 `teams/` 被清空事故）

## 多租户（Users & Teams，2026-06-03）

- **team = workspace 子目录前缀**，不是 `project.json` 里一列。项目落在 `workspace_root/teams/{team_slug}/{slug}/`(目录名是 `Team.slug` 这种人类可读 handle，**不是** `t_xxx` id；id 只活在 `teams.json` 做稳定引用锚，复用 `workspace/slug.py::derive_slug`，同 project 模型)。隔离=物理目录(agent cwd 自动收紧到本 team)。`tools/`/`paths.py`/`chat/service.py` 一律接收 `workspace: Path`，**不读 settings**——只有 route 层经 `bind_workspace` 依赖把 `settings.workspace_root` 解析成 team 工作区(它读 `Team.slug` 拼路径),handler 用 `current_ws()` 取。
- **Open mode ↔ Tenant mode**：`store.auth_configured`(=是否有用户)是开关。**无用户**→ 扁平 root + 零鉴权(= 引入多租户前的行为,存量测试照常)。`create_superuser` 建首个用户后翻成 tenant mode:`/lab/*` 强制鉴权、项目落 `teams/` 下。别把鉴权写成无条件强制——会搞挂所有不鉴权的存量 route 测试。
- **双通道鉴权(同事精神)**：浏览器走 `SessionMiddleware` 长效 rolling cookie;headless 走长效 PAT `Authorization: Bearer`。`current_user` 同时认两者。`/lab/*` 任何能力都必须对 headless 可达(UI 可被 Claude Code/Desktop cowork 替换)。`mcp_server.py` 经 `EMERGE_TEAM_ID` 选 team。
- **auth 数据全局**:`_auth/{users,teams,pats}.json` 在**真实根**,用 `settings.workspace_root` 读写,**绝不**用 `current_ws()`。`_keys.json` prod keystore 也留真实根(prod 不靠登录态)。
- **superuser 独占建 team**(一客户一 team,成员转发同一邀请链接拉人,team 内无管理员);跨 team 项目共享下一期(复用 M9.4 fork)。

## 仓库布局

```
backend/app/
  api/       # /lab/* routes + /v1/{pid}/extract (prod fast-path)
  chat/      # claude_agent_sdk 集成层
  skills/    # emerge-extractor / autoresearch / publish skill prompts
  tools/     # @tool 函数（~35 个）+ mcp_server.py（standalone stdio MCP）
  provider/  # anthropic / openai / gemini adapter
  schemas/   # SchemaField 等 pydantic models
  jobs/      # JobRunner (asyncio queue)
  workspace/ # filesystem helper（atomic write、flock）
frontend/    # 三栏 chat shell + review 模式
docs/superpowers/{specs,plans}/
```

参考实现（不导入、不迁移）：
- `/Users/qinqiang02/colab/office/agent-harness/` — claude_agent_sdk 集成模式
- `/Users/qinqiang02/colab/codespace/ai/emerge-v1/` — 上一代，可参考 engine 算法 / contract_diff 等纯计算逻辑
