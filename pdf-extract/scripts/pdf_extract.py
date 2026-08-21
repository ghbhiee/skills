#!/usr/bin/env python3
"""
pdf_extract.py — Extract structured data (markdown / json) from PDF.

Decision flow (the whole point of this script):
  1. Probe each PDF's text layer with PyMuPDF (chars per page over a sample).
  2. Has a real text layer  -> opendataloader-pdf "Local" mode (fast, accurate,
     deterministic, no GPU). This is the right path for >90% of PDFs.
  3. No usable text layer (scanned / image-only) -> docling + EasyOCR.
  4. Robustness: opendataloader silently writes an EMPTY output on two known bugs
     (RasterFormatException on an out-of-raster image; a sortPageContents
     comparator crash). We detect the empty output and escalate:
         local(images on) -> local(images off) -> docling OCR.
     So a hard text-layer PDF still comes out, just via a different engine.

Usage:
  python3 pdf_extract.py INPUT [INPUT ...] [-o OUTDIR] [options]

INPUT may be a .pdf file or a directory (all *.pdf inside are processed).

Run `python3 pdf_extract.py --help` for the full option list.
If imports fail, run the sibling `setup.sh` to install dependencies.
"""
import argparse
import glob
import json
import os
import sys
import site
import subprocess
import time

TEXT_EXT = {"markdown": ".md", "markdown-with-html": ".md",
            "markdown-with-images": ".md", "text": ".txt",
            "html": ".html", "json": ".json"}


def log(msg):
    print(msg, flush=True)


def _java_works():
    try:
        return subprocess.run(["java", "-version"], capture_output=True).returncode == 0
    except Exception:
        return False


def ensure_paths():
    """Make `java` reachable, user-site packages importable, and the locale
    UTF-8. The last one matters: with no LANG/LC_ALL set (common when launched
    from a non-interactive process), the JVM decodes argv with US-ASCII and
    cannot open a PDF whose filename has non-ASCII chars (e.g. Chinese) — it
    exits 1 with no clear error. Forcing a UTF-8 locale fixes that."""
    if not os.environ.get("LC_ALL") and not os.environ.get("LANG"):
        os.environ["LC_ALL"] = "en_US.UTF-8"
        os.environ["LANG"] = "en_US.UTF-8"
    try:
        sys.path.append(site.getusersitepackages())
    except Exception:
        pass
    # Note: don't trust `which java`. macOS ships a /usr/bin/java *stub* that
    # exists even with no JDK and exits 1 ("Unable to locate a Java Runtime"),
    # which would silently break the engine. Check java actually RUNS instead.
    if not _java_works():
        for cand in ("/opt/homebrew/opt/openjdk@21/bin",
                     "/opt/homebrew/opt/openjdk/bin",
                     "/opt/homebrew/opt/openjdk@17/bin",
                     "/usr/local/opt/openjdk/bin",
                     "/opt/homebrew/opt/openjdk@11/bin"):
            if os.path.exists(os.path.join(cand, "java")):
                os.environ["PATH"] = cand + os.pathsep + os.environ.get("PATH", "")
                break


def text_stats(pdf, cap=400):
    """Scan the WHOLE document (not a small sample) and report avg chars/page and
    the fraction of near-textless pages. Sampling is unreliable for *mixed* PDFs
    — e.g. a scanned music book whose only text is a few front-matter pages: a
    15-page sample lands on those and over-estimates, but the true average is
    near zero. The textless fraction additionally catches docs whose average is
    dragged up by a handful of dense pages while most pages are images."""
    import fitz
    doc = fitz.open(pdf)
    n = doc.page_count
    if n == 0:
        return 0.0, 1.0, 0
    idx = range(n) if n <= cap else [int(i * (n - 1) / (cap - 1)) for i in range(cap)]
    counts = [len(doc[i].get_text("text").strip()) for i in idx]
    avg = sum(counts) / len(counts)
    textless = sum(1 for c in counts if c < 10) / len(counts)
    return avg, textless, n


def primary_output(pdf, outdir, fmt):
    stem = os.path.splitext(os.path.basename(pdf))[0]
    first = fmt.split(",")[0].strip()
    return os.path.join(outdir, stem + TEXT_EXT.get(first, ".md"))


