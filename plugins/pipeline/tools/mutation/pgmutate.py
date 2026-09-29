#!/usr/bin/env python3
import argparse
import glob
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from collections import namedtuple

Token = namedtuple("Token", "kind text start end")

OP_CHARS = set("+-*/<>=~!@#%^&|`?")
IDENT_RE = re.compile(r"[A-Za-z_\u0080-\uffff][A-Za-z0-9_$\u0080-\uffff]*")
NUM_RE = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
DOLLAR_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")
PARAM_RE = re.compile(r"\$\d+")

OPERATORS = (
    "null-guard-removed",
    "null-guard-negated",
    "boundary",
    "time-constant",
    "limit-constant",
    "scope-filter-removed",
    "role-filter-removed",
    "audit-removed",
    "raise-removed",
    "and-or-swap",
    "coalesce-default-removed",
)
DEFAULT_SCOPE_COLUMNS = ("household_id", "tenant_id", "org_id", "organization_id", "workspace_id",
                         "account_id", "team_id", "user_id", "owner_id")
DEFAULT_ROLE_COLUMNS = ("role", "papel", "is_admin", "admin", "permission", "permissao", "nivel")
DEFAULT_AUDIT_PATTERN = r"audit|auditoria|log"
BOUNDARY_SWAP = {">=": ">", ">": ">=", "<=": "<", "<": "<="}
RAISE_NON_ERROR_LEVELS = {"debug", "log", "info", "notice", "warning"}
TRANSACTION_WORDS = {"begin", "start", "commit", "end", "rollback", "abort"}
FORBIDDEN_META = {"i", "ir", "include", "include_relative", "c", "connect", "!", "o", "out", "w", "write",
                  "copy", "gexec"}
DDL_MARKER = "PGMUTATE_DDL_OK"
FAIL_LINE_RE = re.compile(r"^\s*not ok\b|\bERROR:|^\s*#\s*Looks like you (?:planned|failed)|\bFATAL:")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal", ""}

HELP_EPILOG = """\
How a mutant is run:
  Each pgTAP file is sent to psql on stdin (the same as `psql -f -`), rewritten as
    begin; set local statement_timeout = ...;
    <create or replace function ... (mutated)>;
    select 'PGMUTATE_DDL_OK';
    <test file without its own top-level begin/commit/rollback>
    rollback;
  so the mutated function and everything the test does are rolled back together, and
  nothing is left in the database. A leading `begin;`/`start transaction;` and a trailing
  `rollback;`/`commit;`/`end;` in the test file are stripped. A test file with any other
  top-level transaction control (commit/rollback/begin in the middle) or with psql
  meta-commands that include files, reconnect, write files or run shell commands
  (\\i \\ir \\c \\! \\o \\w \\copy \\gexec) is refused: it could commit the mutant or escape the transaction.
  The function definitions are fingerprinted (md5 of pg_get_functiondef) before and after
  the run; any difference aborts with exit code 3.

Verdicts:
  killed    a test file printed `not ok`, an ERROR, or a pgTAP plan/failed summary
  survived  every test file ran clean with the mutant in place
  invalid   the mutated function did not compile (not counted in the score)
  timeout   the run exceeded --timeout (counted as killed)

Connection (local only):
  --db-url URL      psql on PATH; the host must be localhost, 127.0.0.1, ::1,
                    host.docker.internal or a dotless docker service name
  --container NAME  `docker exec -i NAME psql -U postgres -d postgres`
  default           DB_URL from `supabase status -o env` when psql is on PATH, otherwise
                    the running container supabase_db_<project_id> (supabase/config.toml)

Exit codes: 0 done (survivors are not a failure), 1 survivors with --fail-on-survivors,
2 tool error, 3 database fingerprint changed during the run.
"""


class ToolError(Exception):
    pass


class IntegrityError(Exception):
    pass


