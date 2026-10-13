import base64, importlib.util, json, os

spec = importlib.util.spec_from_file_location("scan", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pre-commit-secret-scan.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
hdr = b64({"alg": "HS256", "typ": "JWT"})
sig = "k3J9xQmZ2pVw8sTnLd4aYb6cRfUoHe1i"
service = f"{hdr}.{b64({'role': 'service_role', 'iss': 'supabase'})}.{sig}"
anon = f"{hdr}.{b64({'role': 'anon', 'iss': 'supabase'})}.{sig}"
user = f"{hdr}.{b64({'sub': 'abc-123', 'role': 'authenticated'})}.{sig}"
must_flag = {
    "JWT service_role in serviceRoleKey": f'+const serviceRoleKey = "{service}";',
    "SUPABASE_SERVICE_ROLE_KEY=": f"+SUPABASE_SERVICE_ROLE_KEY={service}",
    "user JWT": f'+const t = "{user}";',
    "bare JWT": f"+{service}",
    "sb_secret_": '+const k = "sb_secret_AbCdEfGhIjKlMnOpQrStUvWxYz012345";',
    "Stripe sk_live": '+const s = "sk_live_51H8xXxXxXxXxXxXxXxXxXxXx";',
    "Anthropic key": "+ANTHROPIC_API_KEY=sk-ant-api03-AbCdEfGhIjKlMnOpQrStUv",
    "remote DB URL with password": "+DATABASE_URL=postgresql://postgres:S3nh4Forte99@db.abcdefgh.supabase.co:5432/postgres",
    "AWS": '+key = "AKIAABCDEFGHIJKLMNOP"',
    "OpenAI key": "+OPENAI_API_KEY=sk-proj-AbCdEfGhIjKlMnOpQrStUvWx",
    "OpenAI legacy key": '+const k = "sk-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcd";',
    "Google API key": '+const g = "AIzaSyA-1234567890abcdefghijklmnopqrstu";',
    "xAI key": "+XAI_API_KEY=xai-AbCdEfGhIjKlMnOpQrStUvWxYz0123",
    "GitHub fine-grained token": "+GH=github_pat_11ABCDEFG0abcdefghijkl_mnopqrstuvwxyz0123456789",
    "Linear key": "+LINEAR=lin_api_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
    "Stripe webhook secret": "+whsec_AbCdEfGhIjKlMnOpQrStUvWxYz012345",
    "token = value": '+token = "abcdefghijklmnopqrstuv1234"',
    "unquoted .env value": "+API_KEY=AbC123dEf456GhI789jKl",
    "unquoted token = value": "+token = abcdefghijklmnopqrstuv1234",
    "quoted dotted literal": '+api_key: "abc.def.ghi.jkl.mno.pqr"',
    "remote Redis URL with password": "+REDIS_URL=redis://default:Xk29fLq81@cache.example.com:6379",
}
must_pass = {
    "anon JWT (public by design)": f"+NEXT_PUBLIC_SUPABASE_ANON_KEY={anon}",
    "local Supabase URL": "+DATABASE_URL=postgresql://postgres:postgres@localhost:54322/postgres",
    "127.0.0.1 URL": "+postgres://postgres:postgres@127.0.0.1:54322/postgres",
    "short example password": '+password: "changeme"',
    "prose about a token": "+O token do convite expira em 7 dias e a service role key nunca vai ao cliente.",
    "prose with sk- inside a word": "+o disk-based cache e o task-runner usam sk-learn como exemplo",
    "plain word starting with lin_api": "+function lin_api_client_name() {",
    "function name": "+export function createServiceRoleClient() {",
    "token from a method call": "+const token = this.jwtService.signAsync(payload);",
    "key read from process.env": "+const accessKey = process.env.AWS_ACCESS_KEY_ID;",
    "key read from os.environ": "+secret_value = os.environ.get('APP_SECRET')",
    "property set from a call": "+  refreshToken: createRefreshTokenFor(user),",
    "docker-compose service URL": "+DATABASE_URL=postgresql://postgres:postgres@db:5432/app",
    "docker-compose redis URL": "+REDIS_URL=redis://default:redispass@redis:6379",
}
results = []
for name, line in must_flag.items():
    ok = bool(m.scan(line, []))
    results.append(ok)
    print("PASS" if ok else "FAIL", "flags:", name)
for name, line in must_pass.items():
    ok = not m.scan(line, [])
    results.append(ok)
    print("PASS" if ok else "FAIL", "allows:", name)
print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
