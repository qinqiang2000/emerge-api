import { beforeEach, describe, expect, it, vi } from 'vitest'

import { _testUtils, useChat } from '../../src/stores/chat'
import { useSchema } from '../../src/stores/schema'
import { useDocs } from '../../src/stores/docs'
import { useProjects } from '../../src/stores/projects'
import { useEval } from '../../src/stores/eval'
import { usePrompts } from '../../src/stores/prompts'
import { useModels } from '../../src/stores/models'

beforeEach(() => {
  useChat.setState({ events: [], busy: false, loadedProjectId: null })
  useSchema.getState().reset()
  usePrompts.getState().reset()
  useModels.getState().reset()
  // Silence post-invalidate background load() fetches that fire in jsdom (no base URL).
  // Fresh Response per call so .json() doesn't hit "Body already read" on parallel reads.
  vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response('[]', { status: 200 }))))
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

  it('refreshes useEval when score completes', () => {
    const refresh = vi.spyOn(useEval.getState(), 'refresh').mockResolvedValue(null)
    useChat.setState({ events: [{
      type: 'tool_call', tool_use_id: 't6', tool_name: 'mcp__emerge_tools__score',
      tool_input: {}, tool_result: null, ok: true,
    }]})
    _testUtils.handleToolResult(
      { tool_use_id: 't6', result_text: '{"macro_f1":0.97,"per_field":[],"n_docs":5,"n_reviewed":5,"errors":[],"ts":"2026-05-11T07-04-00Z","schema_field_count":1}', ok: true },
      'p_a', null,
    )
    expect(refresh).toHaveBeenCalledWith('p_a')
    refresh.mockRestore()
  })

  it.each([
    'mcp__emerge_tools__write_prompt',
    'mcp__emerge_tools__create_prompt',
    'mcp__emerge_tools__switch_active_prompt',
    'mcp__emerge_tools__delete_prompt',
  ])('invalidates usePrompts (and useSchema) when %s completes', (toolName) => {
    useChat.setState({ events: [{
      type: 'tool_call', tool_use_id: 'tp', tool_name: toolName,
      tool_input: {}, tool_result: null, ok: true,
    }]})
    usePrompts.setState({
      list: { p_a: [{ prompt_id: 'pr_baseline', label: 'B', derived_from: null, is_active: true, created_at: 'x', updated_at: 'x' }] },
      activeByProject: { p_a: { prompt_id: 'pr_baseline', label: 'B', schema: [], global_notes: '', derived_from: null, created_at: 'x', updated_at: 'x' } as any },
      loading: {},
    })
    useSchema.setState({ byProject: { p_a: [{ name: 'x', type: 'string', description: '' }] } })
    _testUtils.handleToolResult({ tool_use_id: 'tp', result_text: 'ok', ok: true }, 'p_a', null)
    expect(usePrompts.getState().list['p_a']).toBeUndefined()
    expect(useSchema.getState().byProject['p_a']).toBeUndefined()
  })

  it.each([
    'mcp__emerge_tools__write_model',
    'mcp__emerge_tools__create_model',
    'mcp__emerge_tools__switch_active_model',
    'mcp__emerge_tools__delete_model',
  ])('invalidates useModels when %s completes', (toolName) => {
    useChat.setState({ events: [{
      type: 'tool_call', tool_use_id: 'tm', tool_name: toolName,
      tool_input: {}, tool_result: null, ok: true,
    }]})
    useModels.setState({
      list: { p_a: [{ model_id: 'm_default', label: 'D', provider: 'google', provider_model_id: 'gemini-2.5-flash', is_active: true, created_at: 'x' }] },
      activeByProject: { p_a: { model_id: 'm_default', label: 'D', provider: 'google', provider_model_id: 'gemini-2.5-flash', params: {}, created_at: 'x' } as any },
      loading: {},
    })
    _testUtils.handleToolResult({ tool_use_id: 'tm', result_text: 'ok', ok: true }, 'p_a', null)
    expect(useModels.getState().list['p_a']).toBeUndefined()
  })

  it('does not refresh useEval when score fails', () => {
    const refresh = vi.spyOn(useEval.getState(), 'refresh').mockResolvedValue(null)
    useChat.setState({ events: [{
      type: 'tool_call', tool_use_id: 't7', tool_name: 'mcp__emerge_tools__score',
      tool_input: {}, tool_result: null, ok: false,
    }]})
    _testUtils.handleToolResult(
      { tool_use_id: 't7', result_text: 'err', ok: false },
      'p_a', null,
    )
    expect(refresh).not.toHaveBeenCalled()
    refresh.mockRestore()
  })
})
