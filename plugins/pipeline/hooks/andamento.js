// Mod (Claude Code v2.1.287 or later): the delivery's progress, drawn from `ledger.py status --json`, in Portuguese
// (the user reads it; the ledger's own text stays in English for the manager). While the ledger of this worktree has
// a delivery, rows above the prompt say, each wrapping instead of cutting: the plan cycle, whether it is paused and
// the tasks and cycles left; the tasks in flight with their time, a verdict no next step covers and what comes next;
// and the VALIDAR items waiting, in the warning color. Only the first row dims while Claude works.
// /andamento opens a pane with what is left per cycle, the current cycle's runs, the next steps, the earlier cycles
// and the other fronts (each worktree with a ledger of its own), and answers in text where nothing draws. Every rule
// stays in ledger.py (its steps and scope): this file only lays them out. It checks the ledger file every 5 s and
// runs ledger.py again only when the file changed, or once a minute (every 5 minutes while there is no ledger file).
// It runs ledger.py with the first of python and python3 that is Python 3, as hooks/python.sh does. It also writes
// the account's rate-limit windows to usage.json beside the ledger (on session.measure, only when they changed;
// advice for ledger.py, whose `usage` it shows: econômico, the wait for a reset, the pane's usage line). A ledger.py
// failure (a broken ledger, no Python 3) shows in the band and the pane instead of passing for "no delivery". Other
// mods' band content is kept below the rows.
// On its own, after each read of the status, it does the two things the user asked never to wait through: a
// native notification (`$.ui.notify`) the moment the delivery needs them — the gate ready, the manager asking
// or stopping, a VALIDAR item — once per state, the line itself being the key; and, for a delivery paused
// waiting for a usage window, one prompt (`$.prompt.submit`) asking this session to resume once the window has
// reset, once per pause and never for a pause with no wait behind it. It writes nothing to the delivery.
// The pane also gives each pipeline agent still running a button that puts its conversation in the main view
// (`$.ui.view`, which only answers the person's own input, as a press of one is), and lists the delivery's
// files (the plan and the reports the ledger kept) as paths for the user to open where they choose.

const PANE = 'andamento'
const POLL_MS = 5000
const REFRESH_MS = 60000
const IDLE_REFRESH_MS = 300000
const AGENT = { reviewer: 'revisão', qa: 'qa' }
const GAP = '   '
// How each part of the band is drawn: the quiet ones dim, color only where something runs, failed or waits for you.
const TONE = {
  title: { weight: 'bold' }, quiet: { dimColor: true }, next: {},
  running: { color: 'claude', weight: 'bold' }, done: { dimColor: true }, failed: { color: 'error' },
  ready: { color: 'success', weight: 'bold' }, you: { color: 'warning', weight: 'bold' },
}

let report = null
let failure = null
let watched = null
let mtime = null
let lastRead = -Infinity
let fronts = []
let python = null
let written = null
let notified = null
let waited = false
let resumed = null

