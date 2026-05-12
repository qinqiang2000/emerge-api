# emerge — Extraction Comparability Family Design (M9.x)

> **Status**: design — accepted 2026-05-12
> **Slogan**: prompt × model 两个轴的可枚举、可对比、可分享
> **Supersedes**: 撤回的 M9a (schema first-class) / M9b (fork) / M9c (A/B compare) / M9d (autoresearch UI) — 它们 pre-commit 了"schema 是唯一对比轴"和"workspace-global schemas/ 目录"两个错误锚点
> **Inputs**: 5 个客户场景（场景 1–4 在本期处理，场景 5 文档匹配 explicit 后置到 M10+）

---

## 0. Motivation

M9.0 quick-look 把 schema.json 渲染成 first-class 可视面板，但只是 viewer 层胜利。深层痛点是：**user 想做的对比不是"看 schema"，是"看 (prompt, model) 组合在我的 docs 上谁表现更好"**。这本质上是 5 个具体业务场景：

1. **跨 project fork**：从 us_invoice 起跑 uk_invoice，少量调整字段后独立运营
2. **跨 project schema 借用试跑**：B 客户拿一批 docs 试现有 N 个 project 的 schema，选最合适的
3. **prompt 文案 A/B**：同 project 改某个字段描述或补 global notes，对比 score
4. **model A/B**：同 project 换 Gemma4 看跟 Gemini-flash 的对比
5. **文档匹配任务**（远期）：非 extraction 任务（发票↔付款单↔合同 三方一致性校验）

场景 1 是**跨 project clone-at-time fork**，独立机制。场景 2–4 都是**同一 project 内固定某些轴 + 变某一/两个轴跑 eval 看效果**。场景 5 跨出 extraction task 范式，本期 explicit out of scope。

撤回的 M9a–d 把 schema 当作"唯一对比轴"，但实际上从 LLM 调用视角看，影响 extraction 行为的是 **prompt（schema fields + descriptions + global_notes 合体）** 和 **model** 两个独立轴。把 schema 单独提为 workspace-global 是错误抽象——它强行把 prompt 文案和 output structure 拆成两个一等公民，反而违背用户"我在调一段 prompt 给一个 model"的天然心智（label-studio baseline 也是 prompt + model 两旋钮）。

本 design 把 prompt 和 model 各自轴化为 project 内的一等列表，experiment 是这两个轴的**引用对 + eval 快照 + per-doc extract 输出**。Active prompt + active model 是 user 显式 selected 的当前组合，**promote** 是 user 显式 action。

---

## Glossary

| 术语 | 含义 |
|---|---|
| **Prompt (variant)** | `{schema:[SchemaField], global_notes}` 合体单元，是给 extract LLM 的"那一段 prompt"。Project 内可有多个 variant 并存。文件：`prompts/{prompt_id}.json` |
| **Model (config)** | `{provider, provider_model_id, params}` 三元组。Project 内可有多个并存。文件：`models/{model_id}.json` |
| **Active prompt / Active model** | Project 当前 selected 的一对引用。`project.json` 持有 `active_prompt_id` + `active_model_id` |
| **Experiment** | `(prompt_id, model_id)` 引用对 + 可选 eval 结果 + per-doc extract 输出目录。文件：`experiments/{exp_id}/meta.json` + `experiments/{exp_id}/extracts/{doc_id}.json` |
| **Promote** | 显式把 experiment 引用的 prompt_id + model_id 设为 active 的动作（`promote_experiment`） |
| **Fork project** | 跨 project clone-at-time，拷整个目录除 chats / _keys / predictions/_draft；docs 默认不拷，可选硬链接 |
| **Import prompt** | 跨 project 单 prompt 文件 clone-at-time（场景 2 用）。`import_prompt(src_pid, src_prompt_id, into_pid, new_label?)` |
| **Frozen version** | `versions/v{N}.json` 仍是 publish API contract 的快照单元，**publish fast-path 零感知** prompt/model/experiment 概念 |

---

## 1. Conceptual model

### 1.1 Two axes per project

```
              ┌───────────────────────────────────┐
              │   Project (1 publish API root)    │
              │   - docs[] / reviewed[]           │
              │   - chats[] / api keys            │
              │   - versions/ (frozen contracts)  │
              └───────────────────────────────────┘
                            │
              ┌─────────────┼─────────────┐
              │                           │
        Axis 1: prompts/             Axis 2: models/
        (schema fields +             (provider +
         descriptions +               provider_model_id +
         global_notes)                params)
              │                           │
              └─────────────┬─────────────┘
                            │
                  experiments/  ← (prompt_id, model_id) 引用对
                                  + per-doc extracts
                                  + 可选 eval 结果
                            │
                       (promote)
                            ↓
                  project.active_prompt_id
                  project.active_model_id
                            ↓
                   (freeze_version)
                            ↓
                  versions/v{N}.json (frozen, publish)
```

### 1.2 Active 是 named selection，不是"最近编辑态"