def lex(text, base=0, psql_meta=False):
    tokens = []
    i, n = 0, len(text)
    line_start = True
    while i < n:
        c = text[i]
        start = i
        if c in " \t\r\n\f":
            while i < n and text[i] in " \t\r\n\f":
                if text[i] == "\n":
                    line_start = True
                i += 1
            tokens.append(Token("ws", text[start:i], base + start, base + i))
            continue
        at_line_start = line_start
        line_start = False
        if psql_meta and c == "\\" and at_line_start:
            j = text.find("\n", i)
            i = n if j < 0 else j
            tokens.append(Token("meta", text[start:i], base + start, base + i))
            continue
        if text.startswith("--", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            tokens.append(Token("comment", text[start:i], base + start, base + i))
            continue
        if text.startswith("/*", i):
            depth, i = 1, i + 2
            while i < n and depth:
                if text.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif text.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            tokens.append(Token("comment", text[start:i], base + start, base + i))
            continue
        if c in "eE" and i + 1 < n and text[i + 1] == "'":
            i += 2
            while i < n:
                if text[i] == "\\":
                    i += 2
                elif text[i] == "'":
                    if i + 1 < n and text[i + 1] == "'":
                        i += 2
                    else:
                        i += 1
                        break
                else:
                    i += 1
            tokens.append(Token("str", text[start:i], base + start, base + i))
            continue
        if c == "'":
            i += 1
            while i < n:
                if text[i] == "'":
                    if i + 1 < n and text[i + 1] == "'":
                        i += 2
                    else:
                        i += 1
                        break
                else:
                    i += 1
            tokens.append(Token("str", text[start:i], base + start, base + i))
            continue
        if c == '"':
            i += 1
            while i < n:
                if text[i] == '"':
                    if i + 1 < n and text[i + 1] == '"':
                        i += 2
                    else:
                        i += 1
                        break
                else:
                    i += 1
            tokens.append(Token("qident", text[start:i], base + start, base + i))
            continue
        if c == "$":
            m = DOLLAR_RE.match(text, i)
            if m:
                tag = m.group(0)
                j = text.find(tag, m.end())
                i = n if j < 0 else j + len(tag)
                tokens.append(Token("dollar", text[start:i], base + start, base + i))
                continue
            m = PARAM_RE.match(text, i)
            if m:
                i = m.end()
                tokens.append(Token("param", text[start:i], base + start, base + i))
                continue
        if c.isdigit() or (c == "." and i + 1 < n and text[i + 1].isdigit()):
            m = NUM_RE.match(text, i)
            i = m.end()
            tokens.append(Token("num", text[start:i], base + start, base + i))
            continue
        m = IDENT_RE.match(text, i)
        if m:
            i = m.end()
            tokens.append(Token("ident", text[start:i], base + start, base + i))
            continue
        if c in OP_CHARS:
            while i < n and text[i] in OP_CHARS and not text.startswith("--", i) and not text.startswith("/*", i):
                i += 1
            if i == start:
                i += 1
            tokens.append(Token("op", text[start:i], base + start, base + i))
            continue
        if c == ":" and i + 1 < n and text[i + 1] in ":=":
            i += 2
        else:
            i += 1
        tokens.append(Token("punct", text[start:i], base + start, base + i))
    return tokens


def significant(tokens):
    return [t for t in tokens if t.kind not in ("ws", "comment")]


def word(tok):
    return tok.text.lower() if tok is not None and tok.kind == "ident" else None


def ident_name(tok):
    if tok.kind == "qident":
        return tok.text[1:-1].replace('""', '"')
    return tok.text.lower()


def split_statements(tokens):
    stmts, cur = [], []
    for t in tokens:
        if t.kind == "meta":
            if significant(cur):
                stmts.append(cur)
            stmts.append([t])
            cur = []
            continue
        cur.append(t)
        if t.kind == "punct" and t.text == ";":
            stmts.append(cur)
            cur = []
    if significant(cur):
        stmts.append(cur)
    return stmts


def line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def matching_paren(sig, idx):
    depth = 0
    for j in range(idx, len(sig)):
        if sig[j].text == "(":
            depth += 1
        elif sig[j].text == ")":
            depth -= 1
            if depth == 0:
                return j
    return None


def parse_qualified_name(sig, idx):
    if idx >= len(sig) or sig[idx].kind not in ("ident", "qident"):
        return None
    first = ident_name(sig[idx])
    if idx + 2 < len(sig) and sig[idx + 1].text == "." and sig[idx + 2].kind in ("ident", "qident"):
        return first, ident_name(sig[idx + 2]), idx + 3
    return None, first, idx + 1


FunctionDef = namedtuple("FunctionDef", "schema name args file text start end body_start body_end language")


def find_function_defs(text, file):
    defs, drops = [], []
    for stmt in split_statements(lex(text)):
        sig = significant(stmt)
        if not sig:
            continue
        words = [word(t) for t in sig[:4]]
        if words[0] == "drop" and len(sig) > 2 and word(sig[1]) in ("function", "procedure"):
            k = 2
            if word(sig[k]) == "if" and len(sig) > k + 2:
                k += 2
            parsed = parse_qualified_name(sig, k)
            if parsed:
                schema, name, after = parsed
                types = None
                if after < len(sig) and sig[after].text == "(":
                    close = matching_paren(sig, after)
                    if close is not None:
                        types = arg_types(text[sig[after].end:sig[close].start])
                drops.append((schema or "public", name, types, sig[0].start))
            continue
        if words[0] != "create":
            continue
        k = 1
        if words[1] == "or" and words[2] == "replace":
            k = 3
        if k >= len(sig) or word(sig[k]) not in ("function", "procedure"):
            continue
        parsed = parse_qualified_name(sig, k + 1)
        if not parsed:
            continue
        schema, name, after = parsed
        if after >= len(sig) or sig[after].text != "(":
            continue
        close = matching_paren(sig, after)
        if close is None:
            continue
        args = " ".join(text[sig[after].end:sig[close].start].split()).lower()
        language = None
        body = None
        for j in range(close + 1, len(sig)):
            if word(sig[j]) == "language" and j + 1 < len(sig):
                language = ident_name(sig[j + 1])
            if body is None and sig[j].kind == "dollar" and word(sig[j - 1]) == "as":
                body = sig[j]
        if body is None:
            continue
        tag = DOLLAR_RE.match(body.text).group(0)
        defs.append(FunctionDef(schema or "public", name, args, file, text, sig[0].start, sig[-1].end,
                                body.start + len(tag), body.end - len(tag), language or "sql"))
    return defs, drops


TYPE_FIRST_WORDS = {"double", "character", "char", "varchar", "timestamp", "timestamptz", "time", "bit", "interval",
                    "national", "int", "int2", "int4", "int8", "integer", "bigint", "smallint", "numeric", "decimal",
                    "real", "float", "boolean", "bool", "text", "uuid", "jsonb", "json", "date", "bytea", "setof"}
ARG_MODES = {"in", "out", "inout", "variadic"}


def split_top_level(text, sep=","):
    parts, depth, cur = [], 0, []
    for t in lex(text):
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            depth -= 1
        if t.text == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(t.text)
    if "".join(cur).strip():
        parts.append("".join(cur))
    return parts


def arg_types(args_text):
    types = []
    for arg in split_top_level(args_text):
        words = significant(lex(arg))
        cut = next((i for i, t in enumerate(words) if word(t) == "default" or t.text == "="), len(words))
        words = words[:cut]
        if words and word(words[0]) in ARG_MODES:
            if word(words[0]) == "out":
                continue
            words = words[1:]
        has_name = (len(words) >= 2 and words[0].kind in ("ident", "qident") and words[1].text != "."
                    and ident_name(words[0]) not in TYPE_FIRST_WORDS)
        if has_name:
            words = words[1:]
        rendered = " ".join(t.text.lower() for t in words)
        rendered = re.sub(r"\s*([.()\[\],])\s*", r"\1", rendered)
        types.append(re.sub(r"^public\.", "", rendered))
    return tuple(types)


def latest_definitions(sources):
    latest = {}
    for file, text in sources:
        defs, drops = find_function_defs(text, file)
        events = [(d.start, "def", d) for d in defs] + [(p[3], "drop", p) for p in drops]
        for _, kind, item in sorted(events, key=lambda e: e[0]):
            if kind == "def":
                latest[(item.schema, item.name, arg_types(item.args))] = item
            else:
                schema, name, types, _ = item
                for key in [k for k in latest if k[0] == schema and k[1] == name and (types is None or k[2] == types)]:
                    del latest[key]
    return latest


def parse_function_arg(value):
    parts = [p.strip().strip('"') for p in value.split(".")]
    if len(parts) == 1:
        return "public", parts[0].lower()
    if len(parts) == 2:
        return parts[0].lower(), parts[1].lower()
    raise ToolError(f"bad --function value: {value!r} (expected schema.name or name)")


def select_functions(latest, wanted):
    chosen = []
    for schema, name in wanted:
        hits = [d for k, d in sorted(latest.items()) if k[0] == schema and k[1] == name]
        if not hits:
            raise ToolError(f"function {schema}.{name} not found in the migrations (or dropped later)")
        chosen.extend(hits)
    return chosen


def functions_in_text(text, file):
    defs, _ = find_function_defs(text, file)
    return {(d.schema, d.name) for d in defs}


Mutant = namedtuple("Mutant", "operator start end replacement description")


def operand_start(sig, idx):
    j = idx
    while j >= 0:
        t = sig[j]
        if t.text == ")":
            depth = 0
            while j >= 0:
                if sig[j].text == ")":
                    depth += 1
                elif sig[j].text == "(":
                    depth -= 1
                    if depth == 0:
                        break
                j -= 1
            if j > 0 and sig[j - 1].kind in ("ident", "qident"):
                j -= 1
        elif t.kind not in ("ident", "qident", "param", "num", "str"):
            return None
        while j >= 2 and sig[j - 1].text == "." and sig[j - 2].kind in ("ident", "qident"):
            j -= 2
        if j >= 2 and sig[j - 1].text == "::":
            j -= 2
            continue
        return j
    return None


def statement_end(sig, idx):
    depth = 0
    for j in range(idx, len(sig)):
        if sig[j].text == "(":
            depth += 1
        elif sig[j].text == ")":
            depth -= 1
        elif sig[j].text == ";" and depth <= 0:
            return j
    return None


def condition_end(sig, idx):
    depth = 0
    stops = {"and", "or", "then", "loop", "order", "group", "limit", "for", "returning", "into", "union",
             "having", "window", "offset", "fetch", "except", "intersect", "end", "when", "else"}
    for j in range(idx, len(sig)):
        t = sig[j]
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            if depth == 0:
                return j
            depth -= 1
        elif depth == 0 and (t.text in (";", ",") or word(t) in stops):
            return j
    return len(sig)


def gen_null_guards(sig, text):
    out = []
    for i, t in enumerate(sig):
        if word(t) != "is" or i == 0:
            continue
        negated = i + 2 < len(sig) and word(sig[i + 1]) == "not" and word(sig[i + 2]) == "null"
        plain = i + 1 < len(sig) and word(sig[i + 1]) == "null"
        if not (negated or plain):
            continue
        s = operand_start(sig, i - 1)
        if plain:
            out.append(Mutant("null-guard-negated", t.start, sig[i + 1].end, "is not null",
                              "is null -> is not null"))
            if s is not None:
                out.append(Mutant("null-guard-removed", sig[s].start, sig[i + 1].end, "false",
                                  f"{text[sig[s].start:sig[i + 1].end]} -> false"))
        else:
            out.append(Mutant("null-guard-negated", t.start, sig[i + 2].end, "is null", "is not null -> is null"))
    return out


def gen_boundary(sig, text):
    return [Mutant("boundary", t.start, t.end, BOUNDARY_SWAP[t.text], f"{t.text} -> {BOUNDARY_SWAP[t.text]}")
            for t in sig if t.kind == "op" and t.text in BOUNDARY_SWAP]


def bump_interval_literal(literal):
    m = re.search(r"\d+", literal)
    if not m:
        return None
    value = int(m.group(0))
    new = value * 2 if value else 1
    return literal[:m.start()] + str(new) + literal[m.end():]


def gen_constants(sig, text):
    out = []
    for i, t in enumerate(sig):
        if t.kind == "str" and not t.text[:1] in "eE":
            is_interval = (i > 0 and word(sig[i - 1]) == "interval") or (
                i + 2 < len(sig) and sig[i + 1].text == "::" and word(sig[i + 2]) == "interval")
            if is_interval:
                new = bump_interval_literal(t.text)
                if new:
                    out.append(Mutant("time-constant", t.start, t.end, new, f"{t.text} -> {new}"))
        if t.kind == "num" and t.text.isdigit():
            prev_t = sig[i - 1] if i > 0 else None
            next_t = sig[i + 1] if i + 1 < len(sig) else None
            in_comparison = (prev_t is not None and prev_t.kind == "op" and prev_t.text in BOUNDARY_SWAP) or (
                next_t is not None and next_t.kind == "op" and next_t.text in BOUNDARY_SWAP)
            in_limit = word(prev_t) == "limit"
            if in_comparison or in_limit:
                value = int(t.text)
                for new in (value + 1, value - 1):
                    if new >= 0:
                        out.append(Mutant("limit-constant", t.start, t.end, str(new), f"{t.text} -> {new}"))
    return out


def gen_filters(sig, text, scope_columns, role_columns):
    out = []
    for i, t in enumerate(sig):
        if t.kind not in ("ident", "qident"):
            continue
        name = ident_name(t)
        if name in scope_columns:
            operator = "scope-filter-removed"
        elif name in role_columns:
            operator = "role-filter-removed"
        else:
            continue
        if i + 1 >= len(sig) or not ((sig[i + 1].kind == "op" and sig[i + 1].text == "=") or word(sig[i + 1]) == "in"):
            continue
        j = i
        while j >= 2 and sig[j - 1].text == "." and sig[j - 2].kind in ("ident", "qident"):
            j -= 2
        if j == 0 or word(sig[j - 1]) not in ("where", "and", "on", "or"):
            continue
        end = condition_end(sig, i + 1)
        if end <= i + 1:
            continue
        span_end = sig[end - 1].end
        out.append(Mutant(operator, sig[j].start, span_end, "true",
                          f"{' '.join(text[sig[j].start:span_end].split())} -> true"))
    return out


def gen_statement_removals(sig, text, audit_re, language):
    if language != "plpgsql":
        return []
    out = []
    for i, t in enumerate(sig):
        w = word(t)
        prev = sig[i - 1] if i else None
        at_statement_start = prev is None or prev.text == ";" or word(prev) in ("then", "else", "begin", "loop")
        if not at_statement_start:
            continue
        operator = None
        if w == "insert" and i + 2 < len(sig) and word(sig[i + 1]) == "into":
            parsed = parse_qualified_name(sig, i + 2)
            if parsed and audit_re.search(parsed[1]):
                operator = "audit-removed"
        elif w == "perform" and i + 1 < len(sig):
            parsed = parse_qualified_name(sig, i + 1)
            if parsed and audit_re.search(parsed[1]):
                operator = "audit-removed"
        elif w == "raise":
            level = word(sig[i + 1]) if i + 1 < len(sig) else None
            if level not in RAISE_NON_ERROR_LEVELS:
                operator = "raise-removed"
        if operator is None:
            continue
        end = statement_end(sig, i)
        if end is None:
            continue
        snippet = " ".join(text[t.start:sig[end].end].split())
        out.append(Mutant(operator, t.start, sig[end].end, "null;",
                          f"{snippet[:70]}{'...' if len(snippet) > 70 else ''} -> null;"))
    return out


def gen_and_or(sig, text):
    out = []
    i = 0
    while i < len(sig):
        w = word(sig[i])
        prev = word(sig[i - 1]) if i else None
        opens = (w in ("if", "elsif") and prev != "end") or (w == "when" and prev in ("exit", "continue"))
        if not opens:
            i += 1
            continue
        closer = "then" if w != "when" else ";"
        depth = 0
        pending_between = 0
        j = i + 1
        while j < len(sig):
            t = sig[j]
            if t.text == "(":
                depth += 1
            elif t.text == ")":
                depth -= 1
            elif depth == 0 and (word(t) == closer or t.text == closer or t.text == ";"):
                break
            elif word(t) == "between":
                pending_between += 1
            elif word(t) in ("and", "or"):
                if word(t) == "and" and pending_between:
                    pending_between -= 1
                else:
                    new = "or" if word(t) == "and" else "and"
                    out.append(Mutant("and-or-swap", t.start, t.end, new, f"{word(t)} -> {new}"))
            j += 1
        i = j
    return out


def gen_coalesce(sig, text):
    out = []
    for i, t in enumerate(sig):
        if word(t) != "coalesce" or i + 1 >= len(sig) or sig[i + 1].text != "(":
            continue
        close = matching_paren(sig, i + 1)
        if close is None:
            continue
        depth, first_comma = 0, None
        for j in range(i + 2, close):
            if sig[j].text == "(":
                depth += 1
            elif sig[j].text == ")":
                depth -= 1
            elif sig[j].text == "," and depth == 0:
                first_comma = j
                break
        if first_comma is None:
            continue
        first = text[sig[i + 2].start:sig[first_comma - 1].end]
        out.append(Mutant("coalesce-default-removed", t.start, sig[close].end, f"({first})",
                          f"{' '.join(text[t.start:sig[close].end].split())[:60]} -> ({first})"))
    return out


def generate_mutants(fdef, operators=OPERATORS, scope_columns=DEFAULT_SCOPE_COLUMNS,
                     role_columns=DEFAULT_ROLE_COLUMNS, audit_pattern=DEFAULT_AUDIT_PATTERN):
    body_text = fdef.text[fdef.body_start:fdef.body_end]
    sig = significant(lex(body_text, base=fdef.body_start))
    text = fdef.text
    audit_re = re.compile(audit_pattern, re.I)
    found = []
    found += gen_null_guards(sig, text)
    found += gen_boundary(sig, text)
    found += gen_constants(sig, text)
    found += gen_filters(sig, text, set(scope_columns), set(role_columns))
    found += gen_statement_removals(sig, text, audit_re, fdef.language)
    found += gen_and_or(sig, text)
    found += gen_coalesce(sig, text)
    seen, result = set(), []
    for m in sorted(found, key=lambda m: (m.start, m.operator, m.end)):
        key = (m.start, m.end, m.replacement)
        if m.operator in operators and key not in seen:
            seen.add(key)
            result.append(m)
    return result


HEADER_RE = re.compile(r"^\s*create\s+(?:or\s+replace\s+)?(function|procedure)", re.I)


def as_replace(statement):
    fixed, count = HEADER_RE.subn(lambda m: f"create or replace {m.group(1).lower()}", statement, count=1)
    if not count:
        raise ToolError("statement does not start with create function/procedure")
    return fixed if fixed.rstrip().endswith(";") else fixed + ";"


def original_ddl(fdef):
    return as_replace(fdef.text[fdef.start:fdef.end])


def mutated_ddl(fdef, mutant):
    text = fdef.text
    return as_replace(text[fdef.start:mutant.start] + mutant.replacement + text[mutant.end:fdef.end])


def function_label(fdef):
    return f"{fdef.schema}.{fdef.name}({fdef.args})"


class UnsupportedTest(ToolError):
    pass


def prepare_test(sql, name="test"):
    tokens = lex(sql, psql_meta=True)
    stmts = split_statements(tokens)
    for stmt in stmts:
        if len(stmt) == 1 and stmt[0].kind == "meta":
            cmd = stmt[0].text[1:].split(None, 1)[0] if stmt[0].text[1:].strip() else ""
            if cmd.lower() in FORBIDDEN_META or cmd.startswith("!"):
                raise UnsupportedTest(f"{name}: psql meta-command \\{cmd} is not allowed inside a mutation run")
    starts = [i for i, s in enumerate(stmts) if significant(s)]
    removed = []

    def is_tx(stmt, words):
        sig = significant(stmt)
        return sig and word(sig[0]) in words

    if starts:
        first = stmts[starts[0]]
        sig = significant(first)
        if word(sig[0]) == "begin" or (word(sig[0]) == "start" and len(sig) > 1 and word(sig[1]) == "transaction"):
            removed.append(starts[0])
    if starts:
        last = stmts[starts[-1]]
        sig = significant(last)
        if word(sig[0]) in ("rollback", "commit", "end", "abort") and not any(word(t) == "to" for t in sig):
            if starts[-1] not in removed:
                removed.append(starts[-1])
    for i in starts:
        if i in removed:
            continue
        sig = significant(stmts[i])
        w0 = word(sig[0])
        if w0 in TRANSACTION_WORDS:
            if w0 == "rollback" and any(word(t) == "to" for t in sig):
                continue
            if w0 == "start" and not (len(sig) > 1 and word(sig[1]) == "transaction"):
                continue
            if w0 == "end" and len(sig) > 1 and sig[1].text != ";" and word(sig[1]) not in ("work", "transaction"):
                continue
            line = line_of(sql, sig[0].start)
            raise UnsupportedTest(f"{name}:{line}: top-level `{w0}` would break the mutation transaction")
        if w0 in ("set",) and len(sig) > 2 and word(sig[1]) == "session" and word(sig[2]) == "characteristics":
            raise UnsupportedTest(f"{name}: `set session characteristics` is not supported")
    keep = []
    for i, stmt in enumerate(stmts):
        if i in removed:
            continue
        keep.append("".join(t.text for t in stmt))
    return "".join(keep)


def build_script(ddl, test_body, statement_timeout):
    return ("begin;\n"
            f"set local statement_timeout = '{int(statement_timeout)}s';\n"
            f"{ddl}\n"
            f"select '{DDL_MARKER}';\n"
            f"{test_body}\n"
            ";\nrollback;\n")


def classify(output):
    lines = output.splitlines()
    marker_seen = any(line.strip() == DDL_MARKER for line in lines)
    if not marker_seen:
        errors = [ln.strip() for ln in lines if "ERROR:" in ln]
        return "invalid", errors[0] if errors else "ddl marker missing"
    marker_at = next(i for i, ln in enumerate(lines) if ln.strip() == DDL_MARKER)
    for ln in lines[marker_at + 1:]:
        if FAIL_LINE_RE.search(ln):
            return "failed", ln.strip()
    return "passed", ""


def host_is_local(host):
    h = host.strip().strip("[]").lower()
    if h in LOCAL_HOSTS or h.startswith("/"):
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        pass
    return "." not in h and bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]*", h))


