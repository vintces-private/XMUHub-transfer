# Managed by XMUHub — copies referenced files into a release of this repository.
import base64, hashlib, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

job = json.load(open(sys.argv[1], encoding='utf8'))
repo = os.environ['GITHUB_REPOSITORY']
H = {'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json', 'User-Agent': 'xmuhub-transfer'}

def call(method, url, body=None, data=None, headers=None):
    h = dict(H, **(headers or {}))
    if body is not None:
        data = json.dumps(body).encode(); h['Content-Type'] = 'application/json'
    # GitHub's API now and then answers 5xx: retry those, give up on anything else.
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=h), timeout=600) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == 3: raise
        except urllib.error.URLError:
            if attempt == 3: raise
        time.sleep(10 * (attempt + 1))

def lfs_pointer(it):
    # Repositories imported with Git LFS list the pointer (oid + size) as the file; its git blob
    # is the key. github.com/<o>/<r>/raw/... serves the real file, checked against the pointer.
    m = re.match(r'https://github\.com/([^/]+)/([^/]+)/raw/', it['url'])
    if not m or not it['key'].startswith('git-') or it['size'] >= 1024: return None
    b = call('GET', f'https://api.github.com/repos/{m[1]}/{m[2]}/git/blobs/{it["key"][4:]}')
    text = base64.b64decode(b['content']).decode('utf8', 'replace')
    oid, size = re.search(r'^oid sha256:([0-9a-f]{64})$', text, re.M), re.search(r'^size (\d+)$', text, re.M)
    if not text.startswith('version https://git-lfs') or not oid or not size: return None
    return oid[1], int(size[1])

try:
    rel = call('GET', f'https://api.github.com/repos/{repo}/releases/tags/{job["tag"]}')
except urllib.error.HTTPError as e:
    if e.code != 404: raise
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
        sha = hashlib.sha256(data).hexdigest()
        lfs_size = None
        if len(data) != it['size']:
            p = lfs_pointer(it)
            if not p or (sha, len(data)) != p:
                raise RuntimeError(f'size {len(data)} != {it["size"]}')
            lfs_size = len(data)
        up = f'https://uploads.github.com/repos/{repo}/releases/{rel["id"]}/assets?name={urllib.parse.quote(it["name"])}'
        a = call('POST', up, data=data, headers={'Content-Type': 'application/octet-stream'})
        results.append({'key': it['key'], 'name': a['name'], 'asset_id': a['id'], 'sha256': sha, 'lfs_size': lfs_size})
    except Exception as e:
        results.append({'key': it['key'], 'error': str(e)[:300]})

os.makedirs('results', exist_ok=True)
json.dump({'tag': job['tag'], 'release_id': rel['id'], 'results': results}, open(f'results/{job["id"]}.json', 'w', encoding='utf8'), ensure_ascii=False)
print(sum(1 for r in results if 'error' not in r), 'ok,', sum(1 for r in results if 'error' in r), 'failed')
