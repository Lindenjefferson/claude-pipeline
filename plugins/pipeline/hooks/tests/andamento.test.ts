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
  steps: [{ step: 'fix', agent: 'reviewer', open: 2 }],
  scope: { cycles: [{ cycle: '1', tasks: ['T1.1'], left: [] }, { cycle: '2', tasks: ['T2.1', 'T2.2'], left: ['T2.1'] },
                    { cycle: 'R', tasks: ['TR.1', 'TR.2'], left: ['TR.1', 'TR.2'] }],
           current: '2', position: 2, total: 3, tasks_left: 3, cycles_left: 2 },
  validar: [{ id: 'V1', text: 'page size 50', decision: null }, { id: 'V2', text: 'sort by date', decision: 'ok' }],
  deferred: [], notes: [], ready_for_gate: false,
  metrics: { cycles: [{ cycle: 1, critical: 0, important: 1, minor: 2, open: 1, fix_rounds: 1, seconds: 3600, tokens: 0 },
                      { cycle: 2, critical: 0, important: 2, minor: 0, open: 2, fix_rounds: 0, seconds: 241, tokens: 98357 }] },
}
const OTHER = { ...STATUS, slug: 'etapa-6', ledger: '/other/.superpowers/ledger.jsonl', dispatched: {}, scope: null }
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

