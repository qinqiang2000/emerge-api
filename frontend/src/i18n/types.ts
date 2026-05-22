export type Locale = 'en' | 'zh'

export type Dict = Record<string, string>

export const SUPPORTED_LOCALES: readonly Locale[] = ['en', 'zh'] as const
