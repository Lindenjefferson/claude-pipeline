// Mod (Claude Code v2.1.287 or later): the delivery's progress, drawn from `ledger.py status --json`. While the
// ledger of this worktree has a delivery, one line above the prompt says the cycle, the tasks in flight with their
// time, the reviewer and qa verdicts, the VALIDAR items waiting and what comes next. /andamento opens a pane with
// the current cycle's runs, the earlier cycles, what is pending and the other fronts (each worktree with a ledger of
// its own), and answers in text where nothing draws. Every rule stays in ledger.py: this file only lays it out. It
// checks the ledger file every 5 s and runs ledger.py again only when the file changed, or once a minute (every 5
// minutes while there is no ledger file); a ledger.py failure (a broken ledger, no python) shows in the band and the
// pane instead of passing for "no delivery". Other mods' band content is kept below the line.

const PANE = 'andamento'
const POLL_MS = 5000
const REFRESH_MS = 60000
const IDLE_REFRESH_MS = 300000

let report = null
let failure = null
let watched = null
let mtime = null
let lastRead = -Infinity
let fronts = []

export function since(at, now) {
  const minutes = Math.max(0, Math.floor((now - Date.parse(at)) / 60000))
  return minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h${minutes % 60}m`
}

export function duration(seconds) {
  if (seconds === undefined || seconds === null) return '-'
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.round(seconds / 60)
  return minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h${minutes % 60}m`
}

function waiting(r) {
  return (r.validar || []).filter((item) => typeof item === 'object' && item.decision === null)
}

function nextSteps(r) {
  const flying = Object.keys(r.dispatched || {})
  return (r.pending || []).filter((item) => !flying.some((task) => item.startsWith(`dev ${task} dispatched`)))
}

export function bandLine(r, now) {
  const parts = [`pipeline · ${r.slug} · cycle ${r.cycle}`]
  if (r.autonomous) parts.push('autonomous')
  for (const [task, at] of Object.entries(r.dispatched || {})) parts.push(`▶ ${task} ${since(at, now)}`)
  for (const agent of ['reviewer', 'qa']) parts.push(`${agent} ${(r[agent] || [])[0]?.verdict ?? '—'}`)
  const items = waiting(r).length
  if (items) parts.push(`VALIDAR ${items}`)
  const next = nextSteps(r)
  if (r.ready_for_gate) parts.push('ready for gate')
  else if (next.length) parts.push(`next: ${next[0]}`)
  return parts.join(' · ')
}

function row(cells) {
  const widths = [14, 10, 20, 8, 9]
  return cells.map((cell, index) => String(cell).padEnd(widths[index])).join(' ').trimEnd()
}

export function paneLines(r, fronts, now, failure = null) {
  const lines = []
  if (r) {
    lines.push(`${r.slug} · cycle ${r.cycle}${r.autonomous ? ' · autonomous' : ''}`, '')
    lines.push(row(['Agent', 'Task', 'Verdict', 'Time', 'Tokens']))
    for (const run of r.runs || []) {
      const verdict = run.agent === 'dev' ? run.verdict : `${run.verdict}${run.open ? ` (${run.open} open)` : ''}`
      lines.push(row([run.agent, run.task || '-', run.waived ? `${verdict}, waived` : verdict, duration(run.seconds),
                      run.tokens ?? '-']))
    }
    for (const [task, at] of Object.entries(r.dispatched || {})) {
      lines.push(row(['dev', task, 'running', since(at, now), '-']))
    }
    const next = nextSteps(r)
    lines.push('', r.ready_for_gate ? 'Ready for gate.' : 'Pending:')
    for (const item of next) lines.push(`- ${item}`)
    const items = waiting(r)
    if (items.length) {
      lines.push('', 'VALIDAR (waiting for the user):')
      for (const item of items) lines.push(`- ${item.id} ${item.text}`)
    }
    const earlier = ((r.metrics || {}).cycles || []).slice(0, -1)
    if (earlier.length) {
      lines.push('', 'Earlier cycles:')
      for (const cycle of earlier) {
        lines.push(`- cycle ${cycle.cycle}: ${cycle.critical} Critical, ${cycle.important} Important, ${cycle.minor} ` +
                   `Minor; ${cycle.fix_rounds} fix round${cycle.fix_rounds === 1 ? '' : 's'}; ` +
                   `${duration(cycle.seconds)} agent time` +
                   (cycle.tokens ? `, ${cycle.tokens} tokens` : ''))
      }
    }
  } else {
    lines.push(failure ? `ledger.py failed: ${failure}` : 'No delivery open in this worktree.')
  }
  if (fronts.length) {
    lines.push('', 'Other fronts:')
    for (const front of fronts) {
      const flying = Object.keys(front.report.dispatched || {}).length
      lines.push(`- ${front.name}: ${front.report.slug} · cycle ${front.report.cycle} · ${flying} running · ` +
                 (front.report.ready_for_gate ? 'ready for gate' : `${nextSteps(front.report).length} pending`))
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
                                 description: 'Delivery progress: the cycle, the agents, what is pending, other fronts' })
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
    const text = report ? bandLine(report, await $.clock.now()) : `pipeline · ledger.py failed: ${failure}`
    const line = Text({ wrap: 'truncate-end', dimColor: e.props.isWorking, children: [text] })
    const theirs = await next(e)
    return Box({ flexDirection: 'column', children: theirs ? [line, theirs] : [line] })
  })
}
