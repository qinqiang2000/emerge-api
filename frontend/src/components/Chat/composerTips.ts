// frontend/src/components/Chat/composerTips.ts
//
// Claude-Code-style 动态 tip：输入框上方一行浅色提示，按用户"当前情况"挑最相关
// 的一条。取代了 EmptyHero 里那堆静态 nudge / starter 卡片——主页只留拖拽区，
// 引导收敛成 composer 上方这一行，跟着上下文走。
//
// 设计原则：永远返回一个 key（不返回 null），这样 tip 行高度恒定、不跳动；内容
// 随上下文切换，但不依赖每次击键（除 filesReady 一支），所以打字时也不闪。

export interface TipCtx {
  /** 未绑定项目（`/` 或 `/c/<cid>`）。 */
  unbound: boolean
  /** 当前项目的文档数（unbound 时为 0）。 */
  docCount: number
  /** 当前项目的 schema 字段数（unbound 时为 0）。 */
  fieldCount: number
  /** 已就绪、可随 turn 发出的待发附件数（staged / uploaded）。 */
  pendingReady: number
  /** 仍在上传 / staging 中的附件数。 */
  pendingInFlight: number
  /** 输入框里是否已有非空文本（用户正在打字）。 */
  hasText: boolean
  /** 本会话是否已暴露熟练度（敲过 / 或 @、或发过一次 turn）。 */
  competent: boolean
  /** 当前会话是否已有事件（对话是否开始）。 */
  hasEvents: boolean
}

// 项目已成型（有文档+字段、对话进行中）时轮播的"进阶" tip 池。每次页面加载挑
// 一条，跨刷新有变化、单次会话内稳定——跟 Claude Code 轮换 tip 是同一手法。
const SETTLED_POOL = ['tip.review', 'tip.compare', 'tip.publish', 'tip.slash'] as const
const SETTLED_PICK = SETTLED_POOL[Math.floor(Math.random() * SETTLED_POOL.length)]

/** 按当前情况挑一条最相关的 tip，返回 i18n key。优先级从"此刻最该做的事"往下
 *  排：上传中 > 文件就绪 > 未绑定引导 > 缺字段 > 缺文档 > 首次抽取 > 进阶轮播。 */
export function pickTipKey(c: TipCtx): string {
  if (c.pendingInFlight > 0) return 'tip.uploading'
  if (c.pendingReady > 0 && !c.hasText) return 'tip.filesReady'
  if (c.unbound) return c.competent ? 'tip.unbound.competent' : 'tip.unbound.new'
  if (c.fieldCount === 0) return 'tip.noFields'
  if (c.docCount === 0) return 'tip.noDocs'
  if (!c.hasEvents) return 'tip.run'
  return SETTLED_PICK
}
