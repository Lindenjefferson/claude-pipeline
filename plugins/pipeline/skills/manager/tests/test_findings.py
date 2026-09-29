import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from findings import finding_paths, fix_scope_reason, uncited

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"| {detail[:400]}")


T1_4_DESIGN = """# T1.4-design-r1

**Verdict: FAIL** (1 Important). Read only (no shell/browser; dark mode and screen reader unverified).

## Important
1. app/onboarding/criar-casa/page.tsx:10 — CardTitle without as="h1" → page has no h1 (pattern: auth screens use as="h1"). Fix: as="h1".

## Minor
2. seletor-casa.tsx:45 — trigger disabled={pendente} loses keyboard focus to body. Fix: aria-disabled + ignore open while pending.
3. layout.tsx:43 — fixed bottom bar lacks safe-area padding (pb-[env(safe-area-inset-bottom)]); text-xs labels open question.
5. menu-conta.tsx:19 — Sair has no pending state; dropdown closes; double click possible.
Open questions: "Criar outra casa" → onboarding offers only Sair (no Voltar when user already has a house); account menu shows no name/e-mail.
Checked OK: skip link + landmarks + single exposed nav; 44px targets + focus ring; empty dashboard + 404 (not-found.tsx).

LEDGER {"agent":"design","verdict":"FAIL","new":{"critical":0,"important":1,"minor":3},"open":{"critical":0,"important":1,"minor":3}}
"""

T0_4_SECURITY = """# T0.4-security-r1

**Verdict: FAIL.** One Important. Probed running app (dev :3099, stopped) + local GoTrue/Mailpit.
OK: no open redirect; admin.ts server-only, non-public key, unused; no secrets in history; errors generic.

## Important
1. Sign-up reveals account existence — actions.ts:47-51 + config.toml [auth.sms] enable_confirmations=false (~267): existing confirmed e-mail → GoTrue 422 user_already_exists. Fix: (a) [auth.sms] enable_confirmations=true; (b) cadastrar maps user_already_exists/email_exists to the same confirmar_email state.

## Minor
3. Session cookies without Secure (@supabase/ssr defaults). Fix: cookieOptions { secure: NODE_ENV === "production" } on server/middleware/client.

Housekeeping: probe users left in local Supabase (seed.sql untouched) — db:reset removes.

LEDGER {"agent":"security","verdict":"FAIL","new":{"critical":0,"important":1,"minor":1},"open":{"critical":0,"important":1,"minor":1}}
"""

T1_1_CODE_REVIEW = """# T1.1-code-review-r1

**Verdict: FAIL.** 2 Important (test-quality gaps on admin-only write rules); migration correct. db:test 5/100 pass; typecheck clean; 0002:121 comment is a legit "why".
Mutation check (rolled back): households_update using(true) → suite stays green.

## Important
1. 04_privilegios.sql / 02_permissoes.sql: admin-only write policies (households_update 0002:226; household_members_insert/update 0002:232-236) have no negative test. Fix in 04: as Caio — afetadas(update households) = 0.
2. 04_privilegios.sql:131-134: lives_ok on UPDATE passes when RLS filters every row. Fix: is(afetadas(update … oculta = true where id='3...a9'), 1, …).

## Minor
4. 02:64: explicit nivel='nenhum' row not exercised.
6. Spec drift docs/specs/modulo-01-pessoas-design.md:140 says triggers record current_user in _origem.

LEDGER {"agent":"code-review","verdict":"FAIL","new":{"critical":0,"important":2,"minor":2},"open":{"critical":0,"important":2,"minor":2}}
"""

T1_5_DESIGN = """**Design review, T1.5 (Tela Pessoas), round 1, range 146616d..a9f4f58**

Reviewed by reading the code; no browser run; `error.tsx` not exercised.

**Verdict: FAIL** (2 Important, 2 Minor)

**T0.1 deferred note (RadioGroupItem / SelectItem 44px):** RadioGroupItem solved — each option is a `Label` cell with `min-h-11` (`grade-permissoes.tsx:400-406`).

**Important**
1. Focus falls to `body` after "Ocultar". `linha-pessoa.tsx:554` (action), `lista-pessoas.tsx:673` and `:690` (hidden person filtered out).
2. Toast "Desfazer" and close buttons below 44px. `lib/household/avisos.ts:15`, `components/ui/sonner.tsx:39-43`, `app/layout.tsx:21` (`<Toaster closeButton />`). Breaks `docs/specs/guia-estilo.md:102`.

**Minor**
- `editor-grade.tsx:330`: `h3` under page `h1` (jump); use `h2` or restructure.
- `adicionar-pessoa.tsx:211`: focus not managed after error/success. Pattern: `app/onboarding/criar-casa/formulario.tsx:871-876`.

**Open questions:** 320-360px grade cells are tight; `AnuncioErros` plus sonner may read an error twice (`components/anuncio-erros.tsx`).

**Checked and consistent:** loading/error/empty states, inline errors with `role="alert"` (`app/(app)/configuracoes/pessoas/loading.tsx`).

LEDGER {"agent":"design","verdict":"FAIL","new":{"critical":0,"important":2,"minor":2},"open":{"critical":0,"important":2,"minor":2}}
"""

cited = finding_paths(T1_4_DESIGN)
check("T1.4 design: '## Important'/'## Minor' headings open the findings, bare names are kept",
      {"app/onboarding/criar-casa/page.tsx", "seletor-casa.tsx", "layout.tsx", "menu-conta.tsx"} <= cited, str(cited))
check("T1.4 design: 'Open questions:' and 'Checked OK:' close the findings", "not-found.tsx" not in cited, str(cited))
universe = ["app/onboarding/criar-casa/page.tsx", "components/seletor-casa.tsx", "app/(app)/layout.tsx",
            "components/menu-conta.tsx", "app/not-found.tsx"]
