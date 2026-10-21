import { expect, mock, test } from 'claude-code/testing'
import { bandRows, paneLines, rowText } from '../andamento.js'

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
// the band's rows as the user reads them
const shown = (r) => bandRows(r, NOW).map(rowText)
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
  // the subscription's rate-limit windows ([] on an API key) and every usage.json written
  log.writes ??= []
  on('session.usage', () => ({ value: { context: {}, rateLimits: log.rateLimits ?? [] } }))
  on('session.measure', (_$, e) => ({ changed: e.changed }))
  on('fs.write', (_$, e) => {
    if (log.writeFails) throw new Error('disk full')
    log.writes.push({ path: e.path, data: JSON.parse(e.text) })
    return { value: undefined }
  })
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
  return clock
}

const MEASURE = { context: {}, rateLimits: [], changed: ['rateLimits'] } as const
const FIVE = { kind: 'five_hour', percentUsed: 82.5, resetsAt: '2026-10-17T20:00:00Z' }
const WEEK = { kind: 'seven_day', percentUsed: 41, resetsAt: '2026-10-20T12:00:00.000Z' }
const WINDOWS = { five_hour: { percent: 82.5, resets_at: '2026-10-17T20:00:00.000Z' },
                  seven_day: { percent: 41, resets_at: '2026-10-20T12:00:00.000Z' } }
// a reset at this local time, as the ISO string ledger.py reads and the band says back in local time
const LOCAL = new Date(2026, 9, 17, 21, 5)
const USAGE = { windows: { five_hour: { percent: 85, resets_at: LOCAL.toISOString() },
                           seven_day: { percent: 41, resets_at: '2026-10-20T12:00:00+00:00' } },
                economy: null, wait: null }

async function start($, clock) {
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await clock.settle()
}

test('the band says where the delivery is, what runs and comes next, and what waits for you, one row each', () => {
  expect(shown(STATUS)).toEqual(['etapa 5, ciclo 2 de 3, modo autônomo   faltam 3 tarefas em 2 ciclos',
                                 '● dev na T2.1 há 14 min   depois: correção (2 achados da revisão)',
                                 '1 decisão espera você'])
})

test('the band names a cycle by its plan name, shows a verdict only when no step covers it, and joins the steps', () => {
  const review = { ...STATUS, dispatched: {}, validar: [],
                   scope: { ...STATUS.scope, current: 'R', position: 3, tasks_left: 1, cycles_left: 1 },
                   reviewer: [{ agent: 'reviewer', verdict: 'PASS', open: 0 }],
                   steps: [{ step: 'qa' }, { step: 'decide', id: 'D1', text: 'x' }, { step: 'decide', id: 'D4', text: 'y' }] }
  expect(shown(review)).toEqual(['etapa 5, ciclo R (3º de 3), modo autônomo   falta 1 tarefa em 1 ciclo',
                                 '✓ revisão   depois: qa e decidir D1 e D4'])
  const rerun = { ...review, reviewer: [{ agent: 'reviewer', verdict: 'FAIL', open: 1 }],
                  steps: [{ step: 'reviewer' }, { step: 'qa', rerun: true }] }
  expect(shown(rerun)[1]).toBe('depois: revisão e qa de novo nos cenários da correção')
  const failed = { ...review, qa: [{ agent: 'qa', verdict: 'FAIL', open: 3 }], steps: [{ step: 'reviewer' }] }
  expect(shown(failed)[1]).toBe('✗ qa reprovou, 3 abertos   depois: revisão')
})

test('a plan cycle named "Ciclo 3" is not called "ciclo Ciclo 3", and its position reads as an ordinal', () => {
  const named = { ...STATUS, scope: { ...STATUS.scope, current: 'Ciclo 3', position: 4, total: 4 } }
  expect(shown(named)[0]).toMatch(/^etapa 5, ciclo 3 \(4º de 4\), /)
  const plan = { ...STATUS, scope: { ...STATUS.scope, cycles: [{ cycle: 'Ciclo 3', tasks: ['T3.1'], left: ['T3.1'] }] } }
  expect(paneLines(plan, [], NOW)).toContain('- ciclo 3: T3.1')
  const same = { ...STATUS, scope: { ...STATUS.scope, current: 'ciclo 2' } }
  expect(shown(same)[0]).toMatch(/^etapa 5, ciclo 2 de 3, /)
})

