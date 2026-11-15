const fs = require('fs');
const path = require('path');
const { JSDOM } = require(path.join(__dirname, '..', '.cache', 'nodetools', 'node_modules', 'jsdom'));
const html = fs.readFileSync(path.join(__dirname, '..', 'reports', 'dashboard.html'), 'utf8');
const errors = [];
const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/dash.html',
  beforeParse(w) { w.addEventListener('error', e => errors.push('window error: ' + e.message)); } });
const w = dom.window, d = w.document;
const $ = s => d.querySelector(s), $$ = s => [...d.querySelectorAll(s)];
let fails = 0;
const check = (name, ok, info = '') => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (info ? '  ' + info : '')); if (!ok) fails++; };
const click = el => el.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
const key = (k, shift = false) => d.dispatchEvent(new w.KeyboardEvent('keydown', { key: k, shiftKey: shift, bubbles: true }));
const change = (el, v) => { el.value = v; el.dispatchEvent(new w.Event('change', { bubbles: true })); };
const toggle = (el, on) => { el.checked = on; el.dispatchEvent(new w.Event('change', { bubbles: true })); };
const px = s => parseFloat(s);
const rotation = () => { const m = /rotate\((-?\d+)deg\)/.exec($('#rotbox img').style.transform); return m ? +m[1] : null; };

const data = JSON.parse($('#data').textContent);
const n = data.docs.length;
check('data parsed', n > 0, 'docs=' + n);
check('no ground truth in data', data.docs.every(x => !('gt' in x) && !('m' in x)) && !('summary' in data));
check('overview rows == docs', $$('#ovin tr.r').length === n);
check('6 summary cards', $$('#ovin .card').length === 6);
check('overview notice present', !!$('#ovin .notice'));
check('no ground truth wording in overview', !/ground truth|GT|Word Acc/.test($('#ovin').textContent));

click($('#ovin th[data-k="words"]'));
const firstAfterSort = $('#ovin tr.r td.name').textContent;
click($('#ovin th[data-k="words"]'));
check('sort toggles order', $('#ovin tr.r td.name').textContent !== firstAfterSort);

const probe = data.docs[0].name.slice(0, 4);
const q = $('#q'); q.value = probe; q.dispatchEvent(new w.Event('input', { bubbles: true }));
check('search filters rows', $$('#ovin tr.r').length >= 1 && $$('#ovin tr.r').length <= n);
$('#q').value = ''; $('#q').dispatchEvent(new w.Event('input', { bubbles: true }));
check('search cleared', $$('#ovin tr.r').length === n);

const idx = data.docs.reduce((best, x, i) => (x.pages.length > data.docs[best].pages.length ? i : best), 0);
const rows = $$('#ovin tr.r');
click(rows[rows.findIndex(r => r.dataset.i == idx)]);
const pagesInDoc = data.docs[idx].pages.length;
check('viewer visible after row click', $('#viewer').style.display === 'flex' && $('#overview').style.display === 'none');
check('search box lost focus when viewer opened', d.activeElement === d.body || d.activeElement.tagName !== 'INPUT');
check('image is a data url', /^data:image\/jpeg;base64,/.test($('#img img').src));
check('our pane has text', $('#paneA').textContent.length > 100);
check('only two panes (image + output)', $$('.grid > .col').length === 2);
check('page select lists every page', $$('#pageSel option').length === pagesInDoc);
check('opens on the page with most issues', +$('#pageSel').value === data.docs[idx].focus);
check('strip has chips', $$('#strip .chip').length === 5);

const first = +$('#pageSel').value;
const size = data.docs[idx].pages[first].size;
const portrait = size[1] > size[0];
check('unrotated: label 0 and rotate(0deg)', $('#rotLabel').textContent === '0°' && rotation() === 0);
const w0 = px($('#rotbox').style.width), h0 = px($('#rotbox').style.height);
check('unrotated box keeps the page aspect ratio', Math.abs(h0 / w0 - size[1] / size[0]) < 0.02, `box=${w0}x${h0} page=${size.join('x')}`);
check('image fills the box when unrotated', px($('#rotbox img').style.width) === w0 && px($('#rotbox img').style.height) === h0);

