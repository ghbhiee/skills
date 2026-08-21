# pdf-extract

Turn PDFs into clean **Markdown or JSON** — the kind you can feed to an LLM, index for RAG,
or load into a database.

Reading a PDF is not the hard part. The hard part is picking the right engine for each file
and surviving the ways they fail. That judgment is baked into `scripts/pdf_extract.py`, so
you run one command and get output.

## Why not just pdfminer / PyPDF

Naive text extraction loses reading order (two-column papers interleave), loses tables
entirely, and returns nothing at all for scanned pages. Instead:

- **Has a text layer** → `opendataloader-pdf` **Local mode**. A deterministic rule engine
  that restores reading order (XY-Cut), heading hierarchy, tables and bounding boxes.
  ~60 pages/sec, no GPU. This is the path almost every PDF takes.
- **No text layer** (scanned / image-only) → `docling` + EasyOCR, Chinese (`ch_sim`) enabled
  by default.
- Two known silent crashes in the Local engine are detected and downgraded around, so you
  still get output instead of a 0-byte file.

The fallback chain runs automatically per file: `local (images on) → local (images off) → docling OCR`.

One trap worth knowing, because it will bite anyone who rolls their own router: **you cannot
use PyMuPDF to decide whether a PDF has a text layer.** For some font encodings `fitz` reports
0 characters per page on a document the Local engine happily extracts 388 KB of text from.
So `auto` mode always *tries* Local first (it takes ~10 s) and only falls back to OCR when the
output comes back empty. The `fitz` probe is printed as information, never used to route.

## Install

Hand this to your coding agent:

> Install the pdf-extract skill from https://github.com/ghbhiee/skills and run its setup script.

Or do it by hand:

```bash
git clone https://github.com/ghbhiee/skills.git /tmp/skills
mkdir -p ~/.claude/skills
cp -r /tmp/skills/pdf-extract ~/.claude/skills/pdf-extract
chmod +x ~/.claude/skills/pdf-extract/scripts/*.sh
bash ~/.claude/skills/pdf-extract/scripts/setup.sh
```

`setup.sh` installs Java 21 (the Local engine is a Java jar), `opendataloader-pdf` and
`pymupdf`, then asks before installing `docling` + EasyOCR — that one pulls in PyTorch and
costs several GB, and you only need it for scanned PDFs. The script auto-detects Homebrew's
`openjdk@21` path, so you do not have to touch `PATH`.

**No credentials.** Everything runs locally; nothing is uploaded anywhere.

## Usage

```bash
S=~/.claude/skills/pdf-extract/scripts/pdf_extract.py

# single file -> markdown next to it
python3 $S report.pdf

# a whole directory, output collected in one folder
python3 $S ~/papers/ -o ~/papers/md

# structured JSON with coordinates
python3 $S invoice.pdf -f json

# known scan, Chinese + Japanese, 4 parallel OCR workers
python3 $S scan.pdf --mode ocr --ocr-lang ch_sim,japan,en --ocr-workers 4

# text-layer PDF, but skip the thousands of embedded images
python3 $S textbook.pdf --no-images
```

`INPUT` is a `.pdf` or a directory (all `*.pdf` inside get processed). For each file the
script prints page count, characters per page, which mode it chose, and the output path and
size — read those lines to confirm you got what you expected.

| Option | Effect |
|--------|--------|
| `-f, --format` | `markdown` (default) / `json` / `text` / `html` / `markdown-with-images`, comma-separated for several at once |
| `--mode` | `auto` (default) / `local` / `ocr` |
| `--text-threshold` | chars/page below which a file is treated as scanned (default 20) |
| `--no-images` | Local mode skips image export — also sidesteps the raster crash |
| `--ocr-lang` | EasyOCR languages, comma-separated (default `ch_sim,en`) |
| `--ocr-workers` | parallel OCR processes (default 1; CPU OCR is slow, use 4 on big files) |
| `--pages` | page range, e.g. `5-12` (OCR supports one contiguous range) |

CPU-only OCR is slow — estimate with `--pages` on a few pages before committing to a
300-page scan.

## Troubleshooting

[`references/troubleshooting.md`](references/troubleshooting.md) covers the two known
`opendataloader` crashes and what causes them, OCR tuning, the output layout, and how to
choose between the formats.

## Not this skill

- **Translating** a PDF while keeping its layout → [pdf-translate](../pdf-translate/).
- Merging / splitting / filling forms / watermarking → a general `pdf` skill, not this one.
  This skill only extracts structure.
