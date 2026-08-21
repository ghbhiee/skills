---
name: book-tools
description: Search and download books from Z-Library and Anna's Archive, or OCR scanned book PDFs into text and EPUB. Use when the user wants to find, search, download, look up, or OCR books, papers, or ebooks.
---

# Book Tools

Search and download books from multiple sources through a unified CLI.

## Language
**Match user's language**: Respond in the same language the user uses.

## Backends

| Backend | Source | Auth Required | Best For |
|---------|--------|---------------|----------|
| **zlib** | Z-Library (EAPI) | Email + Password | Largest catalog, direct download |
| **annas** | Anna's Archive | API Key (donation) | Aggregated sources, multiple mirrors |

## Preflight

Before any workflow, run preflight to check environment readiness:

```bash
python3 ${SKILL_PATH}/scripts/book.py preflight
```

Returns standardized JSON:
```json
{
  "ready": true,
  "dependencies": { "python3": {"status": "ok"}, "requests": {"status": "ok"} },
  "credentials": { "zlib": {"status": "configured"}, "annas_api_key": {"status": "not_configured"} },
  "services": { "annas_binary": {"status": "ok"} }
}
```

- If `ready: true` — proceed directly to the Workflow section.
- If `ready: false` — follow the Check/Fix table below, then run the Setup flow.

