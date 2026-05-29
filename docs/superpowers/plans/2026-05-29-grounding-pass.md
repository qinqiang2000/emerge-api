# 2026-05-29 — Grounding pass (decoupled source-quote resolver)

> Fix-line for `[[2026-05-29-field-source-grounding]]` + `[[2026-05-29 locate precision]]`.
> Branch: `fix/locate-precision-high-precision` (continues `4112bb8`).

## Why

Field-source-grounding 的 locate resolver(`app/tools/locate.py`)是**高精度低召回**:
`source` verbatim 引文是去歧义的主锚点,排在 value 匹配之前。但 dogfood 发现绝大多数字段
**无框**(`totalNetAmount=111` / `totalAmount=111` / `currency=USD` / `articleName=…`)。

根因不在匹配逻辑,在**契约在 schema 边界被截断**:

- `_EXTRACT_SYSTEM`(`extract.py:26`)要求模型 emit `_evidence`(page + verbatim `source`)。
- 但 `_build_response_schema`(`extract.py:49-61`)**故意把 `_evidence` 排除在 response_schema 外**
  (理由:Gemini OpenAPI-3.0 拒 `additionalProperties`,逐字段重列会让 schema 翻倍)。
- Gemini 走 **constrained decoding**(`google.py:82-83` `response_mime_type` + `response_schema`),
  输出被硬约束成 schema 精确形状——**schema 里没有的 key,模型物理上吐不出来**。prompt 的要求
  被约束解码静默覆盖。

证据:`predictions/_draft/*.json` top keys 只有 `['entities']`,**从无 `_evidence`**。所以每个字段
到达 locate 时 `page_hint=None` / `source_quote=None`,直接掉进 value 匹配 + 全文扫描;凡是值重复
的字段(`111` 在一张发票里是 5 个字段的值)→ 多簇并列 → 按"宁可 none"返回无框。**"只有部分
字段 OK" = 值唯一的字段(invoiceNumber 等)撞上 value 匹配的运气**,不是设计在工作。

这正是 `[[feedback_three_patches_means_missing_noun]]`:缺的 noun 是 **evidence 锚点本身**。
反复改 locate.py 是在调一个输入恒为空的匹配器。

## Decision — Option A:把 grounding 做成 extract 之后的独立 pass

用户 2026-05-29 选定 **A(解耦)**,核心诉求:**别污染 extraction,保护提取准确率**。

- **不**把 `_evidence` 塞回 extraction 的 response_schema(那会让深嵌套 schema 翻倍 → 结构遵从度↓、
  延迟↑、截断风险↑,间接伤提取)。
- grounding 是**独立的一趟 provider 调用**:输入 = 文档 + 已提取的 `(entity,path,value)` 列表,
  任务 = "为这些值找 verbatim 出处",输出走一个**专为 grounding 设计的扁平 schema**
  (`{groundings:[{entity,path,page,source}]}`,无 `additionalProperties`、无深嵌套,Gemini-friendly)。
- 复用 **active extract model**(`read_active_model`),不新增第 6 个 LLM 层;走 provider adapter 直连
  HTTP,绝不递归回 SDK(遵守 5 层分离 + 红线)。
- 触发时机 **lazy**:review 打开某 prediction tab 时若 `_evidence` 为空 → 调一次 `/ground`,结果
  **写回 prediction blob 缓存**(`_evidence` key),后续打开命中缓存。extraction money-path **零改动**,
  也**无需重新 extract**——存量预测首次 review 时按需补 grounding。

红线复核:`source` 只携带纯文本引文(已是现状);**bbox/坐标仍永不进任何 prompt**;grounding 输出
(text 引文)对 agent context 安全,但**无 agent 用例**,故与 locate 一样做成 **render-support HTTP
route,非 @tool**(symmetry 只强制 `@tool ⇒ route`,route 无需 exempt)。

## Tasks

