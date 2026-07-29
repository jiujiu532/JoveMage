/**
 * ECharts 统一主题配置
 * 基于项目的设计系统，提供一致的图表样式
 */
import { FALLBACK_CHAT_MODELS, FALLBACK_IMAGE_MODELS } from '@/config/modelCatalog'

// 主题色板：奶油纸面 + pen 蓝 / 修正红 / 墨
export const chartColors = {
  primary: '#2D5DA1',
  success: '#2F6B3A',
  warning: '#8A6A12',
  danger: '#FF4D4D',
  info: '#2D5DA1',
  purple: '#2D2D2D',
  pink: '#FF4D4D',
  slate: '#6B6560',
  gray: '#6B6560',
  lightGreen: '#2F6B3A',
  cyan: '#2D5DA1',
  emerald: '#2D2D2D',
}

// 图表系列：pen 蓝 / 修正红 / 墨 / 暖灰 循环
export const modelColorPalette = [
  '#2D5DA1',
  '#FF4D4D',
  '#2D2D2D',
  '#6B6560',
  '#7EB0E8',
  '#FF6B6B',
  '#8A6A12',
  '#3F3F3F',
  '#1A3F70',
  '#D93636',
]

// 当前实际模型显式绑定，避免主力模型在不同图表中颜色漂移。
export const modelColors: Record<string, string> = {
  auto: '#6B6560',
  'gpt-5.5': modelColorPalette[0],
  'gpt-5-5': modelColorPalette[0],
  'gpt-5-5-thinking': modelColorPalette[9],
  'gpt-5.5-mini': modelColorPalette[6],
  'gpt-5': modelColorPalette[3],
  'gpt-5-1': modelColorPalette[4],
  'gpt-5-2': modelColorPalette[5],
  'gpt-5-3': modelColorPalette[6],
  'gpt-5-3-mini': modelColorPalette[8],
  'gpt-5-mini': modelColorPalette[7],
  'gpt-image-2': modelColorPalette[1],
  'codex-gpt-image-2': modelColorPalette[2],
  'plus-codex-gpt-image-2': modelColorPalette[4],
  'team-codex-gpt-image-2': modelColorPalette[6],
  'pro-codex-gpt-image-2': modelColorPalette[5],
  'gpt-4o': modelColorPalette[7],
  'o3': modelColorPalette[9],
  'gpt-image-1': modelColorPalette[8],
}

// 有效模型列表
export const validModels = [
  ...FALLBACK_CHAT_MODELS,
  ...FALLBACK_IMAGE_MODELS,
]

const nonModelKeys = new Set([
  '',
  '-',
  'default',
  'unknown',
  'null',
  'none',
  'low',
  'medium',
  'high',
  'standard',
  'hd',
  'portrait',
  'landscape',
  'square',
  'vertical',
  'horizontal',
  'image',
  'images',
  'text',
  'chat',
  'generation',
  'generations',
  'edit',
  'edits',
])

function looksLikeSizeOrRatioLabel(value: string): boolean {
  return /^\d+$/.test(value) || /^\d+k$/i.test(value) || /^\d{1,5}x\d{1,5}$/i.test(value) || /^\d{1,3}:\d{1,3}$/.test(value)
}

function normalizeModelKey(value: string): string {
  return value.trim().toLowerCase()
}

function looksLikeModelLabel(value: string): boolean {
  const key = normalizeModelKey(value)
  if (nonModelKeys.has(key) || key.startsWith('/') || looksLikeSizeOrRatioLabel(key)) return false
  return true
}

function getStablePaletteIndex(value: string): number {
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0
  }
  return hash % modelColorPalette.length
}

// 获取模型颜色：已知模型固定颜色，未知模型按名称稳定映射到 palette，避免全部回退成灰色。
export function getModelColor(model: string): string {
  const key = normalizeModelKey(model)
  if (!key || !looksLikeModelLabel(key)) return chartColors.gray
  return modelColors[key] || modelColorPalette[getStablePaletteIndex(key)]
}

