# Focused-tune UX 收尾（Q1 + Q2 + Q3）

> Handoff for a fresh session. 前置工作（修正→tune 闭环 A/B/C/D）已落地并 dogfood 过，
> 见 `2026-05-31-tune-loop.md` 思路 + 实现：toast/⌘S、ReviewBar 横幅、focused tune
> (`target_fields`)、按字段计数器。本文件只收尾 dogfood 暴露的 3 个 UX 问题。

## Context（dogfood 发现）

真实 UI 跑通了「改字段 → 横幅 → 点『优化该字段』→ 右侧出进度卡 → focused job
(`target_fields:["currency"]`) → turn_0 候选 headline=currency 单字段准确率」。但用户在
dogfood 里指出三处不顺：

1. **多字段同时修正时，只有「热点字段」被 tune，单次修正的字段被丢。**
2. **进度卡叠在了项目的旧持久会话之上**（用户预期是「新建的 chat」里展示过程）。
3. **看不到「prompt 怎么被优化」的过程**：turn 0 是基线只打分、每轮真实重抽 ~4min、
   卡片只显示准确率数字，不显示 proposer 每轮改了哪条 description / 为什么。

红线不变：proposer 仍只改 description、永不自动 promote、人工 Accept 是真 gate、结构变更
只走 `write_schema`。

---

## Q1 — 多字段 target + 横幅文案

**现状**（`frontend/src/components/ReviewMode/ReviewOverlay.tsx`，`tuneTargets` 计算）：
```ts
const tuneTargets = tuneSignal
  ? (tuneSignal.hot_fields.length > 0 ? tuneSignal.hot_fields : tuneSignal.corrected_fields)
  : []
```
有热点字段（≥2 次）时只取热点 → 只改一次的字段被挤掉。dogfood 里
currency×2 + invoiceType×1 → 只优化了 currency。

**改法**：
- `tuneTargets` 改为 **始终 = `tuneSignal.corrected_fields`**（本次 backlog 所有被修正字段）。
  `hot_fields` 仅用于文案强调/排序，不再用于裁剪 target。
- 横幅文案（i18n `review.tune.*`，`frontend/src/i18n/{zh,en}.ts`）补多字段形态：
  - 1 个字段：保持 `字段 {field} 已被你修正 {count} 次 · 优化该字段`。
  - 多个字段：新增 key，如 `已修正 {fields}（共 {n} 个字段）· 优化这些字段`，
    `{fields}` 取前 2~3 个字段名 + 「等」。
- POST body 自然带上全部字段（`startFocused` 已透传 target_fields，无需改）。

**注意**：`target_fields` 越多，proposer 改动面越大、聚焦优势越弱。可考虑给个上限
（如 >6 个字段时提示「字段较多，建议 broad /improve」），非必须。

涉及文件：`ReviewOverlay.tsx`（tuneTargets + 横幅 JSX）、`i18n/{zh,en}.ts`。

---

## Q2 — focused tune 进度走「新建的干净 chat」

**现状**：`ReviewChatColumn.tsx` 在 `<ChatPanel compact/>` 上方 prepend `rev-chat-jobs`
（进度卡），但 ChatPanel 加载的是项目持久会话（旧消息）。`handleTune`
（`ReviewOverlay.tsx`）只做 `startFocused` + `onToggleRight`，**没新建会话** → 卡片叠在
无关旧对话上（用户截图圈的「老会话还在这里？？？」）。

**改法（推荐）**：`handleTune` 触发 focused tune 时，先 `useChat.getState().newChat(slug)`
开一个干净 thread，再 `startFocused` + 打开右栏。这样：
- 进度卡（`rev-chat-jobs` 来自 `useReviewTune.jobIds`，与 chatId 解耦）落在空白对话上方，
  视觉干净。
- 旧会话按自己的 chatId 保留，可从历史（`ChatHistoryActions`）切回，不丢。

**校验点**：`newChat` 的副作用（清当前输入、切 chatId）不要打断正在跑的 job 订阅
（job 订阅在 `useJob`，独立于 chat）。确认切换后卡片仍在、SSE 不断。

可选更进一步：把 tune 作为一条**真实 user/system turn** 注入新 chat（让 agent 也能就这次
优化对话），而不仅是浮在顶部的卡——但这要打通 chat 消息模型，范围更大，Q2 先做「新建干净
chat + 卡片置顶」即可。