// found: the status ledger.py prints (null: no delivery; a string: its stderr on failure); pythons: the interpreter
// names that are Python 3 on PATH (another name answers like the Windows store alias)
function stubs(on, found, log = { runs: 0, mtime: 1 }, pythons = ['python']) {
  const clock = mock.clock(on, { now: NOW })
  on('session.start', () => ({ cwd: '/work' }))
  on('session.cwd', () => ({ value: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('fs.stat', () => ({ value: { kind: 'file', size: 10, mtimeMs: log.mtime, isLink: false } }))
  on('process.run', ($, e) => {
    if (e.argv[0] === 'git') return { value: { exitCode: 0, stdout: 'worktree /work\nworktree /other\n', stderr: '' } }
    if (!pythons.includes(e.argv[0])) return { value: { exitCode: 49, stdout: '', stderr: 'Python was not found' } }
    if (e.argv[1] === '-c') return { value: { exitCode: 0, stdout: '', stderr: '' } }
    log.runs += 1
    log.python = e.argv[0]
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

test('the band says, in Portuguese, the plan cycle, what runs, what comes next, what is left and VALIDAR', () => {
  expect(bandLine(STATUS, NOW)).toBe('etapa 5 · ciclo 2 de 3 · autônomo · dev na T2.1 há 14 min · ' +
                                     'depois: correção (2 achados da revisão) · faltam 3 tarefas em 2 ciclos · ' +
                                     '1 decisão espera você')
})

test('the band names a cycle by its plan name, shows a verdict only when no step covers it, and joins the steps', () => {
  const review = { ...STATUS, dispatched: {}, validar: [],
                   scope: { ...STATUS.scope, current: 'R', position: 3, tasks_left: 1, cycles_left: 1 },
                   reviewer: [{ agent: 'reviewer', verdict: 'PASS', open: 0 }],
                   steps: [{ step: 'qa' }, { step: 'decide', id: 'D1', text: 'x' }, { step: 'decide', id: 'D4', text: 'y' }] }
  expect(bandLine(review, NOW)).toBe('etapa 5 · ciclo R (3 de 3) · autônomo · revisão ok · depois: qa e decidir D1 e D4 · ' +
                                     'falta 1 tarefa em 1 ciclo')
  const rerun = { ...review, reviewer: [{ agent: 'reviewer', verdict: 'FAIL', open: 1 }],
                  steps: [{ step: 'reviewer' }, { step: 'qa', rerun: true }] }
  expect(bandLine(rerun, NOW)).toContain('depois: revisão e qa de novo nos cenários da correção')
  expect(bandLine(rerun, NOW)).not.toContain('reprovou')
  const failed = { ...review, qa: [{ agent: 'qa', verdict: 'FAIL', open: 3 }], steps: [{ step: 'reviewer' }] }
  expect(bandLine(failed, NOW)).toContain('qa reprovou (3 abertos) · depois: revisão')
})

test('the band says when the gate is next, and with no scope shows the ledger cycle', () => {
  const ready = { ...STATUS, dispatched: {}, steps: [], pending: [], ready_for_gate: true, scope: null, validar: [],
                  reviewer: [], qa: [] }
  expect(bandLine(ready, NOW)).toBe('etapa 5 · ciclo 2 · autônomo · pronto para o gate')
  const running = { ...STATUS, steps: [], scope: null, validar: [], autonomous: false, reviewer: [],
                    dispatched: { 'T2.1': DISPATCHED, 'T2.3': '2026-10-17T16:32:48+00:00' } }
  expect(bandLine(running, NOW)).toBe('etapa 5 · ciclo 2 · dev na T2.1 há 14 min e na T2.3 há 1h14')
})

test('the pane lists what is left per cycle, the cycle runs, what comes next, VALIDAR, earlier cycles and fronts', () => {
  const lines = paneLines(STATUS, [{ name: 'other', report: OTHER }], NOW)
  expect(lines[0]).toBe('etapa 5 · ciclo 2 de 3 · autônomo')
  expect(lines).toContain('Faltam 3 tarefas em 2 ciclos:')
  expect(lines).toContain('- ciclo 2: T2.1')
  expect(lines).toContain('- ciclo R: TR.1, TR.2')
  expect(lines).toContain('Agente         Tarefa     Veredito             Tempo    Tokens')
  expect(lines).toContain('dev            T2.2       DONE                 3 min    98.357')
  expect(lines).toContain('reviewer       -          FAIL (2 abertos)     1 min    -')
  expect(lines).toContain('dev            T2.1       rodando              14 min   -')
  expect(lines).toContain('Depois:')
  expect(lines).toContain('- correção (2 achados da revisão)')
  expect(lines).toContain('Decisões que esperam você (VALIDAR):')
  expect(lines).toContain('- V1 page size 50')
  expect(lines.join('\n')).not.toContain('sort by date')
  expect(lines).toContain('- ciclo 1: 0 Critical, 1 Important, 2 Minor; 1 rodada de correção; 1h00 de agente')
  expect(lines).toContain('Outras frentes:')
  expect(lines).toContain('- other: etapa 6 · ciclo 2 · 0 rodando · 1 pendente')
})

test('the pane spells out each kind of step', () => {
  const stuck = { ...STATUS, steps: [{ step: 'stop', agent: 'qa', rounds: 3 }, { step: 'decide', id: 'D2', text: 'export later' }] }
  const lines = paneLines(stuck, [], NOW)
  expect(lines).toContain('- parar e registrar como VALIDAR (qa ainda reprova depois de 3 rodadas)')
  expect(lines).toContain('- decidir D2: export later')
  const asked = { ...STATUS, autonomous: false,
                  steps: [{ step: 'ask', agent: 'reviewer' }, { step: 'dev', task: 'T2.1', verdict: 'BLOCKED' }] }
  expect(paneLines(asked, [], NOW)).toContain('- falar com você (revisão ainda reprova depois da correção)')
  expect(paneLines(asked, [], NOW)).toContain('- dev na T2.1 (voltou BLOCKED)')
  expect(paneLines({ ...STATUS, steps: [{ step: 'dev' }] }, [], NOW)).toContain('- primeira tarefa do dev')
  const loop = { ...STATUS, steps: [{ step: 'review', task: 'plan', round: 2, open: 3, report: '/w/r.md' },
                                     { step: 'ask', task: 'spec', rounds: 3 }, { step: 'stop', task: 'plan', rounds: 4 }] }
  expect(paneLines(loop, [], NOW)).toContain('- revisão do plano, rodada 2 (3 achados abertos)')
  expect(paneLines(loop, [], NOW)).toContain('- falar com você (revisão da spec ainda reprova depois de 3 rodadas)')
  expect(paneLines(loop, [], NOW)).toContain('- parar e registrar como VALIDAR (revisão do plano ainda reprova depois de 4 rodadas)')
  const ready = { ...STATUS, dispatched: {}, steps: [], ready_for_gate: true }
  expect(paneLines(ready, [], NOW)).toContain('Pronto para o gate.')
})

test('an old ledger without VALIDAR ids, runs, tokens, steps or scope still draws', () => {
  const old = { ...STATUS, validar: ['page size 50'], runs: undefined, dispatched: undefined, metrics: {},
                steps: undefined, scope: undefined, reviewer: [] }
  expect(bandLine(old, NOW)).toBe('etapa 5 · ciclo 2 · autônomo')
  expect(paneLines(old, [], NOW)[0]).toBe('etapa 5 · ciclo 2 · autônomo')
})

test('a paused delivery says so in the title and spells out the resume step', () => {
  const text = 'rerun the gate after the API key is set'
  const paused = { ...STATUS, dispatched: {}, scope: null, validar: [], reviewer: [], paused: { text, at: DISPATCHED },
                   steps: [{ step: 'resume', text, at: DISPATCHED }] }
  expect(bandLine(paused, NOW)).toBe(`etapa 5 · ciclo 2 · autônomo · pausada · depois: retomar a entrega (pausada: ${text})`)
  expect(paneLines(paused, [], NOW)[0]).toBe('etapa 5 · ciclo 2 · autônomo · pausada')
  expect(paneLines(paused, [], NOW)).toContain(`- retomar a entrega (pausada: ${text})`)
  expect(bandLine({ ...paused, paused: null, steps: [] }, NOW)).toBe('etapa 5 · ciclo 2 · autônomo')
})

test('with a delivery open, the band is drawn above the prompt and keeps what other mods draw there', async ($, on) => {
  const clock = stubs(on, STATUS)
  await start($, clock)
  const ui = await $.ui.mount(BAND)
  expect(await ui.find({ type: 'Text', text: /^etapa 5 · ciclo 2 de 3/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'drawn by Claude Code' })).toBeDefined()
  await ui.unmount()
})

test('while a survey holds the band, the mod yields it', async ($, on) => {
  const clock = stubs(on, STATUS)
  await start($, clock)
  const ui = await $.ui.mount({ ...BAND, props: { ...BAND.props, hasSurvey: true } })
  expect(await ui.find({ type: 'Text', text: /ciclo/ })).toBeUndefined()
  await ui.unmount()
})

test('with no delivery, the band is left to Claude Code', async ($, on) => {
  const clock = stubs(on, null)
  await start($, clock)
  const ui = await $.ui.mount(BAND)
  expect(await ui.find({ type: 'Text', text: /ciclo|pipeline/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: 'drawn by Claude Code' })).toBeDefined()
  await ui.unmount()
})

test('a ledger.py failure shows in the band and in /andamento, not as "no delivery"', async ($, on) => {
  const clock = stubs(on, 'x.jsonl:3: not a ledger entry (bad); fix or remove that line by hand')
  on('ui.open', () => ({ deny: 'no pane here' }))
  await start($, clock)
  const ui = await $.ui.mount(BAND)
  expect(await ui.find({ type: 'Text', text: /^pipeline · ledger\.py falhou: x\.jsonl:3/ })).toBeDefined()
  await ui.unmount()
  const answer = await $.command.run({ command: 'andamento', args: '' })
  expect(answer.text).toContain('ledger.py falhou: x.jsonl:3')
})

test('with only python3 on PATH, as on Linux, ledger.py runs with python3', async ($, on) => {
  const log = { runs: 0, mtime: 1 }
  const clock = stubs(on, STATUS, log, ['python3'])
  await start($, clock)
  expect(log.python).toBe('python3')
  const ui = await $.ui.mount(BAND)
  expect(await ui.find({ type: 'Text', text: /^etapa 5 · ciclo 2 de 3/ })).toBeDefined()
  await ui.unmount()
})

test('with no Python 3 on PATH, the band says so instead of passing for "no delivery"', async ($, on) => {
  const clock = stubs(on, STATUS, { runs: 0, mtime: 1 }, [])
  await start($, clock)
  const ui = await $.ui.mount(BAND)
  expect(await ui.find({ type: 'Text', text: /^pipeline · ledger\.py falhou: no Python 3 on PATH \(tried python, python3\)/ }))
    .toBeDefined()
  await ui.unmount()
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
  expect(answer.text).toContain('etapa 5 · ciclo 2 de 3 · autônomo')
  expect(answer.text).toContain('Ciclos anteriores:')
  expect(answer.text).toContain('- other: etapa 6')
  expect(answer.text).not.toContain('- work:')
})

test('/andamento opens the pane and the pane draws the same table', async ($, on) => {
  const clock = stubs(on, STATUS)
  on('ui.open', () => ({ value: { isPlaced: true } }))
  await start($, clock)
  const answer = await $.command.run({ command: 'andamento', args: '' })
  expect(answer).toEqual({})
  const ui = await $.ui.mount(PANE)
  expect(await ui.find({ type: 'Text', text: 'etapa 5 · ciclo 2 de 3 · autônomo' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /T2\.1\s+rodando/ })).toBeDefined()
  await ui.unmount()
})
