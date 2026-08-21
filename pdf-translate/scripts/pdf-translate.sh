#!/usr/bin/env bash
# pdf-translate — layout-preserving PDF translation that keeps colors/styles, translates
# tables AND figure/flowchart text, and uses a context-aware glossary so abbreviations are
# not mistranslated. Default engine: BabelDOC (intermediate-representation reflow) driven by
# DeepSeek (OpenAI-compatible). Falls back to the original pdf2zh engine with --engine pdf2zh.
#
# Outputs per file (BabelDOC): <name>.no_watermark.zh.mono.pdf (translation only),
# <name>.no_watermark.zh.dual.pdf (bilingual), <name>.no_watermark.zh.glossary.csv (terms).
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: pdf-translate.sh [options] FILE.pdf [FILE2.pdf ...]

Options:
  -li, --lang-in   CODE   source language               (default: en)
  -lo, --lang-out  CODE   target language               (default: zh)
  -p,  --pages     RANGE  pages, e.g. 1-3 or 1,3,5       (default: all)
  -o,  --output    DIR    output directory              (default: <pdf-dir>/translated)
      --engine     NAME   babeldoc | pdf2zh             (default: babeldoc)
      --context    TEXT   document context appended to the system prompt
                          (e.g. "review on anticoagulation after cardiac surgery")
      --glossary   CSV    custom glossary file (source,target,tgt_lng) to force terms
      --model      NAME   DeepSeek model                (default: deepseek-chat)
      --base-url   URL    OpenAI-compatible base URL     (default: https://api.deepseek.com)
      --qps        N      requests/sec limit            (default: 4)
      --no-table              do NOT translate table text
      --side-by-side          dual PDF = original/translation side-by-side on one page
                              (default: alternating pages — 1 page original, 1 page translation,
                               better for printing)
      --keep-watermark        keep BabelDOC watermark (default: removed)
  -h, --help              show this help

Notes:
  * BabelDOC translates tables and figure/flowchart text, preserves text color & styles,
    and auto-extracts a glossary first (kept abbreviations like MI=Michigan vs myocardial).
  * Scanned/image PDFs (no text layer) need OCR; this is weak there — use RetainPDF instead.
EOF
}

ENGINE="babeldoc"
LANG_IN="en"; LANG_OUT="zh"; PAGES=""; OUTPUT=""; QPS="4"
MODEL="deepseek-chat"; BASE_URL="https://api.deepseek.com"
CONTEXT=""; GLOSSARY=""; NO_TABLE=0; KEEP_WM=0; ALT_DUAL=1
MODEL_SET=0; BASE_SET=0
FILES=()

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${PDF_TRANSLATE_CONFIG:-$SCRIPT_DIR/config.json}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -li|--lang-in)   LANG_IN="$2";  shift 2;;
    -lo|--lang-out)  LANG_OUT="$2"; shift 2;;
    -p|--pages)      PAGES="$2";    shift 2;;
    -o|--output)     OUTPUT="$2";   shift 2;;
    --engine)        ENGINE="$2";   shift 2;;
    --context)       CONTEXT="$2";  shift 2;;
    --glossary)      GLOSSARY="$2"; shift 2;;
    --model)         MODEL="$2"; MODEL_SET=1;   shift 2;;
    --base-url)      BASE_URL="$2"; BASE_SET=1;  shift 2;;
    --qps)           QPS="$2";      shift 2;;
    --no-table)      NO_TABLE=1;    shift;;
    --side-by-side)  ALT_DUAL=0;    shift;;
    --keep-watermark) KEEP_WM=1;    shift;;
    -h|--help)       usage; exit 0;;
    -*)              echo "unknown option: $1" >&2; usage; exit 1;;
    *)               FILES+=("$1"); shift;;
  esac
done

