# Managed by XMUHub — renders first-page thumbnails into a release of this repository.
import json, os, shutil, subprocess, sys, tempfile, time, urllib.parse, urllib.request, zipfile
from PIL import Image, ImageDraw, ImageFont

job = json.load(open(sys.argv[1], encoding='utf8'))
repo = os.environ['GITHUB_REPOSITORY']
H = {'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json', 'User-Agent': 'xmuhub-thumbs'}

def call(method, url, body=None, data=None, headers=None):
    h = dict(H, **(headers or {}))
    if body is not None:
        data = json.dumps(body).encode(); h['Content-Type'] = 'application/json'
    with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=h), timeout=300) as r:
        raw = r.read()
        return json.loads(raw) if raw else None

try:
    rel = call('GET', f'https://api.github.com/repos/{repo}/releases/tags/{job["tag"]}')
except urllib.error.HTTPError:
    rel = call('POST', f'https://api.github.com/repos/{repo}/releases', {'tag_name': job['tag'], 'name': job['tag'], 'make_latest': 'false'})
have = {a['name'] for a in rel.get('assets', [])}

PDF = {'pdf'}
IMGS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'tif', 'tiff'}
DOCS = {'doc', 'docx', 'docm', 'dot', 'dotx', 'rtf', 'odt', 'wps', 'ppt', 'pptx', 'pptm', 'pps', 'ppsx', 'odp', 'dps',
        'xls', 'xlsx', 'xlsm', 'xlsb', 'ods', 'et', 'csv'}
TEXT = {'txt', 'md', 'markdown', 'py', 'c', 'cpp', 'cc', 'h', 'hpp', 'java', 'js', 'ts', 'html', 'htm', 'css', 'tex',
        'json', 'xml', 'm', 'r', 'sql', 'log', 'go', 'rs', 'sh', 'yaml', 'yml', 'ini', 'v', 'asm'}
ARCH = {'zip', 'rar', '7z', 'tar', 'gz', 'tgz', 'bz2', 'xz'}
PREFER = ['pdf', 'docx', 'doc', 'pptx', 'ppt', 'xlsx', 'xls', 'jpg', 'jpeg', 'png', 'md', 'txt']
SEVENZ = shutil.which('7z') or shutil.which('7zz')
FONT = next((f for f in ['/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
                         '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc'] if os.path.exists(f)), None)

class Unsupported(Exception):
    pass

def run(cmd, timeout):
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        pass

def ext_of(p):
    return os.path.splitext(p)[1].lstrip('.').lower()

def sniff(path):
    head = open(path, 'rb').read(8)
    if head.startswith(b'%PDF'): return 'pdf'
    if head.startswith(b'PK'): return 'zip'
    if head.startswith(b'Rar!'): return 'rar'
    if head.startswith(b'7z\xbc\xaf'): return '7z'
    if head.startswith(b'\x89PNG'): return 'png'
    if head.startswith(b'\xff\xd8'): return 'jpg'
    if head.startswith(b'\xd0\xcf\x11\xe0'): return 'doc'
    return ''

def pdf_page(path, d):
    out = os.path.join(d, 'page')
    run(['pdftoppm', '-f', '1', '-l', '1', '-r', '60', '-png', path, out], 120)
    pages = sorted(f for f in os.listdir(d) if f.startswith('page') and f.endswith('.png'))
    return os.path.join(d, pages[0]) if pages else None

def office(path, d):
    run(['soffice', '--headless', '--norestore', '--convert-to', 'pdf', '--outdir', d, path], 240)
    pdf = os.path.join(d, os.path.splitext(os.path.basename(path))[0] + '.pdf')
    return pdf_page(pdf, d) if os.path.exists(pdf) else None

def text_image(path, d):
    raw = open(path, 'rb').read(16000)
    for enc in ('utf-8', 'gb18030', 'latin-1'):
        try:
            s = raw.decode(enc); break
        except UnicodeDecodeError:
            continue
    img = Image.new('RGB', (600, 800), 'white')
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 18) if FONT else ImageFont.load_default()
    y = 16
    for line in s.replace('\t', '    ').splitlines()[:38]:
        draw.text((16, y), line[:48], fill=(30, 30, 30), font=font)
        y += 20
    out = os.path.join(d, 'text.png'); img.save(out)
    return out

