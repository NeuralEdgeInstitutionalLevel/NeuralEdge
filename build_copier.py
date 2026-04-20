"""Generate tawk_copier.html - split long articles into chunks of max 1500 chars"""
import re

with open('tawk_ai_knowledge.md', 'r', encoding='utf-8') as f:
    text = f.read()

MAX_BODY = 1500  # Tawk.to KB article body limit (approx)

sections = re.split(r'^## ', text, flags=re.MULTILINE)
sections = [s.strip() for s in sections if s.strip() and len(s.strip()) > 50]

articles = []
for s in sections:
    lines = s.split('\n')
    title = lines[0].strip()
    body = '\n'.join(lines[1:]).strip()
    if not body or len(body) < 30:
        continue

    is_special = 'PERSONALITY' in title.upper()
    if is_special:
        display_title = 'AI INSTRUCTIONS (Custom Instructions)'
        raw_title = 'AI Personality Instructions'
    elif ':' in title:
        display_title = title.split(':', 1)[-1].strip()
        raw_title = display_title
    else:
        display_title = title
        raw_title = title

    # Split long bodies into chunks
    if len(body) > MAX_BODY and not is_special:
        paragraphs = body.split('\n\n')
        chunks = []
        current = ''
        for p in paragraphs:
            if len(current) + len(p) + 2 > MAX_BODY and current:
                chunks.append(current.strip())
                current = p
            else:
                current = current + '\n\n' + p if current else p
        if current.strip():
            chunks.append(current.strip())

        for ci, chunk in enumerate(chunks):
            suffix = f' (Part {ci+1})' if len(chunks) > 1 else ''
            articles.append({
                'display': display_title + suffix,
                'raw_title': raw_title + suffix,
                'body': chunk,
                'special': is_special,
            })
    else:
        articles.append({
            'display': display_title,
            'raw_title': raw_title,
            'body': body,
            'special': is_special,
        })

# Build HTML
html_parts = ['''<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Tawk.to KB Copier</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0f;color:#e0e0e0;font-family:system-ui;padding:20px;max-width:900px;margin:0 auto}
h1{font-size:1.3rem;margin-bottom:6px;color:#c4666e}
.sub{color:#666;font-size:0.8rem;margin-bottom:20px}
.steps{background:#12121a;border:1px solid #6b1d3a;border-radius:10px;padding:14px;margin-bottom:20px;font-size:0.78rem;line-height:1.7}
.steps b{color:#c4666e}
.card{background:#12121a;border:1px solid #222;border-radius:10px;margin-bottom:10px;overflow:hidden}
.ch{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;background:#16161f;cursor:pointer}
.ch:hover{background:#1a1a25}
.ct{font-weight:700;font-size:0.82rem}
.cb{font-size:0.58rem;background:rgba(155,35,53,0.2);color:#c4666e;padding:2px 8px;border-radius:6px}
.chars{font-size:0.55rem;color:#555;margin-left:6px}
.cc{padding:0;max-height:0;overflow:hidden;transition:max-height 0.3s ease}
.card.open .cc{max-height:8000px;padding:10px 14px}
.tx{white-space:pre-wrap;font-size:0.7rem;line-height:1.4;color:#888;font-family:Consolas,monospace;background:#08080f;padding:10px;border-radius:8px;margin-bottom:8px;max-height:250px;overflow-y:auto}
.btns{display:flex;gap:8px;margin-bottom:6px}
.cp{padding:6px 16px;background:#6b1d3a;color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:0.75rem;font-weight:600;flex:1}
.cp:hover{background:#9b2335}
.cp.ok{background:#10b981}
.cp.tb{background:#333;flex:0.4}
.cp.tb:hover{background:#444}
.cp.tb.ok{background:#10b981}
.sp{border-color:#6b1d3a}
.sp .ch{background:#1a0f15}
.pg{margin-bottom:14px;font-size:0.8rem;color:#666}
.pg b{color:#10b981}
.dm{display:none;color:#10b981;font-size:0.65rem;margin-left:6px}
.card.done .dm{display:inline}
.card.done .ch{opacity:0.5}
</style></head><body>
<h1>Tawk.to KB Copier</h1>
<p class="sub">Copy Title -> paste -> Copy Body -> paste -> Publish. Repeat.</p>
<div class="steps">
<b>1.</b> Tawk.to: <b>+ Create -> Article</b><br>
<b>2.</b> Here: <b>Copy Title</b> -> Tawk.to title -> Ctrl+V<br>
<b>3.</b> Here: <b>Copy Body</b> -> Tawk.to body -> Ctrl+V<br>
<b>4.</b> Tawk.to: <b>Publish</b> -> repeat
</div>
<p class="pg">Done: <b id="c">0</b> / TOTAL_COUNT</p>
''']

for i, art in enumerate(articles):
    safe_body = (art['body'].replace('&','&amp;').replace('<','&lt;')
        .replace('>','&gt;').replace('"','&quot;'))
    safe_title = (art['raw_title'].replace('&','&amp;').replace('<','&lt;')
        .replace('>','&gt;').replace('"','&quot;'))
    sp = ' sp' if art['special'] else ''
    label = 'INSTR' if art['special'] else f'{i+1}'
    chars = len(art['body'])

    html_parts.append(f'''<div class="card{sp}" id="c{i}">
<div class="ch" onclick="this.parentElement.classList.toggle('open')">
<span class="ct">{art['display']}<span class="dm">DONE</span><span class="chars">{chars} chars</span></span><span class="cb">{label}</span></div>
<div class="cc">
<div class="btns">
<button class="cp tb" onclick="cpT(this,{i})">Copy Title</button>
<button class="cp" onclick="cpB(this,{i})">Copy Body</button>
</div>
<div class="tx">{safe_body}</div>
<textarea id="t{i}" style="display:none">{safe_title}</textarea>
<textarea id="b{i}" style="display:none">{safe_body}</textarea>
</div></div>
''')

html_parts.append('''<script>
let d=new Set();
function dec(s){return s.replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&').replace(/&quot;/g,'"');}
function cpT(b,i){navigator.clipboard.writeText(dec(document.getElementById('t'+i).value)).then(function(){
b.textContent='OK!';b.classList.add('ok');setTimeout(function(){b.textContent='Copy Title';b.classList.remove('ok')},1200);});}
function cpB(b,i){navigator.clipboard.writeText(dec(document.getElementById('b'+i).value)).then(function(){
b.textContent='OK!';b.classList.add('ok');d.add(i);document.getElementById('c'+i).classList.add('done');
document.getElementById('c').textContent=d.size;
setTimeout(function(){b.textContent='Copy Body';b.classList.remove('ok')},1200);});}
</script></body></html>''')

html = '\n'.join(html_parts).replace('TOTAL_COUNT', str(len(articles)))
with open('tawk_copier.html', 'w', encoding='utf-8') as f:
    f.write(html)

print(f"Generated {len(articles)} articles (long ones split at {MAX_BODY} chars)")