[[ ${#FILES[@]} -eq 0 ]] && { echo "error: no input PDF given" >&2; usage; exit 1; }

# Credentials: scripts/config.json (preferred, portable across runtimes and
# non-interactive shells) -> $DEEPSEEK_API_KEY -> an interactive zsh that sources ~/.zshrc.
cfg_get() {
  [[ -f "$CONFIG" ]] || return 0
  python3 -c 'import json,sys
try: d = json.load(open(sys.argv[1]))
except Exception: sys.exit(0)
v = d.get(sys.argv[2])
print(v if isinstance(v, str) else "")' "$CONFIG" "$1" 2>/dev/null
}

if [[ $MODEL_SET -eq 0 ]]; then v="$(cfg_get model)";    [[ -n "$v" ]] && MODEL="$v";    fi
if [[ $BASE_SET  -eq 0 ]]; then v="$(cfg_get base_url)"; [[ -n "$v" ]] && BASE_URL="$v"; fi

API_KEY="$(cfg_get api_key)"
[[ -z "$API_KEY" ]] && API_KEY="${DEEPSEEK_API_KEY:-}"
if [[ -z "$API_KEY" ]] && command -v zsh >/dev/null 2>&1; then
  API_KEY="$(zsh -ic 'print -r -- ${DEEPSEEK_API_KEY}' 2>/dev/null | tail -1)"
fi
if [[ -z "$API_KEY" ]]; then
  cat >&2 <<EOF
error: no API key for the translation backend.
  Either copy scripts/config.example.json to scripts/config.json and fill in "api_key",
  or export DEEPSEEK_API_KEY in your shell.
EOF
  exit 1
fi
export DEEPSEEK_API_KEY="$API_KEY"

# Context-aware system prompt: faithful terminology, keep abbreviations/proper nouns,
# keep source text when unsure instead of guessing.
build_prompt() {
  printf '%s' "You are a professional translator rendering an academic / medical / scientific paper from ${LANG_IN} into ${LANG_OUT}. Use precise professional terminology and stay faithful to the meaning. Keep standard abbreviations, drug names, scale/score names, clinical trial names, gene/protein symbols, journal and institution names, and other proper nouns accurate; when a term has no well-established ${LANG_OUT} equivalent or you are not sure, keep the original ${LANG_IN} text rather than guessing, and never invent an expansion for an acronym."
  [[ -n "$CONTEXT" ]] && printf ' Document context: %s' "$CONTEXT"
}

run_babeldoc() {
  local f="$1" outdir="$2"
  local args=(--openai --openai-model "$MODEL" --openai-base-url "$BASE_URL"
              --openai-api-key "$API_KEY"
              --lang-in "$LANG_IN" --lang-out "$LANG_OUT" --qps "$QPS"
              --save-auto-extracted-glossary
              --custom-system-prompt "$(build_prompt)"
              --output "$outdir")
  [[ $KEEP_WM -eq 0 ]] && args+=(--watermark-output-mode no_watermark)
  [[ $NO_TABLE -eq 0 ]] && args+=(--translate-table-text)
  [[ $ALT_DUAL -eq 1 ]] && args+=(--use-alternating-pages-dual)
  [[ -n "$PAGES" ]] && args+=(--pages "$PAGES")
  [[ -n "$GLOSSARY" ]] && args+=(--glossary-files "$GLOSSARY")
  babeldoc "${args[@]}" --files "$f"
}

run_pdf2zh() {
  local f="$1" outdir="$2"
  local args=(--service deepseek --lang-in "$LANG_IN" --lang-out "$LANG_OUT" --thread 4 --output "$outdir")
  [[ -n "$PAGES" ]] && args+=(--pages "$PAGES")
  pdf2zh "$f" "${args[@]}"
}

rc=0
for f in "${FILES[@]}"; do
  if [[ ! -f "$f" ]]; then echo "skip (not found): $f" >&2; rc=1; continue; fi
  outdir="${OUTPUT:-$(dirname "$f")/translated}"
  mkdir -p "$outdir"
  echo ">> [$ENGINE] translating: $f  ($LANG_IN -> $LANG_OUT${PAGES:+, pages $PAGES})"
  if [[ "$ENGINE" == "pdf2zh" ]]; then
    run_pdf2zh "$f" "$outdir" && echo ">> done -> $outdir/" || { echo ">> FAILED: $f" >&2; rc=1; }
  else
    run_babeldoc "$f" "$outdir" && echo ">> done -> $outdir/ (*.mono.pdf / *.dual.pdf / *.glossary.csv)" \
      || { echo ">> FAILED: $f" >&2; rc=1; }
  fi
done
exit $rc