def db_url_hosts(url):
    if "://" not in url:
        fields = dict(re.findall(r"(\w+)\s*=\s*('(?:[^'\\]|\\.)*'|\S+)", url))
        if "service" in fields:
            raise ToolError("connection strings with service= are refused: pass an explicit local host")
        hosts = fields.get("host", "").strip("'")
        hostaddr = fields.get("hostaddr", "").strip("'")
        result = [h for h in hosts.split(",")] + ([hostaddr] if hostaddr else [])
        return result if (hosts or hostaddr) else [os.environ.get("PGHOST", "")]
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("postgres", "postgresql"):
        raise ToolError(f"unsupported URL scheme {parsed.scheme!r}")
    netloc = parsed.netloc.rsplit("@", 1)[-1]
    hosts = []
    for part in netloc.split(","):
        if part.startswith("["):
            hosts.append(part[1:part.index("]")])
        else:
            hosts.append(part.split(":", 1)[0])
    query = urllib.parse.parse_qs(parsed.query)
    if "service" in query:
        raise ToolError("connection strings with service= are refused: pass an explicit local host")
    for key in ("host", "hostaddr"):
        for value in query.get(key, []):
            hosts.extend(value.split(","))
    if all(not h for h in hosts):
        hosts.append(os.environ.get("PGHOST", ""))
    return hosts


