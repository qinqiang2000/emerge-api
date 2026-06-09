# 分享材料：数字同事 · Software 3.0 · emerge

公司内部分享用。一块白板讲清三件事：**范式 → 应用全貌 → 平台判断**。

## 文件

| 文件 | 是什么 |
|---|---|
| `2026-06-09-emerge-vision-board.excalidraw` | **主白板**（一张图，三个区 ①②③ + 右侧图例）。拖进 [excalidraw.com](https://excalidraw.com) 或用 VS Code Excalidraw 插件打开。 |
| `2026-06-09-digital-colleague.md` | **讲稿要点**（6 拍主线 + emerge 现场演示点编排）。 |
| `README.md` | 本文（阅读线 + 图例详表 + 架构判断全文）。 |

> 设计原则：方框只留**概念**，`≈ 传统对应` 与 `emerge 实例` 放右侧图例区 / 本文，不塞进图形。

## 阅读线

**① 范式转移** — 从「软件 + copilot，人适应软件」到「数字同事，给目标不点击」。Software 3.0：自然语言即程序（1.0 代码 → 2.0 权重 → 3.0 自然语言）。

**② 一个 Software 3.0 应用：组成 + 交付** — 这是核心。一个 agent 应用由这些组成（用计算机解剖类比）：

| 组件 | ≈ 传统 | emerge 实例 |
|---|---|---|
| 意图 | GUI | chat / `/emerge:run` |
| Agent 内核 | CPU（写死的业务逻辑） | Claude（agent brain） |
| 程序 = Prompt / Skill | 源代码（改一句话就改软件） | `SKILL.md` |
| 能力 = Tools / MCP | SDK / 库调用 | `extract` · `score` · `ws_*` |
| 上下文 + 记忆 | RAM | Active context · `reviewed/` |
| 文件系统总线 | 磁盘 / 数据库 **+ 接口** | `project.json` · `models/` · `predictions/` |

> **本会话最值钱的洞见 —— 存储即接口**：传统软件里存储（DB/磁盘）藏在专用 API 后面，是两层；emerge 把**同一批文件**经 MCP 直接暴露成通用文件操作 `ws_list / ws_read / ws_grep`，于是「文件系统」既是**磁盘（存储状态）**又是**接口（能力面）**。因为核心对象本来就是文件，一个通用文件操作面就打通了所有对象的 CRUD——无需 `list_models` 等几十个专用 API。这就是为什么叫「**总线**」（共享通道，内核/工具/agent 都挂上去）而非「磁盘」。对应架构判断那句「**数据当总线，不当私仓**」，也是 dogfood 名场面的根因：「`list_models` 不存在也没关系，agent 直接 `ws_read` 那个文件」。

| 纠正闭环 | 单元测试（但会**学习**） | `score` · `save_reviewed` · autoresearch |
| 能力包 / 交付 | App Store 安装 | `/plugin install` · Cowork Upload plugin |

交付与扩展：客户端可换（**换前端 = 换 agent 客户端**：CLI / Cowork / Desktop / Web）；能力靠**能力包**装一次全点亮；输出从同一根总线分叉出 **提取 ✓ / 分类 / 匹配**——新任务不做多个应用。

**③ 为 OS 编程 → 为 Agent 平台编程** — iOS/Linux/Windows 的平台范式正在 agent 平台上逐层重演：

| 为 OS 编程 | 为 Agent 平台编程 |
|---|---|
| 交互：人点 UI · 手搬数据 | 人给目标 · agent 编排 |
| 应用：App（二进制 + GUI） | 能力包（skill + connector，无 GUI） |
| 分发 + 权限：App Store · 沙箱 | 插件 marketplace · OAuth scope |
| 接口 · 语言：系统调用/SDK · C/Swift | 工具/MCP · 自然语言 prompt/skill |
| 底座：OS 内核 + 硬件 | Agent 内核（LLM）+ OS 成了底座 |

### 架构判断

**Agent 平台 = OS 之上的新一层，不是替代 OS**（跑在 Linux/macOS/Win 上，用其文件/进程/网络）。

- 别做 App，做**能力包**
- 编程对 **MCP**，不对 UI
- 数据当**总线**，不当私仓
- 分发 / 鉴权用**平台标准**，别自造
- 护城河迁移：从「占住 UI / 工作流」→「**能力 + 数据纠正闭环**（越纠正越准）」—— UI 锁定已死
- 时点 ≈ **2008 的 iOS**：标准(MCP)刚稳 · marketplace 刚现 · OAuth/DCR 刚标准化 → 早在开放标准上建能力者吃复利
- 关键差异（类比断裂处）：App 是**确定调用**；能力是被**概率规划器『选中』**调用 → 工具命名 / skill = 对 agent 的『营销』

emerge 把这些都押对了：能力包（plugin）· 工具+HTTP 对称 · 文件系统总线（`ws_*`）· OAuth+marketplace · 数据纠正闭环（`save_reviewed`/autoresearch）。