涉及文件：`ReviewOverlay.tsx`（`handleTune`）、`stores/chat.ts`（`newChat` 复用）、
可能 `ReviewChatColumn.tsx`。

---

## Q3 — 让「优化过程」可见 + 慢任务进度反馈

**现状**：`JobProgressCard.tsx` 只显示 `formatJobLine`（turn/acc/Δ）+ 候选 Δ 块；
`rationale` 仅在 best candidate 上显示。turn 0 是基线（不改 prompt），且每轮重抽 ~4min，
所以用户长时间看「第 0 轮 0%」毫无反馈。

**改法**：
1. **基线轮文案**：turn 0 显示「基线评测中…」而非「0%」，让用户知道在量基线、还没开始改。
2. **每轮 rationale 实时显示**：per-turn `turn` 事件已带 `rationale`
   （见 `autoresearch.py` 的 turn>0 emit）。卡片在 running 态显示「本轮在尝试：{rationale}」，
   让「在怎么改 prompt」可见。`stores/jobs.ts` 的 `TurnEvent` 已含 rationale，前端取最近一轮即可。
3. **（可选）描述 diff**：候选 turn JSON 里有完整 schema；可对比 baseline(turn_0) schema
   展示「{field} 的 description 改成了 …」。比纯 rationale 更具体，但要 fetch 候选 JSON，
   按需做。
4. **慢任务预期**：卡片或 toast 提示「每轮需重抽全部 reviewed 文档，约数分钟/轮」，
   降低「卡住了？」的焦虑。

涉及文件：`JobProgressCard.tsx`、`stores/jobs.ts`（确认 rationale 已在 TurnEvent 上）、
i18n。无需后端改（rationale 已 emit）。

---

## Q4（已澄清，无需动工）

「优化该字段」按钮 = 直接 `POST /lab/jobs {target_fields}`（绕过 agent，不发 /improve 文本）；
卡片「/improve 运行中」只是 `JobProgressCard` 对 autoresearch job 的标签。Q2 做完后，
若把 tune 注入为真实 turn，可再统一这个叙述；当前保持直接触发即可。

---

## 关键文件速查
- `frontend/src/components/ReviewMode/ReviewOverlay.tsx` — `tuneTargets`、横幅 JSX、`handleTune`
- `frontend/src/stores/reviewTune.ts` — `startFocused` / `jobIds`（透传 target_fields，基本不动）
- `frontend/src/components/ReviewMode/ReviewChatColumn.tsx` — `rev-chat-jobs` + `<ChatPanel>`
- `frontend/src/stores/chat.ts` — `newChat(slug)`
- `frontend/src/components/Chat/JobProgressCard.tsx` — 进度卡呈现（rationale / 基线文案）
- `frontend/src/stores/jobs.ts` — `TurnEvent.rationale`
- `frontend/src/i18n/{zh,en}.ts` — `review.tune.*` 文案
- 后端无需改（`target_fields`、per-turn `rationale`、scoped headline 都已就位）

## 验证（沿用 dogfood 手法）
1. **Q1**：在 review 改 ≥2 个不同字段各 1 次 + 某字段 2 次 → 横幅文案体现多字段；
   点按钮，`POST /lab/jobs` 的 `params.target_fields` 含**全部**被修正字段（不只热点）。
2. **Q2**：点按钮 → 右栏是**干净新 chat**（无旧消息），卡片在顶部；历史里能切回旧会话。
3. **Q3**：turn 0 显示「基线评测中」；turn≥1 时卡片显示该轮 rationale；（可选）显示 description diff。
4. 回归：`cd backend && uv run pytest -q`；前端 `npx tsc --noEmit`。

## 环境备注（dogfood 残留）
- `振兴_testset` 两篇 reviewed 被写了 dogfood 修正（currency→USD/SGD、invoiceType→Credit Note），
  `corrections_by_field={currency:2, invoiceType:1}`。gitignored，可删/改。
- 取消的 job `j_6vyfkjnx5i93` 候选目录在 `versions/_candidate/`，可删。
- dev：`./dev.sh restart`（会 tail，放后台跑）；backend :8080、frontend :5173。
