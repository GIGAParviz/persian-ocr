const fs = require('fs');
const path = require('path');
const { JSDOM } = require(path.join(__dirname, '..', '.cache', 'nodetools', 'node_modules', 'jsdom'));
const html = fs.readFileSync(path.join(__dirname, '..', 'persian_ocr', 'api', 'static', 'app.html'), 'utf8');

const errors = [], calls = [], exportCalls = [], alerts = [], downloads = [], blobs = [];
let active = 0, maxActive = 0;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const PX = '/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=';
const page = (n, extra = {}) => ({ page: n, image: PX, size: [200, 400], processed_image: PX, processed_size: [200, 400], plain_text: `متن صفحه ${n}`, layout: { size: [200, 400], items: [{ box: [10, 20, 150, 45], text: `متن صفحه ${n}`, conf: 0.9, source: 'line' }], cells: [], tables: [] }, html: `<div class='l'>متن صفحه ${n}</div>`, notes: n === 1 ? "<div class='box rev'>reading_conflict</div>" : '', invoice: '', stats: { words: 3, tables: 0, corr: 0, rev: n === 1 ? 1 : 0, low: 0 }, ...extra });
const doc = (name, pages) => ({ name, file: name + '.png', time: 1.5, mismatch: 0, focus: 0, pages: Array.from({ length: pages }, (_, i) => page(i + 1)) });

const fakeFetch = async (url, opts = {}) => {
  if (url === '/health') return { ok: true, status: 200, json: async () => ({ model_loaded: false, auth_required: true }) };
  if (url.startsWith('/app/export')) {
    const body = JSON.parse(opts.body);
    exportCalls.push({ url, body, key: (opts.headers || {})['X-API-Key'] });
    return { ok: true, status: 200, blob: async () => new w.Blob(['BIN'], { type: 'application/octet-stream' }) };
  }
  const name = opts.body.get('file').name;
  calls.push({ url, name, key: (opts.headers || {})['X-API-Key'] });
  active++; maxActive = Math.max(maxActive, active);
  await sleep(25);
  active--;
  if (name.startsWith('bad')) return { ok: false, status: 422, json: async () => ({ detail: 'فایل PDF معتبر نیست.' }) };
  if (name.startsWith('down')) throw new TypeError('Failed to fetch');
  const pages = name.startsWith('multi') ? 3 : 1;
  const rawJson = JSON.stringify({ file: name, pages: Array.from({ length: pages }, (_, i) => ({ page: i + 1, text_dedup: `متن صفحه ${i + 1}` })) });
  return { ok: true, status: 200, json: async () => ({ doc: doc(name.replace(/\.[^.]+$/, ''), pages), txt: 'TXT:' + name, json: rawJson }) };
};

const dom = new JSDOM(html, {
  runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/app',
  beforeParse(w) {
    w.addEventListener('error', e => errors.push('window error: ' + e.message));
    w.fetch = fakeFetch;
    w.alert = m => alerts.push(m);
    w.URL.createObjectURL = b => { blobs.push(b); return 'blob:' + blobs.length; };
    w.URL.revokeObjectURL = () => {};
    w.HTMLAnchorElement.prototype.click = function () { downloads.push(this.download); };
  },
});
const w = dom.window, d = w.document;
const $ = s => d.querySelector(s), $$ = s => [...d.querySelectorAll(s)];
let fails = 0;
const check = (name, ok, info = '') => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (info ? '  ' + info : '')); if (!ok) fails++; };
const click = el => el.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
const keyDown = (k, shift = false) => d.dispatchEvent(new w.KeyboardEvent('keydown', { key: k, shiftKey: shift, bubbles: true }));
const shown = id => $('#' + id).style.display;
const rotation = () => { const m = /rotate\((-?\d+)deg\)/.exec($('#rotbox img').style.transform); return m ? +m[1] : null; };
const pick = files => { Object.defineProperty($('#file'), 'files', { value: files, configurable: true }); $('#file').dispatchEvent(new w.Event('change', { bubbles: true })); };
const file = name => new w.File(['x'], name);