User 改 prompt 默认编辑 active variant（兼容现有"改 schema 立即生效"心智）；要做隔离对比就 `create_prompt(derived_from=active)` 起新 variant，在 variant 上编辑，跑 experiment 验证，满意了 `promote_experiment` 切 active。Baseline 文件不被污染，对照基准始终存在。

### 1.3 Promote 是显式 user action

- `freeze_version` 不再隐含 promote 任何 experiment——freeze 永远只看 active prompt + active model
- AutoResearch 仍然 hard rule "never auto-promote"——产出落 `prompts/_candidate/`，user accept 落成 named variant，user 再显式 promote

### 1.4 Cross-project clone-at-time fork

`fork_project(src_pid, new_label, include_docs=False)` 整个项目复制到新 pid，从此两个 project 完全无关。Docs 默认不拷（fork 用例通常带新 docs），可选硬链接零成本拷贝。无 live-link / transclusion——符合 hard rule "forks are clone-at-time"。

### 1.5 Experiment 双重职能

Experiment 不只是"批量 eval 算 score"的容器，也是**per-doc 探索单元**：

- User 在 review 模式可对同一个 doc attach 多个 experiment tab，切换查看不同组合的 extract 结果做主观判断（详见 §7.4 — tab strip 切换，非分屏并排）
- Per-doc extract 输出落 `experiments/{exp_id}/extracts/{doc_id}.json`
- 显式 `run_experiment_eval` 才在 reviewed 全集上跑 + 算 score 写 `meta.json.eval`
- 一个全新 experiment 状态 = `status: "draft"`, extracts/ 空，eval=null —— 也是合法的（user 只是建了个组合占位，还没跑）

---

## 2. Data model

### 2.1 Disk layout

```
workspace/{pid}/
├── project.json
│     # 新增字段:
│     #   active_prompt_id: "pr_baseline"
│     #   active_model_id: "m_gemini_flash"
│     # 现有字段保留迁移期:
│     #   extract_model, extract_params (lazy migration source；新 project 不再写)
│     #   active_version_id (publish 路径不变)
├── prompts/
│   ├── pr_baseline.json
│   │     { prompt_id, label, schema:[SchemaField, ...], global_notes,
│   │       derived_from: null | "pr_xxx" | "{src_pid}/{src_prompt_id}",
│   │       created_at, updated_at }
│   ├── pr_compact_notes.json
│   ├── pr_uk_adapt.json
│   └── _candidate/{job_id}/turn_N.json    # autoresearch staging (替代旧 versions/_candidate/)
├── models/
│   └── m_<slug>.json
│         { model_id, label, provider:"anthropic|openai|google",
│           provider_model_id, params:{...},
│           created_at }
├── experiments/
│   └── ex_<id>/
│       ├── meta.json
│       │     { experiment_id, label, prompt_id, model_id,
│       │       status: "draft|ran|archived|promoted",
│       │       created_at, promoted_at?: ISO, notes,
│       │       eval: { ran_at, score, per_field:{name:score},
│       │               per_doc:{doc_id:score}, run_id, coverage } | null }
│       └── extracts/
│           └── {doc_id}.json    # ExtractionOutput (跟 predictions/_draft/{doc_id}.json 同 schema)
├── docs/                  # 不变
├── reviewed/              # 不变 — ground truth，跨 experiment 共享
├── predictions/_draft/    # 不变 — active prompt+model 的 draft 输出
├── versions/
│   └── v{N}.json          # 不变结构 + 新增可选 derived_from audit 字段
└── chats/                 # 不变
```

**消失的文件**：
- `schema.json` —— 数据搬进 `prompts/{active_prompt_id}.json`
- `versions/_candidate/` —— 搬到 `prompts/_candidate/`（autoresearch 探索的就是 prompt unit）
- `global_notes.md` —— 内容并入 `prompts/{id}.json.global_notes` 字段

**保留的不变量**：
1. `versions/v{N}.json` 结构 + publish fast-path 0 感知 prompt/model/experiment
2. `SchemaField` pydantic class 不动（name/type/required/enum/description/children）
3. `reviewed/` 跨 experiment 共享，ground truth 是 project 级
4. Per-route `safe_project_id()` 验证（INSIGHTS #8）维持

### 2.2 Pydantic models

`SchemaField` 完全不动。新增 3 个简单 BaseModel：

```python
class PromptVariant(BaseModel):
    prompt_id: str                    # "pr_<slug>"
    label: str
    schema: list[SchemaField]
    global_notes: str = ""
    derived_from: Optional[str] = None  # "pr_xxx" 同项目 / "{src_pid}/{src_prompt_id}" 跨项目
    created_at: str
    updated_at: str

class ModelConfig(BaseModel):
    model_id: str                     # "m_<slug>"
    label: str
    provider: Literal["anthropic", "openai", "google"]
    provider_model_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: str

class Experiment(BaseModel):
    experiment_id: str                # "ex_<slug>"
    label: str
    prompt_id: str
    model_id: str
    status: Literal["draft", "ran", "archived", "promoted"] = "draft"
    created_at: str
    promoted_at: Optional[str] = None
    notes: str = ""
    eval: Optional["ExperimentEval"] = None

class ExperimentEval(BaseModel):
    ran_at: str
    score: float
    per_field: dict[str, float]
    per_doc: dict[str, float]         # doc_id → score
    run_id: str
    coverage: int                     # 跑了几个 reviewed doc
```