test('the cleanup and fix tasks are named in words', () => {
  const late = { ...STATUS, steps: [], reviewer: [], dispatched: { cleanup: DISPATCHED, 'fix-2': DISPATCHED } }
  expect(shown(late)[1]).toBe('● dev na limpeza há 14 min   ● dev na correção 2 há 14 min')
  const back = { ...STATUS, dispatched: {}, reviewer: [], steps: [{ step: 'dev', task: 'cleanup', verdict: 'BLOCKED' }] }
  expect(shown(back)[1]).toBe('depois: dev na limpeza (voltou BLOCKED)')
})

test('each part of the band carries its tone: running, done, failed, ready, next, and what waits for you', () => {
  const tones = (r) => bandRows(r, NOW).map((row) => row.map((part) => part.tone))
  expect(tones(STATUS)).toEqual([['title', 'quiet'], ['running', 'next'], ['you']])
  const failed = { ...STATUS, dispatched: {}, validar: [], steps: [],
                   reviewer: [{ agent: 'reviewer', verdict: 'PASS', open: 0 }], qa: [{ agent: 'qa', verdict: 'FAIL', open: 1 }] }
  expect(tones(failed)).toEqual([['title', 'quiet'], ['done', 'failed']])
  expect(tones({ ...failed, qa: [], ready_for_gate: true })).toEqual([['title', 'quiet'], ['done', 'ready']])
})

test('the band says when the gate is next, and with no scope shows the ledger cycle', () => {
  const ready = { ...STATUS, dispatched: {}, steps: [], pending: [], ready_for_gate: true, scope: null, validar: [],
                  reviewer: [], qa: [] }
  expect(shown(ready)).toEqual(['etapa 5, ciclo 2, modo autônomo', '✓ pronto para o gate'])
  const running = { ...STATUS, steps: [], scope: null, validar: [], autonomous: false, reviewer: [],
                    dispatched: { 'T2.1': DISPATCHED, 'T2.3': '2026-10-17T16:32:48+00:00' } }
  expect(shown(running)).toEqual(['etapa 5, ciclo 2', '● dev na T2.1 há 14 min   ● dev na T2.3 há 1h14'])
})

test('the pane lists what is left per cycle, the cycle runs, what comes next, VALIDAR, earlier cycles and fronts', () => {
  const lines = paneLines(STATUS, [{ name: 'other', report: OTHER }], NOW)
  expect(lines[0]).toBe('etapa 5, ciclo 2 de 3, modo autônomo')
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
  expect(lines).toContain('- other: etapa 6, ciclo 2: 0 rodando, 1 pendente')
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
  expect(shown(old)).toEqual(['etapa 5, ciclo 2, modo autônomo'])
  expect(paneLines(old, [], NOW)[0]).toBe('etapa 5, ciclo 2, modo autônomo')
})

test('a paused delivery says so in the title and spells out the resume step', () => {
  const text = 'rerun the gate after the API key is set'
  const paused = { ...STATUS, dispatched: {}, scope: null, validar: [], reviewer: [], paused: { text, at: DISPATCHED },
                   steps: [{ step: 'resume', text, at: DISPATCHED }] }
  expect(shown(paused)).toEqual(['etapa 5, ciclo 2, modo autônomo, pausada', `depois: retomar a entrega (pausada: ${text})`])
  expect(paneLines(paused, [], NOW)[0]).toBe('etapa 5, ciclo 2, modo autônomo, pausada')
  expect(paneLines(paused, [], NOW)).toContain(`- retomar a entrega (pausada: ${text})`)
  expect(shown({ ...paused, paused: null, steps: [] })).toEqual(['etapa 5, ciclo 2, modo autônomo'])
})