def check_local_url(url):
    bad = [h for h in db_url_hosts(url) if not host_is_local(h)]
    if bad:
        raise ToolError(f"refusing non-local database host(s): {', '.join(bad)}; pgmutate only runs against a local DB")


def check_local_docker():
    docker_host = os.environ.get("DOCKER_HOST", "")
    if not docker_host or docker_host.startswith(("unix://", "npipe://")):
        return
    host = urllib.parse.urlsplit(docker_host).hostname or ""
    if not host_is_local(host):
        raise ToolError(f"refusing DOCKER_HOST={docker_host}: pgmutate only runs against a local DB")


def psql_command_for_url(url, psql):
    return [psql, "-X", "-q", "-At", "-v", "ON_ERROR_STOP=0", "-d", url, "-f", "-"]


def psql_command_for_container(container):
    return ["docker", "exec", "-i", "-e", "PGCLIENTENCODING=UTF8", container, "psql", "-X", "-q", "-At", "-v", "ON_ERROR_STOP=0",
            "-U", "postgres", "-d", "postgres", "-f", "-"]


def supabase_project_id(root):
    path = os.path.join(root, "supabase", "config.toml")
    if not os.path.exists(path):
        return None
    m = re.search(r'^\s*project_id\s*=\s*"([^"]+)"', open(path, encoding="utf-8").read(), re.M)
    return m.group(1) if m else None