### 2.3 SchemaField 跟 PromptVariant 的关系

`SchemaField` 承担 output JSON 的结构定义（name / type / required / enum / children）+ prompt 文案（description）。这两件事在 axis 化模型下**仍然合体**——一个 PromptVariant 完整自描述：包含 fields 结构定义 + descriptions + global_notes。

**Pre-publish 阶段**：within-project experiment 可以自由加减字段、改 type（"税率从 number → 含'免征'枚举"这种认知演进是常态，不该被分层）

**Post-publish 阶段**：要改 contract 触发 user explicit `freeze_version`，新 v{N+1} 写入；client API 调用按 version 路由，老版本仍可用——这跟现有 "schema.json 是 lab / versions 是 prod" 隔离保持一致

### 2.4 schema.json 物理消失，user-facing 词汇改名

- FSSpine 不再有 `schema.json` 行
- UI "Schema" → "Prompt" / 中文 "提示词"
- 内部 pydantic class `SchemaField` 名称**不改**（它精确描述 output JSON 的 schema 部分，是 PromptVariant 的子结构）
- `write_schema` tool **改名为** `write_prompt`（保留 wrapper 一两个 milestone 后弃用）

---

## 3. Tool catalog

### 3.1 Prompt axis tools

| Tool | 签名 | 行为 |
|---|---|---|
| `write_prompt` | `(prompt_id=None, schema, global_notes="")` | 写指定 prompt（None = active）；agent 在 chat 里改字段描述最常用 |
| `create_prompt` | `(label, derived_from=None)` | 新建 prompt variant；`derived_from=None` 默认 clone active；`derived_from="{pid}/{prompt_id}"` 跨项目 lineage |
| `switch_active_prompt` | `(prompt_id)` | `project.active_prompt_id = prompt_id` |
| `list_prompts` | `()` | `[{prompt_id, label, derived_from, is_active, created_at}]` |
| `delete_prompt` | `(prompt_id)` | 不能删 active；不能删被未 archived experiment 引用的（先 archive） |
| `import_prompt` | `(src_pid, src_prompt_id, into_pid=current, new_label=None)` | 跨 project 单文件 clone；新 prompt 的 `derived_from = "{src_pid}/{src_prompt_id}"` |

### 3.2 Model axis tools

| Tool | 签名 | 行为 |
|---|---|---|
| `write_model` | `(model_id, label, provider, provider_model_id, params)` | upsert（新增或改 label/params） |
| `create_model` | `(label, provider, provider_model_id, params={})` | 自动 mint model_id slug |
| `switch_active_model` | `(model_id)` | `project.active_model_id = model_id` |
| `list_models` | `()` | `[{model_id, label, provider, ..., is_active}]` |
| `delete_model` | `(model_id)` | 不能删 active；不能删被未 archived experiment 引用的 |

### 3.3 Experiment tools

| Tool | 签名 | 行为 |
|---|---|---|
| `create_experiment` | `(label=None, prompt_id=None, model_id=None)` | 默认 active+active；label 默认 `"trial_{ISO_ts}"`；写 meta.json, extracts/ 空 |
| `extract_with_experiment` | `(exp_id, doc_id)` | 调底层 extract，写 `experiments/{exp_id}/extracts/{doc_id}.json` |
| `run_experiment_eval` | `(exp_id)` | 在 reviewed/ 全集上循环 extract + 算 score → 写 meta.json.eval；status 升到 "ran" |
| `promote_experiment` | `(exp_id)` | 见 §3.5 行为细节 |
| `archive_experiment` | `(exp_id)` | status → "archived"；不再列入 review tab attach 候选 |
| `list_experiments` | `(include_archived=False)` | `[{exp_id, label, prompt_id, model_id, status, eval.score?}]` |
| `delete_experiment` | `(exp_id)` | 物理删除目录（含 extracts）；不能删 status="promoted"（audit trail 保留） |

### 3.4 Cross-project tool

| Tool | 签名 | 行为 |
|---|---|---|
| `fork_project` | `(src_pid, new_label, include_docs=False)` | 整个 pid 目录复制；不拷 chats / _keys / predictions/_draft / reviewed (除非 user 显式要)；docs 可选硬链接 |

### 3.5 `promote_experiment` 精确语义（UX 最优解）

```python
promote_experiment(exp_id):
    ex = read experiments/{exp_id}/meta.json
    
    async with project_lock:
        # 1. 切换 active
        project.active_prompt_id = ex.prompt_id
        project.active_model_id  = ex.model_id
        atomic_write project.json
        
        # 2. predictions/_draft/ 整体清空 + 用 experiment.extracts 重填
        rm -rf predictions/_draft/*
        for doc_id in experiments/{exp_id}/extracts/:
            cp experiments/{exp_id}/extracts/{doc_id}.json
               → predictions/_draft/{doc_id}.json
        
        # 3. mark experiment promoted (audit)
        ex.status = "promoted"
        ex.promoted_at = now()
        atomic_write experiments/{exp_id}/meta.json
```