// 过滤有效模型
export function filterValidModels(modelRequests: Record<string, number[]>): Record<string, number[]> {
  const filtered: Record<string, number[]> = {}
  const allowedModels = new Set(validModels.filter(looksLikeModelLabel))
  Object.entries(modelRequests || {}).forEach(([model, data]) => {
    if (!Array.isArray(data)) return
    if (allowedModels.has(model) || looksLikeModelLabel(model)) {
      filtered[model] = data
    }
  })
  return filtered
}

/** 当前是否深色主题（读 html[data-theme]） */
export function isDarkTheme(): boolean {
  if (typeof document === 'undefined') return false
  return document.documentElement.dataset.theme === 'dark'
}

function readCssVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

/** 图表表面令牌：浅色硬阴影/纸面，深色 card + line-soft + soft shadow */
export function getChartSurfaceTokens(isDark = isDarkTheme()) {
  return {
    isDark,
    ink: readCssVar('--bauhaus-ink', isDark ? '#f2f2f2' : '#2d2d2d'),
    card: readCssVar('--bauhaus-card', isDark ? '#212121' : '#ffffff'),
    lineSoft: readCssVar('--bauhaus-line-soft', isDark ? '#3d3d3d' : '#c9c2b4'),
    grey: readCssVar('--bauhaus-grey', isDark ? '#a3a3a3' : '#6b6560'),
    paper: readCssVar('--bauhaus-paper', isDark ? '#1a1a1a' : '#fdfbf7'),
    fontDisplay: readCssVar(
      '--font-display',
      '"Space Grotesk", "Noto Sans SC", "Helvetica Neue", Arial, sans-serif',
    ),
    fontBody: readCssVar(
      '--font-body',
      '"Noto Sans SC", "Space Grotesk", "Helvetica Neue", Arial, sans-serif',
    ),
  }
}

function getTextStyle(isDark = isDarkTheme()) {
  const tokens = getChartSurfaceTokens(isDark)
  return {
    fontFamily: tokens.fontBody,
    color: tokens.grey,
    fontSize: 11,
  }
}

// 网格配置
const gridConfig = {
  left: 24,
  right: 16,
  top: 44,
  bottom: 24,
  containLabel: true,
}

/** 工具提示：浅色硬墨边 + hard shadow；深色 card + line-soft + soft shadow */
export function getTooltipConfig(isDark = isDarkTheme()) {
  const tokens = getChartSurfaceTokens(isDark)
  if (isDark) {
    return {
      backgroundColor: tokens.card,
      borderColor: tokens.lineSoft,
      borderWidth: 1,
      textStyle: {
        color: tokens.ink,
        fontSize: 12,
      },
      padding: [8, 12] as [number, number],
      extraCssText: 'border-radius: 2px; box-shadow: 0 3px 9px rgba(0, 0, 0, 0.55);',
    }
  }
  return {
    backgroundColor: 'rgba(255, 255, 255, 0.98)',
    borderColor: tokens.ink,
    borderWidth: 2,
    textStyle: {
      color: tokens.ink,
      fontSize: 12,
    },
    padding: [8, 12] as [number, number],
    extraCssText: `border-radius: 2px; box-shadow: 2px 2px 0 0 ${tokens.ink};`,
  }
}

function getLegendConfig(isDark = isDarkTheme()) {
  return {
    textStyle: {
      ...getTextStyle(isDark),
      fontSize: 11,
    },
    itemWidth: 14,
    itemHeight: 14,
    itemGap: 16,
  }
}

/**
 * 折线图主题配置（随 data-theme 切换）
 */
