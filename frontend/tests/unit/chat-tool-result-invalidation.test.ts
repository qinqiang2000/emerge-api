import { beforeEach, describe, expect, it, vi } from 'vitest'

import { _testUtils, useChat } from '../../src/stores/chat'
import { useSchema } from '../../src/stores/schema'
import { useDocs } from '../../src/stores/docs'
import { useProjects } from '../../src/stores/projects'

beforeEach(() => {
  useChat.getState().reset()
  useSchema.getState().reset()
})

describe('handleToolResult side effects', () => {
  it('invalidates useSchema when write_schema completes', () => {
    useChat.setState({ events: [{
      type: 'tool_call', tool_use_id: 't1', tool_name: 'mcp__emerge_tools__write_schema',
      tool_input: {}, tool_result: null, ok: true,
    }]})
    useSchema.setState({ byProject: { p_a: [{ name: 'x', type: 'string', description: '' }] } })
    _testUtils.handleToolResult({ tool_use_id: 't1', result_text: '{"ok":true}', ok: true }, 'p_a', null)
    expect(useSchema.getState().byProject['p_a']).toBeUndefined()
  })

  it('refreshes useDocs when upload_doc completes', () => {
    const refresh = vi.spyOn(useDocs.getState(), 'refresh').mockResolvedValue()
    useChat.setState({ events: [{
      type: 'tool_call', tool_use_id: 't2', tool_name: 'mcp__emerge_tools__upload_doc',
      tool_input: {}, tool_result: null, ok: true,
    }]})
    _testUtils.handleToolResult({ tool_use_id: 't2', result_text: '{"doc_id":"d_x"}', ok: true }, 'p_a', null)
    expect(refresh).toHaveBeenCalledWith('p_a')
    refresh.mockRestore()
  })

  it('refreshes useDocs when extract_batch completes (PENDING → DRAFT)', () => {
    const refresh = vi.spyOn(useDocs.getState(), 'refresh').mockResolvedValue()
    useChat.setState({ events: [{
      type: 'tool_call', tool_use_id: 't3', tool_name: 'mcp__emerge_tools__extract_batch',
      tool_input: {}, tool_result: null, ok: true,
    }]})
    _testUtils.handleToolResult({ tool_use_id: 't3', result_text: '{"ok_count":1}', ok: true }, 'p_a', null)
    expect(refresh).toHaveBeenCalledWith('p_a')
    refresh.mockRestore()
  })

  it('refreshes useDocs when extract_one completes', () => {
    const refresh = vi.spyOn(useDocs.getState(), 'refresh').mockResolvedValue()
    useChat.setState({ events: [{
      type: 'tool_call', tool_use_id: 't4', tool_name: 'mcp__emerge_tools__extract_one',
      tool_input: {}, tool_result: null, ok: true,
    }]})
    _testUtils.handleToolResult({ tool_use_id: 't4', result_text: '{"ok":true}', ok: true }, 'p_a', null)
    expect(refresh).toHaveBeenCalledWith('p_a')
    refresh.mockRestore()
  })

  it('refreshes useProjects when freeze_version completes (sidebar ▲vN bump)', () => {
    const refresh = vi.spyOn(useProjects.getState(), 'refresh').mockResolvedValue()
    useChat.setState({ events: [{
      type: 'tool_call', tool_use_id: 't5', tool_name: 'mcp__emerge_tools__freeze_version',
      tool_input: {}, tool_result: null, ok: true,
    }]})
    _testUtils.handleToolResult({ tool_use_id: 't5', result_text: '{"version_id":"v3"}', ok: true }, 'p_a', null)
    expect(refresh).toHaveBeenCalled()
    refresh.mockRestore()
  })
})