**UX 收益**：promote 后 review 立刻能看到当前 active 在已跑过 docs 上的最新结果，无需 user 手动 re-extract。**冗余成本**：每 doc 几 KB × N，可忽略。**Audit 完整**：experiment 目录保留，user 可回头查"我什么时候 promote 的、来源是 ex_X"；prompt 自身也有 `derived_from` lineage 链。

未跑过的 doc：review 中显示"未提取"状态（沿用现有行为），user 自行触发 `extract_one`。

### 3.6 现有 tool 几乎不动

- `score`（eval 算法不动）
- `readiness_check`（规则放宽——§6.3）
- `freeze_version`（数据源换源——§6.2）
- `upload_doc`, `save_reviewed`, `read_reviewed`
- `extract_one`（active 路径，沿用）
- `issue_api_key`, `revoke_api_key`, `list_docs`, `read_doc_meta`
- 所有 chat / log / SSE 路径（INSIGHTS #1, #2, #11 维持）

---

## 4. Scenario walkthroughs

### 4.1 场景 1：UK invoice fork from US

```
User: "我要做 UK invoice 识别，从 us_invoice 起跑"
Agent:
  fork_project(src_pid="p_us_invoice", new_label="UK invoice")
    → 新建 p_uk_invoice/
    → 拷 prompts/ models/ versions/ project.json
    → 不拷 chats/ _keys.json predictions/_draft/ docs/ reviewed/
    → docs/ 默认不拷（fork 用例通常带新 docs）

[user 切到 p_uk_invoice]
User: <上传一批 UK 票>
User: "把 supplier_state 改成 county，VAT registration number 必填"
Agent:
  write_prompt(prompt_id=None,  # = active
               schema=<updated SchemaField list>,
               global_notes=<unchanged>)
  → pr_baseline 在 p_uk_invoice 内是独立副本，改它不污染 p_us_invoice

[标准流程: extract → review → eval → freeze → publish]
```

### 4.2 场景 2：B 客户试现有多 project 找最合适

```
User: "B 客户有一批票，试 us / uk / sg 哪个 schema 最合适"
Agent:
  create_project(label="B vendor eval")
  [user 上传 B 的 docs 到 p_b_eval]
  
  import_prompt(src_pid="p_us_invoice", src_prompt_id="pr_baseline",
                new_label="from US")    → pr_from_us
  import_prompt(src_pid="p_uk_invoice", ...)  → pr_from_uk
  import_prompt(src_pid="p_sg_invoice", ...)  → pr_from_sg
  
  create_experiment(label="试 US", prompt_id=pr_from_us, model_id=active) → ex_us
  create_experiment(label="试 UK", prompt_id=pr_from_uk, model_id=active) → ex_uk
  create_experiment(label="试 SG", prompt_id=pr_from_sg, model_id=active) → ex_sg

User: "在 invoice_001 上跑这三个看效果"
Agent:
  extract_with_experiment(ex_us, doc_invoice_001) → experiments/ex_us/extracts/...
  extract_with_experiment(ex_uk, doc_invoice_001) → ...
  extract_with_experiment(ex_sg, doc_invoice_001) → ...

[Review 模式 attach 4 个 tab：active + ex_us + ex_uk + ex_sg，切换查看]
[user 主观判断 + review 几个 doc 给 ground truth + run_experiment_eval 三个]
User: "UK 最合适，promote"
Agent:
  promote_experiment(ex_uk)
  archive_experiment(ex_us); archive_experiment(ex_sg)
```

### 4.3 场景 3：us_invoice 改某字段描述对比效果

```
User: "supplier 字段描述补充'通常出现在右上角'"
Agent:
  create_prompt(label="supplier 右上角提示", derived_from=active) → pr_try_supplier
  write_prompt(prompt_id=pr_try_supplier, schema=<supplier.description 加一句>)
  create_experiment(label="试 supplier 提示",
                    prompt_id=pr_try_supplier, model_id=active) → ex_try_supplier
  run_experiment_eval(ex_try_supplier)

Agent (reply):
  "ex_try_supplier eval 完成。score=0.91（baseline 0.87，+0.04）。
   per-field: supplier=1.00（baseline 0.85，+0.15），其他持平。
   要 promote 吗？"

User: "promote"
Agent: promote_experiment(ex_try_supplier)
  → active_prompt_id = pr_try_supplier
```

### 4.4 场景 4：试 Gemma4 vs Gemini-flash