export function getLineChartTheme(isDark = isDarkTheme()) {
  const tokens = getChartSurfaceTokens(isDark)
  const textStyle = getTextStyle(isDark)
  const splitColor = isDark
    ? 'rgba(61, 61, 61, 0.85)'
    : 'rgba(201, 194, 180, 0.7)'

  return {
    animation: true,
    animationThreshold: 4000,
    animationDuration: 700,
    animationEasing: 'cubicOut',
    animationDurationUpdate: 420,
    animationEasingUpdate: 'cubicOut',
    tooltip: {
      ...getTooltipConfig(isDark),
      trigger: 'axis',
      axisPointer: {
        type: 'line',
        lineStyle: {
          color: tokens.lineSoft,
          type: 'dashed',
        },
      },
    },
    legend: {
      ...getLegendConfig(isDark),
      right: 0,
      top: 0,
    },
    grid: gridConfig,
    xAxis: {
      type: 'category',
      boundaryGap: false,
      axisLine: {
        lineStyle: {
          color: tokens.lineSoft,
        },
      },
      axisTick: {
        show: false,
      },
      axisLabel: {
        ...textStyle,
        fontSize: 10,
      },
    },
    yAxis: {
      type: 'value',
      axisLine: {
        show: false,
      },
      axisTick: {
        show: false,
      },
      axisLabel: {
        ...textStyle,
        fontSize: 10,
      },
      splitLine: {
        lineStyle: {
          color: splitColor,
          type: 'solid',
        },
      },
    },
  }
}

/**
 * 饼图主题配置（随 data-theme 切换）
 */
export function getPieChartTheme(isMobile = false, isDark = isDarkTheme()) {
  const tokens = getChartSurfaceTokens(isDark)
  const textStyle = getTextStyle(isDark)
  const legendPosition = isMobile
    ? {
      left: 'center',
      bottom: 0,
      orient: 'horizontal' as const,
    }
    : {
      left: 0,
      top: 'middle',
      orient: 'vertical' as const,
    }

  const pieCenter = isMobile ? ['50%', '42%'] : ['60%', '50%']
  const pieRadius = isMobile ? ['35%', '55%'] : ['45%', '70%']

  return {
    animation: true,
    animationDuration: 600,
    animationEasing: 'cubicOut',
    animationDurationUpdate: 300,
    animationEasingUpdate: 'cubicOut',
    tooltip: {
      ...getTooltipConfig(isDark),
      trigger: 'item',
    },
    legend: {
      ...getLegendConfig(isDark),
      ...legendPosition,
      type: isMobile ? 'scroll' : 'plain',
      pageIconSize: 10,
    },
    series: {
      type: 'pie',
      radius: pieRadius,
      center: pieCenter,
      startAngle: 90,
      animationType: 'scale',
      animationEasing: 'cubicOut',
      avoidLabelOverlap: true,
      label: {
        show: true,
        fontSize: 11,
        color: textStyle.color,
      },
      labelLine: {
        show: true,
        length: 12,
        length2: 10,
        lineStyle: {
          color: tokens.lineSoft,
        },
      },
      itemStyle: {
        borderWidth: 2,
        borderColor: tokens.card,
        borderRadius: 2,
      },
      emphasis: {
        label: {
          show: true,
          fontSize: 13,
          fontWeight: 'bold',
        },
      },
    },
  }
}

/**
 * 创建折线图系列配置
 */
export function createLineSeries(
  name: string,
  data: number[],
  color: string,
  options?: {
    smooth?: boolean
    showSymbol?: boolean
    areaOpacity?: number
    lineWidth?: number
    zIndex?: number
    lineStyle?: {
      type?: 'solid' | 'dashed' | 'dotted'
      width?: number
    }
  }
) {
  const {
    smooth = true,
    showSymbol = false,
    areaOpacity = 0.25,
    lineWidth = 2,
    zIndex = 1,
    lineStyle,
  } = options || {}

  return {
    name,
    type: 'line',
    data,
    smooth,
    showSymbol,
    lineStyle: {
      width: lineStyle?.width ?? lineWidth,
      ...(lineStyle?.type && { type: lineStyle.type }),
    },
    areaStyle: {
      opacity: areaOpacity,
    },
    itemStyle: {
      color,
    },
    emphasis: {
      disabled: true,
    },
    z: zIndex,
  }
}

/**
 * 创建饼图数据项配置
 */
export function createPieDataItem(
  name: string,
  value: number,
  color: string
) {
  return {
    name,
    value,
    itemStyle: {
      color,
      borderRadius: 2,
    },
  }
}
