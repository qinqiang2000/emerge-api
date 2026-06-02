# emerge

Software 3.0 文档 API 平台。**Slogan**: Documents in. APIs emerge. They get better as you correct them.

## Design source of truth

- Handoff bundle: `docs/design/emerge-api/`
- **Roadmap**: `docs/superpowers/plans/ROADMAP.md` — milestone chain + status. **Read first** when picking up work.
- **Insights / trap notes**: `docs/superpowers/INSIGHTS.md` — why certain non-obvious code paths exist. Consult before "simplifying" anything that looks redundant.
- 实施 plan: `docs/superpowers/plans/YYYY-MM-DD-<milestone>.md`，按 ROADMAP 顺序执行

## Collaboration

- 中文叙述、简洁、不要 trailing summary
- 推荐而非菜单 — 给方向 + 主要 trade-off，不要罗列等价选项让用户挑
- manual-confirm: destructive 操作（删除文件、force-push、改 spec、改 schema 结构）先问
- 用户是 Karpathy software-3.0 fluent + label-studio veteran，不需要解释 task/annotation/prediction 分离这种基础概念
- SSU 原则：客户体验佳，无须学习，架构 simple and stupid。任何"保留 vs 重写"选择优先 SSU
- Lab 侧不预算 token / $ — 只 `max_turn` 和 `early_stop_no_improvement` 边界

## Engineering

- **Backend**: FastAPI + `claude_agent_sdk` + 直连 provider HTTP（Anthropic / OpenAI / Gemini）+ pydantic v2 + uv 管理依赖。**无 DB**——project = filesystem folder
- **Frontend**: Vite + React 19 + TypeScript + Zustand + react-router 6 + Tailwind v3（CSS-var token system，Anthropic palette）+ Radix + shadcn-style + Lucide
- 错误响应统一 `{error_code, error_message_en}` envelope；前端按 `error_code` 翻译
- **不允许** Tailwind 直接 color class，只用语义 token（`paper`/`ink`/`ochre`/`rose`/`moss`，见 `frontend/tailwind.config.js`）
- 测试: `cd backend && uv run pytest -v`
- 单一 schema 真相: `backend/app/schemas/schema_field.py` 的 `SchemaField` pydantic model
- **任务类型无关的 UI**：本 shell 要复用到非文档提取任务（matching、classification 等）。chrome 层（按钮、空状态、popover、slash-menu copy、kind chips）用通用动词（`init / run / tune / review / publish / ingest`），不出现 `extract` / `invoice` / 文档提取专用名词；提取专用术语只允许出现在 content/help 文案和真实路径（如 `docs/`）里。API 发布层（`/v1/{pid}/extract` 路由名等已固化部分）保持现状不破坏兼容
- **Tool ↔ HTTP dual-form symmetry**：每个 `@tool` 注册必须配套 HTTP route（由 `backend/tests/unit/test_symmetry_invariant.py` 强制）。无法对称的 tool（如 `ui_*` 侧通道、`ask_user` 请求半）走 `_HTTP_EXEMPT` 并写明一行理由。新加 tool 时同步加 route（thin-delegate 模板见 `2026-05-19-turn-as-resource.md` §Phase B）或加 exempt 项。

## 五层 LLM（互不交叉）

| 角色 | 走哪 | 配置 | 配置作用 |
|---|---|---|---|
| Agent brain | `claude_agent_sdk.ClaudeSDKClient`（chat 大脑） | 系统级 env，锁 Anthropic | `EMERGE_*` 锁 Anthropic（系统级 runtime） |
| Extract LLM | `provider/{anthropic,openai,gemini}.py` 直连 HTTP | per project，`project.json.active_model_id` → `models/{mid}.json` | `EMERGE_DEFAULT_EXTRACT_MODEL` 仅 **bootstrap seed**（`create_project` 时写入 `m_default.provider_model_id` + 老 project lazy-migrate）；runtime 完全走 `read_active_model`，env 改了不会影响已有项目 |
| Proposer LLM (autoresearch) | 同上，直连 HTTP | per-job override + per project | `EMERGE_DEFAULT_PROPOSER_MODEL` 是真 **runtime fallback**：链 = per-job override → `project.json.autoresearch_proposer_model` → `project.json.active_model_id` → env → raise `ProposerNotConfiguredError` |
| Labeler LLM (pro 预标) | 同上，直连 HTTP | per project `project.json.labeler_model` | `EMERGE_DEFAULT_LABELER_MODEL` 是真 **runtime fallback**（每次 `label_docs` 现场解析） |
| Translator LLM (review-mode 翻译) | `provider/{anthropic,openai,gemini}.py` 直连 HTTP | per project `project.json.translate_model` | `EMERGE_DEFAULT_TRANSLATE_MODEL` 是真 **runtime fallback**（默认 `gemini-flash-lite-latest`） |

工具体内绝不递归回 SDK——Agent 与 Extract / Proposer / Labeler / Translator 是分开的代码路径。

Translator LLM 有两种模式：textlayer 模式（电子 PDF，直接翻译 fitz 抽出的 spans）和 vision 模式（scanned PDF / 纯图片，OCR + 翻译）。仅 review 渲染层使用；不进 extract / labeler / proposer 上下文。

Review viewer 双轨：每页同时叠加 (a) 透明 text layer（从 fitz `get_text("dict")` 抽出的 DOM spans，原文可选可复制；scanned 页降级为空层），(b) 150dpi raster PNG（视觉显示）。翻译热区是可选的第三层，按需开启。

## "同事"精神 (Colleague principle)

emerge 的人格定位是**一位文档处理能力很强的同事**，不是绑定在某个界面的工具。
每次迭代必须守住以下约束，防止退化：

### 行为层

