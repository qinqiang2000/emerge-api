# 2026-06-10 — SDK buffer 隐患根治（大图 base64 撑爆 1MB 控制协议缓冲）

> **Status**: ✅ T1–T6 implemented (2026-06-10)。全量 1480 passed 零回归（+9 新测试）；实测报价单.pdf 150dpi render 467KB PNG → 149KB JPEG(1568px)。待 commit + prod 部署后跑下方"验证"。
> **现象**: `read_doc_image`/`pdf_render_page`(150dpi PNG) 的 base64 进 agent 上下文,多张/大图累积超 claude_agent_sdk 控制协议 1MB buffer → `agent_failure: JSON exceeded maximum buffer size`(实测一张报价单 render b64 0.59MB,3 张累积 1.34MB 崩)。audit 已绕开(图走 provider 直连),但**任何** agent 看几张大文档图的场景(识别一下/对比两页/审 UI 截图)都会崩。
> **方案**: 双保险——①SDK 边界统一降采样(主修);②`max_buffer_size` 提到 8MB(兜底)。**provider 直连路径(audit/translate/textlayer OCR)不动,保持全分辨率。**

---

## 为什么降采样无损

Anthropic vision 最优输入是长边 ≤1568px,更大的图 API 侧也会被缩到这个尺度——agent 经 SDK 看图,1568px 之上的像素本来就到不了模型。所以在 SDK 边界缩到 1568px + JPEG 重编码,对 agent 视力**零损失**,体积降一个量级(150dpi A4 PNG ≈ 1240×1754,0.5-0.8MB → 1568px JPEG q80 ≈ 100-250KB)。

## 改动点(SDK 边界仅两处 + 一个兜底)

### T1 — 共享压图原语 `app/tools/docs.py::fit_image_for_agent`
- `fit_image_for_agent(data: bytes, mime: str) -> tuple[bytes, str]`:
  - 长边 >1568px → 等比缩到 1568;缩后(或原始尺寸已小但字节大,>400KB)→ JPEG q80 重编码;若 JPEG 反而更大或图本来就小(≤400KB 且尺寸合规)→ 原样返回。
  - 用 **PyMuPDF(fitz,已有硬依赖)**: `fitz.open(stream=…)` 把图当单页文档,`get_pixmap(matrix=Matrix(scale,scale))` 缩放,`tobytes("jpeg", jpg_quality=80)` 编码。**先验证当前 pymupdf 版本支持 jpeg tobytes**(不支持则加 Pillow 依赖,实现同语义——二选一,别两个都上)。
  - 透明通道:JPEG 无 alpha,fitz pixmap 若带 alpha 先铺白底。
  - 纯函数,失败(损坏图/未知格式)原样返回不抛——压不动 ≠ 看不了。
- 设计权衡注释:阈值 1568 来自 Anthropic vision 上限,400KB 来自 1MB buffer ÷ 经验并发图数,改前先读此注释。

### T2 — 边界一:`tools/__init__.py::t_read_doc_image`
- wrapper 里 `fit_image_for_agent(base64.b64decode(out["data"]), out["mime"])` → 重编 b64 + 更新 mimeType。`read_doc_image` 本体**不动**(audit/translate/textlayer 直调它要全分辨率)。
- mcp_server.py(standalone stdio)自动继承此 wrapper,Claude Desktop/Code 侧同收益。

### T3 — 边界二:`chat/service.py::_load_image_blocks`
- 用户附件图同样过 `fit_image_for_agent` 再进 SDK 上下文(同一隐患的另一入口:用户拖 3 张高清截图问"哪张对")。

### T4 — 兜底:`ClaudeAgentOptions(max_buffer_size=8MB)`
- `chat/service.py` 构造 options 处(~733 行)加 `max_buffer_size=8 * 1024 * 1024`,常量注明:这是对累积场景的防线,不是放任大图的许可——主修在 T1。

### T5 — skill 措辞回收
- `emerge_extractor.md` audit 小节"拉几张图会撑爆 buffer"的警示**保留但软化**(撑爆→已有降采样防护,但审核仍必须走 run_audit:那是 provider 直连全分辨率,judge 看得更清,且报告才是产物);`t_read_doc_image` 工具描述去掉"每页一次调用"之外的恐吓性约束?——不,描述不动,只查有无与新行为矛盾的句子。

### T6 — tests
- `test_image_fit.py`(新):fitz 合成大 PNG(如 2400×3400)→ 输出长边 ≤1568、字节 ≤400KB、mime=jpeg;小图(800×600 50KB)原样返回;带 alpha PNG → 白底 JPEG 不报错;垃圾字节 → 原样返回。
- `t_read_doc_image` 集成:上传合成大图 → tool result 的 b64 解码后 ≤400KB 且 mimeType 正确;`read_doc_image` 本体仍返回原始大小(直连路径未被污染的回归锚)。
- `_load_image_blocks` 同样收敛断言。
- options 单测:构造的 ClaudeAgentOptions.max_buffer_size == 8MB。
- 全量 pytest 绿。

## 验证(部署后)
- prod 用 audit_demo 的报价单.pdf:chat 让 agent `read_doc_image` 3 张大图(A0 当时崩的复现路径)→ 不崩且 agent 能描述图;run_audit 照常(直连全分辨率)。

## 红线
- Doc vision is pulled, not pushed:本修不加任何 auto-attach。
- provider 直连(Extract/judge/OCR/translate)永远全分辨率——压图只许发生在 SDK/agent 边界。
- 不动 `pdf_render_page` 的 150dpi 与缓存(textlayer 的 image_w/h 与 150dpi 锁死,见 textlayer.py:48)。