function clock(minutes) {
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, '0')}`
}

export function since(at, now) {
  return clock(Math.max(0, Math.floor((now - Date.parse(at)) / 60000)))
}

export function duration(seconds) {
  if (seconds === undefined || seconds === null) return '-'
  return seconds < 60 ? `${seconds} s` : clock(Math.round(seconds / 60))
}

function plural(count, one, many) {
  return `${count} ${count === 1 ? one : many}`
}

function listed(items) {
  return items.length < 2 ? items.join('') : `${items.slice(0, -1).join(', ')} e ${items[items.length - 1]}`
}

function thousands(count) {
  return String(count).replace(/\B(?=(\d{3})+(?!\d))/g, '.')
}

function waiting(r) {
  return (r.validar || []).filter((item) => typeof item === 'object' && item.decision === null)
}

// A plan may name its cycles "Ciclo 3": the word is said once.
function cycleName(name) {
  return String(name).replace(/^ciclo\s+/i, '')
}

function title(r) {
  const scope = r.scope
  const name = scope && cycleName(scope.current)
  const cycle = !scope ? `ciclo ${r.cycle}`
    : name === String(scope.position) ? `ciclo ${scope.position} de ${scope.total}`
    : `ciclo ${name} (${scope.position}º de ${scope.total})`
  const modes = [...(r.autonomous ? ['autônomo'] : []), ...(r.usage && r.usage.economy ? ['econômico'] : [])]
  return [String(r.slug).replace(/[-_]+/g, ' '), cycle, ...(modes.length ? [`modo ${listed(modes)}`] : []),
          ...(r.paused ? ['pausada'] : [])].join(', ')
}

// The plan's task ids as they are; the two the manager names itself, in words.
function taskName(task) {
  const fix = /^fix-(\d+)$/.exec(task)
  return task === 'cleanup' ? 'limpeza' : fix ? `correção ${fix[1]}` : task
}

const WINDOW = { five_hour: ['5 h', 'da janela de 5 horas'], seven_day: ['semana', 'da semana'] }

function two(number) {
  return String(number).padStart(2, '0')
}

// ledger.py's wait advice, in the user's local time: "esperar o reset da semana (97% + 9% por execução, volta em 17/10 21:05)".
// With no usable reset time it says none (new Date(null) is the epoch).
function waitText(wait) {
  const at = wait.resets_at ? new Date(wait.resets_at) : null
  const [, name] = WINDOW[wait.window] || [wait.window, `da janela ${wait.window}`]
  const used = `${Math.floor(wait.percent)}%${wait.margin > 0 ? ` + ${Math.round(wait.margin)}% por execução` : ''}`
  if (!at || Number.isNaN(at.getTime())) return `esperar o reset ${name} (${used})`
  const hour = `${two(at.getHours())}:${two(at.getMinutes())}`
  const back = wait.window === 'five_hour' ? `volta às ${hour}` : `volta em ${two(at.getDate())}/${two(at.getMonth() + 1)} ${hour}`
  return `esperar o reset ${name} (${used}, ${back})`
}

function usageLine(usage) {
  const order = Object.keys(WINDOW)
  const windows = Object.entries((usage && usage.windows) || {})
  if (!windows.length) return null
  windows.sort(([a], [b]) => (order.includes(a) ? order.indexOf(a) : 9) - (order.includes(b) ? order.indexOf(b) : 9))
  return `Uso da conta: ${windows.map(([kind, w]) => `${(WINDOW[kind] || [kind])[0]} ${Math.floor(w.percent)}%`).join(', ')}`
}

function left(scope) {
  return `${plural(scope.tasks_left, 'tarefa', 'tarefas')} em ${plural(scope.cycles_left, 'ciclo', 'ciclos')}`
}

// One step of ledger.py's steps, spelled out.
function said(step) {
  // a step with a task is a round of the spec or plan review loop, before the code
  const agent = step.task ? `revisão ${step.task === 'spec' ? 'da spec' : 'do plano'}` : AGENT[step.agent] ?? step.agent
  switch (step.step) {
    case 'dev': return step.task ? `dev na ${taskName(step.task)} (voltou ${step.verdict})` : 'primeira tarefa do dev'
    case 'reviewer': return 'revisão'
    case 'qa': return step.rerun ? 'qa de novo nos cenários da correção' : 'qa'
    case 'fix': return `correção (${plural(step.open, 'achado', 'achados')} ${step.agent === 'qa' ? 'do qa' : 'da revisão'})`
    case 'review': return `${agent}, rodada ${step.round} (${plural(step.open, 'achado aberto', 'achados abertos')})`
    case 'ask': return `falar com você (${agent} ainda reprova depois ${step.task ? `de ${step.rounds} rodadas` : 'da correção'})`
    case 'stop': return `parar e registrar como VALIDAR (${agent} ainda reprova depois de ${step.rounds} rodadas)`
    case 'decide': return `decidir ${step.id}: ${step.text}`
    case 'resume': return `retomar a entrega (pausada: ${step.text})`
    default: return step.step
  }
}

export function rowText(row) {
  return row.map((part) => part.text).join(GAP)
}

// One line naming everything the delivery needs from the user right now, or null: the gate ready, the manager asking
// or stopping, and the VALIDAR items. It is also the key of the notification: a new item changes the text.
export function waitsForYou(r) {
  if (!r) return null
  const ids = waiting(r).map((item) => item.id)
  const asked = (r.steps || []).filter((step) => step.step === 'ask' || step.step === 'stop').map((step) => said(step))
  const parts = [...(r.ready_for_gate ? ['pronto para o gate'] : []), ...asked,
                 ...(ids.length ? [`${ids.length === 1 ? '1 decisão espera' : `${ids.length} decisões esperam`} você `
                                   + `(${listed(ids)})`] : [])]
  return parts.length ? `${title(r)}: ${listed(parts)}` : null
}

// The session's pipeline agents that have not finished, each with the task of the ledger its description names.
export function paneAgents(list, dispatched) {
  const tasks = Object.keys(dispatched || {})
  return (list || []).filter((agent) => String(agent.type || '').startsWith('pipeline:')
                                        && ['pending', 'running', 'waiting'].includes(agent.status))
    .map((agent) => {
      const kind = agent.type.slice('pipeline:'.length)
      const task = tasks.find((name) => String(agent.description || '').includes(name))
      return { id: agent.id, label: task ? `${kind} ${taskName(task)}` : kind }
    })
}

// The files this delivery wrote, as paths for the user to open: the plan and the reports the ledger kept.
export function deliveryFiles(r) {
  return [...(r.plan ? [`plano: ${r.plan}`] : []),
          ...(r.runs || []).filter((run) => run.report).map((run) => `${run.agent}: ${run.report}`)]
}

// The band's rows, each a list of {text, tone}, a row with nothing left out: where the delivery is and what is left;
// what runs, a verdict no step covers and what comes next; the VALIDAR items that wait for the user.
export function bandRows(r, now) {
  const where = [{ text: title(r), tone: 'title' }]
  if (r.scope && r.scope.tasks_left) {
    where.push({ text: `${r.scope.tasks_left === 1 ? 'falta' : 'faltam'} ${left(r.scope)}`, tone: 'quiet' })
  }
  const current = Object.entries(r.dispatched || {})
    .map(([task, at]) => ({ text: `● dev na ${taskName(task)} há ${since(at, now)}`, tone: 'running' }))
  const steps = r.steps || []
  for (const agent of ['reviewer', 'qa']) {
    const verdict = (r[agent] || [])[0]
    if (!verdict || steps.some((step) => step.step === agent || step.agent === agent)) continue
    current.push(verdict.verdict === 'PASS' ? { text: `✓ ${AGENT[agent]}`, tone: 'done' }
      : { text: `✗ ${AGENT[agent]} reprovou, ${plural(verdict.open, 'aberto', 'abertos')}`, tone: 'failed' })
  }
  const wait = r.usage && r.usage.wait
  if (r.ready_for_gate) current.push({ text: '✓ pronto para o gate', tone: 'ready' })
  else if (steps.length || wait) {
    const decide = steps.filter((step) => step.step === 'decide').map((step) => step.id)
    const next = [...(wait ? [waitText(wait)] : []), ...steps.filter((step) => step.step !== 'decide').map((step) => said(step))]
    current.push({ text: `depois: ${listed(decide.length ? [...next, `decidir ${listed(decide)}`] : next)}`, tone: 'next' })
  }
  const items = waiting(r).length
  const you = items ? [{ text: items === 1 ? '1 decisão espera você' : `${items} decisões esperam você`, tone: 'you' }] : []
  return [where, current, you].filter((row) => row.length)
}

function row(cells) {
  const widths = [14, 10, 20, 8, 9]
  return cells.map((cell, index) => String(cell).padEnd(widths[index])).join(' ').trimEnd()
}

export function paneLines(r, fronts, now, failure = null) {
  const lines = []
  if (r) {
    lines.push(title(r), '')
    const usage = usageLine(r.usage)
    if (usage) lines.push(usage, '')
    if (r.scope && r.scope.tasks_left) {
      lines.push(`${r.scope.tasks_left === 1 ? 'Falta' : 'Faltam'} ${left(r.scope)}:`)
      for (const cycle of r.scope.cycles) {
        if (cycle.left.length) lines.push(`- ciclo ${cycleName(cycle.cycle)}: ${cycle.left.join(', ')}`)
      }
      lines.push('')
    }
    lines.push(row(['Agente', 'Tarefa', 'Veredito', 'Tempo', 'Tokens']))
    for (const run of r.runs || []) {
      const verdict = run.agent === 'dev' ? run.verdict : `${run.verdict}${run.open ? ` (${run.open} abertos)` : ''}`
      lines.push(row([run.agent, run.task || '-', run.waived ? `${verdict}, dispensado` : verdict, duration(run.seconds),
                      run.tokens ? thousands(run.tokens) : '-']))
    }
    for (const [task, at] of Object.entries(r.dispatched || {})) {
      lines.push(row(['dev', task, 'rodando', since(at, now), '-']))
    }
    if (r.ready_for_gate) lines.push('', 'Pronto para o gate.')
    else if ((r.steps || []).length || (r.usage && r.usage.wait)) {
      lines.push('', 'Depois:', ...(r.usage && r.usage.wait ? [`- ${waitText(r.usage.wait)}`] : []),
                 ...(r.steps || []).map((step) => `- ${said(step)}`))
    }
    const items = waiting(r)
    if (items.length) {
      lines.push('', 'Decisões que esperam você (VALIDAR):')
      for (const item of items) lines.push(`- ${item.id} ${item.text}`)
    }
    const files = deliveryFiles(r)
    if (files.length) {
      lines.push('', 'Arquivos da entrega:')
      for (const file of files) lines.push(`- ${file}`)
    }
    const earlier = ((r.metrics || {}).cycles || []).slice(0, -1)
    if (earlier.length) {
      lines.push('', 'Ciclos anteriores:')
      for (const cycle of earlier) {
        lines.push(`- ciclo ${cycle.cycle}: ${cycle.critical} Critical, ${cycle.important} Important, ${cycle.minor} ` +
                   `Minor; ${plural(cycle.fix_rounds, 'rodada', 'rodadas')} de correção; ` +
                   `${duration(cycle.seconds)} de agente` +
                   (cycle.tokens ? `, ${thousands(cycle.tokens)} tokens` : ''))
      }
    }
  } else {
    lines.push(failure ? `ledger.py falhou: ${failure}` : 'Nenhuma entrega aberta nesta worktree.')
  }
  if (fronts.length) {
    lines.push('', 'Outras frentes:')
    for (const front of fronts) {
      const flying = Object.keys(front.report.dispatched || {}).length
      lines.push(`- ${front.name}: ${title({ ...front.report, autonomous: false })}: ${flying} rodando, ` +
                 (front.report.ready_for_gate ? 'pronto para o gate'
                   : plural((front.report.steps || []).length, 'pendente', 'pendentes')))
    }
  }
  return lines
}

// Kept once found; null while neither name is Python 3.
async function interpreter($) {
  for (const name of ['python', 'python3']) {
    try {
      const probe = await $.process.run([name, '-c', 'import sys; sys.exit(sys.version_info[0] < 3)'],
                                        { timeoutMs: 15000 })
      if (probe.exitCode === 0) return (python = name)
    } catch {}
  }
  return null
}

// { report } for a delivery, {} for none, { error } when ledger.py could not answer (a broken ledger, no python).
async function status($, ledger) {
  const name = python || await interpreter($)
  if (!name) return { error: 'no Python 3 on PATH (tried python, python3)' }
  const argv = [name, `${$.plugin.root}/skills/manager/ledger.py`, ...(ledger ? ['--ledger', ledger] : []),
                'status', '--json']
  let out
  try {
    out = await $.process.run(argv, { timeoutMs: 15000 })
  } catch (error) {
    return { error: `could not run python: ${error?.message ?? error}` }
  }
  if (out.exitCode === 0) {
    try {
      return { report: JSON.parse(out.stdout) }
    } catch {
      return { error: 'ledger.py printed no JSON' }
    }
  }
  const message = (out.stderr || '').trim().split('\n').pop() || `ledger.py exited ${out.exitCode}`
  return message.startsWith('no delivery started') ? {} : { error: message }
}

async function read($) {
  ({ report = null, error: failure = null } = await status($))
}

async function modified($, path) {
  try {
    return (await $.fs.stat(path)).mtimeMs
  } catch {
    return null
  }
}

async function refresh($) {
  const now = await $.clock.now()
  watched = report ? report.ledger : `${await $.session.cwd()}/.superpowers/ledger.jsonl`
  const current = await modified($, watched)
  if (current === mtime && now - lastRead < (current === null ? IDLE_REFRESH_MS : REFRESH_MS)) return false
  await read($)
  mtime = current
  lastRead = now
  return true
}

function stamp(iso) {
  if (!iso) return null
  const at = new Date(iso)
  return Number.isNaN(at.getTime()) ? null : at.toISOString()
}

// usage.json beside the ledger: the windows {kind: {percent, resets_at}} and when they were read. Nothing without a
// ledger file or without windows (an API key); nothing when only the time changed. A window with no usable reset time
// is left out: ledger.py would never expire it. Never throws.
async function writeUsage($) {
  try {
    if (!watched || mtime === null) return
    const windows = {}
    for (const limit of (await $.session.usage()).rateLimits || []) {
      const resets = stamp(limit.resetsAt)
      if (resets) windows[limit.kind] = { percent: limit.percentUsed, resets_at: resets }
    }
    const body = JSON.stringify(windows)
    if (!Object.keys(windows).length || body === written) return
    const folder = watched.slice(0, Math.max(watched.lastIndexOf('/'), watched.lastIndexOf('\\')) + 1)
    const at = new Date(await $.clock.now()).toISOString()
    await $.fs.write(`${folder}usage.json`, JSON.stringify({ at, windows }))
    written = body
  } catch {}
}

// A native notification the moment the delivery starts needing the user, once per state (ui.notify limits nothing).
async function notifyWaiting($) {
  const line = waitsForYou(report)
  if (line === notified) return
  notified = line
  if (!line) return
  try {
    await $.ui.notify(line, { title: 'pipeline' })
  } catch {}
}

// A delivery paused waiting for the usage window: once the window has reset, ask this session to go on, so it does
// not sit until the user comes back to the terminal. Once per pause, and never for a pause with no wait behind it.
async function resumeAfterReset($) {
  if (!report || !report.paused) {
    waited = false
    resumed = null
    return
  }
  if (report.usage && report.usage.wait) {
    waited = true
    return
  }
  if (!waited || resumed === report.paused.at) return
  resumed = report.paused.at
  try {
    await $.prompt.submit({ text: 'pipeline: a janela de uso renovou. Rode o `ledger.py status`, dê `resume` e '
                                  + 'retome a entrega, despachando de novo cada claim que ele listar.' })
  } catch {}
}

// What the mod does on its own with a fresh status: nothing that writes to the delivery, only the two waits the
// user asked never to sit through (the notification and the resume after a usage reset).
async function attend($) {
  await notifyWaiting($)
  await resumeAfterReset($)
}

async function otherFronts($) {
  let listing = ''
  try {
    listing = (await $.process.run(['git', 'worktree', 'list', '--porcelain'])).stdout
  } catch {
    return []
  }
  const fronts = []
  for (const line of listing.split('\n')) {
    if (!line.startsWith('worktree ')) continue
    const folder = line.slice('worktree '.length).trim()
    const ledger = `${folder}/.superpowers/ledger.jsonl`
    if (report && report.ledger.replaceAll('\\', '/') === ledger.replaceAll('\\', '/')) continue
    if ((await modified($, ledger)) === null) continue
    const found = await status($, ledger)
    if (found.report) fronts.push({ name: folder.split('/').pop(), report: found.report })
  }
  return fronts
}

export function register(on) {
  on('session.start', async ($, e, next) => {
    $.clock.every(POLL_MS, async () => {
      const changed = await refresh($)
      if (changed) await attend($)
      if (changed || (report && Object.keys(report.dispatched || {}).length)) $.ui.invalidate('ui.render')
    })
    $.clock.after(0, async () => {
      if (await refresh($)) $.ui.invalidate('ui.render')
      await attend($)
      await writeUsage($)
    })
    try {
      await $.command.register({ name: 'andamento', immediate: true,
                                 description: 'Andamento da entrega: o ciclo, os agentes, o que falta e as outras frentes' })
    } catch {}
    return next(e)
  })

  on('session.measure', async ($, e, next) => {
    await writeUsage($)
    return next(e)
  })

  on('command.run', { command: 'andamento' }, async ($) => {
    await read($)
    lastRead = await $.clock.now()
    fronts = await otherFronts($)
    try {
      const placed = await $.ui.open({ id: PANE, title: 'Andamento', closeOnEscape: true })
      if (!placed || placed.isPlaced) return {}
    } catch {}
    return { text: paneLines(report, fronts, await $.clock.now(), failure).join('\n') }
  })

  on('ui.render', { component: 'Pane' }, async ($, e, next) => {
    if (e.requestId !== PANE) return next(e)
    const { Box, Text, Button } = $.ui.resolve(e)
    const lines = paneLines(report, fronts, await $.clock.now(), failure)
    const drawn = lines.map((line, index) =>
      Text({ wrap: 'wrap', ...(index === 0 ? TONE.title : {}), children: [line || ' '] }))
    let agents = []
    try {
      agents = paneAgents(await $.agent.list(), report && report.dispatched)
    } catch {}
    // $.ui.view only answers the person's own input, which a press of these is
    if (agents.length) {
      drawn.push(Text({ children: [' '] }), Text({ ...TONE.quiet, children: ['Abrir a conversa de:'] }),
                 Box({ children: agents.map((agent) => Button({
                   key: `agente-${agent.id}`, label: agent.label, onPress: () => $.ui.view({ agentId: agent.id }),
                 })) }))
    }
    return Box({ flexDirection: 'column', children: drawn })
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if ((!report && !failure) || e.props.hasSurvey) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const rows = report ? bandRows(report, await $.clock.now())
      : [[{ text: `pipeline: ledger.py falhou: ${failure}`, tone: 'failed' }]]
    // a row of one part takes its tone whole; a row of several sets each part apart
    const drawn = rows.map((row, index) => Text({
      wrap: 'wrap', ...(row.length === 1 ? TONE[row[0].tone] : {}), ...(index === 0 && e.props.isWorking ? { dimColor: true } : {}),
      children: row.length === 1 ? [row[0].text]
        : row.flatMap((part, at) => [...(at ? [GAP] : []), Text({ ...TONE[part.tone], children: [part.text] })]),
    }))
    const theirs = await next(e)
    return Box({ flexDirection: 'column', children: theirs ? [...drawn, theirs] : drawn })
  })
}
