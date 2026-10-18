// Mod (Claude Code v2.1.287 or later): the delivery's progress, drawn from `ledger.py status --json`, in Portuguese
// (the user reads it; the ledger's own text stays in English for the manager). While the ledger of this worktree has
// a delivery, one line above the prompt says the plan cycle, the tasks in flight with their time, a verdict no next
// step covers, what comes next, the tasks and cycles left and the VALIDAR items waiting. /andamento opens a pane with
// what is left per cycle, the current cycle's runs, the next steps, the earlier cycles and the other fronts (each
// worktree with a ledger of its own), and answers in text where nothing draws. Every rule stays in ledger.py (its
// steps and scope): this file only lays them out. It checks the ledger file every 5 s and runs ledger.py again only
// when the file changed, or once a minute (every 5 minutes while there is no ledger file); a ledger.py failure (a
// broken ledger, no python) shows in the band and the pane instead of passing for "no delivery". Other mods' band
// content is kept below the line.

const PANE = 'andamento'
const POLL_MS = 5000
const REFRESH_MS = 60000
const IDLE_REFRESH_MS = 300000
const AGENT = { reviewer: 'revisão', qa: 'qa' }

let report = null
let failure = null
let watched = null
let mtime = null
let lastRead = -Infinity
let fronts = []

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

function title(r) {
  const scope = r.scope
  const cycle = !scope ? `ciclo ${r.cycle}`
    : scope.current === String(scope.position) ? `ciclo ${scope.position} de ${scope.total}`
    : `ciclo ${scope.current} (${scope.position} de ${scope.total})`
  return [String(r.slug).replace(/[-_]+/g, ' '), cycle, ...(r.autonomous ? ['autônomo'] : [])].join(' · ')
}

function left(scope) {
  return `${plural(scope.tasks_left, 'tarefa', 'tarefas')} em ${plural(scope.cycles_left, 'ciclo', 'ciclos')}`
}

// One step of ledger.py's steps, spelled out.
function said(step) {
  const agent = AGENT[step.agent] ?? step.agent
  switch (step.step) {
    case 'dev': return step.task ? `dev na ${step.task} (voltou ${step.verdict})` : 'primeira tarefa do dev'
    case 'reviewer': return 'revisão'
    case 'qa': return step.rerun ? 'qa de novo nos cenários da correção' : 'qa'
    case 'fix': return `correção (${plural(step.open, 'achado', 'achados')} ${step.agent === 'qa' ? 'do qa' : 'da revisão'})`
    case 'ask': return `falar com você (${agent} ainda reprova depois da correção)`
    case 'stop': return `parar e registrar como VALIDAR (${agent} ainda reprova depois de ${step.rounds} rodadas)`
    case 'decide': return `decidir ${step.id}: ${step.text}`
    default: return step.step
  }
}

export function bandLine(r, now) {
  const parts = [title(r)]
  const running = Object.entries(r.dispatched || {}).map(([task, at]) => `na ${task} há ${since(at, now)}`)
  if (running.length) parts.push(`dev ${listed(running)}`)
  const steps = r.steps || []
  for (const agent of ['reviewer', 'qa']) {
    const verdict = (r[agent] || [])[0]
    if (!verdict || steps.some((step) => step.step === agent || step.agent === agent)) continue
    parts.push(verdict.verdict === 'PASS' ? `${AGENT[agent]} ok`
      : `${AGENT[agent]} reprovou (${plural(verdict.open, 'aberto', 'abertos')})`)
  }
  if (r.ready_for_gate) parts.push('pronto para o gate')
  else if (steps.length) {
    const decide = steps.filter((step) => step.step === 'decide').map((step) => step.id)
    const next = steps.filter((step) => step.step !== 'decide').map((step) => said(step))
    parts.push(`depois: ${listed(decide.length ? [...next, `decidir ${listed(decide)}`] : next)}`)
  }
  if (r.scope && r.scope.tasks_left) parts.push(`${r.scope.tasks_left === 1 ? 'falta' : 'faltam'} ${left(r.scope)}`)
  const items = waiting(r).length
  if (items) parts.push(items === 1 ? '1 decisão espera você' : `${items} decisões esperam você`)
  return parts.join(' · ')
}

function row(cells) {
  const widths = [14, 10, 20, 8, 9]
  return cells.map((cell, index) => String(cell).padEnd(widths[index])).join(' ').trimEnd()
}

export function paneLines(r, fronts, now, failure = null) {
  const lines = []
  if (r) {
    lines.push(title(r), '')
    if (r.scope && r.scope.tasks_left) {
      lines.push(`${r.scope.tasks_left === 1 ? 'Falta' : 'Faltam'} ${left(r.scope)}:`)
      for (const cycle of r.scope.cycles) {
        if (cycle.left.length) lines.push(`- ciclo ${cycle.cycle}: ${cycle.left.join(', ')}`)
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
    else if ((r.steps || []).length) lines.push('', 'Depois:', ...r.steps.map((step) => `- ${said(step)}`))
    const items = waiting(r)
    if (items.length) {
      lines.push('', 'Decisões que esperam você (VALIDAR):')
      for (const item of items) lines.push(`- ${item.id} ${item.text}`)
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
      lines.push(`- ${front.name}: ${title({ ...front.report, autonomous: false })} · ${flying} rodando · ` +
                 (front.report.ready_for_gate ? 'pronto para o gate'
                   : plural((front.report.steps || []).length, 'pendente', 'pendentes')))
    }
  }
  return lines
}

// { report } for a delivery, {} for none, { error } when ledger.py could not answer (a broken ledger, no python).
async function status($, ledger) {
  const argv = ['python', `${$.plugin.root}/skills/manager/ledger.py`, ...(ledger ? ['--ledger', ledger] : []),
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
      if (changed || (report && Object.keys(report.dispatched || {}).length)) $.ui.invalidate('ui.render')
    })
    $.clock.after(0, async () => {
      if (await refresh($)) $.ui.invalidate('ui.render')
    })
    try {
      await $.command.register({ name: 'andamento', immediate: true,
                                 description: 'Andamento da entrega: o ciclo, os agentes, o que falta e as outras frentes' })
    } catch {}
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
    const { Box, Text } = $.ui.resolve(e)
    const lines = paneLines(report, fronts, await $.clock.now(), failure)
    return Box({ flexDirection: 'column', children: lines.map((line, index) =>
      Text({ wrap: 'wrap', bold: index === 0, children: [line || ' '] })) })
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if ((!report && !failure) || e.props.hasSurvey) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const text = report ? bandLine(report, await $.clock.now()) : `pipeline · ledger.py falhou: ${failure}`
    const line = Text({ wrap: 'truncate-end', dimColor: e.props.isWorking, children: [text] })
    const theirs = await next(e)
    return Box({ flexDirection: 'column', children: theirs ? [line, theirs] : [line] })
  })
}
