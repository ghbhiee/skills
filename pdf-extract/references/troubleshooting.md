# pdf-extract — troubleshooting & engine notes

Read this when the runner script misbehaves or you need to tune extraction. The
script `scripts/pdf_extract.py` already handles the common cases automatically;
this file explains *why*, so you can adapt when something new comes up.

## How the mode is chosen
`text_per_page()` samples ~15 pages spread across the document and averages the
extractable characters. A real text layer yields hundreds of chars/page; a
scanned/image PDF yields single digits (page numbers only). The threshold
(`--text-threshold`, default 20) splits the two. Override with `--mode local`
or `--mode ocr` when you already know.

## Known opendataloader-pdf failures (and why the script escalates)
`opendataloader_pdf.convert()` **swallows engine exceptions** — on a crash it
prints a `SEVERE` line to the log and writes **no output**, without raising. So
the script cannot catch the exception; it detects success by checking the output
file is non-empty, and escalates if not.

1. **`RasterFormatException: (x + width) is outside raster`**
   An image whose bounding box extends past the page raster crashes the
   image-writer, killing the *whole file* (silent empty output). Fix: re-run with
   `image_output="off"` — the script does this automatically as retry #2. You
   lose extracted images but keep all text. (Seen on a PEP English textbook.)

2. **`IllegalArgumentException: Comparison method violates its general contract!`**
   A `sortPageContents` comparator bug (Java TimSort) that fires in
   post-processing on some PDFs, in both Local and hybrid paths. Unfixable from
   our side (compiled JAR). The script falls back to **docling OCR**. (Seen on a
   简谱 music textbook, which also had no text layer — OCR was the right call
   anyway.)

If you hit a *new* opendataloader crash: confirm the output is empty, then just
let the fallback run, or pass `--mode ocr` to skip straight to docling.

## OCR (docling + EasyOCR) notes
- **Language matters.** EasyOCR defaults to `["fr","de","es","en"]` — **no
  Chinese**. The script forces `--ocr-lang ch_sim,en`. For other scripts use the
  EasyOCR codes (`japan`, `korean`, `ch_tra`, etc.). Mixed-language pages: list
  several, but EasyOCR slows down with more languages.
- **It is slow on CPU** (~30–60 s/page; no CUDA on Apple Silicon, and EasyOCR
  doesn't use MPS). For a big scanned book use `--ocr-workers 4` to split pages
  across processes — roughly Nx faster, bounded by RAM (each worker loads ~2 GB
  of models; 4 workers ≈ 8 GB).
- **First run downloads models** (docling layout + EasyOCR weights) to
  `~/.cache`. One-time, a few hundred MB.
- **Quality ceiling:** OCR only recovers *text*. Diagrams, musical notation,
  handwriting stay as images. For a 简谱 book you get titles / composers /
  lyrics, not the melody line. Set expectations accordingly.
- `do_table_structure=False` is set for speed; turn it on in `_build_converter`
  if you need TableFormer to reconstruct complex tables from scanned pages.

## Output layout
- Local mode writes `<stem>.md` (or `.json`/`.html`/`.txt`) plus a
  `<stem>_images/` folder (unless `--no-images`). The markdown references images
  by **relative** path, so keep the `_images/` folder next to the `.md`.
- OCR markdown has no extracted image files (text only); pages are separated by
  `<!-- pages a-b -->` markers when run in parallel chunks.

## Picking format
- `markdown` — best default for LLM/RAG context.
- `json` — bounding boxes + semantic element types; use when you need layout
  coordinates or to post-process structure.
- `markdown-with-images` — embeds images inline (base64); large files.
- You can request several at once: `--format markdown,json`.

## Quick manual probe (when deciding by hand)
```python
import fitz
d = fitz.open("file.pdf")
print(sum(len(d[i].get_text("text").strip()) for i in range(min(10, d.page_count))))
# hundreds+ -> Local mode;  single digits -> needs OCR
```
