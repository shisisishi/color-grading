"""Exercise actual local HTTP image processing without personal photos."""
from pathlib import Path
import base64, io, json, subprocess, sys, time, urllib.request
from PIL import Image

root = Path(__file__).resolve().parent
port = 18766
proc = subprocess.Popen([sys.executable, str(root/'serve.py'), str(port)], cwd=root,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def request(path, payload=None):
    data=None if payload is None else json.dumps(payload).encode()
    req=urllib.request.Request(f'http://127.0.0.1:{port}{path}',data=data,
                              headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=15) as r: return r.read()
try:
    for attempt in range(50):
        try:
            health=json.loads(request('/check')); break
        except OSError: time.sleep(.1)
    else: raise RuntimeError('Server failed to start')
    assert health['ok']
    original=base64.b64encode((root/'samples/demo_gradient.jpg').read_bytes()).decode()
    styles=json.loads(request('/api/styles'))['styles']
    for style in styles:
        result=json.loads(request('/api/process',{'image':original,'style':style['key']}))
        assert result['ok'],result
        image=Image.open(io.BytesIO(base64.b64decode(result['image'])))
        assert image.size==(384,256) and image.format=='PNG'
    auto=json.loads(request('/api/autograde',{'image':original}))
    assert auto['ok'] and auto['style'] in {s['key'] for s in styles}
    data=request('/api/download',{'image':auto['image'],'name':'demo.png'})
    assert Image.open(io.BytesIO(data)).size==(384,256)
    assert len(json.loads(request('/api/samples'))['samples'])==2
    assert b'<html' in request('/').lower()
    print(json.dumps({'health':health,'stylesTested':len(styles),'autoStyle':auto['style'],
                      'downloadBytes':len(data),'result':'passed'},ensure_ascii=False))
finally:
    proc.terminate(); proc.wait(timeout=10)