### T1 — `app/tools/ground.py`(grounding 核心)
- `async def ground_prediction(workspace, project_id, filename, *, tab: str = "_draft", provider=None, model_id=None) -> list[dict]`
  - tab ∈ `{"_draft","_pending"}` → 解析对应 blob 路径(`prediction_draft_path` / `_pending`)。
  - 读 blob;若已有非空 `_evidence` → 直接返回(缓存命中)。
  - 用 `read_active_prompt` 拿 schema(字段 description 帮模型去歧义);`_flatten_entity`(复用
    locate 的 flatten,或 `_collect_leaves`)逐 entity 取 `(path, value)`,只送 **value 非空** 的叶子。
  - 构造 grounding system prompt + user blocks(global_notes? + 值清单 + `_doc_to_block`)。
  - response_schema(扁平):
    ```json
    {"type":"object","required":["groundings"],"properties":{"groundings":{"type":"array","items":{
      "type":"object","required":["entity","path","page","source"],"properties":{
        "entity":{"type":"integer"},"path":{"type":"string"},
        "page":{"type":"integer","nullable":true},"source":{"type":"string","nullable":true}}}}}}
    ```
  - `provider.extract(...)` → 把 `groundings` 列表 reshape 成 `_evidence`:`list[dict[path → {page,source}]]`,
    长度 == entities;缺失的 path 落空(`{page:None,source:None}` 或省略)。
  - `atomic_write_json` 写回 blob 的 `_evidence`(`project_lock`),返回 evidence 列表。
- grounding system prompt(新常量):强调 **copy verbatim、原语言、≤120 字、不改写**;derived/computed/
  absent → page+source 均 null;**NEVER 输出坐标/bbox/区域**。

### T2 — `app/api/routes/ground.py` + 注册
- `POST /lab/projects/{slug}/docs/by-name/{filename:path}/ground`,body `{tab?: "_draft"|"_pending"}`。
- `safe_slug` / `safe_filename`;doc 不存在 → 404 `doc_not_found`;blob 不存在 → 404 `prediction_not_found`。
- 返回 `{evidence: [...]}`。docstring 写明 render-support、非 @tool 的理由(照搬 locate 风格)。
- `main.py` include router。

### T3 — extract prompt 去死代码
- `_EXTRACT_SYSTEM` 删掉 `_evidence` emit 那几行(constrained decoding 本就吐不出,且现在 grounding 独立)。
- `_build_response_schema` 删掉 `_evidence` 的 omit 注释块(已无意义)。
- `ExtractionOutput` 保持容忍 `_evidence`(reviewed-save 仍写;grounding 也写)。检查无测试断言 prompt 含 `_evidence`。

### T4 — frontend lazy ground-then-locate
- `lib/locate.ts` 加 `fetchGround(projectId, filename, tab)` → `evidence[]`。
- `stores/locate.ts::loadFor`:当 `evidence` 为 null/全空 且 tabKey 是 `_draft`/`_pending` →
  先 `fetchGround` 取 evidence,再 `fetchLocate(..., grounded)`;否则用传入 evidence。
  缓存键不变(每 tab 一次)。
- tabKey → tab 名映射:`_draft`/`_pending` 直传;experiment/reviewed tab 暂不 ground(用已有 evidence)。

### T5 — tests + live verify
- backend:`test_ground.py`(reshape 正确、缓存命中跳过 LLM、derived→null、multi-entity 对齐);route smoke(404 分支 + happy path with fake provider)。
- frontend:`locate.test.ts` 扩展——空 evidence → 先 ground 再 locate;非空 → 跳过 ground。
- live(Claude in Chrome,`[[reference_claude_in_chrome]]`):硬刷新 + 重开 `Airbus Invoice.pdf`,
  点 `totalNetAmount` / `totalAmount` / `currency` / `detailOfGoodsOrServices.articleName` → 出框。
- 收尾:更新 `[[project_locate_precision_pass]]` memory + ROADMAP 行。

## Out of scope / 已知限制
- **array 子字段 evidence 仍 1 槽/entity**:`detailOfGoodsOrServices[].articleName` 多行项目时,
  `_evidence` 每 entity 只有一个该 path 的槽 → 多行只能锚一个。Airbus 单行项目不受影响;多行留作 follow-up。
- grounding 失败/超时不阻断 review:catch → 回退 page 级 click-to-page(现状)。
- 不做 grounding 的 JobRunner 化(lazy 单次调用够用,lab 不预算 token)。
