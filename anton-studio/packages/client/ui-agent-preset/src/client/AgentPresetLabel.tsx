import { useEffect } from 'react'
import type { SnapshotStore } from '@deepseek-ai/dsh-client-runtime/client'
import type { InjectFace, PropsLocale, PropsRuntime } from '@deepseek-ai/dsh-client-ui-slots'
import type {} from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { AgentPresetSettingsState } from './settings-store.ts'

export interface AgentPresetLabelInjected {
  hooks: {
    agentPresets: SnapshotStore<AgentPresetSettingsState>
  }
  load: () => Promise<void>
}

export type AgentPresetLabelProps =
  PropsRuntime<'conversation.session.header.actions'>
  & PropsLocale<'settings.agentPreset'>
  & InjectFace<AgentPresetLabelInjected>

export function AgentPresetLabel({
  sessionId, useSessions, load,
}: AgentPresetLabelProps) {
  const preset = useSessions(state => state.byId[sessionId]?.agentPreset)

  useEffect(() => {
    if (preset !== undefined) void load()
  }, [preset, load])

  return null
}
