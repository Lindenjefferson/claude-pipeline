import { expect, mock, test } from 'claude-code/testing'
import { bandLine, paneLines } from '../andamento.js'

const DISPATCHED = '2026-10-17T17:32:48+00:00'
const NOW = Date.parse(DISPATCHED) + 14 * 60000
const STATUS = {
  slug: 'etapa-5', base: 'f293a86', ledger: '/work/.superpowers/ledger.jsonl', cycle: 2, autonomous: true,
  in_flight: ['T2.1'], dispatched: { 'T2.1': DISPATCHED },
  tasks: { 'T2.2': 'DONE' },
  runs: [
    { agent: 'dev', task: 'T2.2', verdict: 'DONE', open: 0, seconds: 180, tokens: 98357 },
    { agent: 'reviewer', task: '', verdict: 'FAIL', open: 2, seconds: 61 },
  ],
  reviewer: [{ agent: 'reviewer', verdict: 'FAIL', open: 2 }], qa: [],
  pending: ['reviewer FAIL (2 open): dev fixes every finding in one batch',
            'dev T2.1 dispatched at 2026-10-17T17:32:48+00:00, no report yet (add it when it reports, or release --task T2.1)'],
  validar: [{ id: 'V1', text: 'page size 50', decision: null }, { id: 'V2', text: 'sort by date', decision: 'ok' }],
  deferred: [], notes: [], ready_for_gate: false,
  metrics: { cycles: [{ cycle: 1, critical: 0, important: 1, minor: 2, open: 1, fix_rounds: 1, seconds: 3600, tokens: 0 },
                      { cycle: 2, critical: 0, important: 2, minor: 0, open: 2, fix_rounds: 0, seconds: 241, tokens: 98357 }] },
}
const BAND = {
  plugin: 'pipeline', component: 'AbovePrompt', requestId: 'band', surface: 'terminal',
  viewport: { columns: 140, rows: 40 },
  props: { hasSurvey: false, isWorking: false, maxRows: 6, bodyColumns: 140, scroll: { offset: 0, bodyRows: 6 }, view: {} },
} as const

function stubs(on, found) {
  mock.clock(on, { now: NOW })
  on('session.start', () => ({ cwd: '/work' }))
  on('session.cwd', () => ({ value: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('fs.stat', () => ({ value: { kind: 'file', size: 10, mtimeMs: 1, isLink: false } }))
  on('process.run', ($, e) => ({
    value: e.argv[0] === 'git' ? { exitCode: 0, stdout: 'worktree /work\n', stderr: '' }
      : found ? { exitCode: 0, stdout: JSON.stringify(found), stderr: '' }
      : { exitCode: 1, stdout: '', stderr: 'no delivery started' },
  }))
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
}

test('the band says the cycle, what runs and for how long, the verdicts, VALIDAR and what comes next', () => {
  const line = bandLine(STATUS, NOW)
  expect(line).toBe('pipeline · etapa-5 · cycle 2 · autonomous · ▶ T2.1 14m · reviewer FAIL · qa — · VALIDAR 1 · ' +
                    'next: reviewer FAIL (2 open): dev fixes every finding in one batch')
})

test('the pane lists the cycle runs with time and tokens, the running task, VALIDAR, earlier cycles and fronts', () => {
  const lines = paneLines(STATUS, [{ name: 'front-b', report: { ...STATUS, slug: 'etapa-6', dispatched: {} } }], NOW)
  expect(lines[0]).toBe('etapa-5 · cycle 2 · autonomous')
  expect(lines).toContain('dev            T2.2       DONE                 3m       98357')
  expect(lines).toContain('reviewer       -          FAIL (2 open)        1m       -')
  expect(lines).toContain('dev            T2.1       running              14m      -')
  expect(lines).toContain('- V1 page size 50')
  expect(lines.join('\n')).not.toContain('sort by date')
  expect(lines).toContain('- cycle 1: 0 Critical, 1 Important, 2 Minor; 1 fix round; 1h0m agent time')
  expect(lines).toContain('- front-b: etapa-6 · cycle 2 · 0 running · 2 pending')
})

test('an old ledger without VALIDAR ids, runs or tokens still draws', () => {
  const old = { ...STATUS, validar: ['page size 50'], runs: undefined, dispatched: undefined, metrics: {} }
  expect(bandLine(old, NOW)).toContain('pipeline · etapa-5 · cycle 2')
  expect(paneLines(old, [], NOW)[0]).toBe('etapa-5 · cycle 2 · autonomous')
})

test('with a delivery open, the band is drawn above the prompt', async ($, on) => {
  stubs(on, STATUS)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  const ui = await $.ui.mount(BAND)
  expect(await ui.find({ type: 'Text', text: /^pipeline · etapa-5 · cycle 2/ })).toBeDefined()
  await ui.unmount()
})

test('with no delivery, the band is left to Claude Code', async ($, on) => {
  stubs(on, null)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  const ui = await $.ui.mount(BAND)
  expect(await ui.find({ type: 'Text', text: /pipeline/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: 'drawn by Claude Code' })).toBeDefined()
  await ui.unmount()
})

test('/andamento answers in text where no pane can open', async ($, on) => {
  stubs(on, STATUS)
  on('ui.open', () => ({ deny: 'no pane here' }))
  const answer = await $.command.run({ command: 'andamento', args: '' })
  expect(answer.text).toContain('etapa-5 · cycle 2 · autonomous')
  expect(answer.text).toContain('Earlier cycles:')
})

test('/andamento opens the pane and the pane draws the same table', async ($, on) => {
  stubs(on, STATUS)
  on('ui.open', () => ({ value: { isPlaced: true } }))
  const answer = await $.command.run({ command: 'andamento', args: '' })
  expect(answer).toEqual({})
  const ui = await $.ui.mount({ ...BAND, component: 'Pane', requestId: 'andamento',
                                props: { title: 'Andamento', isFocused: true, bodyColumns: 100, placement: 'inline',
                                         scroll: { offset: 0, bodyRows: 20 }, view: {} } })
  expect(await ui.find({ type: 'Text', text: 'etapa-5 · cycle 2 · autonomous' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /T2\.1\s+running/ })).toBeDefined()
  await ui.unmount()
})
