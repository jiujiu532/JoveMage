import apiClient from './client'
import type { ChannelDescriptor } from '@/config/channels'

/**
 * GET /api/channels 响应。
 * 字段与后端 services/channels/descriptors.py 对齐；
 * 熔断/临期预警等 P1-B/C 字段前端可选消费，缺席不炸。
 */
export type ChannelsListResponse = {
  channels: ChannelDescriptor[]
}

export const channelsApi = {
  /** 渠道描述符权威列表（鉴权：Bearer） */
  list: () => apiClient.get<never, ChannelsListResponse>('/api/channels'),
}
