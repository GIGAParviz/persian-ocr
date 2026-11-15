import ast
import builtins
import html
import io
import itertools
import keyword
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MD_PATH = ROOT / "docs" / "code-reference.md"
OUT_PATH = ROOT / "docs" / "code-reference.html"
SOURCE_DIRS = ("persian_ocr", "evaluation", "tests", "tools")
BUILTINS = set(dir(builtins))
STRING_TOKENS = {tokenize.STRING, getattr(tokenize, "FSTRING_START", -1), getattr(tokenize, "FSTRING_MIDDLE", -1), getattr(tokenize, "FSTRING_END", -1)}
LIST_RE = re.compile(r"^(\s*)(?:[-*]|\d+\.)\s+(.*)$")
OPEN_LIMIT = 15
MAX_SNIPPETS = 4


@dataclass
class Definition:
    kind: str
    start: int
    end: int


@dataclass
class SourceFile:
    rel: str
    src: str
    lines_html: list
    defs: dict
    n_defs: int

    @property
    def n_lines(self) -> int:
        return len(self.src.rstrip("\n").split("\n"))


def highlight_lines(src: str) -> list:
    lines = src.split("\n")
    classes = [[None] * len(line) for line in lines]

    def mark(start, end, cls):
        (sr, sc), (er, ec) = start, end
        for row in range(sr, er + 1):
            length = len(lines[row - 1])
            lo = sc if row == sr else 0
            hi = ec if row == er else length
            for col in range(lo, min(hi, length)):
                classes[row - 1][col] = cls

    previous = None
    skip = (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.COMMENT)
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        cls = None
        if tok.type == tokenize.COMMENT:
            cls = "c"
        elif tok.type in STRING_TOKENS:
            cls = "s"
        elif tok.type == tokenize.NUMBER:
            cls = "n"
        elif tok.type == tokenize.NAME:
            if keyword.iskeyword(tok.string):
                cls = "k"
            elif previous == "def":
                cls = "f"
            elif previous == "class":
                cls = "cl"
            elif previous == "@":
                cls = "d"
            elif tok.string in ("self", "cls"):
                cls = "sf"
            elif tok.string in BUILTINS:
                cls = "b"
        elif tok.type == tokenize.OP and tok.string == "@":
            cls = "d"
        if cls:
            mark(tok.start, tok.end, cls)
        if tok.type not in skip:
            previous = tok.string

    rendered = []
    for text, row in zip(lines, classes):
        parts, i = [], 0
        for cls, run in itertools.groupby(row):
            j = i + len(list(run))
            chunk = html.escape(text[i:j], quote=False)
            parts.append(f'<span class="t-{cls}">{chunk}</span>' if cls else chunk)
            i = j
        rendered.append("".join(parts))
    return rendered


def load_source(path: Path) -> SourceFile:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    defs: dict = {}
    n_defs = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            n_defs += 1
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            defs.setdefault(node.name, Definition(kind, min([node.lineno] + [d.lineno for d in node.decorator_list]), node.end_lineno))
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        for name in targets:
            defs.setdefault(name, Definition("constant", node.lineno, node.end_lineno))
    return SourceFile(path.relative_to(ROOT).as_posix(), src, highlight_lines(src), defs, n_defs)


def load_sources() -> dict:
    files = {}
    for folder in SOURCE_DIRS:
        for path in sorted((ROOT / folder).rglob("*.py")):
            if "__pycache__" not in path.parts:
                files[path.relative_to(ROOT).as_posix()] = load_source(path)
    return files


def code_lines_html(info: SourceFile, start: int, end: int) -> str:
    rows = "".join(f'<span class="l">{info.lines_html[i] or "&#8203;"}</span>' for i in range(start - 1, end))
    return f'<pre style="counter-reset: ln {start - 1}"><code>{rows}</code></pre>'


def snippet_html(info: SourceFile, d: Definition) -> str:
    first = info.lines_html[d.start - 1]
    if d.kind != "constant":
        for ln in range(d.start, d.end + 1):
            if re.match(r"\s*(async\s+)?(def|class)\s", info.src.split("\n")[ln - 1]):
                first = info.lines_html[ln - 1]
                break
    more = " …" if d.end > d.start else ""
    size = d.end - d.start + 1
    open_attr = " open" if size <= OPEN_LIMIT else ""
    label = {"function": "تابع", "class": "کلاس", "constant": "ثابت"}[d.kind]
    return (
        f'<details class="code"{open_attr}><summary><span class="badge">{label}</span>'
        f'<span class="sig">{first.strip()}{more}</span><span class="rng">خط {d.start}–{d.end}</span></summary>'
        f'<div class="codewrap"><button class="copy" type="button">کپی</button>{code_lines_html(info, d.start, d.end)}</div></details>'
    )