def resolve_connection(args):
    if args.db_url and args.container:
        raise ToolError("use either --db-url or --container, not both")
    if args.db_url:
        check_local_url(args.db_url)
        if not shutil.which(args.psql):
            raise ToolError(f"{args.psql} not found on PATH; install psql or use --container")
        return psql_command_for_url(args.db_url, args.psql), f"url {args.db_url}"
    if args.container:
        check_local_docker()
        return psql_command_for_container(args.container), f"container {args.container}"
    if shutil.which(args.psql) and shutil.which("supabase"):
        try:
            out = subprocess.run(["supabase", "status", "-o", "env"], cwd=args.root, capture_output=True,
                                 text=True, timeout=60).stdout
            m = re.search(r'^DB_URL="?([^"\n]+)"?', out, re.M)
            if m:
                check_local_url(m.group(1))
                return psql_command_for_url(m.group(1), args.psql), "supabase status DB_URL"
        except (OSError, subprocess.TimeoutExpired):
            pass
    if shutil.which("docker"):
        check_local_docker()
        names = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True,
                               timeout=60).stdout.split()
        project = supabase_project_id(args.root)
        if project and f"supabase_db_{project}" in names:
            name = f"supabase_db_{project}"
            return psql_command_for_container(name), f"container {name}"
        candidates = [n for n in names if n.startswith("supabase_db_")]
        if len(candidates) == 1:
            return psql_command_for_container(candidates[0]), f"container {candidates[0]}"
    raise ToolError("no local database found: start it (supabase start) or pass --db-url / --container")