| Check | Fix |
|-------|-----|
| `requests` missing | `bash ${SKILL_PATH}/scripts/setup.sh install-deps` (or manually: `pip3 install requests` / `uv pip install requests`) |
| `zlib` not configured | Guide user to edit `${SKILL_PATH}/scripts/config.json` — set `zlib.email` and `zlib.password` |
| `zlib` expired | Cached tokens expired and no email/password stored. Guide user to re-add `zlib.email` / `zlib.password` in `${SKILL_PATH}/scripts/config.json` |
| `annas_api_key` not configured | Guide user to donate at Anna's Archive for an API key, then set `annas.secret_key` in `${SKILL_PATH}/scripts/config.json` |
| `annas_binary` missing | `bash ${SKILL_PATH}/scripts/setup.sh install-annas` (or manually: download from [annas-mcp releases](https://github.com/iosifache/annas-mcp/releases), extract to `~/.local/bin/annas-mcp`) |

## Setup (First-Time Only)

Only run setup when preflight reports `ready: false`. Guide the user through configuration interactively.

### Step 1: Install Dependencies

```bash
bash ${SKILL_PATH}/scripts/setup.sh install-deps
```

### Step 2: Configure Credentials

Credentials live in `${SKILL_PATH}/scripts/config.json`, next to the scripts. Create it from
the bundled template:

```bash
# Only copy if config.json does not already exist — never overwrite existing credentials
if [ ! -f ${SKILL_PATH}/scripts/config.json ]; then
  cp ${SKILL_PATH}/scripts/config.example.json ${SKILL_PATH}/scripts/config.json
else
  echo "Existing config.json found — skipping copy to preserve credentials."
fi
```

The file looks like this:

```json
{
  "zlib": {
    "email": "you@example.com",
    "password": "your-z-library-password"
  },
  "annas": {
    "secret_key": ""
  }
}
```

**IMPORTANT**: Do NOT ask the user for credentials directly in chat unless they offered them
first. Instead:
1. Create `scripts/config.json` from the template
2. Tell the user to edit `${SKILL_PATH}/scripts/config.json`
3. Wait for the user to confirm they've filled it in
4. Then proceed with search

### Step 3: Verify

```bash
python3 ${SKILL_PATH}/scripts/book.py preflight
```

Confirm `ready: true` before proceeding.

### Credential Storage

**Canonical path**: `${SKILL_PATH}/scripts/config.json` — one file, inside the skill, holding
both credentials and settings. It is gitignored, so it survives in place and never reaches a
commit. Override the location with `$BOOK_TOOLS_CONFIG` if you need to.

| Key | Purpose | Required |
|-----|---------|----------|
| `zlib.email` | Z-Library email | For Z-Library backend |
| `zlib.password` | Z-Library password | For Z-Library backend |
| `zlib.domain` | Pin a working EAPI domain instead of probing | No |
| `annas.secret_key` | Anna's Archive API key | For Anna's Archive backend |

On first successful Z-Library login, session tokens (`zlib.remix_userid` / `zlib.remix_userkey`)
are cached back into the same file automatically. Leave those alone; if login misbehaves,
delete just those two keys and the script re-logs in with the email and password.

Older installs kept credentials in `~/.codex/skills-data/book-tools/.env` or a `config.json`
under that directory. Those are still read if `scripts/config.json` is absent, and the first
write migrates everything into `scripts/config.json`.

## Workflow

The typical flow is: **search → pick → download**.

### Default Format Preference

When the user does not specify a format and the same title and edition are available in multiple formats, prefer **EPUB**, then **PDF**, then other formats. A user-requested format always takes precedence. If EPUB is unavailable, fall back to PDF without asking unless the format materially affects the request.

### 1. Search

```bash
# Auto-detect backend (tries zlib first, then annas)
python3 ${SKILL_PATH}/scripts/book.py search "machine learning" --limit 10

# Z-Library with filters
python3 ${SKILL_PATH}/scripts/book.py search "deep learning" --source zlib --lang english --ext pdf --limit 5

# Anna's Archive
python3 ${SKILL_PATH}/scripts/book.py search "reinforcement learning" --source annas

# Chinese books
python3 ${SKILL_PATH}/scripts/book.py search "莱姆 索拉里斯" --source zlib --lang chinese --limit 5
```

**Output** (JSON to stdout):
```json
{
  "source": "zlib",
  "count": 5,
  "books": [
    {
      "source": "zlib",
      "id": "12345",
      "hash": "abc123def",
      "title": "Deep Learning",
      "author": "Ian Goodfellow",
      "year": "2016",
      "language": "english",
      "extension": "pdf",
      "filesize": "22.5 MB"
    }
  ]
}
```

### 2. Present Results to User

After searching, present results as a **numbered table** so the user can pick:

```
| # | Title | Author | Year | Format | Size |
|---|-------|--------|------|--------|------|
| 1 | Deep Learning | Ian Goodfellow | 2016 | pdf | 22.5 MB |
| 2 | ... | ... | ... | ... | ... |
```

If results span multiple languages or editions, **group them by language or category** with sub-headings for clarity.

Ask: "Which book would you like to download? (number)"

### 3. Download

```bash
# Z-Library download (needs id + hash from search results)
python3 ${SKILL_PATH}/scripts/book.py download --source zlib --id 12345 --hash abc123def -o ~/Downloads/

# Anna's Archive download (needs MD5 hash from search results)
python3 ${SKILL_PATH}/scripts/book.py download --source annas --hash a1b2c3d4e5 --filename "deep_learning.pdf" -o ~/Downloads/
```

**Output**:
```json
{
  "source": "zlib",
  "status": "ok",
  "path": "~/Downloads/Deep Learning (Ian Goodfellow).pdf",
  "size": 23592960
}
```

### 4. Report to User

After download, present a structured completion report:

```
[Book Download] Complete!
Book: [title] by [author]
Source: [zlib/annas]
Path: [file path]
Size: [file size]
```

If using Z-Library, also mention any remaining daily download quota.

## Scanned PDF OCR

Use `scripts/ocr_book_openai.py` only when the user asks to OCR a scanned PDF or convert one into text/EPUB. It requires `pdftoppm`, the Python `openai` package, and `OPENAI_API_KEY`; because it invokes a paid API, do not run it without an explicit OCR/conversion request.

```bash
python3 ${SKILL_PATH}/scripts/ocr_book_openai.py /path/to/book.pdf \
  --out-dir ./tmp/book-ocr \
  --model gpt-4.1-mini \
  --chunk-size 15 \
  --pause-seconds 0.75 \
  --title "Book title" \
  --creator "Author"
```

The helper renders pages to JPEG, resumes completed chunks, writes `book_cleaned.txt`, and packages `book_cleaned.epub`.

## Other Commands

### Book Info (Z-Library only)

```bash
python3 ${SKILL_PATH}/scripts/book.py info --source zlib --id 12345 --hash abc123def
```

Returns full metadata: description, ISBN, pages, table of contents, etc.

### Check Config

```bash
python3 ${SKILL_PATH}/scripts/book.py config show
```

### Check Backend Status

```bash
python3 ${SKILL_PATH}/scripts/book.py setup
```

## Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| "Z-Library not configured" | No credentials | Guide user to edit `${SKILL_PATH}/scripts/config.json` |
| "Z-Library login failed" | Bad credentials or service down | Ask user to verify credentials. Z-Library domains change — if persistent, the vendored `Zlibrary.py` domain may need updating. |
| "No working Z-Library EAPI domain" or "non-JSON content" | Domains are blocked, moved, or returning an HTML anti-bot/error page | Retry once. If needed, set `ZLIBRARY_EAPI_DOMAIN=https://z-library.ec` in the canonical `.env`; the CLI must report JSON errors without a traceback. |
| "annas-mcp binary not found" | Binary not installed | Run `setup.sh install-annas` |
| "Anna's Archive API key not configured" | No API key | Guide user to donate at Anna's Archive for API access, then add key to `.env` |
| Search timeout | Network issue | Retry once. If persistent, try the other backend. |
| "No backend available" | Neither backend configured | Walk through full setup flow from Step 1 |

## Degradation

| Scenario | Behavior |
|----------|----------|
| Z-Library down | Auto-fallback to Anna's Archive (`--source auto` handles this) |
| Anna's Archive unavailable | Use Z-Library only |
| Neither configured | Halt and guide user through Setup flow |

## Tips

- Z-Library has a daily download limit (usually 10/day for free accounts). Use `info` to check a book before downloading to avoid wasting quota.
- Anna's Archive requires an API key for both search and download (obtained via donation).
- For Chinese books, use `--lang chinese` with Z-Library for best results.
- If Z-Library is unreachable, automatically fall back to Anna's Archive with `--source auto`.
- When searching for a specific author in multiple languages, run parallel searches (e.g. English name + Chinese name) and merge results into one table.
