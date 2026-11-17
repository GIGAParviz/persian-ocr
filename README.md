# Persian OCR

Persian OCR extracts text, ruled tables, and selected fields from scanned images and PDFs. It runs on CPU with [Indra OCR](https://huggingface.co/datalab-to/indra-ocr) and adds page orientation, overlapping tiles, table reconstruction, text normalization, and invoice checks. The service includes a browser UI, a CLI, and an HTTP API.

Financial readings need human verification. A plausible total or a consistent invoice equation does not prove that every digit was recognized correctly. Ambiguous cases are reported for review where the pipeline detects them; some errors can still pass silently.

## Features

| Area | Behavior |
| --- | --- |
| Input | PDF pages and PNG, JPEG, BMP, TIFF, or WebP images |
| OCR | Orientation and skew correction, right-to-left recognition, overlapping page tiles |
| Image handling | Header watermark suppression, faint footer recovery, circular stamp reading, and optional preprocessing modes |
| Tables | Ruled-table detection and OCR of individual cells, including dark headers |
| Invoices | Column mapping, item equations, tax and discount checks, and document totals |
| Text | Persian character and digit normalization, identifier validation, Jalali date checks, and an optional organization lexicon |
| Output | Plain text, JSON, and HTML review pages; the Web UI also exports a positioned page-layout HTML file |
| Service | FastAPI, locally bundled Swagger UI, optional API key, and an upload-byte limit |

The default preprocessing mode is `original`. Sharpening, small stroke-gap connection, and mild lighting correction are available for comparison, but some of these modes changed verified amounts in local scans. See [preprocessing results](docs/preprocessing-web-ui.md).

## Requirements and installation

- Python 3.12 and a CPU. A GPU is not required.
- The pinned dependencies in `requirements.lock`.
- The Indra model weights, stored in `indra-ocr/` by default. The weights are downloaded separately and are not tracked by Git.

On Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements.lock
.\.venv\Scripts\hf.exe download datalab-to/indra-ocr --local-dir indra-ocr
```

Set `PERSIAN_OCR_MODEL_DIR` if the weights are elsewhere. The package uses `.cache/` in this repository for its temporary files and sets `HF_HOME` there when that variable is unset. The application does not require an internet connection after installation and model download.

`requirements.txt` is an unpinned reference list. Use `requirements.lock` with `--no-deps` for the tested dependency set.

## Quick start

```powershell
.\.venv\Scripts\python.exe -m persian_ocr run samples/invoice-sample.png --out output/demo
```

The command writes `invoice-sample.txt`, `invoice-sample.json`, and `invoice-sample.html` to `output/demo/`. The bundled sample is synthetic. Open the HTML file to compare the page image with extracted text and review items.

The shortcut `run.bat <file>` runs the same CLI with the local virtual environment. Running `python -m persian_ocr <file>` is equivalent to the `run` subcommand.

### CLI options

```text
python -m persian_ocr run <file> [--out DIR] [--max-pages N] [--no-lexicon] [--no-html] [--no-tables] [--preprocess MODE]
python -m persian_ocr debug <file> [--page N]
python -m persian_ocr serve [--host HOST] [--port PORT]
```

`MODE` is one of `original`, `sharpen`, `sharpen_light`, `connect`, or `soft_light`. `--no-tables` disables table and invoice extraction for comparisons; ordinary line OCR still runs. `debug` writes a page-level invoice inspection under `.cache/debug/`.

## Web UI

Start the local server:

```powershell
.\.venv\Scripts\python.exe -m persian_ocr serve --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000/app](http://127.0.0.1:8000/app). Upload one or more images or PDFs, drop files onto the page, or paste an image. Jobs run one at a time. The organization lexicon is off in the Web UI by default so that the raw model behavior is easier to assess.

The default result view places recognized lines and table cells at their detected coordinates beside the image actually sent to OCR. You can switch to continuous text, adjust the layout zoom, compare the OCR input with the original image, and download the current page as a standalone positioned HTML file. Copying the page copies plain OCR text. The layout is approximate: missed text, wrong boxes, and incorrect table boundaries cannot be reconstructed from the OCR result. See the [layout guide](docs/layout-web-ui.md).

Select an image preprocessing mode before adding files. The selection is saved with each queued file. `original` remains the default because the experimental modes have regressed verified financial amounts. The [preprocessing guide](docs/preprocessing-web-ui.md) records those controls.

The Web UI also offers TXT and JSON downloads. Its JSON includes page geometry under `layout`; the standard `/ocr` response does not include Web UI layout data.

## HTTP API

The server exposes Swagger UI at `/docs` and these main endpoints:

| Endpoint | Result |
| --- | --- |
| `POST /ocr` | Full page text, corrections, review items, tables, and invoice fields |
| `POST /ocr/text` | Final text for each page |
| `POST /ocr/review` | Human-review HTML |
| `POST /ocr/download?format=txt\|json\|html\|zip` | Named output files |
| `POST /validate/national-id`, `/validate/legal-id`, `/validate/iban`, `/validate/postal-code` | Deterministic validation and conservative correction |
| `POST /text/postprocess`, `/text/normalize` | Text-processing rules |
| `POST /invoice/verify-item` | Invoice-row equation checks |
| `GET /health` | Service status |

OCR endpoints accept `lexicon`, `tables`, `max_pages`, and `preprocess`. The API defaults are `lexicon=true`, `tables=true`, `max_pages=0` (all pages), and `preprocess=original`. The Web UI uses `lexicon=false` by default. To compare line OCR without table extraction, set `tables=false`.

```bash
curl -F "file=@samples/invoice-sample.png" "http://127.0.0.1:8000/ocr?lexicon=false"
curl -F "file=@samples/invoice-sample.png" -OJ "http://127.0.0.1:8000/ocr/download?format=zip"
```

By default `serve` listens on `0.0.0.0:8000` and has no authentication. For local use, bind to `127.0.0.1`. For network access, set `PERSIAN_OCR_API_KEY` and send it in the `X-API-Key` header. Uploaded files are kept in `.cache/tmp` only during processing, then removed. OCR requests are serialized because the model state is shared. The upload limit controls file bytes, not decoded image size or PDF work.

## Python API

```python
from persian_ocr.config import PipelineConfig, PreprocessMode
from persian_ocr.engine import OcrEngine
from persian_ocr.pipeline import process_document

engine = OcrEngine.load(threads=4)
config = PipelineConfig(use_lexicon=False, preprocess=PreprocessMode.original)
result = process_document(engine, "samples/invoice-sample.png", config)
page = result["pages"][0]
print(page["text_dedup"])
print(page["review_queue"])
```

`text_dedup` combines table rows and lines outside tables without their usual duplicates. `text` contains normalized line readings. `corrections`, `review_queue`, `low_confidence_lines`, `tables_markdown`, and `invoice` hold the additional evidence. `invoice` may be `null` when no invoice is recognized. `PipelineConfig.baseline(tiling=False)` provides a less engineered comparison path.

## Docker

The root Compose file builds a CPU image with the model weights and exposes the API and Web UI on port 8000:

```bash
docker compose up -d --build
```

The build downloads a pinned Indra model revision. Runtime OCR does not require internet access. Set `PERSIAN_OCR_API_KEY` and, if needed, `PERSIAN_OCR_PORT` in the environment before starting Compose. Review the network binding before exposing the service.

The workflow in `.github/workflows/docker.yml` runs unit tests, builds an image, starts it, checks `/app` and `/docs`, performs OCR on the synthetic `deploy/test-invoice.png` with and without table extraction, and pushes GHCR tags only if those steps pass. The image name is `ghcr.io/ai-transformation-team/ocr`; registry access depends on the repository and package permissions.

`deploy/docker-compose.yml` can run a prebuilt image. `deploy/check.ps1` and `deploy/check.sh` load or start it, wait for health, and run a real OCR smoke check. The optional image tarball is generated locally; it is not tracked in Git.

## Outputs and pipeline

| Output | Contents |
| --- | --- |
| `<name>.txt` | Final `text_dedup` per page |
| `<name>.json` | Raw and processed text, corrections, review queue, low-confidence lines, tables, and invoice data |
| `<name>.html` | Page image beside extracted text and review evidence |
| Web UI layout HTML | Positioned text for one page, exported from `/app` |

The main processing path is:

```text
PDF or image
  -> grayscale page rendering
  -> optional preprocessing
  -> orientation and skew correction
  -> overlapping tile OCR and targeted recovery
  -> ruled-table detection and cell OCR
  -> text normalization and invoice checks
  -> TXT, JSON, and HTML
```

The [pipeline walkthrough](docs/pipeline-walkthrough.md) traces each stage. `tools/pipeline_visual_report.py` can generate a local HTML report with intermediate images. `tools/descreen_ab_report.py`, `tools/preprocessing_stage_report.py`, and `tools/soft_lighting_report.py` run local comparisons; they do not enable those experimental filters in the default OCR path. Generated reports and user-provided scans stay outside Git.

## Evaluation and tests

Earlier in-sample evaluation covered eight documents and 27 pages. On six shorter documents, reported word accuracy improved from 74.2% for the Indra baseline to 83.9% for this pipeline; unordered WER changed from 25.8% to 16.3%. These results are historical, mostly on documents used during development, and should not be treated as out-of-sample performance. Some ground-truth numbers required manual verdicts or masking. Equation consistency is not OCR accuracy. The evaluation code is under `evaluation/`; generated reports and private ground truth are not tracked.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

Tests that need local Indra weights or user-provided images skip when those assets are unavailable. Optional browser smoke checks in `tools/` require `jsdom` installed under `.cache/nodetools`.

## Known limitations

- Unruled tables are not supported, and low-quality scans can lose digits at cell boundaries.
- Multi-column reading order can change after tile merging. The spatial Web UI view can only position detected text.
- The invoice document logic assumes that all pages of one PDF belong to one invoice.
- A failure on one page or table can stop processing of the full document.
- The model can confuse faint digits and text under opaque stamps. Targeted payable recovery is guarded and limited to the pattern documented in [the recovery note](docs/payable-recovery-result.md).
- Global image preprocessing can make OCR worse. Keep `original` as the reference when evaluating new scans.
- Only the first page of a multi-page TIFF is read. The API runs one OCR request at a time.
- The default network deployment is unauthenticated unless an API key is configured. Upload-byte limits do not cap decoded pixels or PDF complexity.

## License

Indra model weights have their own [license](https://huggingface.co/datalab-to/indra-ocr). Check its terms before organizational or commercial deployment. The model license is also included with downloaded weights and in the Docker image.