```
User: "试一下 Gemma4"
Agent:
  create_model(label="Gemma 4 12B-it",
               provider="google",
               provider_model_id="gemma-4-12b-it",
               params={"temperature": 0.0}) → m_gemma4
  create_experiment(label="try gemma4",
                    prompt_id=active,   # 同 prompt
                    model_id=m_gemma4)  # 换 model
                    → ex_try_gemma

User: "在 invoice_001 跑一下我看看"
Agent:
  extract_with_experiment(ex_try_gemma, doc_invoice_001)
  → experiments/ex_try_gemma/extracts/invoice_001.json

[Review 模式 attach ex_try_gemma tab，切换跟 active 对比]
[user 翻几个 doc 主观判断 → 满意 → run_experiment_eval → 比 score → promote]
```

### 4.5 场景 5：文档匹配（out of scope）

文档匹配 ("比较 2+ docs，验证规则") 跟 extraction ("1 doc → JSON") 的 mental model 不同。需要：
- `project_type` 多态化（现 hard-code `"extraction"`）
- 不同的 task data shape（`reviewed/` 改成"匹配标注"，eval metric 改成 precision/recall 而非 field-by-field）
- 不同的 publish API contract（POST 多 docs vs POST 1 doc）

本 design **explicit 不处理**。M9.x family 只解决 prompt/model 轴化 + experiment + fork。task_type 多态化是独立的 M10+ 工作。当前 chrome 层已经做了 task-type-agnostic vocabulary 改造（M8 已做），未来加 task_type 时基础设施在。

---

## 5. Autoresearch fit

### 5.1 Disk 路径搬迁

| 现状 | 新版 | 原因 |
|---|---|---|
| `versions/_candidate/{job_id}/turn_N.json` | `prompts/_candidate/{job_id}/turn_N.json` | autoresearch 探索的是 prompt unit，跟 active prompt 同物种；跟 frozen version 不同物种 |
| `turn_N.json` 仅含 `fields[]` | `turn_N.json` 是完整 PromptVariant blob | proposer LLM 产 prompt unit，含 schema + global_notes |

### 5.2 "Accept turn N" 改名为 "Save turn N as variant"

```
现状:
  user 点 "Accept turn N"
  → atomic copy versions/_candidate/{job}/turn_N.json 到 schema.json
  → 直接覆盖 active

新版:
  user 点 "Save turn N as variant"
  → atomic copy prompts/_candidate/{job}/turn_N.json
    → prompts/pr_autoresearch_{job_short}_t{N}.json
    → derived_from = active prompt at the moment job started
  → 不动 active；user 后续显式 promote 才生效
  → JobProgressCard 显示 chip:
      ✓ saved as pr_autoresearch_xxxx_t3
      [open quick-look ↗]  [start experiment ↗]
```

两条后续路径：
- **直接 promote**（user 信任 autoresearch score）→ `switch_active_prompt(pr_autoresearch_xxxx_t3)`
- **先起 experiment 二次验证** → `create_experiment(prompt_id=pr_autoresearch_xxxx_t3, model_id=active)` → `run_experiment_eval` → 比 score → 满意再 `promote_experiment`

### 5.3 Counterexamples / regression cases 不动

仍存现有位置（实现 detail，本期不动），仍只用于 autoresearch 内部 regression eval，仍 hard rule "never enter runtime prompt"。Counterexamples 绑 project 而非 prompt variant，对 axis 化透明。

### 5.4 Autoresearch ↔ Experiment 边界

| Autoresearch | Experiment |
|---|---|
| Proposer LLM 自主探索 prompt 文案 → 产 candidate | User 显式 design 一个 (prompt, model) 组合 |
| 写 `prompts/_candidate/`（自动） | 写 `experiments/`（显式 create） |
| 内部 turn-by-turn 自评分 | 显式 `run_experiment_eval` 跑 reviewed |
| User accept = 落 named prompt variant | User promote = 切 active |

Pipeline: `autoresearch candidate → (user accept) → prompt variant → (user create experiment) → experiment → (eval) → (promote) → active`

---

## 6. Publish path + readiness

### 6.1 Publish fast-path 零改动（hard rule）

`/v1/{pid}/extract` 仍只读 `versions/v{N}.json`，零感知 prompts/ models/ experiments/ 概念。

```json
{
  "version_id": "v3",
  "schema": [...],                  // SchemaField[]，来自 active prompt 快照
  "global_notes": "...",            // 来自 active prompt 快照
  "model_id": "gemini-2.5-flash",   // 来自 active model.provider_model_id
  "params": {"temperature": 0.0},
  "frozen_at": "2026-05-12T...Z",
  "derived_from": {                 // 新增 audit 字段（可选，loose schema）
    "prompt_id": "pr_try_supplier",
    "model_id": "m_gemini_flash",
    "experiment_id": "ex_try_supplier"
  }
}
```

`derived_from` 是 audit 字段，publish path 解析时忽略未识别字段——0 breaking change。

### 6.2 freeze_version 行为