test('with a delivery open, the band is drawn above the prompt and keeps what other mods draw there', async ($, on) => {
  const clock = stubs(on, STATUS)
  await start($, clock)
  const ui = await $.ui.mount(BAND)
  expect(await ui.find({ type: 'Text', text: /^etapa 5, ciclo 2 de 3/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'drawn by Claude Code' })).toBeDefined()
  await ui.unmount()
})

test('the band rows wrap instead of cutting, only the title dims while Claude works, and VALIDAR is a warning', async ($, on) => {
  const clock = stubs(on, STATUS)
  await start($, clock)
  const ui = await $.ui.mount({ ...BAND, props: { ...BAND.props, isWorking: true } })
  const title = await ui.find({ type: 'Text', text: /^etapa 5, ciclo 2 de 3/ })
  const now = await ui.find({ type: 'Text', text: /^● dev na T2\.1/ })
  const you = await ui.find({ type: 'Text', text: /^1 decisão espera você$/ })
  for (const row of [title, now, you]) expect(row?.props.wrap).toBe('wrap')
  expect(title?.props.dimColor).toBe(true)
  expect(now?.props.dimColor).toBeFalsy()
  expect(you?.props.color).toBe('warning')
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
  expect(await ui.find({ type: 'Text', text: /^pipeline: ledger\.py falhou: x\.jsonl:3/ })).toBeDefined()
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
  expect(await ui.find({ type: 'Text', text: /^etapa 5, ciclo 2 de 3/ })).toBeDefined()
  await ui.unmount()
})

test('with no Python 3 on PATH, the band says so instead of passing for "no delivery"', async ($, on) => {
  const clock = stubs(on, STATUS, { runs: 0, mtime: 1 }, [])
  await start($, clock)
  const ui = await $.ui.mount(BAND)
  expect(await ui.find({ type: 'Text', text: /^pipeline: ledger\.py falhou: no Python 3 on PATH \(tried python, python3\)/ }))
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
  expect(answer.text).toContain('etapa 5, ciclo 2 de 3, modo autônomo')
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
  expect(await ui.find({ type: 'Text', text: 'etapa 5, ciclo 2 de 3, modo autônomo' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /T2\.1\s+rodando/ })).toBeDefined()
  await ui.unmount()
})

test('at start and on each measure the subscription usage goes to usage.json beside the ledger', async ($, on) => {
  const log = { runs: 0, mtime: 1, rateLimits: [FIVE, WEEK], writes: [] }
  const clock = stubs(on, STATUS, log)
  await start($, clock)
  expect(log.writes.length).toBe(1)
  expect(log.writes[0].path.replaceAll('\\', '/')).toMatch(/\/work\/\.superpowers\/usage\.json$/)
  expect(log.writes[0].data.windows).toEqual(WINDOWS)
  expect(new Date(log.writes[0].data.at).toISOString()).toBe(new Date(NOW).toISOString())
  log.rateLimits = [{ ...FIVE, percentUsed: 90 }, WEEK, { kind: 'spend_limit', percentUsed: 12, resetsAt: '2026-11-01T00:00:00Z' }]
  await $.session.measure(MEASURE)
  expect(log.writes.length).toBe(2)
  expect(log.writes[1].data.windows.five_hour.percent).toBe(90)
  expect(log.writes[1].data.windows.spend_limit).toEqual({ percent: 12, resets_at: '2026-11-01T00:00:00.000Z' })
})

test('an API-key session, with no rate-limit windows, writes no usage.json', async ($, on) => {
  const log = { runs: 0, mtime: 1, rateLimits: [], writes: [] }
  const clock = stubs(on, STATUS, log)
  await start($, clock)
  await $.session.measure(MEASURE)
  expect(log.writes).toEqual([])
})

test('usage.json is not rewritten when only its time would change', async ($, on) => {
  const log = { runs: 0, mtime: 1, rateLimits: [FIVE, WEEK], writes: [] }
  const clock = stubs(on, STATUS, log)
  await start($, clock)
  await clock.advance(30000)
  await $.session.measure(MEASURE)
  await $.session.measure(MEASURE)
  expect(log.writes.length).toBe(1)
})

