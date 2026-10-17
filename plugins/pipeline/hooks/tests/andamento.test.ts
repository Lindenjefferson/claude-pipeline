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
const OTHER = { ...STATUS, slug: 'etapa-6', ledger: '/other/.superpowers/ledger.jsonl', dispatched: {} }
const BAND = {
  plugin: 'pipeline', component: 'AbovePrompt', requestId: 'band', surface: 'terminal',
  viewport: { columns: 140, rows: 40 },
  props: { hasSurvey: false, isWorking: false, maxRows: 6, bodyColumns: 140, scroll: { offset: 0, bodyRows: 6 }, view: {} },
} as const
const PANE = {
  ...BAND, component: 'Pane', requestId: 'andamento',
  props: { title: 'Andamento', isFocused: true, bodyColumns: 100, placement: 'inline', scroll: { offset: 0, bodyRows: 20 },
           view: {} },
} as const

// found: the status ledger.py prints (null: no delivery; a string: its stderr on failure)
function stubs(on, found, log = { runs: 0, mtime: 1 }) {
  const clock = mock.clock(on, { now: NOW })
  on('session.start', () => ({ cwd: '/work' }))
  on('session.cwd', () => ({ value: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('fs.stat', () => ({ value: { kind: 'file', size: 10, mtimeMs: log.mtime, isLink: false } }))
  on('process.run', ($, e) => {
    if (e.argv[0] === 'git') return { value: { exitCode: 0, stdout: 'worktree /work\nworktree /other\n', stderr: '' } }
    log.runs += 1
    if (e.argv.includes('/other/.superpowers/ledger.jsonl')) {
      return { value: { exitCode: 0, stdout: JSON.stringify(OTHER), stderr: '' } }
    }
    if (typeof found === 'string') return { value: { exitCode: 1, stdout: '', stderr: found } }
    return { value: found ? { exitCode: 0, stdout: JSON.stringify(found), stderr: '' }
                          : { exitCode: 1, stdout: '', stderr: 'no delivery started' } }
  })
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
  return clock
}

async function start($, clock) {
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await clock.settle()
}

test('the band says the cycle, what runs and for how long, the verdicts, VALIDAR and what comes next', () => {
  expect(bandLine(STATUS, NOW)).toBe('pipeline · etapa-5 · cycle 2 · autonomous · ▶ T2.1 14m · reviewer FAIL · qa — · ' +
                                     'VALIDAR 1 · next: reviewer FAIL (2 open): dev fixes every finding in one batch')
})

test('the band leaves out the pending line of a task it already shows running, and says when the gate is next', () => {
  const running = { ...STATUS, pending: STATUS.pending.slice(1) }
  expect(bandLine(running, NOW)).not.toContain('next:')
  const ready = { ...STATUS, dispatched: {}, pending: [], ready_for_gate: true }
  expect(bandLine(ready, NOW)).toMatch(/ · ready for gate$/)
})

test('the pane lists the cycle runs with time and tokens, the running task, VALIDAR, earlier cycles and fronts', () => {
  const lines = paneLines(STATUS, [{ name: 'other', report: OTHER }], NOW)
  expect(lines[0]).toBe('etapa-5 · cycle 2 · autonomous')
  expect(lines).toContain('dev            T2.2       DONE                 3m       98357')
  expect(lines).toContain('reviewer       -          FAIL (2 open)        1m       -')
  expect(lines).toContain('dev            T2.1       running              14m      -')
  expect(lines).toContain('- V1 page size 50')
  expect(lines.join('\n')).not.toContain('sort by date')
  expect(lines).toContain('- cycle 1: 0 Critical, 1 Important, 2 Minor; 1 fix round; 1h0m agent time')
  expect(lines).toContain('- other: etapa-6 · cycle 2 · 0 running · 2 pending')
})

test('an old ledger without VALIDAR ids, runs or tokens still draws', () => {
  const old = { ...STATUS, validar: ['page size 50'], runs: undefined, dispatched: undefined, metrics: {} }
  expect(bandLine(old, NOW)).toContain('pipeline · etapa-5 · cycle 2')
  expect(paneLines(old, [], NOW)[0]).toBe('etapa-5 · cycle 2 · autonomous')
})

test('with a delivery open, the band is drawn above the prompt and keeps what other mods draw there', async ($, on) => {
  const clock = stubs(on, STATUS)
  await start($, clock)
  const ui = await $.ui.mount(BAND)
  expect(await ui.find({ type: 'Text', text: /^pipeline · etapa-5 · cycle 2/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'drawn by Claude Code' })).toBeDefined()
  await ui.unmount()
})

test('while a survey holds the band, the mod yields it', async ($, on) => {
  const clock = stubs(on, STATUS)
  await start($, clock)
  const ui = await $.ui.mount({ ...BAND, props: { ...BAND.props, hasSurvey: true } })
  expect(await ui.find({ type: 'Text', text: /pipeline/ })).toBeUndefined()
  await ui.unmount()
})

test('with no delivery, the band is left to Claude Code', async ($, on) => {
  const clock = stubs(on, null)
  await start($, clock)
  const ui = await $.ui.mount(BAND)
  expect(await ui.find({ type: 'Text', text: /pipeline/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: 'drawn by Claude Code' })).toBeDefined()
  await ui.unmount()
})

test('a ledger.py failure shows in the band and in /andamento, not as "no delivery"', async ($, on) => {
  const clock = stubs(on, 'x.jsonl:3: not a ledger entry (bad); fix or remove that line by hand')
  on('ui.open', () => ({ deny: 'no pane here' }))
  await start($, clock)
  const ui = await $.ui.mount(BAND)
  expect(await ui.find({ type: 'Text', text: /^pipeline · ledger\.py failed: x\.jsonl:3/ })).toBeDefined()
  await ui.unmount()
  const answer = await $.command.run({ command: 'andamento', args: '' })
  expect(answer.text).toContain('ledger.py failed: x.jsonl:3')
})

test('the poll runs ledger.py again only when the ledger file changes, or after a minute', async ($, on) => {
  const log = { runs: 0, mtime: 1 }
  const clock = stubs(on, STATUS, log)
  await start($, clock)
  expect(log.runs).toBe(1)
  await clock.advance(15000)
  expect(log.runs).toBe(1)
  log.mtime = 2
  await clock.advance(5000)
  expect(log.runs).toBe(2)
  await clock.advance(60000)
  expect(log.runs).toBe(3)
})

test('/andamento answers in text where no pane can open, listing the other fronts but not its own', async ($, on) => {
  const clock = stubs(on, STATUS)
  on('ui.open', () => ({ deny: 'no pane here' }))
  await start($, clock)
  const answer = await $.command.run({ command: 'andamento', args: '' })
  expect(answer.text).toContain('etapa-5 · cycle 2 · autonomous')
  expect(answer.text).toContain('Earlier cycles:')
  expect(answer.text).toContain('- other: etapa-6')
  expect(answer.text).not.toContain('- work:')
})

test('/andamento opens the pane and the pane draws the same table', async ($, on) => {
  const clock = stubs(on, STATUS)
  on('ui.open', () => ({ value: { isPlaced: true } }))
  await start($, clock)
  const answer = await $.command.run({ command: 'andamento', args: '' })
  expect(answer).toEqual({})
  const ui = await $.ui.mount(PANE)
  expect(await ui.find({ type: 'Text', text: 'etapa-5 · cycle 2 · autonomous' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /T2\.1\s+running/ })).toBeDefined()
  await ui.unmount()
})
