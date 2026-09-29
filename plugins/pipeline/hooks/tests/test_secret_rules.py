import importlib.util, os

spec = importlib.util.spec_from_file_location("scan", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pre-commit-secret-scan.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
q = lambda value: '"' + value + '"'
# secret-looking values are split so this file's own lines do not trip the scanner
must_flag = {
    "quoted password literal": "+password = " + q("S3cr3tP4ss" "w0rd!2026"),
    "quoted password literal, colon form": "+  password: " + q("Tr0ub4dor&" "3xyz"),
    "quoted long lowercase token": "+token = " + q("abcdefghijkl" "mnopqrstuv1234"),
    "unquoted mixed-case value": "+API_KEY=" + "AbC123dEf4" "56GhI789jKl",
    "unquoted high-digit snake value": "+secret = " + "a8f3e9_1c2d4b" "5e6f7a8b9c",
    "second assignment on the line": "+const a = { password: foo, token: " + q("Zx9Qw8Er7T" "y6Ui5Op4") + " }",
    "SQL literal password": "+update auth.users set encrypted_password = " + q("S3cr3tP4ss" "w0rd!2026") + ";",
    "unquoted alternating-case run": "+to" "ken: " + "xKqPzLmNvB" "rTwYaSdFgH",
    "unquoted upper-case run": "+API_TO" "KEN=" + "QWERTYUIOPAS" "DFGHJKLZXCVB",
    "unquoted lower-case run": "+api_k" "ey: " + "abcdefghijklmn" "opqrstuvwxyzab",
    "underscored passphrase under a password key": "+pass" "word: " + "correct_horse_" "battery_staple",
    "quoted value that only starts with a placeholder word": "+sec" "ret: " + q("example-real-" "QnX8m2Kp9Lz"),
    "random snake-shaped value": "+api_k" "ey = " + "xkqpzl_mnvbrt_" "wyasdf",
}
must_pass = {
    "A9 SQL self-assignment": "+update auth.users set encrypted_pass" "word = encrypted_password where id = '00000000-0000-0000-0000-000000000001';",
    "self-assignment, other column": "+  service_role_to" "ken = service_role_token,",
    "column from a qualified name": "+set encrypted_password = t.encrypted_password",
    "upsert excluded column": "+on conflict (id) do update set encrypted_password = excluded.encrypted_password",
    "snake_case identifier": "+pass" "word = new_password_value",
    "SQL keyword": "+password_changed_at = current_timestamp",
    "SQL keyword upper case": "+ACCESS_TO" "KEN = CURRENT_TIMESTAMP",
    "camelCase variable": "+const pass" "word = hashedPasswordValue;",
    "SCREAMING constant": "+API_K" "EY = DEFAULT_API_KEY_NAME",
    "process.env": "+const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY",
    "process.env bracket": "+const token = process.env['GITHUB_TOKEN_VALUE']",
    "${VAR} unquoted": "+password: ${DB_PASSWORD_FROM_ENV}",
    "${VAR} quoted": "+password: " + q("${DB_PASSWORD_FROM_ENV}"),
    "$VAR": "+DB_PASSWORD=$POSTGRES_PASSWORD_VALUE",
    "os.environ": "+secret = os.environ[" + q("APP_SECRET_KEY_VALUE") + "]",
    "os.getenv": "+api_key = os.getenv(" + q("OPENAI_API_KEY_VALUE") + ")",
    "import.meta.env": "+const apiKey = import.meta.env.VITE_PUBLIC_API_KEY",
    "Windows %VAR%": "+set API_KEY=%MY_API_KEY_FROM_ENV%",
    "templated quoted": "+token: " + q("{{ secrets.DEPLOY_TOKEN_VALUE }}"),
    "placeholder": "+API_KEY=" + q("your-api-key-goes-here"),
    "short quoted": "+password: " + q("changeme"),
    "angle-bracket placeholder": "+api_k" "ey: " + q("<your-api-key-here>"),
    "all-x placeholder": "+to" "ken: " + q("xxxxxxxxxxxx" "xxxxxxxx"),
    "camelCase value under a key": "+api_k" "ey: " + "publishableKey" "FromSettings",
    "snake value under a password key naming a code word": "+pass" "word = " + "user_input_" "value",
    "quoted prose": "+password: " + q("Senha incorreta, tente de novo"),
}
results = []
for name, line in must_flag.items():
    ok = bool(m.scan(line, []))
    results.append(ok)
    print("PASS" if ok else "FAIL", "flags:", name)
for name, line in must_pass.items():
    findings = m.scan(line, [])
    ok = not findings
    results.append(ok)
    print("PASS" if ok else "FAIL", "allows:", name, "" if ok else findings)

flagged = "+password = " + q("S3cr3tP4ss" "w0rd!2026")
mark = m.fingerprint(None, flagged[1:])
findings = m.scan(flagged, [])
ok = len(findings) == 1 and f"fingerprint {mark}" in findings[0]
results.append(ok)
print("PASS" if ok else "FAIL", "finding carries the line fingerprint", findings)
ok = m.fingerprint(None, "  password  =\t" + q("S3cr3tP4ss" "w0rd!2026") + "  ") == mark
results.append(ok)
print("PASS" if ok else "FAIL", "fingerprint ignores whitespace differences")
other = "+token = " + q("abcdefghijkl" "mnopqrstuv1234")
findings = m.scan(flagged + "\n" + other, [], {mark})
ok = len(findings) == 1 and m.fingerprint(None, other[1:]) in findings[0]
results.append(ok)
print("PASS" if ok else "FAIL", "allowlist suppresses only the matching line", findings)
diff = "+++ b/src/db.sql\n" + flagged
findings = m.scan(diff, [])
ok = len(findings) == 1 and " in src/db.sql " in findings[0]
results.append(ok)
print("PASS" if ok else "FAIL", "finding names the file", findings)
ok = m.fingerprint("src/a.sql", flagged[1:]) != m.fingerprint("src/b.sql", flagged[1:])
results.append(ok)
print("PASS" if ok else "FAIL", "fingerprint depends on the file path")
two = "+++ b/src/a.sql\n" + flagged + "\n+++ b/src/b.sql\n" + flagged
findings = m.scan(two, [], {m.fingerprint("src/a.sql", flagged[1:])})
ok = len(findings) == 1 and " in src/b.sql " in findings[0]
results.append(ok)
print("PASS" if ok else "FAIL", "an entry for one file does not cover the same line in another", findings)
print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