check("T1.4 design: a fix in the cited files, named by basename, is inside the findings",
      uncited(["components/seletor-casa.tsx", "app/(app)/layout.tsx", "app/onboarding/criar-casa/page.tsx"],
              cited, universe) == [], str(cited))
check("T1.4 design: a fix in a file named only under 'Checked OK' is outside",
      uncited(["app/not-found.tsx"], cited, universe) == ["app/not-found.tsx"])
check("T1.4 design: a bare basename that matches two task files is ambiguous",
      uncited(["app/(app)/layout.tsx"], cited, universe + ["app/layout.tsx"]) == ["app/(app)/layout.tsx"])

cited = finding_paths(T0_4_SECURITY)
check("T0.4 security: findings cite actions.ts and config.toml",
      {"actions.ts", "config.toml"} <= cited and "admin.ts" not in cited and "seed.sql" not in cited, str(cited))
universe = ["app/(auth)/actions.ts", "supabase/config.toml", "lib/supabase/admin.ts", "supabase/seed.sql"]
check("T0.4 security: the preamble and the 'Housekeeping:' line are not findings",
      uncited(["app/(auth)/actions.ts", "supabase/config.toml", "lib/supabase/admin.ts"], cited, universe)
      == ["lib/supabase/admin.ts"], str(cited))

cited = finding_paths(T1_1_CODE_REVIEW)
universe = ["supabase/migrations/0002_pessoas.sql", "supabase/tests/02_permissoes.sql",
            "supabase/tests/04_privilegios.sql", "supabase/tests/01_rls.sql", "docs/specs/modulo-01-pessoas-design.md",
            "supabase/migrations/0001_base.sql"]
check("T1.1 code-review: shorthand 0002:226 and 02:64 and bare 04_privilegios.sql all match their files",
      uncited(universe[:3], cited, universe) == [], str(cited))
check("T1.1 code-review: files no finding names (01_rls.sql, 0001_base.sql) are outside",
      uncited(["supabase/tests/01_rls.sql", "supabase/migrations/0001_base.sql"], cited, universe)
      == ["supabase/tests/01_rls.sql", "supabase/migrations/0001_base.sql"], str(cited))
check("T1.1 code-review: a repo-relative path matches itself",
      uncited(["docs/specs/modulo-01-pessoas-design.md"], cited, universe) == [])

cited = finding_paths(T1_5_DESIGN)
universe = ["app/(app)/configuracoes/pessoas/linha-pessoa.tsx", "app/(app)/configuracoes/pessoas/lista-pessoas.tsx",
            "lib/household/avisos.ts", "components/ui/sonner.tsx", "app/layout.tsx",
            "app/(app)/configuracoes/pessoas/editor-grade.tsx", "app/(app)/configuracoes/pessoas/adicionar-pessoa.tsx",
            "components/anuncio-erros.tsx", "app/(app)/configuracoes/pessoas/loading.tsx",
            "app/(app)/configuracoes/pessoas/grade-permissoes.tsx"]
check("T1.5 design: bold **Important**/**Minor** labels open the findings",
      uncited(universe[:7], cited, universe) == [], str(cited))
check("T1.5 design: bold '**Open questions:**' and '**Checked and consistent:**' close them",
      uncited(universe[7:9], cited, universe) == universe[7:9], str(cited))
check("T1.5 design: the bold note before the findings is not a finding",
      uncited([universe[9]], cited, universe) == [universe[9]], str(cited))

for name, report, expected in (
        ("'**Notes**: text' closes a heading-opened section",
         "## Findings\n### Important\n1. `src/a.ts:3` misses a check.\n**Notes**: I also read `src/c.ts`.\n",
         {"src/a.ts"}),
        ("'## Other domains' closes it", "## Important\n1. src/a.ts:1 wrong\n## Other domains\n- `src/s.ts`\n",
         {"src/a.ts"}),
        ("'**Other domains**' closes it", "**Important**\n- src/a.ts:1 wrong\n**Other domains**\n- `src/s.ts`\n",
         {"src/a.ts"}),
        ("'For other reviewers:' closes it", "**Important**\n- x/a.ts:1\nFor other reviewers: `x/y.ts`\n", {"x/a.ts"}),
        ("a 'for <agent>:' line inside the findings is not a finding",
         "## Important\n1. x/a.ts:1\n- for security: `x/s.ts:4` trusts input\n2. x/b.ts:2\n", {"x/a.ts", "x/b.ts"}),
        ("numbered severity headings, with 'Fix:' kept and 'Checked:' closing",
         "### 1. Important — takeover\nsrc/f.ts:1 is wrong.\nFix: change `src/g.ts`.\n### 2. Minor — quota\n"
         "src/h.ts:2\n\nChecked: `src/k.ts`\n", {"src/f.ts", "src/g.ts", "src/h.ts"}),
        ("a bold finding title without a colon does not close",
         "## Important\n**R3-1 — racing attacker.** see `src/r.ts:7`\nmore at src/q.ts:3\n", {"src/r.ts", "src/q.ts"}),
        ("a verdict line naming severities is not a findings section", "**Verdict: FAIL** (1 Important)\n`src/v.ts`\n",
         None)):
    found = finding_paths(report)
    check(f"finding_paths: {name}", found == expected, str(found))

check("fix_scope_reason: an unreadable report", "cannot be read" in fix_scope_reason(None, "r.md", ["a"], ["a"]))
check("fix_scope_reason: findings that cite no file",
      "cite no file" in fix_scope_reason("## Important\n1. the flow is wrong\n", "r.md", ["a.ts"], ["a.ts"]))

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
