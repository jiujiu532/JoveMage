/**
 * 浮层定位公共算法：placement 决策、可用空间、贴边钳制。
 * 组件特有逻辑（窄屏、子菜单、对齐策略）留在调用方。
 */

export type FloatingPlacement = 'auto' | 'top' | 'bottom' | 'left' | 'right' | 'up' | 'down'
export type ResolvedPlacement = 'top' | 'bottom' | 'left' | 'right'

export type FloatingSpace = {
  menuWidth: number
  menuHeight: number
  availableDown: number
  availableUp: number
  availableRight: number
  availableLeft: number
}

export type AnchorRect = Pick<DOMRect, 'top' | 'bottom' | 'left' | 'right' | 'width' | 'height'>

export type MenuSize = {
  width: number
  height: number
}

export type ComputeFloatingPositionOptions = {
  placement?: FloatingPlacement
  /** 与锚点间距，默认 8 */
  gap?: number
  /** 视口边距，默认 8 */
  margin?: number
  /** 上下展开时的水平对齐，默认 'left' */
  align?: 'left' | 'right'
  /** 只在上下方向决策（窄屏），忽略左右 */
  verticalOnly?: boolean
  /** maxHeight 下限，默认 96 */
  minMaxHeight?: number
  viewportWidth?: number
  viewportHeight?: number
}

export type FloatingPositionResult = {
  left: number
  top: number
  maxHeight: number
  placement: ResolvedPlacement
}

/** up/down → top/bottom，其余原样 */
export function normalizePlacement(placement: FloatingPlacement): 'auto' | ResolvedPlacement {
  if (placement === 'up') return 'top'
  if (placement === 'down') return 'bottom'
  return placement
}

/** 根据可用空间解析最终 placement（含 auto） */
export function resolvePlacement(
  placement: FloatingPlacement,
  space: FloatingSpace,
): ResolvedPlacement {
  const normalized = normalizePlacement(placement)
  if (normalized !== 'auto') return normalized
  if (space.menuHeight <= space.availableDown) return 'bottom'
  if (space.menuHeight <= space.availableUp) return 'top'
  if (space.menuWidth <= space.availableRight) return 'right'
  if (space.menuWidth <= space.availableLeft) return 'left'
  return space.availableDown >= space.availableUp ? 'bottom' : 'top'
}

/** 计算锚点四周可用空间（扣除 gap 与 margin） */
export function computeAvailableSpace(
  anchorRect: AnchorRect,
  opts: {
    gap?: number
    margin?: number
    viewportWidth?: number
    viewportHeight?: number
  } = {},
) {
  const gap = opts.gap ?? 8
  const margin = opts.margin ?? 8
  const viewportWidth = opts.viewportWidth
    ?? (typeof window !== 'undefined'
      ? (window.innerWidth || document.documentElement.clientWidth)
      : 0)
  const viewportHeight = opts.viewportHeight
    ?? (typeof window !== 'undefined'
      ? (window.innerHeight || document.documentElement.clientHeight)
      : 0)

  return {
    availableDown: Math.max(0, viewportHeight - margin - anchorRect.bottom - gap),
    availableUp: Math.max(0, anchorRect.top - margin - gap),
    availableRight: Math.max(0, viewportWidth - margin - anchorRect.right - gap),
    availableLeft: Math.max(0, anchorRect.left - margin - gap),
    viewportWidth,
    viewportHeight,
  }
}

/**
 * 根据锚点矩形与菜单尺寸计算 left/top/maxHeight/placement。
 * 不处理 minWidth、子菜单、窄屏宽度等业务字段。
 */
export function computeFloatingPosition(
  anchorRect: AnchorRect,
  menuSize: MenuSize,
  opts: ComputeFloatingPositionOptions = {},
): FloatingPositionResult {
  const gap = opts.gap ?? 8
  const margin = opts.margin ?? 8
  const align = opts.align ?? 'left'
  const minMaxHeight = opts.minMaxHeight ?? 96

  const space = computeAvailableSpace(anchorRect, {
    gap,
    margin,
    viewportWidth: opts.viewportWidth,
    viewportHeight: opts.viewportHeight,
  })
  const {
    viewportWidth,
    viewportHeight,
    availableDown,
    availableUp,
    availableRight,
    availableLeft,
  } = space
  const { width: menuWidth, height: menuHeight } = menuSize

  const placement: ResolvedPlacement = opts.verticalOnly
    ? (availableDown >= availableUp ? 'bottom' : 'top')
    : resolvePlacement(opts.placement ?? 'auto', {
      menuWidth,
      menuHeight,
      availableDown,
      availableUp,
      availableRight,
      availableLeft,
    })

  const verticalLeft = align === 'left' ? anchorRect.left : anchorRect.right - menuWidth
  const maxLeft = Math.max(margin, viewportWidth - margin - menuWidth)
  const maxTop = Math.max(margin, viewportHeight - margin - menuHeight)

  let left = Math.min(maxLeft, Math.max(margin, verticalLeft))
  let top = anchorRect.bottom + gap
  let maxHeight = availableDown

  if (placement === 'top') {
    top = anchorRect.top - gap - menuHeight
    maxHeight = availableUp
  } else if (placement === 'left') {
    left = anchorRect.left - gap - menuWidth
    top = anchorRect.top
    maxHeight = viewportHeight - margin * 2
  } else if (placement === 'right') {
    left = anchorRect.right + gap
    top = anchorRect.top
    maxHeight = viewportHeight - margin * 2
  }

  left = Math.min(maxLeft, Math.max(margin, left))
  top = Math.min(maxTop, Math.max(margin, top))

  return {
    left,
    top,
    maxHeight: Math.max(minMaxHeight, Math.floor(maxHeight)),
    placement,
  }
}
