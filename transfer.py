# Managed by XMUHub — copies referenced files into a release of this repository.
import hashlib, json, os, sys, time, urllib.parse, urllib.request

job = json.load(open(sys.argv[1], encoding='utf8'))
repo = os.environ['GITHUB_REPOSITORY']
H = {'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json', 'User-Agent': 'xmuhub-transfer'}

def call(method, url, body=None, data=None, headers=None):
    h = dict(H, **(headers or {}))
    if body is not None:
        data = json.dumps(body).encode(); h['Content-Type'] = 'application/json'
    with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=h), timeout=600) as r:
        raw = r.read()
        return json.loads(raw) if raw else None

try:
    rel = call('GET', f'https://api.github.com/repos/{repo}/releases/tags/{job["tag"]}')
except urllib.error.HTTPError:
    rel = call('POST', f'https://api.github.com/repos/{repo}/releases', {'tag_name': job['tag'], 'name': job['tag'], 'make_latest': 'false'})
have = {a['name'] for a in rel.get('assets', [])}

results = []
for it in job['items']:
    try:
        if it['name'] in have:
            results.append({'key': it['key'], 'name': it['name'], 'existing': True}); continue
        data = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(it['url'], headers={'User-Agent': 'xmuhub-transfer'}), timeout=600) as r:
                    data = r.read()
                break
            except Exception:
                if attempt == 2: raise
                time.sleep(5)
        if len(data) != it['size']:
            raise RuntimeError(f'size {len(data)} != {it["size"]}')
        sha = hashlib.sha256(data).hexdigest()
        up = f'https://uploads.github.com/repos/{repo}/releases/{rel["id"]}/assets?name={urllib.parse.quote(it["name"])}'
        a = call('POST', up, data=data, headers={'Content-Type': 'application/octet-stream'})
        results.append({'key': it['key'], 'name': a['name'], 'asset_id': a['id'], 'sha256': sha})
    except Exception as e:
        results.append({'key': it['key'], 'error': str(e)[:300]})

os.makedirs('results', exist_ok=True)
json.dump({'tag': job['tag'], 'release_id': rel['id'], 'results': results}, open(f'results/{job["id"]}.json', 'w', encoding='utf8'), ensure_ascii=False)
print(sum(1 for r in results if 'error' not in r), 'ok,', sum(1 for r in results if 'error' in r), 'failed')
