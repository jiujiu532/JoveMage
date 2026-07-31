/**
 * 全局响应式断点（与 Tailwind 对齐）。
 *
 * 配对约定（避免边界重叠）：
 * - 窄屏向下用 max-width: (N-1)px
 * - 宽屏向上用 min-width: Npx
 *
 * 组件局部 layout 断点（900/960 等）不进这里，保持在各组件 @media。
 *
 * CSS 侧断点使用约定：
 * - 全局 token：sm=640 / md=768 / lg=1024
 *   · 窄屏：@media (max-width: 639px) | (max-width: 767px) | (max-width: 1023px)
 *   · 宽屏：@media (min-width: 640px) | (min-width: 768px) | (min-width: 1024px)
 * - JS 侧统一走 MQ / mqDown / mqUp，勿手写像素串
 * - 局部布局断点（不进本 token，保留在组件 @media）：
 *   · 720px：Studio / Proxy「小平板」级局部改排（搜索抽屉、消息列表、输入栏、代理卡片/出口行）
 *   · 760px：Studio 图片对比弹层的局部改排
 *   原因：这些组件在 sm(640) 与 md(768) 之间还有一档需要更早收拢/改列，硬并入全局会改触发点
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
