/**
 * 全局响应式断点（与 Tailwind 对齐）。
 *
 * 配对约定（避免边界重叠）：
 * - 窄屏向下用 max-width: (N-1)px
 * - 宽屏向上用 min-width: Npx
 *
 * 组件局部 layout 断点（900/960 等）不进这里，保持在各组件 @media。
 */
export const BP = {
  /** 手机主断点 */
  sm: 640,
  /** 平板/桌面分界 */
  md: 768,
  /** 桌面 / 壳 immersive 分界 */
  lg: 1024,
} as const

/** max-width 查询：向下（含 sm-1） */
export const mqDown = (n: number) => `(max-width: ${n - 1}px)`
/** min-width 查询：向上（含 n） */
export const mqUp = (n: number) => `(min-width: ${n}px)`

/** 常用查询串 */
export const MQ = {
  /** ≤639 手机 */
  phone: mqDown(BP.sm),
  /** ≤767 平板及以下 */
  tabletDown: mqDown(BP.md),
  /** ≤1023 非桌面（壳 immersive / Studio 全屏 / Settings Tab 横滑） */
  notDesktop: mqDown(BP.lg),
  /** ≥1024 桌面 */
  desktopUp: mqUp(BP.lg),
} as const