def nonempty(path, floor=50):
    return path and os.path.exists(path) and os.path.getsize(path) > floor


# ---------------------------------------------------------------- local engine
def extract_local(pdf, outdir, fmt, images, pages):
    """opendataloader-pdf Local mode. Returns output path if it produced
    non-empty output, else None (caller escalates)."""
    import opendataloader_pdf as odl
    out = primary_output(pdf, outdir, fmt)

    def run(image_output):
        kw = dict(input_path=[pdf], output_dir=outdir, format=fmt, quiet=True)
        if pages:
            kw["pages"] = pages
        if image_output:
            kw["image_output"] = image_output
        try:
            odl.convert(**kw)
        except Exception as e:           # convert() usually swallows engine errors,
            log("    local engine raised: %s" % e)  # but guard anyway

    run("off" if not images else None)
    if nonempty(out):
        return out
    # Empty output: most often the RasterFormatException image bug. Retry with
    # images disabled, which skips the crashing image-writer code path.
    if images:
        log("    local output empty -> retrying with images off (raster-bug workaround)")
        run("off")
        if nonempty(out):
            return out
    return None


# ----------------------------------------------------------------- ocr engine
_PAGES_NOTE_SHOWN = False


def parse_range(pages):
    """docling page_range only supports one (start,end). Return it or None."""
    if not pages:
        return None
    s = pages.strip()
    if "," in s:
        return None
    if "-" in s:
        a, b = s.split("-", 1)
        return (int(a), int(b))
    return (int(s), int(s))


def _build_converter(lang, force_ocr):
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import EasyOcrOptions, PdfPipelineOptions
    opts = PdfPipelineOptions(
        do_ocr=True, do_table_structure=False,
        ocr_options=EasyOcrOptions(force_full_page_ocr=force_ocr, lang=lang))
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def _ocr_chunk(pdf, lang, force_ocr, page_range):
    """Worker: OCR one page range, return markdown. Top-level for pickling."""
    import os as _os
    _os.environ.setdefault("OMP_NUM_THREADS", "2")
    try:
        import torch
        torch.set_num_threads(2)
    except Exception:
        pass
    conv = _build_converter(lang, force_ocr)
    res = conv.convert(pdf, page_range=page_range) if page_range else conv.convert(pdf)
    return res.document.export_to_markdown()


def extract_ocr(pdf, outdir, fmt, lang_csv, pages, force_ocr, workers):
    """docling + EasyOCR. Writes markdown (or json) and returns the path."""
    lang = [x.strip() for x in lang_csv.split(",") if x.strip()]
    out = primary_output(pdf, outdir, "json" if fmt.split(",")[0] == "json" else "markdown")
    want_json = fmt.split(",")[0].strip() == "json"
    pr = parse_range(pages)

    if want_json or workers <= 1 or pr is not None:
        # Single process (json export or an explicit single range).
        conv = _build_converter(lang, force_ocr)
        res = conv.convert(pdf, page_range=pr) if pr else conv.convert(pdf)
        if want_json:
            json.dump(res.document.export_to_dict(), open(out, "w"),
                      ensure_ascii=False, indent=2)
        else:
            open(out, "w").write(res.document.export_to_markdown())
        return out

    # Parallel full-document OCR: split pages into `workers` chunks. This is the
    # big lever for scanned books — EasyOCR on CPU is ~30-60s/page, so 4 workers
    # cut wall-clock roughly 4x.
    import fitz
    from concurrent.futures import ProcessPoolExecutor
    n = fitz.open(pdf).page_count
    step = (n + workers - 1) // workers
    ranges = [(i + 1, min(i + step, n)) for i in range(0, n, step)]
    log("    OCR %d pages in %d parallel chunks: %s" % (n, len(ranges), ranges))
    parts = [None] * len(ranges)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_ocr_chunk, pdf, lang, force_ocr, r): i
                for i, r in enumerate(ranges)}
        for fut in futs:
            i = futs[fut]
            parts[i] = fut.result()
    sep = "\n\n---\n\n"
    open(out, "w").write(sep.join("<!-- pages %d-%d -->\n\n%s" % (ranges[i][0], ranges[i][1], (parts[i] or "").strip())
                                  for i in range(len(parts))))
    return out