1. **Chat 可以完成一切**。用户通过 chat（browser 或 headless）能做到的事，不能比点 UI 少。
   若某操作只能在浏览器界面完成而不能通过 chat 触发，视为违反本原则。

2. **interface-aware 渲染**。所有 skill prompts 的"Rendering contract"必须同时覆盖
   `browser` 和 `headless` 两种模式：
   - **browser**：依赖前端 UI 组件渲染的，agent 给一句摘要即可。
   - **headless**：agent 必须输出完整文字内容（表格、列表、明文等），不能说"看那个卡片"。
   新增 rendering contract 时必须写两个分支，只写一个不合格。

3. **`ui_*` 工具不能静默失败**。在 headless 模式下，agent 必须用一行文字叙述代替
   `ui_*` 调用（`→ page N` / `→ focus field_name`），不能无声跳过。

### 架构层

4. **tool ↔ HTTP ↔ MCP 三形对称**。每个业务 tool 必须同时存在：
   - `@tool` 注册（in-process MCP，agent brain 用）
   - HTTP route（M11 对称，CLI/脚本用）
   - MCP server 可用（`build_mcp_server()` 自动继承；`ui_*`/`ask_user` 例外，
     须在 `_HEADLESS_EXCLUDE` 里注明）
   新增 tool 时三者同步，对称测试 `test_symmetry_invariant.py` + `test_headless_interface.py`。

5. **`interface` 信号必须透传**。任何调用 `chat_turn` / `_build_system_prompt` / 
   `_build_active_context` 的新路径，都必须传 `interface=` 参数，不得硬编码 `"browser"`
   或丢弃该字段。

6. **MCP server 不能暴露浏览器专用工具**。`_HEADLESS_EXCLUDE`（见 `mcp_server.py`）
   与 `_HTTP_EXEMPT`（见 `test_symmetry_invariant.py`）两张表必须保持一致：
   若一个工具在 `_HTTP_EXEMPT` 标注为 "ui side-channel"，它就必须在 `_HEADLESS_EXCLUDE` 里。

### 验证检查单（每个 milestone 发布前）

- [ ] 新增的 tool/功能是否可以通过 chat 完成（不需要点 UI）？
- [ ] 如果有新的 rendering contract，是否同时写了 `browser` 和 `headless` 分支？
- [ ] `test_symmetry_invariant.py` 通过？
- [ ] `test_headless_interface.py` 通过？
- [ ] `build_mcp_server()` 是否能正常初始化（`uv run python -c "from app.mcp_server import build_mcp_server"`）？

## Hard rules (red lines)

- **没有 image few-shot**。任何 prompt 路径都不准注入 example I/O pairs。要"教模型"只能改 `description` / `global_notes`
- **没有 bbox / 区域信息进 prompt**。`_evidence` 携带 page 整数 + 可选 verbatim source 引文（纯文本，非坐标；review click-to-page + field-source-grounding 用）；**bbox / 坐标 仍永不进任何 prompt**——只活在 review UX 渲染层（text-layer 复制 + 翻译热区 + locate rects），永不进 extract / labeler / proposer / autoresearch 上下文。
- **AutoResearch 永不自动 promote**。output 是候选 ProjectVersion，user 必须显式 activate
- **Counterexample 永不进 runtime prompt**。仅作 AutoResearch 回归测试集
- **Public API 读 `versions/v{active_version_id}.json`**。`schema.json` 是 lab 编辑态，不得渗入 prod
- **不读取/打印/提交 secrets**：不要读取或输出 `backend/.env`、provider key、JWT、API key 明文、token/password；前端示例只使用 `EMERGE_API_KEY` 等占位符。API key 明文只允许在 create-key 响应后的 one-time reveal 中短暂存在。`backend/app/chat/sdk_settings.json` + `_workspace_safety_gate` 是这条规则的 runtime 实现（见 INSIGHTS #1.5）
- **Agent brain (SDK) 与 Extract LLM (provider adapter) 是分离代码路径**。tool 内绝不递归回 SDK
- **`schema.json` 只通过 `write_schema` tool 修改**；autoresearch 只写 `versions/_candidate/`，user-accept 才 atomic copy 到 `schema.json`
- **Doc vision is pulled, not pushed**。当前 review doc 通过 `surface_context.filename` 暴露为指针——字节不会自动 inline 进任何 chat turn。Agent 在（且仅在）问题需要视觉时调 `read_doc_image(slug, filename, page)`。不要给 `_load_image_blocks` 加 "auto-attach current doc" 分支——多数 review turn 是纯文字反馈，那样会无谓推高 token 成本

## 仓库布局

```
emerge/
├── backend/
│   ├── app/
│   │   ├── api/          # /lab/chat /lab/upload /lab/jobs + /v1/{pid}/extract (prod fast-path)
│   │   ├── chat/         # claude_agent_sdk 集成层
│   │   ├── skills/       # SKILL.md (emerge-extractor / emerge-autoresearch / emerge-publish)
│   │   ├── tools/        # @tool 装饰器函数（~17 个）
│   │   ├── provider/     # provider adapter（anthropic.py / openai.py / gemini.py）
│   │   ├── schemas/      # pydantic models（SchemaField 等）
│   │   ├── jobs/         # JobRunner (asyncio queue)
│   │   └── workspace/    # filesystem 操作 helper（atomic write、flock）
│   └── tests/
└── frontend/             # 三栏 chat shell + review 模式
└── docs/superpowers/{specs,plans}/
```

参考实现（不导入、不迁移）：
- `/Users/qinqiang02/colab/office/agent-harness/` — claude_agent_sdk 集成模式参考
- `/Users/qinqiang02/colab/codespace/ai/emerge-v1/` — 上一代 emerge，可参考 engine 算法 / contract_diff / readiness checklist 等纯计算逻辑，但不 import / 不 git mv