test('a usage.json write failure leaves the band and the next write alone', async ($, on) => {
  const log = { runs: 0, mtime: 1, rateLimits: [FIVE, WEEK], writes: [], writeFails: true }
  const clock = stubs(on, STATUS, log)
  await start($, clock)
  await $.session.measure(MEASURE)
  const ui = await $.ui.mount(BAND)
  expect(await ui.find({ type: 'Text', text: /^etapa 5, ciclo 2 de 3/ })).toBeDefined()
  await ui.unmount()
  log.writeFails = false
  await $.session.measure(MEASURE)
  expect(log.writes.length).toBe(1)
})

test('economy shows in the title, and a wait puts the reset first in "depois", in local time', () => {
  const saving = { ...STATUS, usage: { ...USAGE, economy: 'five_hour at 85%' } }
  expect(shown(saving)[0]).toBe('etapa 5, ciclo 2 de 3, modo autônomo e econômico   faltam 3 tarefas em 2 ciclos')
  expect(paneLines(saving, [], NOW)[0]).toBe('etapa 5, ciclo 2 de 3, modo autônomo e econômico')
  expect(shown({ ...saving, paused: { text: 'x', at: DISPATCHED } }).join('\n')).toContain('modo autônomo e econômico, pausada')
  const five = { ...STATUS, usage: { ...USAGE, wait: { window: 'five_hour', percent: 85, resets_at: LOCAL.toISOString() } } }
  expect(shown(five).join('\n')).toContain(
    'depois: esperar o reset da janela de 5 horas (85%, volta às 21:05) e correção (2 achados da revisão)')
  const week = { ...STATUS, usage: { ...USAGE, wait: { window: 'seven_day', percent: 97, resets_at: LOCAL.toISOString() } } }
  expect(shown(week).join('\n')).toContain('depois: esperar o reset da semana (97%, volta em 17/10 21:05) e correção')
  expect(paneLines(week, [], NOW)).toContain('- esperar o reset da semana (97%, volta em 17/10 21:05)')
  const idle = { ...five, steps: [] }
  expect(shown(idle).join('\n')).toContain('depois: esperar o reset da janela de 5 horas (85%, volta às 21:05)')
})

test('the pane says how much of each window the account used', () => {
  const lines = paneLines({ ...STATUS, usage: { ...USAGE, windows: { ...USAGE.windows, five_hour: { percent: 82.5, resets_at: null } } } }, [], NOW)
  expect(lines).toContain('Uso da conta: 5 h 82%, semana 41%')
})

test('with no usage, or an older ledger without it, the band and the pane are unchanged', () => {
  const plain = shown(STATUS).join('\n')
  expect(shown({ ...STATUS, usage: null }).join('\n')).toBe(plain)
  expect(shown({ ...STATUS, usage: { windows: {}, economy: null, wait: null } }).join('\n')).toBe(plain)
  expect(paneLines({ ...STATUS, usage: null }, [], NOW)).toEqual(paneLines(STATUS, [], NOW))
  expect(paneLines(STATUS, [], NOW).join(' ')).not.toContain('Uso da conta')
})

test('a wait with no reset time says no time instead of printing the epoch', () => {
  const five = { ...STATUS, usage: { ...USAGE, wait: { window: 'five_hour', percent: 90, resets_at: null } } }
  expect(shown(five).join('\n')).toContain('depois: esperar o reset da janela de 5 horas (90%) e correção')
  const week = { ...STATUS, usage: { ...USAGE, wait: { window: 'seven_day', percent: 97.4, resets_at: null } } }
  expect(shown(week).join('\n')).toContain('depois: esperar o reset da semana (97%) e correção')
  expect(paneLines(week, [], NOW)).toContain('- esperar o reset da semana (97%)')
  expect(paneLines(week, [], NOW).join(' ')).not.toContain('1970')
  const odd = { ...STATUS, usage: { ...USAGE, wait: { window: 'five_hour', percent: 90, resets_at: 'not a date' } } }
  expect(shown(odd).join('\n')).toContain('esperar o reset da janela de 5 horas (90%) e correção')
})