# --------------------------------------------------------------------- driver
def process(pdf, outdir, args):
    name = os.path.basename(pdf)
    t = time.time()
    avg, textless, npages = text_stats(pdf)
    # The probe is a HINT, not the router. PyMuPDF under-reports on some font
    # encodings (e.g. a science textbook reads as 0 chars/page in fitz yet
    # opendataloader extracts it fully), so we never skip local based on it.
    # In auto mode we always try the cheap local engine first and fall back to
    # OCR only when it produces nothing — that is the reliable signal.
    hint = "looks scanned" if (avg < args.text_threshold or textless >= 0.6) else "has text layer"
    log("[%s] %d pages, %.0f chars/page, %.0f%% textless (%s) -> mode=%s"
        % (name, npages, avg, textless * 100, hint, args.mode))

    out = None
    used = args.mode
    if args.mode in ("auto", "local"):
        out = extract_local(pdf, outdir, args.format, not args.no_images, args.pages)
        used = "local"
        if not out and args.mode == "auto":
            log("    local produced nothing (no text layer / engine crash) -> docling OCR")
            used = "ocr(fallback)"
            out = extract_ocr(pdf, outdir, args.format, args.ocr_lang, args.pages,
                              args.force_ocr, args.ocr_workers)
    else:  # forced ocr
        out = extract_ocr(pdf, outdir, args.format, args.ocr_lang, args.pages,
                          args.force_ocr, args.ocr_workers)

    dt = time.time() - t
    if nonempty(out, 0):
        kb = os.path.getsize(out) // 1024
        log("    OK via %s in %.1fs -> %s (%dKB)" % (used, dt, out, kb))
        return True
    log("    FAILED in %.1fs (no usable output)" % dt)
    return False


def collect_pdfs(inputs):
    pdfs = []
    for p in inputs:
        if os.path.isdir(p):
            pdfs += sorted(glob.glob(os.path.join(p, "*.pdf")))
        elif p.lower().endswith(".pdf"):
            pdfs.append(p)
        else:
            log("skip (not a pdf/dir): %s" % p)
    return pdfs


def main():
    ap = argparse.ArgumentParser(description="Extract structured markdown/json from PDF.")
    ap.add_argument("inputs", nargs="+", help="PDF file(s) or director(ies)")
    ap.add_argument("-o", "--output-dir", help="Output dir (default: alongside each PDF)")
    ap.add_argument("-f", "--format", default="markdown",
                    help="markdown|json|text|html|markdown-with-images (comma-sep). Default markdown")
    ap.add_argument("--mode", choices=["auto", "local", "ocr"], default="auto",
                    help="auto = probe text layer and choose (default)")
    ap.add_argument("--text-threshold", type=float, default=20.0,
                    help="chars/page below which a PDF is treated as scanned (default 20)")
    ap.add_argument("--no-images", action="store_true",
                    help="Local mode: skip image extraction (also dodges the raster bug)")
    ap.add_argument("--ocr-lang", default="ch_sim,en",
                    help="EasyOCR languages, comma-sep (default ch_sim,en)")
    ap.add_argument("--force-ocr", action="store_true", default=True,
                    help="OCR: force full-page OCR (default on; best for no-text PDFs)")
    ap.add_argument("--ocr-workers", type=int, default=1,
                    help="OCR: parallel page-chunk workers for big scanned docs (default 1)")
    ap.add_argument("--pages", help='Page range, e.g. "5-12" (OCR: single range only)')
    args = ap.parse_args()

    ensure_paths()
    pdfs = collect_pdfs(args.inputs)
    if not pdfs:
        log("No PDFs found."); sys.exit(1)
    log("Found %d PDF(s)." % len(pdfs))

    ok = 0
    for pdf in pdfs:
        outdir = args.output_dir or os.path.dirname(os.path.abspath(pdf))
        os.makedirs(outdir, exist_ok=True)
        try:
            ok += 1 if process(pdf, outdir, args) else 0
        except ImportError as e:
            log("Missing dependency: %s\n-> run this skill's scripts/setup.sh" % e)
            sys.exit(2)
        except Exception as e:
            log("    ERROR on %s: %s" % (os.path.basename(pdf), e))
    log("Done: %d/%d succeeded." % (ok, len(pdfs)))
    sys.exit(0 if ok == len(pdfs) else 3)


if __name__ == "__main__":
    main()
