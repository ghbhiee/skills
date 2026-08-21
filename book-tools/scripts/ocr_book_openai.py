#!/usr/bin/env python3
import argparse
import base64
import json
import shutil
import subprocess
import tempfile
import time
import zipfile
from html import escape
from pathlib import Path

from openai import OpenAI


def render_pages(pdf: Path, pages_dir: Path, dpi: int = 144):
    pages_dir.mkdir(parents=True, exist_ok=True)
    first = pages_dir / "page-001.jpg"
    if first.exists():
        return sorted(pages_dir.glob("page-*.jpg"))
    subprocess.run(
        ["pdftoppm", "-jpeg", "-gray", "-r", str(dpi), str(pdf), str(pages_dir / "page")],
        check=True,
    )
    return sorted(pages_dir.glob("page-*.jpg"))


def ocr_chunks(images, out_dir: Path, model: str, chunk_size: int, pause_seconds: float):
    client = OpenAI()
    out_dir.mkdir(parents=True, exist_ok=True)
    for idx in range(0, len(images), chunk_size):
        group = images[idx : idx + chunk_size]
        start_page = idx + 1
        end_page = idx + len(group)
        out_file = out_dir / f"chunk_{start_page:03d}_{end_page:03d}.txt"
        meta_file = out_dir / f"chunk_{start_page:03d}_{end_page:03d}.json"
        if out_file.exists() and meta_file.exists():
            print("SKIP", out_file.name, flush=True)
            continue
        content = [
            {
                "type": "input_text",
                "text": (
                    "OCR these Chinese scanned book pages into plain text only. "
                    "Preserve the original wording as faithfully as possible. "
                    "Do not summarize. Do not rewrite stylistically. "
                    "Remove obvious decorative artifacts, repeated running headers/footers "
                    "when clearly non-body text, and OCR garbage that is clearly not part of "
                    "the content. Fix obviously broken line wraps caused by OCR when the "
                    "sentence clearly continues. Keep meaningful titles and paragraph breaks. "
                    "Separate pages clearly with markers like ===== PAGE N =====."
                ),
            }
        ]
        for page_num, img_path in enumerate(group, start=start_page):
            encoded = base64.b64encode(img_path.read_bytes()).decode("ascii")
            content.append({"type": "input_text", "text": f"PAGE {page_num}"})
            content.append(
                {"type": "input_image", "image_url": f"data:image/jpeg;base64,{encoded}"}
            )
        started = time.time()
        response = client.responses.create(
            model=model,
            input=[{"role": "user", "content": content}],
        )
        elapsed = time.time() - started
        out_file.write_text(response.output_text, encoding="utf-8")
        usage = getattr(response, "usage", None)
        meta = {
            "start_page": start_page,
            "end_page": end_page,
            "elapsed_seconds": elapsed,
            "usage": usage.model_dump() if hasattr(usage, "model_dump") else str(usage),
        }
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print("DONE", out_file.name, "sec=", round(elapsed, 2), flush=True)
        if pause_seconds > 0:
            time.sleep(pause_seconds)


def merge_chunks(out_dir: Path, merged_txt: Path):
    parts = sorted(out_dir.glob("chunk_*.txt"))
    with merged_txt.open("w", encoding="utf-8") as output:
        for part in parts:
            output.write(part.read_text(encoding="utf-8").rstrip())
            output.write("\n\n")


def build_epub(src_txt: Path, out_epub: Path, title: str, creator: str):
    text = src_txt.read_text(encoding="utf-8")
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    body = "\n".join(
        f'<p>{escape(paragraph).replace(chr(10), "<br/>")}</p>'
        for paragraph in paragraphs
    )
    work = Path(tempfile.mkdtemp(prefix="epubbuild_"))
    try:
        (work / "META-INF").mkdir(parents=True)
        (work / "OEBPS").mkdir(parents=True)
        (work / "mimetype").write_text("application/epub+zip", encoding="utf-8")
        (work / "META-INF" / "container.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
            '  <rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles>\n</container>\n',
            encoding="utf-8",
        )
        (work / "OEBPS" / "book.xhtml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN"><head>'
            f"<title>{escape(title)}</title><meta charset=\"utf-8\"/>"
            "<style>body{font-family:serif;line-height:1.6;margin:5%;}"
            "h1{text-align:center;}p{text-indent:2em;margin:.4em 0;}</style></head>"
            f"<body><h1>{escape(title)}</h1>{body}</body></html>",
            encoding="utf-8",
        )
        (work / "OEBPS" / "nav.xhtml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN">'
            f"<head><title>目录</title><meta charset=\"utf-8\"/></head><body>"
            f'<nav epub:type="toc" id="toc"><ol><li><a href="book.xhtml">{escape(title)}</a>'
            "</li></ol></nav></body></html>",
            encoding="utf-8",
        )
        (work / "OEBPS" / "content.opf").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
            'unique-identifier="bookid" xml:lang="zh-CN"><metadata '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f'<dc:identifier id="bookid">ocr-book</dc:identifier><dc:title>{escape(title)}</dc:title>'
            f"<dc:language>zh-CN</dc:language><dc:creator>{escape(creator)}</dc:creator>"
            '</metadata><manifest><item id="book" href="book.xhtml" '
            'media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" '
            'media-type="application/xhtml+xml" properties="nav"/></manifest>'
            '<spine><itemref idref="book"/></spine></package>',
            encoding="utf-8",
        )
        with zipfile.ZipFile(out_epub, "w") as archive:
            archive.write(work / "mimetype", "mimetype", compress_type=zipfile.ZIP_STORED)
            for path in sorted(work.rglob("*")):
                if path.is_dir() or path.name == "mimetype":
                    continue
                archive.write(
                    path,
                    path.relative_to(work).as_posix(),
                    compress_type=zipfile.ZIP_DEFLATED,
                )
    finally:
        shutil.rmtree(work)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("--out-dir", default="tmp/openai_book_ocr_skill")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--chunk-size", type=int, default=15)
    parser.add_argument("--pause-seconds", type=float, default=0.75)
    parser.add_argument("--title", default="OCR Book")
    parser.add_argument("--creator", default="Unknown")
    args = parser.parse_args()

    pdf = Path(args.pdf).resolve()
    out_dir = Path(args.out_dir).resolve()
    pages_dir = out_dir / "pages"
    merged_txt = out_dir / "book_cleaned.txt"
    epub = out_dir / "book_cleaned.epub"

    images = render_pages(pdf, pages_dir)
    ocr_chunks(images, out_dir, args.model, args.chunk_size, args.pause_seconds)
    merge_chunks(out_dir, merged_txt)
    build_epub(merged_txt, epub, args.title, args.creator)
    print("TXT", merged_txt)
    print("EPUB", epub)


if __name__ == "__main__":
    main()
