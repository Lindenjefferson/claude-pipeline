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
    "unquoted password with symbols, YAML": "+POSTGRES_PASS" "WORD: " + "Pr0d#Db!" "2024x",
    "unquoted password with symbols, properties": "+spring.datasource.pass" "word=" + "Pr0d#Db!" "2024x",
    "unquoted secret with symbols": "+client_sec" "ret: " + "Xk#29fLq" "81!Zp",
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
    "unquoted kebab phrase under a password key": "+# pass" "word: min-12-chars",
    "unquoted call under a password key": "+pass" "word: z.string().min(12, " + q("Senha#Fraca1") + ")",
    "unquoted regex under a password key": "+pass" "word: ^(?=.*[A-Z])(?=.*#).{12,}$",
    "unquoted URL under a secret key": "+sec" "ret: https://vault.example.com/kv#app-2024",
    "unquoted short password": "+pass" "word: Senha@123",
    "unquoted templated secret": "+sec" "ret: ${{ secrets.DEPLOY_KEY_2024 }}",
    "unquoted symbols under a key that is not a password": "+api_key_label: " + "Pr0d#Db!" "2024x",
    "type annotation under a password key": "+    pass" "word: Optional[str] = None",
    "annotated parameter": "+def login(username: str, pass" "word: Optional[str] = None):",
    "annotated field": "+    pass" "word: Annotated[str, Field(min_length=8)]",
    "generic type under a secret key": "+  sec" "ret: Record<string, string>;",
    "subscript under a password key": "+pass" "word = request.POST[" + q("password") + "]",
    "nested subscript": "+    pass" "word=settings.DATABASES['default']['PASSWORD'],",
    "qualified name with ::": "+  pass" "word: Faker::Internet.password",
    "optional chaining": "+pass" "word = userInput?.Password",
    "member access with a non-null mark": "+this.pass" "word = this.loginForm.value.Password!;",
}
results = []
hunk = lambda text: f"@@ -0,0 +1,{text.count(chr(10)) + 1} @@\n" + text
for name, line in must_flag.items():
    ok = bool(m.scan(hunk(line), []))
    results.append(ok)
    print("PASS" if ok else "FAIL", "flags:", name)
for name, line in must_pass.items():
    findings = m.scan(hunk(line), [])
    ok = not findings
    results.append(ok)
    print("PASS" if ok else "FAIL", "allows:", name, "" if ok else findings)

flagged = "+password = " + q("S3cr3tP4ss" "w0rd!2026")
mark = m.fingerprint(None, flagged[1:])
findings = m.scan(hunk(flagged), [])
ok = len(findings) == 1 and f"fingerprint {mark}" in findings[0]
results.append(ok)
print("PASS" if ok else "FAIL", "finding carries the line fingerprint", findings)
ok = m.fingerprint(None, "  password  =\t" + q("S3cr3tP4ss" "w0rd!2026") + "  ") == mark
results.append(ok)
print("PASS" if ok else "FAIL", "fingerprint ignores whitespace differences")
other = "+token = " + q("abcdefghijkl" "mnopqrstuv1234")
findings = m.scan(hunk(flagged + "\n" + other), [], {mark})
ok = len(findings) == 1 and m.fingerprint(None, other[1:]) in findings[0]
results.append(ok)
print("PASS" if ok else "FAIL", "allowlist suppresses only the matching line", findings)
diff = "+++ b/src/db.sql\n" + hunk(flagged)
findings = m.scan(diff, [])
ok = len(findings) == 1 and " in src/db.sql " in findings[0]
results.append(ok)
print("PASS" if ok else "FAIL", "finding names the file", findings)
ok = m.fingerprint("src/a.sql", flagged[1:]) != m.fingerprint("src/b.sql", flagged[1:])
results.append(ok)
print("PASS" if ok else "FAIL", "fingerprint depends on the file path")
two = "+++ b/src/a.sql\n" + hunk(flagged) + "\n+++ b/src/b.sql\n" + hunk(flagged)
findings = m.scan(two, [], {m.fingerprint("src/a.sql", flagged[1:])})
ok = len(findings) == 1 and " in src/b.sql " in findings[0]
results.append(ok)
print("PASS" if ok else "FAIL", "an entry for one file does not cover the same line in another", findings)
inside = "+++ b/src/x.txt\n@@ -0,0 +1,2 @@\n+++ " + "AKIAABCDEF" "GHIJKLMNOP\n+ok"
findings = m.scan(inside, [])
ok = len(findings) == 1 and " in src/x.txt " in findings[0]
results.append(ok)
print("PASS" if ok else "FAIL", "an added line that starts with ++ is content, not a file header", findings)
context = "+++ b/src/y.txt\n@@ -1,2 +1,3 @@\n kept\n-gone\n+" + "AKIAABCDEF" "GHIJKLMNOP\n kept too"
findings = m.scan(context, [])
ok = len(findings) == 1 and " in src/y.txt " in findings[0]
results.append(ok)
print("PASS" if ok else "FAIL", "context and removed lines are counted by the hunk header", findings)
wide = "+++ b/cfg.txt\n@@ -0,0 +1 @@\n+" + "".join(c + "\0" for c in "KEY=AKIAABCDEF" "GHIJKLMNOP")
findings = m.scan(wide, [])
ok = len(findings) == 1
results.append(ok)
print("PASS" if ok else "FAIL", "a UTF-16 line (a NUL after every character) is scanned", findings)
print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
