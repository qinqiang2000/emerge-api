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
- 主题: light/dark/system 从 day one；**不允许** Tailwind 直接 color class，只用语义 token
- 测试: `cd backend && uv run pytest -v`
- 单一 schema 真相: `backend/app/schemas/schema_field.py` 的 `SchemaField` pydantic model
- **任务类型无关的 UI**：本 shell 要复用到非文档提取任务（matching、classification 等）。chrome 层（按钮、空状态、popover、slash-menu copy、kind chips）用通用动词（`init / run / tune / review / publish / ingest`），不出现 `extract` / `invoice` / 文档提取专用名词；提取专用术语只允许出现在 content/help 文案和真实路径（如 `docs/`）里。API 发布层（`/v1/{pid}/extract` 路由名等已固化部分）保持现状不破坏兼容

## 三层 LLM（互不交叉）

| 角色 | 走哪 | 配置 |
|---|---|---|
| Agent brain | `claude_agent_sdk.ClaudeSDKClient`（chat 大脑） | 系统级 env，锁 Anthropic |
| Extract LLM | `provider/{anthropic,openai,gemini}.py` 直连 HTTP | per project，`project.json.extract_model` |
| Proposer LLM (autoresearch) | 同上，直连 HTTP | 系统默认 + per-job override |

工具体内绝不递归回 SDK——Agent 与 Extract 是分开的代码路径。

## Hard rules (red lines)

- **没有 image few-shot**。任何 prompt 路径都不准注入 example I/O pairs。要"教模型"只能改 `description` / `global_notes`
- **没有 bbox / 区域信息**。`_evidence` 只携带 page 整数（不是坐标），且 review 模式 click-to-page 用它
- **AutoResearch 永不自动 promote**。output 是候选 ProjectVersion，user 必须显式 activate
- **Counterexample 永不进 runtime prompt**。仅作 AutoResearch 回归测试集
- **Public API 读 `versions/v{active_version_id}.json`**。`schema.json` 是 lab 编辑态，不得渗入 prod
- **不读取/打印/提交 secrets**：不要读取或输出 `backend/.env`、provider key、JWT、API key 明文、token/password；前端示例只使用 `EMERGE_API_KEY` 等占位符。API key 明文只允许在 create-key 响应后的 one-time reveal 中短暂存在
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
