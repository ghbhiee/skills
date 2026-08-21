# book-tools

Search and download books through one CLI, and OCR scanned book PDFs into text and EPUB.

Two backends behind a single interface:

| Backend | Source | Auth | Best for |
|---------|--------|------|----------|
| **zlib** | Z-Library (EAPI) | email + password | Largest catalog, direct download |
| **annas** | Anna's Archive | API key (donation) | Aggregated sources, multiple mirrors |

`book.py` auto-detects which backend to use — it tries Z-Library first and falls back to
Anna's Archive — so most of the time you just search and download without naming one.

## Install

Hand this to your coding agent:

> Install the book-tools skill from https://github.com/ghbhiee/skills — copy the
> `book-tools/` directory into my agent skills folders, then run
> `python3 scripts/book.py preflight` and walk me through whatever it reports.

Or do it by hand:

```bash
git clone https://github.com/ghbhiee/skills.git /tmp/skills
mkdir -p ~/.claude/skills
cp -r /tmp/skills/book-tools ~/.claude/skills/book-tools
chmod +x ~/.claude/skills/book-tools/scripts/*.sh
```

Then let the skill tell you what is missing:

```bash
python3 ~/.claude/skills/book-tools/scripts/book.py preflight
```

It returns JSON covering dependencies, credentials and the optional `annas-mcp` binary. If
`ready` is `false`, follow what it reports:

```bash
bash ~/.claude/skills/book-tools/scripts/setup.sh install-deps    # python deps
bash ~/.claude/skills/book-tools/scripts/setup.sh install-annas   # annas-mcp binary
```

Credentials go in a `.env` outside the skill directory, so a reinstall never wipes them:

```bash
mkdir -p ~/.codex/skills-data/book-tools
cp ~/.claude/skills/book-tools/scripts/.env.example \
   ~/.codex/skills-data/book-tools/.env
# ZLIB_EMAIL / ZLIB_PASSWORD   — required for Z-Library
# ANNAS_SECRET_KEY             — optional, needs a donation to Anna's Archive
# ZLIBRARY_EAPI_DOMAIN         — optional, pins a working EAPI domain instead of probing
```

That path is shared by every runtime the skill is installed into. Re-run `preflight` to confirm. Z-Library session tokens are cached and refreshed from the
email/password pair, so keep those in `.env` rather than only pasting a token.

## Usage

```bash
S=~/.claude/skills/book-tools/scripts/book.py

python3 $S search "sapiens"        # auto backend: zlib first, annas as fallback
python3 $S info <id>               # book details
python3 $S download <id>
python3 $S config show             # non-sensitive settings
```

See [`SKILL.md`](SKILL.md) for the full command surface (filters, formats, the download
workflow) and [`references/api_reference.md`](references/api_reference.md) for the backend
APIs.

## OCR

`scripts/ocr_book_openai.py` turns a scanned book PDF into text and EPUB. It is separate
from search/download and needs `pdftoppm`, the Python `openai` package, and `OPENAI_API_KEY`.
It calls a **paid** API, so run it only on an explicit request:

```bash
python3 ~/.claude/skills/book-tools/scripts/ocr_book_openai.py book.pdf \
  --out-dir ./tmp/book-ocr --title "..." --creator "..."
```

For general-purpose PDF → Markdown/JSON extraction that runs entirely locally and needs no
API key, use [pdf-extract](../pdf-extract/) instead.