def make_runner(command, timeout):
    def run(script):
        try:
            p = subprocess.run(command, input=script.encode("utf-8"), capture_output=True, timeout=timeout,
                               env=dict(os.environ, PGCLIENTENCODING="UTF8"))
        except subprocess.TimeoutExpired:
            return None
        except OSError as e:
            raise ToolError(f"could not run {command[0]}: {e}")
        out = p.stdout.decode("utf-8", "replace") + "\n" + p.stderr.decode("utf-8", "replace")
        if p.returncode != 0:
            raise ToolError(f"psql exited {p.returncode}: {out.strip()[:500]}")
        return out
    return run


def fingerprint_sql(fdefs):
    pairs = sorted({(f.schema, f.name) for f in fdefs})
    cond = " or ".join(
        "(n.nspname = '{}' and p.proname = '{}')".format(s.replace("'", "''"), n.replace("'", "''")) for s, n in pairs)
    return ("select 'PGMUTATE_FP ' || coalesce(md5(string_agg(pg_get_functiondef(p.oid), E'\\n' order by p.oid)), '') "
            f"from pg_proc p join pg_namespace n on n.oid = p.pronamespace where {cond};\n")


def fingerprint(runner, fdefs):
    out = runner(fingerprint_sql(fdefs))
    if out is None:
        raise ToolError("timed out reading function fingerprints")
    m = re.search(r"PGMUTATE_FP (\S*)", out)
    if not m:
        raise ToolError(f"could not read function fingerprints: {out.strip()[:300]}")
    return m.group(1)


def run_mutant(runner, ddl, tests, statement_timeout, all_tests=False):
    killers = []
    for name, body in tests:
        out = runner(build_script(ddl, body, statement_timeout))
        if out is None:
            killers.append((name, "timeout"))
            if not all_tests:
                return "timeout", killers
            continue
        verdict, detail = classify(out)
        if verdict == "invalid":
            return "invalid", [(name, detail)]
        if verdict == "failed":
            killers.append((name, detail))
            if not all_tests:
                return "killed", killers
    if killers:
        return ("killed" if any(d != "timeout" for _, d in killers) else "timeout"), killers
    return "survived", []


def run_baseline(runner, fdefs, tests, statement_timeout):
    ddl = "\n".join(original_ddl(f) for f in fdefs)
    problems = []
    for name, body in tests:
        out = runner(build_script(ddl, body, statement_timeout))
        if out is None:
            problems.append(f"{name}: timeout")
            continue
        verdict, detail = classify(out)
        if verdict != "passed":
            problems.append(f"{name}: {verdict}: {detail}")
    return problems