def full_code_html(info: SourceFile) -> str:
    return (
        f'<details class="code full"><summary><span class="badge">فایل</span><span class="sig">کد کامل {html.escape(info.rel)}</span>'
        f'<span class="rng">{info.n_lines} خط</span></summary>'
        f'<div class="codewrap"><button class="copy" type="button">کپی</button>{code_lines_html(info, 1, info.n_lines)}</div></details>'
    )


def file_meta_html(info: SourceFile) -> str:
    return (
        f'<div class="filemeta"><code dir="ltr">{html.escape(info.rel)}</code>'
        f'<span>{info.n_lines} خط</span><span>{info.n_defs} تابع/کلاس</span></div>'
    )


def inline(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(text, quote=False))
    return "".join(f'<code dir="auto">{part}</code>' if i % 2 else part for i, part in enumerate(text.split("`")))


def plain(text: str) -> str:
    return re.sub(r"[`*]", "", text)


def parse_blocks(md: str) -> list:
    lines = md.split("\n")
    blocks, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("```"):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            blocks.append(("code", "\n".join(buf)))
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            blocks.append(("h", len(m.group(1)), m.group(2)))
            i += 1
            continue
        if re.fullmatch(r"-{3,}", line.strip()):
            blocks.append(("hr",))
            i += 1
            continue
        if line.lstrip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(lines[i])
                i += 1
            blocks.append(("table", rows))
            continue
        if LIST_RE.match(line):
            item_lines = []
            while i < len(lines):
                cur = lines[i]
                if LIST_RE.match(cur):
                    item_lines.append(cur)
                elif cur.strip() and cur.startswith("  ") and item_lines:
                    item_lines.append(cur)
                else:
                    break
                i += 1
            blocks.append(("list", build_tree(item_lines)))
            continue
        buf = []
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", "```", "|")) and not LIST_RE.match(lines[i]):
            buf.append(lines[i].strip())
            i += 1
        blocks.append(("p", " ".join(buf)))
    return blocks


def build_tree(item_lines: list) -> list:
    root: list = []
    stack = [(-1, root)]
    last = None
    for line in item_lines:
        m = LIST_RE.match(line)
        if m:
            indent = len(m.group(1))
            item = {"text": m.group(2), "ordered": bool(re.match(r"\s*\d+\.", line)), "children": []}
            while stack[-1][0] >= indent:
                stack.pop()
            stack[-1][1].append(item)
            stack.append((indent, item["children"]))
            last = item
        else:
            last["text"] += " " + line.strip()
    return root


def head_names(text: str) -> list:
    head = text.split(":", 1)[0] if ":" in text[:220] else text[:220]
    return re.findall(r"`(\w+)(?=[\s(=`])", head)


class Renderer:
    def __init__(self):
        self.current: SourceFile | None = None
        self.covered: set = set()
        self.snippets = 0
        self.missing: list = []

    def code_for(self, names: list, drop_classes: bool = False) -> str:
        if self.current is None:
            return ""
        seen, parts = set(), []
        for name in names:
            d = self.current.defs.get(name)
            if d is None or name in seen or (drop_classes and d.kind == "class"):
                continue
            seen.add(name)
            parts.append(snippet_html(self.current, d))
        self.snippets += len(parts[:MAX_SNIPPETS])
        return "".join(parts[:MAX_SNIPPETS])

    def render_list(self, items: list) -> str:
        out = []
        for ordered, group in itertools.groupby(items, key=lambda it: it["ordered"]):
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>{''.join(self.render_item(it) for it in group)}</{tag}>")
        return "".join(out)

    def render_item(self, item: dict) -> str:
        names = head_names(item["text"])
        code = self.code_for(names, drop_classes=bool(item["children"]))
        children = self.render_list(item["children"]) if item["children"] else ""
        return f'<li><div class="itx">{inline(item["text"])}</div>{code}{children}</li>'

    def render_table(self, rows: list) -> str:
        cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
        cells = [r for r in cells if not all(re.fullmatch(r":?-{2,}:?", c) for c in r)]
        head, body = cells[0], cells[1:]
        thead = "".join(f"<th>{inline(c)}</th>" for c in head)
        tbody = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body)
        return f'<div class="tablewrap"><table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table></div>'


def build() -> str:
    sources = load_sources()
    r = Renderer()
    blocks = parse_blocks(MD_PATH.read_text(encoding="utf-8"))
    out, toc = [], []
    package, subdir, counter = "", "", 0
    pending: list = []

    def flush_pending(next_kind: str = "") -> None:
        nonlocal pending
        if pending:
            out.append(r.code_for(pending, drop_classes=(next_kind == "list")))
            pending = []

    def flush_file() -> None:
        if r.current is not None:
            out.append(full_code_html(r.current))
            r.current = None

    for block in blocks:
        kind = block[0]
        if kind == "h":
            flush_pending("heading")
            flush_file()
            level, text = block[1], block[2]
            rel = None
            m_py = re.search(r"`([\w/]+\.py)`", text)
            m_dir = re.search(r"`(\w+)/`", text)
            if level == 1:
                package, subdir = (m_dir.group(1) if m_dir else package), ""
            elif level == 2:
                if m_py:
                    subdir, rel = "", "/".join(p for p in (package, m_py.group(1)) if p)
                elif m_dir:
                    subdir = m_dir.group(1)
            elif level == 3 and m_py:
                rel = "/".join(p for p in (package, subdir, m_py.group(1)) if p)
            counter += 1
            sid = f"s{counter}"
            info = sources.get(rel) if rel else None
            if rel and info is None:
                r.missing.append(rel)
            keywords = " ".join(info.defs) if info else ""
            out.append(f'<h{level} id="{sid}">{inline(text)}</h{level}>')
            toc.append((level, plain(text), sid, keywords))
            if info:
                out.append(file_meta_html(info))
                r.current = info
                r.covered.add(rel)
            continue
        if kind == "hr":
            flush_pending("hr")
            out.append("<hr>")
            continue
        if kind == "code":
            flush_pending("code")
            out.append(f'<pre class="diagram"><code>{html.escape(block[1], quote=False)}</code></pre>')
            continue
        if kind == "table":
            out.append(r.render_table(block[1]))
            flush_pending("table")
            continue
        if kind == "list":
            flush_pending("list")
            out.append(r.render_list(block[1]))
            continue
        text = block[1]
        flush_pending("p")
        out.append(f"<p>{inline(text)}</p>")
        if text.startswith("**`"):
            pending = head_names(text)
        else:
            m = re.match(r"^`(\w+)", text)
            if m and (text.startswith(f"`{m.group(1)}(") or text.split(":", 1)[0].count("`") == 2):
                out.append(r.code_for([m.group(1)]))
    flush_pending("end")
    flush_file()

    counter += 1
    extras = sorted(rel for rel in sources if rel not in r.covered)
    out.append(f'<h1 id="s{counter}">پیوست: کد کامل سایر فایل‌ها</h1>')
    toc.append((1, "پیوست: کد کامل سایر فایل‌ها", f"s{counter}", ""))
    out.append("<p>فایل‌هایی که در بخش‌های بالا عنوان جدا ندارند (فایل‌های <code dir=\"auto\">__init__.py</code> و تست‌ها).</p>")
    for rel in extras:
        counter += 1
        info = sources[rel]
        out.append(f'<h3 id="s{counter}"><code dir="ltr">{html.escape(rel)}</code></h3>')
        toc.append((3, plain(rel), f"s{counter}", " ".join(info.defs)))
        out.append(file_meta_html(info))
        out.append(full_code_html(info))

    nav = "".join(
        f'<a class="l{lvl}" href="#{sid}" data-k="{html.escape(kw)}">{html.escape(title)}</a>' for lvl, title, sid, kw in toc
    )
    page = PAGE.replace("{{NAV}}", nav).replace("{{COUNT}}", str(r.snippets)).replace("{{BODY}}", "\n".join(out))
    print(f"snippets: {r.snippets}, files covered: {len(r.covered)}, appendix files: {len(extras)}")
    if r.missing:
        print("heading files not found:", r.missing)
    return page


PAGE = """<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>مرجع کد — persian_ocr</title>
<style>
:root{--bg:#f6f7f9;--panel:#fff;--fg:#1c2330;--muted:#5d6878;--line:#dfe3ea;--accent:#2457c5;--accent-bg:#e8effc;--code-bg:#f6f8fa;--code-fg:#24292f;--ln:#9aa4b2;
--c:#6e7781;--s:#0a3069;--n:#0550ae;--k:#cf222e;--f:#8250df;--cl:#953800;--b:#0550ae;--d:#116329;--sf:#953800}
:root[data-theme=dark]{--bg:#0e1116;--panel:#161b22;--fg:#e6edf3;--muted:#9aa5b1;--line:#2b323c;--accent:#79a8ff;--accent-bg:#1b2740;--code-bg:#0d1117;--code-fg:#e6edf3;--ln:#5d6773;
--c:#8b949e;--s:#a5d6ff;--n:#79c0ff;--k:#ff7b72;--f:#d2a8ff;--cl:#ffa657;--b:#79c0ff;--d:#7ee787;--sf:#ffa657}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:16px}
body{margin:0;background:var(--bg);color:var(--fg);font-family:Vazirmatn,Tahoma,"Segoe UI",sans-serif;line-height:1.95;font-size:16px;display:flex;align-items:flex-start}
aside{position:sticky;top:0;height:100vh;width:310px;flex:none;background:var(--panel);border-inline-end:1px solid var(--line);display:flex;flex-direction:column}
.brand{padding:16px 18px 8px;font-weight:700;font-size:17px}
.brand small{display:block;font-weight:400;color:var(--muted);font-size:12px}
#q{margin:8px 14px;padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);font:inherit;font-size:14px}
.tools{display:flex;gap:6px;padding:0 14px 10px;flex-wrap:wrap}
.tools button{flex:1;border:1px solid var(--line);background:var(--bg);color:var(--fg);border-radius:8px;padding:5px 8px;font:inherit;font-size:12px;cursor:pointer}
.tools button:hover{border-color:var(--accent);color:var(--accent)}
#toc{overflow:auto;padding:4px 8px 24px;flex:1}
#toc a{display:block;padding:3px 10px;border-radius:6px;color:var(--fg);text-decoration:none;font-size:13.5px;line-height:1.7;border-inline-start:3px solid transparent;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#toc a:hover{background:var(--accent-bg)}
#toc a.active{background:var(--accent-bg);color:var(--accent);border-inline-start-color:var(--accent)}
#toc a.l1{font-weight:700;margin-top:10px}
#toc a.l2{padding-inline-start:18px}
#toc a.l3{padding-inline-start:32px;color:var(--muted)}
main{flex:1;min-width:0;max-width:1000px;margin:0 auto;padding:28px 36px 80px}
h1{font-size:26px;margin:44px 0 12px;padding-bottom:8px;border-bottom:2px solid var(--accent)}
main>h1:first-child{margin-top:0}
h2{font-size:21px;margin:36px 0 8px}
h3{font-size:17px;margin:28px 0 6px}
p{margin:8px 0}
hr{border:0;border-top:1px dashed var(--line);margin:28px 0}
ul,ol{padding-inline-start:26px;margin:6px 0}
li{margin:6px 0}
.itx{display:inline}
code{font-family:Consolas,"Cascadia Mono","Courier New",monospace;font-size:.88em;background:var(--accent-bg);color:var(--accent);padding:1px 6px;border-radius:5px;unicode-bidi:isolate}
strong{font-weight:700}
.tablewrap{overflow-x:auto;margin:12px 0}
table{border-collapse:collapse;width:100%;background:var(--panel);font-size:14.5px}
th,td{border:1px solid var(--line);padding:6px 10px;text-align:start;vertical-align:top}
th{background:var(--accent-bg)}
.filemeta{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:6px 0 12px;font-size:13px;color:var(--muted)}
.filemeta>*{background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:1px 12px}
.filemeta code{background:none;color:var(--fg);padding:0}
pre.diagram{direction:ltr;text-align:left;background:var(--code-bg);color:var(--code-fg);border:1px solid var(--line);border-radius:10px;padding:14px 16px;overflow:auto;font-size:13px;line-height:1.6}
pre.diagram code{background:none;color:inherit;padding:0}
details.code{margin:10px 0;border:1px solid var(--line);border-radius:10px;background:var(--panel);overflow:hidden}
details.code.full{margin-top:18px}
details.code>summary{display:flex;align-items:center;gap:10px;padding:7px 12px;cursor:pointer;list-style:none;direction:ltr;text-align:left;background:var(--code-bg);font-family:Consolas,"Cascadia Mono",monospace;font-size:13px}
details.code>summary::-webkit-details-marker{display:none}
details.code>summary::before{content:"▸";color:var(--muted);transition:transform .15s}
details.code[open]>summary::before{transform:rotate(90deg)}
.badge{font-family:Vazirmatn,Tahoma,sans-serif;font-size:11px;background:var(--accent-bg);color:var(--accent);border-radius:5px;padding:0 7px;direction:rtl}
.sig{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--code-fg)}
.rng{color:var(--muted);font-family:Vazirmatn,Tahoma,sans-serif;font-size:11.5px;direction:rtl;white-space:nowrap}
.codewrap{position:relative;border-top:1px solid var(--line)}
.copy{position:absolute;top:8px;right:10px;z-index:1;border:1px solid var(--line);background:var(--panel);color:var(--muted);border-radius:6px;font:inherit;font-size:11px;padding:1px 10px;cursor:pointer;opacity:.0;transition:opacity .15s}
.codewrap:hover .copy{opacity:1}
pre{margin:0;direction:ltr;text-align:left;background:var(--code-bg);color:var(--code-fg);overflow:auto;padding:10px 0;font-size:13px;line-height:1.6;tab-size:4}
pre code{background:none;color:inherit;padding:0;font-size:inherit;unicode-bidi:normal;font-family:Consolas,"Cascadia Mono","Courier New",monospace}
.l{display:block;white-space:pre;padding-inline-end:16px;min-height:1.6em}
.l::before{counter-increment:ln;content:counter(ln);display:inline-block;width:3.2em;margin-inline-end:14px;text-align:right;color:var(--ln);user-select:none}
.t-c{color:var(--c);font-style:italic}.t-s{color:var(--s)}.t-n{color:var(--n)}.t-k{color:var(--k)}.t-f{color:var(--f);font-weight:600}
.t-cl{color:var(--cl);font-weight:600}.t-b{color:var(--b)}.t-d{color:var(--d)}.t-sf{color:var(--sf);font-style:italic}
summary .t-c,summary .t-s{font-style:normal}
@media (max-width:900px){body{display:block}aside{position:static;height:auto;width:auto;max-height:46vh}main{padding:18px 14px 60px}}
</style>
</head>
<body>
<aside>
<div class="brand">مرجع کد · persian_ocr<small>{{COUNT}} پیش‌نمایش کد، قابل جست‌وجو</small></div>
<input id="q" type="search" placeholder="جست‌وجو: فایل یا نام تابع…" autocomplete="off">
<div class="tools"><button id="expand" type="button">باز کردن همه کدها</button><button id="collapse" type="button">بستن همه</button><button id="theme" type="button">تیره/روشن</button></div>
<nav id="toc">{{NAV}}</nav>
</aside>
<main>
{{BODY}}
</main>
<script>
const root=document.documentElement;
if(localStorage.getItem('theme')==='dark')root.dataset.theme='dark';
document.getElementById('theme').onclick=()=>{const d=root.dataset.theme==='dark';if(d)delete root.dataset.theme;else root.dataset.theme='dark';localStorage.setItem('theme',d?'light':'dark')};
const setAll=o=>document.querySelectorAll('details.code').forEach(d=>d.open=o);
document.getElementById('expand').onclick=()=>setAll(true);
document.getElementById('collapse').onclick=()=>setAll(false);
const links=[...document.querySelectorAll('#toc a')];
document.getElementById('q').addEventListener('input',e=>{const v=e.target.value.trim().toLowerCase();links.forEach(a=>{const t=(a.textContent+' '+(a.dataset.k||'')).toLowerCase();a.style.display=!v||t.includes(v)?'':'none'})});
document.addEventListener('click',e=>{const b=e.target.closest('.copy');if(!b)return;const text=b.parentElement.querySelector('pre').innerText.replace(/\\u200b/g,'');navigator.clipboard.writeText(text).then(()=>{b.textContent='کپی شد';setTimeout(()=>b.textContent='کپی',1200)})});
const byId=Object.fromEntries(links.map(a=>[a.getAttribute('href').slice(1),a]));
const io=new IntersectionObserver(es=>{es.forEach(en=>{if(en.isIntersecting){links.forEach(a=>a.classList.remove('active'));const a=byId[en.target.id];if(a){a.classList.add('active');a.scrollIntoView({block:'nearest'})}}})},{rootMargin:'0px 0px -80% 0px'});
document.querySelectorAll('main h1,main h2,main h3').forEach(h=>io.observe(h));
</script>
</body>
</html>
"""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT_PATH.write_text(build(), encoding="utf-8", newline="\n")
    print(f"written: {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} KB)")
    return 0


sys.exit(main())