```python
freeze_version(force=False):
    if not force:
        readiness = readiness_check()
        if not readiness.hard_pass:
            raise PublishNotReadyError(...)
    
    prompt = read prompts/{active_prompt_id}.json
    model  = read models/{active_model_id}.json
    
    v_blob = {
        "version_id": f"v{next_n}",
        "schema": prompt.schema,
        "global_notes": prompt.global_notes,
        "model_id": model.provider_model_id,
        "params": model.params,
        "frozen_at": now(),
        "derived_from": {
            "prompt_id": active_prompt_id,
            "model_id": active_model_id,
            "experiment_id": <latest promoted exp> | None
        }
    }
    atomic_write versions/v{n}.json (chmod 0o444)
    project.active_version_id = f"v{n}"
```

跟现有行为本质相同，仅数据源从 `schema.json + project.extract_model` → `prompts/{active} + models/{active}`。

### 6.3 readiness_check 规则放宽

| Hard pass (fail → block freeze) | Soft warning (UI 提示，不 block) |
|---|---|
| active prompt.schema 非空 | reviewed 覆盖率 < 阈值（"3/10 reviewed docs 有 eval"） |
| active prompt 文件存在 | 最近 eval score 低于阈值 |
| active model 配置完整 & API key 可用 | 最近 eval 时效（"7 天前的 eval"） |
| frozen 当前 active prompt 跟之前 active version 不冲突 | 无 reviewed docs（"无 ground truth 验证"） |

`freeze_version(force=False)` default 行为：hard 通过即可 freeze；soft warning 在 chat / UI 显示但不阻塞。User 决定 publish 时承担风险，符合 description-as-code 哲学 "user 是 senior judge"。

---

## 7. UI surface impact

### 7.1 FSSpine 树形结构

```
现状:                          新版:
  docs/                          docs/
  predictions/                   predictions/_draft/
  reviewed/                      reviewed/
  schema.json (inert)            prompts/                ← 可展开
  versions/v3.json (active)        └ pr_baseline.json (active ⭐)
  chats/                           └ pr_try_supplier.json
                                   └ _candidate/...
                                 models/                 ← 可展开
                                   └ m_gemini_flash.json (active ⭐)
                                   └ m_gemma4.json
                                 experiments/            ← 可展开
                                   └ ex_try_supplier/ (status: ran, score: 0.91)
                                 versions/v3.json (active)
                                 chats/
```

`schema.json` 行整个消失。Active prompt / model 用 ⭐ 标记。Experiment 行显示 status + score 摘要。

### 7.2 Quick-look lineage 槽位绑定

Quick-look sheet 入口从 `schema.json` row → `prompts/{active}` row（同 affordance / 同 sheet 渲染）：
- `synthesised schemaId` → 真 `prompt.prompt_id`
- `derived from: —` 槽位 → 填 `prompt.derived_from` 真值
  - 同 project：`derived from: pr_baseline` (hyperlink → 父 quick-look)
  - 跨 project：`derived from: us_invoice/pr_baseline`
- 每字段 `review-notes` hint 槽位 → 仍预留（M9.x 后续 user 反馈 UI 用）

### 7.3 ContextSurface 右上 card 拆双

- 现状：单一 "Schema (8 fields, +N more)" card
- 新版：两张并列 card
  - `Prompt: pr_baseline · 8 fields · 2 notes ¶` → 点开 prompt quick-look
  - `Model: Gemini Flash 2.5` → 点开 model 配置详情（本期可只读 JSON 视图）
- User-facing 词汇 "Schema" → "Prompt" / 中文 "提示词"

### 7.4 Review 模式多 tab 切换（截图 UX 落地）

**心智**：tab 是横向 strip（segmented control），content area 一次只渲染一个 tab——像 Chrome tab，不是分屏并排。