def collect_mutants(fdefs, operators, scope_columns, role_columns, audit_pattern, root):
    rows = []
    for f in fdefs:
        for m in generate_mutants(f, operators, scope_columns, role_columns, audit_pattern):
            rel = os.path.relpath(f.file, root) if os.path.isabs(f.file) else f.file
            rows.append({
                "id": f"M{len(rows) + 1:03d}",
                "function": function_label(f),
                "operator": m.operator,
                "file": rel.replace("\\", "/"),
                "line": line_of(f.text, m.start),
                "change": m.description,
                "status": "pending",
                "killed_by": None,
                "detail": None,
                "_fdef": f,
                "_mutant": m,
            })
    return rows


def run_all(rows, fdefs, tests, runner, statement_timeout, all_tests=False, progress=None):
    before = fingerprint(runner, fdefs)
    problems = run_baseline(runner, fdefs, tests, statement_timeout)
    if problems:
        raise ToolError("baseline failed (unmutated functions): " + "; ".join(problems[:5]))
    for row in rows:
        status, killers = run_mutant(runner, mutated_ddl(row["_fdef"], row["_mutant"]), tests, statement_timeout,
                                     all_tests)
        row["status"] = status
        if killers:
            row["killed_by"] = ", ".join(k for k, _ in killers) if status != "invalid" else None
            row["detail"] = killers[0][1]
        if progress:
            progress(row)
    after = fingerprint(runner, fdefs)
    if before != after:
        raise IntegrityError(f"function fingerprint changed during the run ({before} -> {after}); "
                             "the database was modified: run `supabase db reset` and report this")
    return rows


def summarize(rows):
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("killed", "survived", "invalid", "timeout", "pending")}
    scored = counts["killed"] + counts["survived"] + counts["timeout"]
    counts["score"] = round(100.0 * (counts["killed"] + counts["timeout"]) / scored, 1) if scored else None
    return counts


def format_table(rows, columns):
    headers = [c[0] for c in columns]
    data = [[str(c[1](r)) if c[1](r) is not None else "" for c in columns] for r in rows]
    widths = [max([len(h)] + [len(d[i]) for d in data]) for i, h in enumerate(headers)]
    widths = [min(w, 70) for w in widths]
    lines = [" | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)),
             "-+-".join("-" * w for w in widths)]
    for d in data:
        lines.append(" | ".join(v[:widths[i]].ljust(widths[i]) for i, v in enumerate(d)))
    return "\n".join(lines)


def table_columns(listing):
    cols = [("id", lambda r: r["id"]), ("function", lambda r: r["function"].split("(")[0]),
            ("operator", lambda r: r["operator"]), ("line", lambda r: f'{r["file"]}:{r["line"]}'),
            ("change", lambda r: r["change"])]
    if not listing:
        cols += [("status", lambda r: r["status"]), ("killing test", lambda r: r["killed_by"])]
    return cols


def public_rows(rows):
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]


def git(root, *args):
    p = subprocess.run(["git", "-C", root, *args], capture_output=True)
    if p.returncode != 0:
        raise ToolError(f"git {' '.join(args)} failed: {p.stderr.decode('utf-8', 'replace').strip()}")
    return p.stdout.decode("utf-8", "replace")


def load_sources_fs(sql_dir):
    files = sorted(glob.glob(os.path.join(sql_dir, "*.sql")))
    if not files:
        raise ToolError(f"no .sql files in {sql_dir}")
    return [(f, open(f, encoding="utf-8").read()) for f in files]


def load_sources_git(root, rev, sql_dir_rel):
    names = git(root, "ls-tree", "-r", "--name-only", rev, "--", sql_dir_rel.rstrip("/") + "/").split("\n")
    names = sorted(n for n in names if n.endswith(".sql") and os.path.dirname(n) == sql_dir_rel.rstrip("/"))
    if not names:
        raise ToolError(f"no .sql files under {sql_dir_rel} at {rev}")
    return [(n, git(root, "show", f"{rev}:{n}")) for n in names]


def changed_functions(root, rev_from, rev_to, sql_dir_rel):
    changed = git(root, "diff", "--name-only", "--diff-filter=AM", rev_from, rev_to, "--",
                  sql_dir_rel.rstrip("/") + "/").split()
    names = set()
    for path in changed:
        if path.endswith(".sql"):
            names |= functions_in_text(git(root, "show", f"{rev_to}:{path}"), path)
    return sorted(names)


def load_tests(root, patterns):
    files = []
    for pattern in patterns:
        full = pattern if os.path.isabs(pattern) else os.path.join(root, pattern)
        files.extend(sorted(glob.glob(full, recursive=True)))
    seen, tests = set(), []
    for f in files:
        if f in seen:
            continue
        seen.add(f)
        rel = os.path.relpath(f, root).replace("\\", "/")
        tests.append((rel, prepare_test(open(f, encoding="utf-8").read(), rel)))
    if not tests:
        raise ToolError(f"no pgTAP test files matched {patterns}")
    return tests


