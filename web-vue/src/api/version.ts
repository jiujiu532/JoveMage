import apiClient from './client'
import type { VersionCheckResponse, VersionInfoResponse } from '@/types/api'

function toVersionInfo(payload: { version?: string; tag?: string; commit?: string }): VersionInfoResponse {
  const version = String(payload.version || '').trim()
  const tag = String(payload.tag || '').trim()
  return {
    version,
    tag: tag || (version.startsWith('v') ? version : version ? `v${version}` : ''),
    commit: String(payload.commit || ''),
  }
}

export const versionApi = {
  async current() {
    const payload = await apiClient.get<never, { version: string }>('/version')
    return toVersionInfo(payload)
  },

  async check(): Promise<VersionCheckResponse> {
    return apiClient.get<never, VersionCheckResponse>('/version/check')
  },
}
