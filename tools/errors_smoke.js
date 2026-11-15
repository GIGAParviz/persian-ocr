const fs = require('fs');
const path = require('path');
const { JSDOM } = require(path.join(__dirname, '..', '.cache', 'nodetools', 'node_modules', 'jsdom'));
const html = fs.readFileSync(path.join(__dirname, '..', 'reports', 'number_errors.html'), 'utf8');
const errors = [];
let copied = null;
const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/errors.html',
  beforeParse(w) {
    w.addEventListener('error', e => errors.push('window error: ' + e.message));
    w.confirm = () => true;
    Object.defineProperty(w.navigator, 'clipboard', { value: { writeText: t => { copied = t; } } });
  } });
const w = dom.window, d = w.document;
const $ = s => d.querySelector(s), $$ = s => [...d.querySelectorAll(s)];
let fails = 0;
const check = (name, ok, info = '') => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (info ? '  ' + info : '')); if (!ok) fails++; };
const click = el => el.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
const change = (el, v) => { el.value = v; el.dispatchEvent(new w.Event('change', { bubbles: true })); };

const data = JSON.parse($('#data').textContent);
const n = data.rows.length;
const articles = () => $$('#list article.row');
check('data parsed', n > 0, 'rows=' + n);
check('one card per row', articles().length === n);
check('summary total matches', data.summary.total === n);
check('kind cards present', $$('#cards .card').length === 2 + Object.keys(data.kinds).length);
check('crops are data urls', $$('#list .img img').every(i => /^data:image\/jpeg;base64,/.test(i.src)) && $$('#list .img img').length === data.summary.located);
check('rows without a crop say so', $$('#list .noimg').length === n - data.summary.located);
check('every row shows GT and OCR numbers', articles().every(a => a.querySelectorAll('.nums code').length === 2));
check('every row has three verdict buttons', articles().every(a => a.querySelectorAll('.verdicts button').length === 3));
check('diff marks are rendered', $$('#list mark').length > 0, 'marks=' + $$('#list mark').length);

const firstKind = Object.keys(data.summary.by_kind)[0];
click($$('#filters .chipbtn').find(b => b.dataset.k === firstKind));
check('kind filter narrows the list', articles().length === data.summary.by_kind[firstKind]);
click($$('#filters .chipbtn').find(b => b.dataset.k === 'all'));
check('"all" restores the list', articles().length === n);

const doc = Object.keys(data.summary.by_doc)[0];
change($('#docSel'), doc);
check('document filter narrows the list', articles().length === data.summary.by_doc[doc]);
change($('#docSel'), 'all');

const first = articles()[0], id = first.dataset.id;
click(first.querySelector('[data-v="gt"]'));
check('verdict is applied to the card', first.classList.contains('v-gt') && first.querySelector('[data-v="gt"]').classList.contains('on'));
check('verdict is saved', JSON.parse(w.localStorage.getItem('ocrerr-verdicts'))[id] === 'gt');
check('tally updated', /قضاوت‌شده 1 از/.test($('#tally').textContent));
click(first.querySelector('[data-v="gt"]'));
check('clicking the same verdict clears it', !first.classList.contains('v-gt') && !JSON.parse(w.localStorage.getItem('ocrerr-verdicts'))[id]);

click(articles()[0].querySelector('[data-v="ocr"]'));
click(articles()[1].querySelector('[data-v="image"]'));
change($('#verSel'), 'none');
check('"no verdict" filter hides judged rows', articles().length === n - 2);
change($('#verSel'), 'ocr');
check('verdict filter shows only that verdict', articles().length === 1);
change($('#verSel'), 'all');

click($('#copy'));
const exported = JSON.parse(copied);
check('export contains judged rows only', exported.length === 2 && exported.every(r => r.doc && r.gt && 'ocr' in r && r.verdict));
check('export carries the verdicts', exported.some(r => r.verdict === 'ocr') && exported.some(r => r.verdict === 'image'));

click($('#clear'));
check('clear removes all verdicts', Object.keys(JSON.parse(w.localStorage.getItem('ocrerr-verdicts'))).length === 0 && /قضاوت‌شده 0 از/.test($('#tally').textContent));
check('no script errors', errors.length === 0, errors.join(' | '));
console.log(fails ? `\n${fails} FAILED` : '\nALL PASSED');
process.exit(fails ? 1 : 0);