def epub_cover(path, d):
    with zipfile.ZipFile(path) as z:
        imgs = [i for i in z.infolist() if ext_of(i.filename) in ('jpg', 'jpeg', 'png')]
        if not imgs: raise Unsupported('epub without images')
        cover = next((i for i in imgs if 'cover' in i.filename.lower()), max(imgs, key=lambda i: i.file_size))
        out = os.path.join(d, 'cover.' + ext_of(cover.filename))
        open(out, 'wb').write(z.read(cover))
        return out

def archive(path, d, depth):
    if not SEVENZ: raise Unsupported('no 7z')
    x = os.path.join(d, 'x'); os.makedirs(x, exist_ok=True)
    run([SEVENZ, 'x', '-y', '-pxmuhub', '-o' + x, path], 300)
    files = [os.path.join(r, f) for r, _, fs in os.walk(x) for f in fs]
    for want in PREFER:
        cands = sorted(f for f in files if ext_of(f) == want)
        for c in cands[:3]:
            sub = tempfile.mkdtemp(dir=d)
            try:
                img = render(c, want, sub, depth + 1)
                if img: return img
            except Exception:
                pass
    raise Unsupported('nothing previewable inside')

def render(path, ext, d, depth=0):
    if ext not in PDF | IMGS | DOCS | TEXT | ARCH | {'epub'}:
        ext = sniff(path) or ext
    if ext in PDF: return pdf_page(path, d)
    if ext in IMGS: return path
    if ext in DOCS: return office(path, d)
    if ext == 'epub': return epub_cover(path, d)
    if ext in ARCH and depth < 2: return archive(path, d, depth)
    if ext in TEXT: return text_image(path, d)
    raise Unsupported('format ' + ext)

def thumbnail(src, out):
    im = Image.open(src); im.load()
    if im.mode in ('RGBA', 'LA', 'P'):
        im = im.convert('RGBA'); bg = Image.new('RGB', im.size, 'white'); bg.paste(im, mask=im.split()[-1]); im = bg
    im = im.convert('RGB')
    w = 360; h = max(1, round(im.height * w / im.width))
    im = im.resize((w, h), Image.LANCZOS)
    if h > 480: im = im.crop((0, 0, w, 480))
    im.save(out, 'WEBP', quality=72, method=6)

results = []
for it in job['items']:
    name = it['key'] + '.webp'
    if name in have:
        results.append({'key': it['key'], 'name': name}); continue
    d = tempfile.mkdtemp()
    try:
        src = os.path.join(d, 'in.' + (it['ext'] or 'bin'))
        with open(src, 'wb') as f:
            for u in it['urls']:
                for attempt in range(3):
                    try:
                        with urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'xmuhub-thumbs'}), timeout=300) as r:
                            shutil.copyfileobj(r, f)
                        break
                    except Exception:
                        if attempt == 2: raise
                        time.sleep(5)
        img = render(src, it['ext'], d)
        if not img: raise RuntimeError('render produced nothing')
        out = os.path.join(d, name)
        thumbnail(img, out)
        up = f'https://uploads.github.com/repos/{repo}/releases/{rel["id"]}/assets?name={urllib.parse.quote(name)}'
        a = call('POST', up, data=open(out, 'rb').read(), headers={'Content-Type': 'image/webp'})
        results.append({'key': it['key'], 'name': a['name']})
    except Unsupported as e:
        results.append({'key': it['key'], 'error': str(e)[:200], 'permanent': True})
    except Exception as e:
        results.append({'key': it['key'], 'error': str(e)[:200]})
    finally:
        shutil.rmtree(d, ignore_errors=True)

os.makedirs('results', exist_ok=True)
json.dump({'tag': job['tag'], 'results': results}, open(f'results/thumbs-{job["id"]}.json', 'w', encoding='utf8'), ensure_ascii=False)
print(sum(1 for r in results if 'error' not in r), 'ok,', sum(1 for r in results if 'error' in r), 'failed')
