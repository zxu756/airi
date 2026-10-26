import type { LeadershipMode } from '@proj-airi/stage-ui/libs/pinia/setup-synced'

import { setupSynced, usePiniaSynced } from '@proj-airi/stage-ui/libs/pinia/setup-synced'
import { useLlmToolsStore } from '@proj-airi/stage-ui/stores/ai/chat-llm/tools'
import { useLlmToolsetPromptsStore } from '@proj-airi/stage-ui/stores/ai/chat-llm/toolset-prompts'
import { createPinia, disposePinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'

import { useTamagotchiMcpToolsStore } from './mcp'

vi.mock('@proj-airi/electron-vueuse', () => ({
  useElectronEventaInvoke: () => vi.fn(async () => []),
}))

type SyncedRuntime = ReturnType<typeof usePiniaSynced>
const windows: Array<{ app: ReturnType<typeof createApp>, pinia: ReturnType<typeof createPinia> }> = []

function openWindow(leadership: LeadershipMode) {
  const plugins = setupSynced({ leadership })
  const pinia = createPinia()
  pinia.use(plugins.pinia)
  let runtime: SyncedRuntime | undefined
  const app = createApp({
    setup() {
      runtime = usePiniaSynced()
      return () => null
    },
  })
  const host = document.createElement('div')
  document.body.append(host)
  app.use(pinia)
  app.use(plugins.vue)
  app.mount(host)
  windows.push({ app, pinia })

  return { pinia, runtime: runtime as SyncedRuntime }
}

describe('tamagotchiMcpToolsStore', () => {
  afterEach(() => {
    for (const window of windows.splice(0)) {
      window.app.unmount()
      disposePinia(window.pinia)
    }
    localStorage.clear()
  })

  it('registers MCP guidance while the proxy tools are mounted', async () => {
    const leader = openWindow('leader-only')
    await vi.waitFor(() => expect(leader.runtime.isLeader()).toBe(true))
    setActivePinia(leader.pinia)

    const prompts = useLlmToolsetPromptsStore()
    const llmTools = useLlmToolsStore()
    const mcpTools = useTamagotchiMcpToolsStore()

    expect(prompts.activeToolsetPrompt).toBe('')

    await mcpTools.refresh()
    await nextTick()

    expect(llmTools.tools.map(tool => tool.id)).toEqual(expect.arrayContaining([
      'mcp:builtIn_mcpListTools',
      'mcp:builtIn_mcpCallTool',
    ]))
    expect(prompts.activeToolsetPrompt).toContain('builtIn_mcpListTools')
    expect(prompts.activeToolsetPrompt).toContain('web search')

    mcpTools.dispose()
    await vi.waitFor(() => expect(llmTools.tools.map(tool => tool.id)).toEqual([]))
    await vi.waitFor(() => expect(prompts.activeToolsetPrompt).toBe(''))
  })
})