test('a wait adds the margin one run is expected to use, when there is one', () => {
  const wait = { window: 'five_hour', percent: 78.6, resets_at: LOCAL.toISOString(), margin: 9 }
  expect(shown({ ...STATUS, usage: { ...USAGE, wait } }).join('\n')).toContain(
    'esperar o reset da janela de 5 horas (78% + 9% por execução, volta às 21:05) e correção')
  expect(paneLines({ ...STATUS, usage: { ...USAGE, wait: { ...wait, window: 'seven_day', margin: 4 } } }, [], NOW)).toContain(
    '- esperar o reset da semana (78% + 4% por execução, volta em 17/10 21:05)')
  expect(shown({ ...STATUS, usage: { ...USAGE, wait: { ...wait, resets_at: null } } }).join('\n')).toContain(
    'esperar o reset da janela de 5 horas (78% + 9% por execução) e correção')
  for (const margin of [0, undefined, null]) {
    expect(shown({ ...STATUS, usage: { ...USAGE, wait: { ...wait, margin } } }).join('\n')).toContain(
      'esperar o reset da janela de 5 horas (78%, volta às 21:05) e correção')
  }
})

test('with only the weekly window, the pane line and the title still draw', () => {
  const only = { ...STATUS, usage: { windows: { seven_day: { percent: 41.9, resets_at: null } }, economy: 'seven_day at 85%', wait: null } }
  expect(paneLines(only, [], NOW)).toContain('Uso da conta: semana 41%')
  expect(paneLines(only, [], NOW)[0]).toBe('etapa 5, ciclo 2 de 3, modo autônomo e econômico')
  expect(shown(only).join('\n')).toContain('modo autônomo e econômico   faltam 3 tarefas em 2 ciclos\n● dev na T2.1')
})

test('a rate limit with no usable reset time is not written to usage.json', async ($, on) => {
  const log = { runs: 0, mtime: 1, rateLimits: [{ kind: 'five_hour', percentUsed: 82.5 }, WEEK], writes: [] }
  const clock = stubs(on, STATUS, log)
  await start($, clock)
  expect(log.writes.length).toBe(1)
  expect(log.writes[0].data.windows).toEqual({ seven_day: WINDOWS.seven_day })
  log.rateLimits = [{ ...FIVE, resetsAt: 'garbage' }, { ...WEEK, resetsAt: null }]
  await $.session.measure(MEASURE)
  expect(log.writes.length).toBe(1)
})

const PAUSED = {
  ...STATUS, dispatched: {}, steps: [{ step: 'resume', text: 'limite de uso' }], validar: [],
  paused: { text: 'limite de uso', at: '2026-10-17T18:00:00+00:00' },
  usage: { ...USAGE, wait: { window: 'five_hour', percent: 90, resets_at: LOCAL.toISOString() } },
}

test('a notification goes out when the delivery starts waiting for you, and not again for the same state', async ($, on) => {
  const log = { runs: 0, mtime: 1, notes: [] as string[] }
  const report = { ...STATUS, dispatched: {}, steps: [], validar: [{ id: 'V1', text: 'page size 50', decision: null }] }
  const clock = stubs(on, report, log)
  on('ui.notify', (_$, e) => { log.notes.push(e.text); return { value: { isSent: true, channel: 'kitty' } } })
  await start($, clock)
  expect(log.notes).toEqual(['etapa 5, ciclo 2 de 3, modo autônomo: 1 decisão espera você (V1)'])
  log.mtime = 2
  await clock.advance(5000)
  expect(log.notes.length).toBe(1)
  report.validar = [...report.validar, { id: 'V3', text: 'outra', decision: null }]
  log.mtime = 3
  await clock.advance(5000)
  expect(log.notes[1]).toContain('2 decisões esperam você (V1 e V3)')
  report.validar = []
  report.ready_for_gate = true
  log.mtime = 4
  await clock.advance(5000)
  expect(log.notes[2]).toContain('pronto para o gate')
})