(async () => {
  await sleep(30);
  check('empty state shown first', shown('empty') === 'flex' && shown('viewer') === 'none' && $('#queue').style.display === 'none');
  check('health pill reflects model state', $('#health').textContent === 'مدل هنوز بارگذاری نشده');
  check('api key field appears when auth is required', $('#keyLabel').style.display === '');
  check('lexicon off by default', $('#lex').checked === false);
  check('file input accepts pdf and images', /pdf/.test($('#file').accept) && /png/.test($('#file').accept));

  $('#key').value = 'k1';
  pick([file('notes.txt')]);
  check('unsupported type is refused with a message', alerts.length === 1 && /notes\.txt/.test(alerts[0]) && calls.length === 0 && Q().length === 0);

  pick([file('multi doc.png'), file('bad.pdf'), file('down.png')]);
  check('three files queued', Q().length === 3 && $$('#queue .item').length === 3);
  check('first file is processing, others wait', Q()[0].status === 'run' && Q()[1].status === 'wait' && shown('busy') === 'flex');
  check('busy box names the file', /multi doc\.png/.test($('#busyT').textContent));
  await sleep(200);
  check('requests run one at a time', maxActive === 1, 'max=' + maxActive);
  check('request carries options and key', calls[0].url === '/app/run?lexicon=false&tables=true&max_pages=0&preprocess=original' && calls[0].key === 'k1');
  check('states: done, error, error', Q().map(x => x.status).join() === 'done,err,err');
  check('first result opens the viewer', shown('viewer') === 'flex' && shown('busy') === 'none');
  check('image is a data url', /^data:image\/jpeg;base64,/.test($('#img img').src));
  check('page select lists the 3 pages', $$('#pageSel option').length === 3);
  check('positioned layout is the default view', !!$('#layoutSheet') && /متن صفحه 1/.test($('#paneA').textContent));
  click($('#layoutToggle'));
  check('continuous text can be selected', !$('#layoutSheet') && /متن صفحه 1/.test($('#paneA').textContent));
  click($('#layoutToggle'));
  check('layout view can be restored', !!$('#layoutSheet'));
  check('notes (reading_conflict) are shown', /reading_conflict/.test($('#paneA').textContent));
  check('strip has chips', $$('#strip .chip').length === 6);

  click($$('#queue .item')[1]);
  check('server error is shown with its message', shown('err') === 'flex' && /PDF معتبر نیست/.test($('#errT').textContent) && /bad\.pdf/.test($('#errT').textContent));
  click($$('#queue .item')[2]);
  check('network failure has a helpful message', /run\.bat serve/.test($('#errT').textContent));
  click($$('#queue .item')[0]);
  check('back to the first result', shown('viewer') === 'flex');

  click($('#rotR'));
  check('rotate right works', rotation() === 90 && $('#rotLabel').textContent === '90°');
  keyDown('ArrowLeft');
  check('next page starts unrotated', +$('#pageSel').value === 1 && rotation() === 0);
  keyDown('ArrowRight');
  check('rotation remembered per page', rotation() === 90);
  click($('#rot0'));
  check('reset rotation', rotation() === 0);

  click($('#dlTxt')); click($('#dlJson')); click($('#dlLayout'));
  check('downloads are named after the input', downloads.join('|') === 'multi doc.txt|multi doc.json|multi doc_layout_p1.html', downloads.join('|'));

  // Inline layout edit syncs to plain_text
  const boxEl = $('#layoutSheet .layout-item');
  boxEl.textContent = 'متن اصلاح‌شده ۱';
  boxEl.dispatchEvent(new w.Event('blur'));
  check('inline layout edit marks page edited', Q()[0].doc.pages[0].plain_text === 'متن اصلاح‌شده ۱' && Q()[0].doc.pages[0].edited === true);

  // Full text editor mode + reset + edit page 2
  click($('#editBtn'));
  check('edit mode opens textarea with current text', !!$('#pageEditor') && $('#pageEditor').value === 'متن اصلاح‌شده ۱');
  click($('#resetEdit'));
  check('reset edit restores original text', $('#pageEditor').value === 'متن صفحه 1' && Q()[0].doc.pages[0].edited === false);
  $('#pageEditor').value = 'اصلاح نهایی صفحه اول';
  $('#pageEditor').dispatchEvent(new w.Event('input', { bubbles: true }));
  check('editor input updates plain_text and strip', Q()[0].doc.pages[0].plain_text === 'اصلاح نهایی صفحه اول' && /ویرایش‌شده/.test($('#strip').textContent));
  click($('#editBtn'));
  check('leaving edit mode returns to viewer', !$('#pageEditor'));

  // Downloads carry edited text across all 3 pages
  click($('#dlTxt')); click($('#dlJson'));
  const txtOut = await blobs[blobs.length - 2].text();
  const jsonOut = JSON.parse(await blobs[blobs.length - 1].text());
  check('txt export includes edited text and all pages', /اصلاح نهایی صفحه اول/.test(txtOut) && /متن صفحه 3/.test(txtOut));
  check('json export includes edited text', jsonOut.pages[0].text_dedup === 'اصلاح نهایی صفحه اول' && jsonOut.pages[0].edited === true);

  click($('#dlDocx'));
  await sleep(30);
  check('word export sends all pages with synced layout edits and key', exportCalls.length === 1 && exportCalls[0].url === '/app/export?format=docx' && exportCalls[0].key === 'k1' && exportCalls[0].body.pages.length === 3 && exportCalls[0].body.pages[0].text === 'اصلاح نهایی صفحه اول' && exportCalls[0].body.pages[0].layout.items[0].text === 'اصلاح نهایی صفحه اول');
  check('word download uses document stem', downloads[downloads.length - 1] === 'multi doc.docx');

  click($('#dlPdf'));
  await sleep(30);
  check('pdf export sends all pages with layout and downloads .pdf', exportCalls.length === 2 && exportCalls[1].url === '/app/export?format=pdf' && exportCalls[1].body.pages.length === 3 && downloads[downloads.length - 1] === 'multi doc.pdf');

  $('#focusBtn').click();
  check('focus mode toggles', d.body.classList.contains('focus'));
  keyDown('f');
  check('F leaves focus mode', !d.body.classList.contains('focus'));

  click($$('#queue .item .x')[1]);
  check('removing an item keeps the selection', Q().length === 2 && $$('#queue .item.on').length === 1 && /multi doc/.test($('#queue .item.on').textContent));
  click($$('#queue .item .x')[0]);
  check('removing the current item selects the next one', Q().length === 1 && /down\.png/.test($('#queue .item.on').textContent));
  click($('#queue .item .x'));
  check('empty queue returns to the drop zone', Q().length === 0 && shown('empty') === 'flex' && $('#queue').style.display === 'none');

  $('#lex').checked = true; $('#lex').dispatchEvent(new w.Event('change', { bubbles: true })); $('#tbl').checked = false; $('#maxp').value = '3';
  w.addFiles([file('ok.png')]);
  await sleep(80);
  check('options are sent', calls[calls.length - 1].url === '/app/run?lexicon=true&tables=false&max_pages=3&preprocess=original');
  check('options are remembered', JSON.parse(w.localStorage.getItem('ocrapp-view')).lex === true);

  check('no script errors', errors.length === 0, errors.join(' | '));
  console.log(fails ? `\n${fails} FAILED` : '\nALL PASSED');
  process.exit(fails ? 1 : 0);
})();

function Q() { return w.eval('Q'); }