def build_parser():
    p = argparse.ArgumentParser(
        prog="pgmutate.py",
        description="Mutation testing for Postgres/Supabase SQL functions against the project's pgTAP suite, "
                    "on a LOCAL database, every mutant inside begin ... rollback.",
        epilog=HELP_EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=".", help="project root (default: current directory)")
    p.add_argument("--function", action="append", default=[], metavar="SCHEMA.NAME",
                   help="function to mutate (repeatable; schema defaults to public; all overloads)")
    p.add_argument("--from", dest="rev_from", metavar="REV",
                   help="discover functions created/replaced in migration files changed in REV..--to")
    p.add_argument("--to", dest="rev_to", metavar="REV",
                   help="end of the discovery range, also the revision the SQL is read from (default HEAD with --from)")
    p.add_argument("--sql-dir", default="supabase/migrations",
                   help="directory with the migration files, applied in name order (default supabase/migrations)")
    p.add_argument("--tests", action="append", default=[], metavar="GLOB",
                   help="pgTAP test files, relative to --root (repeatable; default supabase/tests/**/*.sql)")
    p.add_argument("--operators", help="comma-separated subset of: " + ", ".join(OPERATORS))
    p.add_argument("--scope-column", action="append", default=[],
                   help="tenant/scope column for scope-filter-removed (repeatable; replaces the default list: "
                        + ", ".join(DEFAULT_SCOPE_COLUMNS) + ")")
    p.add_argument("--role-column", action="append", default=[],
                   help="role/permission column for role-filter-removed (repeatable; replaces the default list: "
                        + ", ".join(DEFAULT_ROLE_COLUMNS) + ")")
    p.add_argument("--audit-pattern", default=DEFAULT_AUDIT_PATTERN,
                   help=f"regex on the table (insert into) or function (perform) name for audit-removed "
                        f"(default {DEFAULT_AUDIT_PATTERN!r})")
    p.add_argument("--db-url", help="local postgres URL (psql on PATH)")
    p.add_argument("--container", help="local docker container running postgres (e.g. supabase_db_<project>)")
    p.add_argument("--psql", default="psql", help="psql executable for --db-url (default psql)")
    p.add_argument("--timeout", type=int, default=120, help="seconds per psql run (default 120)")
    p.add_argument("--statement-timeout", type=int, default=30, help="statement_timeout in seconds (default 30)")
    p.add_argument("--all-tests", action="store_true",
                   help="run every test file for every mutant and list all killers (default: stop at the first)")
    p.add_argument("--list", action="store_true", help="only list the mutants, do not touch the database")
    p.add_argument("--max-mutants", type=int, help="cap on the number of mutants run")
    p.add_argument("--json", action="store_true", help="print JSON instead of the table")
    p.add_argument("--fail-on-survivors", action="store_true", help="exit 1 when any mutant survives")
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    args.root = os.path.abspath(args.root)
    try:
        operators = OPERATORS
        if args.operators:
            operators = tuple(o.strip() for o in args.operators.split(",") if o.strip())
            unknown = [o for o in operators if o not in OPERATORS]
            if unknown:
                raise ToolError(f"unknown operator(s): {', '.join(unknown)}")
        sql_dir_rel = os.path.relpath(os.path.join(args.root, args.sql_dir), args.root).replace("\\", "/")
        if args.rev_from and not args.rev_to:
            args.rev_to = "HEAD"
        if args.rev_to:
            sources = load_sources_git(args.root, args.rev_to, sql_dir_rel)
        else:
            sources = load_sources_fs(os.path.join(args.root, args.sql_dir))
        wanted = [parse_function_arg(v) for v in args.function]
        if args.rev_from:
            wanted += [w for w in changed_functions(args.root, args.rev_from, args.rev_to, sql_dir_rel) if w not in wanted]
        if not wanted:
            raise ToolError("nothing to mutate: pass --function or --from/--to")
        latest = latest_definitions(sources)
        present = [w for w in wanted if any(k[0] == w[0] and k[1] == w[1] for k in latest)]
        skipped = [w for w in wanted if w not in present]
        if args.function:
            explicit = {parse_function_arg(v) for v in args.function}
            missing = [w for w in skipped if w in explicit]
            if missing:
                select_functions(latest, missing)
        fdefs = select_functions(latest, present)
        rows = collect_mutants(fdefs, operators, tuple(args.scope_column) or DEFAULT_SCOPE_COLUMNS,
                               tuple(args.role_column) or DEFAULT_ROLE_COLUMNS, args.audit_pattern, args.root)
        if args.max_mutants is not None:
            rows = rows[:args.max_mutants]
        notes = [f"skipped {s}.{n}: dropped later in the migrations" for s, n in skipped]
        if args.list:
            if args.json:
                print(json.dumps({"functions": [function_label(f) for f in fdefs], "notes": notes,
                                  "mutants": public_rows(rows)}, indent=2, ensure_ascii=False))
            else:
                for note in notes:
                    print(note)
                print(format_table(rows, table_columns(True)))
                print(f"\n{len(rows)} mutants in {len(fdefs)} function(s)")
            return 0
        tests = load_tests(args.root, args.tests or ["supabase/tests/**/*.sql"])
        command, how = resolve_connection(args)
        runner = make_runner(command, args.timeout)
        progress = None if args.json else (lambda r: print(f"  {r['id']} {r['status']}", file=sys.stderr, flush=True))
        if not args.json:
            print(f"pgmutate: {len(rows)} mutants, {len(fdefs)} function(s), {len(tests)} test file(s), via {how}",
                  file=sys.stderr)
        run_all(rows, fdefs, tests, runner, args.statement_timeout, args.all_tests, progress)
        summary = summarize(rows)
        if args.json:
            print(json.dumps({"functions": [function_label(f) for f in fdefs], "tests": [t for t, _ in tests],
                              "notes": notes, "summary": summary, "mutants": public_rows(rows)},
                             indent=2, ensure_ascii=False))
        else:
            for note in notes:
                print(note)
            print(format_table(rows, table_columns(False)))
            print(f"\nkilled {summary['killed']}, survived {summary['survived']}, timeout {summary['timeout']}, "
                  f"invalid {summary['invalid']}; score {summary['score']}%")
        return 1 if args.fail_on_survivors and summary["survived"] else 0
    except IntegrityError as e:
        print(f"pgmutate: INTEGRITY FAILURE: {e}", file=sys.stderr)
        return 3
    except ToolError as e:
        print(f"pgmutate: error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