test('a delivery with nothing waiting for you raises no notification', async ($, on) => {
  const log = { runs: 0, mtime: 1, notes: [] as string[] }
  const clock = stubs(on, { ...STATUS, validar: [] }, log)
  on('ui.notify', (_$, e) => { log.notes.push(e.text); return { value: { isSent: true, channel: 'kitty' } } })
  await start($, clock)
  expect(log.notes).toEqual([])
})

test('the delivery resumes itself once the usage window resets, once per pause', async ($, on) => {
  const log = { runs: 0, mtime: 1, prompts: [] as string[] }
  const report = JSON.parse(JSON.stringify(PAUSED))
  const clock = stubs(on, report, log)
  on('prompt.submit', (_$, e) => { log.prompts.push(e.text); return { text: e.text } })
  await start($, clock)
  expect(log.prompts).toEqual([])
  report.usage.wait = null
  log.mtime = 2
  await clock.advance(5000)
  expect(log.prompts.length).toBe(1)
  expect(log.prompts[0]).toContain('retome a entrega')
  log.mtime = 3
  await clock.advance(5000)
  expect(log.prompts.length).toBe(1)
})

test('a pause the mod never saw waiting on the usage window is not resumed on its own', async ($, on) => {
  const log = { runs: 0, mtime: 1, prompts: [] as string[] }
  const report = { ...PAUSED, usage: { ...USAGE, wait: null } }
  const clock = stubs(on, report, log)
  on('prompt.submit', (_$, e) => { log.prompts.push(e.text); return { text: e.text } })
  await start($, clock)
  log.mtime = 2
  await clock.advance(5000)
  expect(log.prompts).toEqual([])
})

test('the pane gives each running pipeline agent a button that opens its conversation', async ($, on) => {
  const log = { runs: 0, mtime: 1, viewed: [] as string[] }
  const clock = stubs(on, STATUS, log)
  on('agent.list', () => ({ value: [
    { id: 'a-dev', description: 'dev na T2.1, do plano', type: 'pipeline:dev', status: 'running' },
    { id: 'a-qa', description: 'qa do ciclo 2', type: 'pipeline:qa', status: 'running' },
    { id: 'a-done', description: 'dev na T2.2', type: 'pipeline:dev', status: 'completed' },
    { id: 'a-other', description: 'outra coisa', type: 'general-purpose', status: 'running' },
  ] }))
  on('ui.view', (_$, e) => { log.viewed.push(e.agentId); return { value: {} } })
  await start($, clock)
  const ui = await $.ui.mount({ plugin: 'pipeline', surface: 'terminal', ...PANE })
  expect((await ui.find({ key: 'agente-a-dev' }))?.text).toContain('dev T2.1')
  expect((await ui.find({ key: 'agente-a-qa' }))?.text).toContain('qa')
  expect(await ui.find({ key: 'agente-a-done' })).toBeUndefined()
  expect(await ui.find({ key: 'agente-a-other' })).toBeUndefined()
  await ui.press({ key: 'agente-a-qa' })
  expect(log.viewed).toEqual(['a-qa'])
  await ui.unmount()
})

test('the pane lists the files of the delivery, to open where the user chooses', () => {
  const r = { ...STATUS, plan: '/work/docs/plano.md',
              runs: [STATUS.runs[0], { ...STATUS.runs[1], report: '/work/.superpowers/reports/etapa-5/2-reviewer-1.md' }] }
  const lines = paneLines(r, [], NOW)
  expect(lines).toContain('Arquivos da entrega:')
  expect(lines).toContain('- plano: /work/docs/plano.md')
  expect(lines).toContain('- reviewer: /work/.superpowers/reports/etapa-5/2-reviewer-1.md')
  expect(paneLines(STATUS, [], NOW).join(' ')).not.toContain('Arquivos da entrega')
})