```
[Review 模式 doc=invoice_001]

┌─────────────────────────────────────────────────────────────────┐
│  ⭐ Active          ex_try_gemma     ex_try_supplier    [ + ]   │ ← tab strip
│     Gemini Flash    Gemma 4          Gemini Flash               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   <当前选中 tab 的字段表单 + PDF 预览>                           │
│   （仅一份内容，切 tab 才切换显示）                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

- 数据源 tab 1（⭐ Active）：`predictions/_draft/{doc_id}.json`
- 数据源 tab 2+：`experiments/{ex_id}/extracts/{doc_id}.json`
- `[+]` 弹出 experiment 列表（仅 non-archived）→ user 选 → lazy 触发 `extract_with_experiment(ex_id, doc_id)` → 新 tab 显示
- 移除 tab：去 attach（不删 extract 文件）
- **字段编辑（保存 reviewed ground truth）只在 ⭐ Active tab 起作用**——其他 tab 是 read-only，避免混淆"哪份是 ground truth"

**Tab strip 溢出策略**（experiment 多了不会"并排不下"，因为不是分屏；但 tab strip 本身可能超出宽度）：
- 默认横向 scroll（Chrome 风格，trackpad / shift+wheel 横滚）
- 数量 > N（建议 6-8）时尾端出现 overflow chevron `…` 弹出完整列表
- Archived experiment 不进 `[+]` 候选 + 不展示在 tab strip
- Tab label 截断策略：默认显示 `{experiment.label}`，悬停 tooltip 显示完整 `{provider}|{provider_model_id} / {prompt.label}`

### 7.4.1 字段并排对比（diff 视图，power-user affordance）

Tab 切换解决"看某一份结果"，但 user 真正想做的"两份哪些字段不一样"是另一个 affordance。本期可后置实现，spec 锁定 UX 方向：

- **不做** tab pin 分屏（"X 方案"）—— 字段 8–30 个并排 2 列已挤，3+ 列字段名都看不全，扩展性差
- **做** diff 视图（"Y 方案"）—— user 选 base tab + target tab → field-by-field diff，只 highlight 差异字段，相同折叠
  - 入口：tab strip 上的 `compare with…` 按钮 / 右键菜单
  - 显示：单视图，每个差异字段一行 `field_name: base_value → target_value`，evidence page 仍可点
  - 多向 diff（A vs B vs C）trivially 扩展，本期先 2-way

本期 explicit 不实现 diff 视图，只锁定 UX 方向，作为 M9.x 后期 follow-up。Tab 切换 + chat 文本回报 score 差异已经覆盖 80% 对比用例。

### 7.5 Single-doc predict 入口

| 路径 | Tool | 写盘 | UI 触发 |
|---|---|---|---|
| Active 单 doc predict | `extract_one(doc_id)` | `predictions/_draft/{doc_id}.json` | doc list 行级 extract 按钮 / chat "跑一下 doc_X" |
| Experiment 单 doc predict | `extract_with_experiment(exp_id, doc_id)` | `experiments/{exp_id}/extracts/{doc_id}.json` | Review 模式 `[+]` 加 tab / chat "在 doc_X 上跑 ex_Y" |

两个 primitive 都是 single-doc，差异只在写哪个目录。**不支持** ad-hoc "用 (prompt_X, model_Y) 跑 doc_Z 但不留痕"——`create_experiment` 设计成极轻（一行命令，label 自动 `"trial_{ISO_ts}"`），UX 等价 ad-hoc，多出来的是 audit trail（feature 不是 cost）。

---

## 8. Migration / backward compat

### 8.1 Lazy migration on first read

旧 project（pre-M9.x layout）第一次被读取时（list_projects / get_project_meta / 任何 schema 读路径）触发自动 lazy migration：

```python
migrate_project_if_needed(workspace, pid):
    pdir = project_dir(workspace, pid)
    if (pdir / "prompts").exists():
        return  # already migrated
    
    project = read project.json
    schema_fields = read schema.json (旧路径)
    global_notes_text = (
        read global_notes.md if exists else ""
    )
    
    # 1. 建 prompts/pr_baseline.json
    pr_baseline = {
        "prompt_id": "pr_baseline",
        "label": "Baseline (migrated)",
        "schema": schema_fields,
        "global_notes": global_notes_text,
        "derived_from": None,
        "created_at": project.created_at,
        "updated_at": now(),
    }
    atomic_write prompts/pr_baseline.json
    
    # 2. 建 models/m_default.json
    m_default = {
        "model_id": "m_default",
        "label": f"Migrated ({project.extract_model})",
        "provider": infer_provider_from(project.extract_model),
        "provider_model_id": project.extract_model,
        "params": project.extract_params or {"temperature": 0.0},
        "created_at": project.created_at,
    }
    atomic_write models/m_default.json
    
    # 3. 更新 project.json
    project.active_prompt_id = "pr_baseline"
    project.active_model_id = "m_default"
    # 保留 extract_model / extract_params 作为 fallback
    atomic_write project.json
    
    # 4. 搬迁 versions/_candidate/ → prompts/_candidate/ (如有 active autoresearch job)
    if (pdir / "versions/_candidate").exists():
        move versions/_candidate/* → prompts/_candidate/
    
    # 5. schema.json + global_notes.md 暂保留磁盘，FSSpine 不再显示，
    #    一个 milestone 后由 cleanup script 删除（避免不可逆删错）
```

### 8.2 新 project 创建

新 project 直接走新 layout（不写 schema.json / global_notes.md / extract_model 旧字段）。

### 8.3 versions/v{N}.json 不迁移

旧版本文件结构跟新版兼容（多出来的 `derived_from` 字段是 optional），publish fast-path 0 改动，老 frozen version 仍可服务 API 调用。

### 8.4 write_schema 兼容 wrapper

```python
async def write_schema(workspace, pid, fields):
    """DEPRECATED — kept for one milestone for backward compat."""
    prompt = read prompts/{active}.json
    return await write_prompt(
        workspace, pid,
        prompt_id=None,           # active
        schema=fields,
        global_notes=prompt.global_notes,  # 不动 notes
    )
```

---

## 9. Hard rules respected (red lines)

逐条 cross-check：

| Hard rule | 本 design 处理 |
|---|---|
| 没有 image few-shot | 不引入；新概念是 prompt unit 含 schema + 文案，无 example I/O pairs |
| 没有 bbox / 区域信息 | 不变；`_evidence` 仍仅 page 整数 |
| AutoResearch 永不自动 promote | §5.2 强化——accept 后落 named variant，user 仍需 explicit promote |
| Counterexample 永不进 runtime prompt | §5.3 维持 |
| Public API 读 `versions/v{N}.json` | §6.1 维持，publish fast-path 0 改动 |
| 不读取/打印/提交 secrets | 不变；`_keys.json` 不参与 fork、不存进 experiment audit |
| Agent brain (SDK) ↔ Extract LLM (provider adapter) 分离 | 维持；experiment 走 provider adapter，跟现 extract_one 同路径 |
| `schema.json` 只通过 `write_schema` tool 修改 | **演化**：`schema.json` retire；`prompts/{id}.json` 只通过 `write_prompt` / `create_prompt` / 内部 promote 写盘；autoresearch 候选只写 `prompts/_candidate/`，user-accept 才落到 `prompts/pr_<id>.json` |
| task-type-agnostic UI vocabulary | "Prompt" / "Model" / "Experiment" 均通用动词，未来非 extraction 任务可复用 |

### Insights cross-check（trap notes 不复发）

| Insight | 本 design 是否触动 |
|---|---|
| #1 `can_use_tool` 强制 | 不触动；新 tools 全部 `mcp__emerge_tools__*` 前缀 |
| #2 `setting_sources=[]` | 不触动 |
| #4 Gemini `additionalProperties` 禁用 | 不触动；`_build_response_schema` 由 prompt.schema 驱动，行为不变 |
| #7 SDK echo ToolResultBlock | 不触动 |
| #8 `safe_project_id` 强制 | 维持；新增 endpoint（list_prompts / list_experiments 等）必须用 |
| #10 `/` 前缀 leading space | 不触动 |
| #11 `resume=...` + session id sidecar | 不触动 |

---

## 10. YAGNI / explicit out of scope

| 项 | 不做的原因 |
|---|---|
| Doc subset / named doc set | experiment 默认跑 reviewed 全集，doc set 是 over-engineering；user 想细分可 fork project |
| 跨 project axis 直接引用（live link） | 违反 clone-at-time 锚点；用 `import_prompt` 复制即可，lineage 通过 `derived_from` 记录 |
| Grid search UI（自动 enumerate prompt × model 矩阵） | user 实际工作流是 one-axis-at-a-time，不真 grid；手动 create_experiment 够 |
| `task_type` 多态化（场景 5 文档匹配） | 独立 M10+ 工作；本 design 锁定 `task_type="extraction"` |
| Per-experiment 历史 / re-run | experiment 只保留 latest eval；要历史就建新 experiment（命名带版本） |
| Archived experiment 自动 GC | 不引入；user 显式 delete |
| Experiment 之间 score diff 可视化 UI | 本期返回 chat 文本即可；专门 diff 视图后置 |
| Tab pin 分屏并排（同时横向显示 2+ tab 字段表单） | 字段 8–30 个并排 2 列已挤，3+ 列字段名都看不全，扩展性差；用 §7.4.1 diff 视图覆盖更好 |
| Cost / latency tracking per model | `models/{id}.json` 留 placeholder 字段，本期不强制；后续可选 |
| Prompt 的 git-style 版本（每改一次自动 commit） | 不引入；user 显式 `create_prompt` 起新 variant 即可 |
| Schema field 级注释（reviewed.notes 进 description）反馈循环 | M9.0 已 reserve 槽位，本期不实现 |

---

## 11. Open questions deferred

- **跨 project experiment**（场景 2 进阶版：在 p_b_eval 里直接引用 p_us_invoice 的 prompt 跑 eval，不复制文件）——本期用 `import_prompt` 解决 80% case，剩下需求等用户反馈再评估
- **Experiment 排序 / 默认隐藏 promoted/archived** UI policy——视实际使用密度决定
- **Autoresearch job 输出多个 candidate variant**（不只 turn-by-turn 的 single chain，而是 beam search 类）——本期仍单链
- **Multi-language prompt variant**（同 project 内中英文 prompt 切换）——架构原生支持（多 prompt variant），UI 入口本期不引入

---

## Next step

本 spec 锁定后，进 `superpowers:writing-plans` skill，按 ROADMAP 节奏拆 M9.1 / M9.2 / M9.3 多个 plan 文件交付。建议拆分次序：

1. **M9.1 — Data model migration**：新 layout disk + pydantic models + lazy migration + write_prompt wrapper（最 load-bearing，先把数据迁移做完，UI 还显示老界面也能跑）
2. **M9.2 — Prompt/Model axis tools + UI**：tool catalog §3.1–3.2 + FSSpine + ContextSurface 改造
3. **M9.3 — Experiment + per-doc predict + review tabs**：§3.3 tools + review tab 多 attach UI
4. **M9.4 — Autoresearch fit**：candidate 路径搬迁 + accept-as-variant
5. **M9.5 — Fork project + import prompt**：跨 project 操作
6. **M9.6 — Publish path audit field + readiness loosening**：低风险收尾

每个 plan 单独 e2e 验证、单独可 ship；M9.1 落地后中间 milestone 即使没接完 UI 也能从 chat 操作完整流程。
