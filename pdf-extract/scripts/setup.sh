#!/usr/bin/env bash
# Install dependencies for pdf-extract.
#   Required:  Java (opendataloader engine) + opendataloader-pdf + PyMuPDF
#   Optional:  docling[hybrid] (only needed for OCR of scanned / image-only PDFs)
# Re-running is safe; already-installed pieces are skipped by the package managers.
set -u
PY="${PYTHON:-python3}"

echo "== 1/4 Java (opendataloader engine) =="
if command -v java >/dev/null 2>&1; then
  echo "   java present: $(java -version 2>&1 | head -1)"
elif command -v brew >/dev/null 2>&1; then
  brew install openjdk@21
  echo "   NOTE: add to PATH ->  /opt/homebrew/opt/openjdk@21/bin"
  echo "   (pdf_extract.py auto-detects this path, so this is only for manual CLI use.)"
else
  echo "   !! No java and no brew. Install a JDK 17+ manually (https://adoptium.net)."
fi

echo "== 2/4 opendataloader-pdf + PyMuPDF (text-layer probe) =="
$PY -m pip install --user opendataloader-pdf pymupdf

echo "== 3/4 docling (OCR for scanned PDFs) — optional but recommended =="
read -r -p "   Install docling+EasyOCR (~several GB, PyTorch)? [y/N] " ans
case "$ans" in
  [yY]*) $PY -m pip install --user 'opendataloader-pdf[hybrid]' ;;
  *)     echo "   skipped. Scanned/no-text PDFs will not OCR until installed." ;;
esac

echo "== 4/4 verify =="
$PY - <<'PYEOF'
for m in ("fitz", "opendataloader_pdf"):
    try:
        __import__(m); print("   ok:", m)
    except Exception as e:
        print("   MISSING:", m, "->", e)
try:
    import docling; print("   ok: docling (OCR available)")
except Exception:
    print("   docling not installed (OCR unavailable; fine for text-layer PDFs)")
PYEOF
echo "Done."
