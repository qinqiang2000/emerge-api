// frontend/src/stores/onboarding.ts
//
// "新人 vs 老手" 的判定锚——但**不靠**账号创建/首登时间(会被借账号骗到),
// 只靠**当前会话里行为暴露出来的熟练度**。判断的是"此刻坐在键盘前的人需不
// 需要引导",不是"这个账号新不新"。
//
// 信号:本会话第一次做出一个称职动作(敲 `/` 开命令、`@` 开 mention、或提交
// 一次真实 turn)→ 翻成 competent,EmptyHero 的 `/help` nudge 即淡出。老手坐
// 下两秒内必然触发;新人迟迟不动作,nudge 一直当安全网留着。
//
// 作用域 = sessionStorage(本 tab、跨刷新存活,关 tab 清零)。这正是它扛借账号
// 的原因:换个人开一个新 tab 就是一段新会话,引导照常出现;而且全程不读身份态。
import { create } from 'zustand'

const KEY = 'emerge.competent'

// jsdom(vitest)下 sessionStorage 存在;真·SSR / 受限环境兜底成内存态。
function readSeed(): boolean {
  try {
    return typeof sessionStorage !== 'undefined' && sessionStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

interface OnboardingState {
  /** 本会话是否已暴露出熟练度。true → 隐藏新手引导。 */
  competent: boolean
  /** 标记一次称职动作。幂等:已 true 时不再写。 */
  markCompetent: () => void
}

export const useOnboarding = create<OnboardingState>((set, get) => ({
  competent: readSeed(),
  markCompetent: () => {
    if (get().competent) return
    try {
      if (typeof sessionStorage !== 'undefined') sessionStorage.setItem(KEY, '1')
    } catch {
      /* 隐私模式 / 配额满 — 退化成纯内存态即可 */
    }
    set({ competent: true })
  },
}))

/** 非 React 调用点的命令式逃生口(事件处理器、store action),对齐 toast.ok 模式。 */
export function markCompetent() {
  useOnboarding.getState().markCompetent()
}