click($('#rotR'));
check('rotate right: 90deg and label', rotation() === 90 && $('#rotLabel').textContent === '90°');
const w90 = px($('#rotbox').style.width), h90 = px($('#rotbox').style.height);
check('rotate 90: box dimensions swap aspect', Math.abs(h90 / w90 - size[0] / size[1]) < 0.02, `box=${w90}x${h90}`);
check('rotate 90: image keeps its own size', px($('#rotbox img').style.width) !== w90 || !portrait);
click($('#rotR')); click($('#rotR'));
check('rotate right x3 = 270deg', rotation() === 270);
click($('#rotR'));
check('rotate right x4 wraps to 0deg', rotation() === 0);
click($('#rotL'));
check('rotate left from 0 = 270deg', rotation() === 270);
click($('#rot180'));
check('180 button adds 180 (270 -> 90)', rotation() === 90);
key('r');
check('R key rotates right', rotation() === 180);
key('R', true);
check('Shift+R rotates left', rotation() === 90);
click($('#rot0'));
check('reset button returns to 0deg', rotation() === 0 && $('#rotLabel').textContent === '0°');

click($('#rotR')); click($('#rotR'));
const rotatedPage = +$('#pageSel').value;
key('ArrowRight');
const other = +$('#pageSel').value;
if (other !== rotatedPage) {
  check('another page starts unrotated', rotation() === 0);
  key('ArrowLeft');
  check('rotation is remembered per page', rotation() === 180 && +$('#pageSel').value === rotatedPage);
} else {
  key('ArrowLeft');
  check('rotation is remembered per page', rotation() === 180 || pagesInDoc === 1);
}
check('rotation saved in localStorage', Object.values(JSON.parse(w.localStorage.getItem('ocrdash-rot'))).includes(180));
click($('#rot0'));
check('reset clears the saved rotation', Object.keys(JSON.parse(w.localStorage.getItem('ocrdash-rot'))).length === 0);

$('#zoom').value = '200'; $('#zoom').dispatchEvent(new w.Event('input', { bubbles: true }));
check('zoom doubles the box width', Math.abs(px($('#rotbox').style.width) - 2 * w0) <= 2, `w=${$('#rotbox').style.width} w0=${w0}`);
$('#zoom').value = '100'; $('#zoom').dispatchEvent(new w.Event('input', { bubbles: true }));

change($('#pageSel'), '1');
check('page select changes page', $('#paneAH').textContent.includes('صفحه 2'));
key('ArrowLeft');
check('ArrowLeft = next page', +$('#pageSel').value === 2);
key('ArrowRight'); key('ArrowRight');
check('ArrowRight = previous page (twice)', +$('#pageSel').value === 0);
key('ArrowRight');
check('previous page clamps at first page', +$('#pageSel').value === 0);
change($('#pageSel'), String(pagesInDoc - 1)); key('ArrowLeft');
check('next page clamps at last page', +$('#pageSel').value === pagesInDoc - 1);

const withTables = data.docs.findIndex(x => x.pages.some(p => p.html.includes("<table class='t'>")));
change($('#docSel'), String(withTables));
change($('#pageSel'), String(data.docs[withTables].pages.findIndex(p => p.html.includes("<table class='t'>"))));
check('tables rendered as html tables', $$('#paneA table.t').length > 0);

const before = $('#docSel').selectedIndex;
click($('#nextDoc'));
check('next doc button', $('#docSel').selectedIndex === (before + 1) % n);
click($('#prevDoc'));
check('previous doc button', $('#docSel').selectedIndex === before);
key('n'); key('p');
check('N/P keys keep doc in range', $('#docSel').selectedIndex === before);

const inv = data.docs.findIndex(x => x.pages.some(p => p.invoice));
if (inv >= 0) {
  change($('#docSel'), String(inv));
  check('invoice details rendered', $$('#paneA details.more').length >= 1);
}

toggle($('#hl'), false);
check('highlight toggle off', d.body.classList.contains('nohl'));
toggle($('#showImg'), false);
check('image toggle hides pane', d.body.classList.contains('noimg'));
click($('#fsP')); check('font size increases', $('#fsV').textContent === '17');
click($('#focusBtn')); check('focus mode on', d.body.classList.contains('focus'));
key('f'); check('F key leaves focus', !d.body.classList.contains('focus'));

click($('#back'));
check('back to overview', $('#overview').style.display === 'block' && $$('#ovin tr.r').length === n);
check('no script errors', errors.length === 0, errors.join(' | '));
console.log(fails ? `\n${fails} FAILED` : '\nALL PASSED');
process.exit(fails ? 1 : 0);
