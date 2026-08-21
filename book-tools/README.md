# book-tools

Search and download books through one CLI.

Two backends behind a single interface:

| Backend | Source | Auth | Best for |
|---------|--------|------|----------|
| **zlib** | Z-Library (EAPI) | email + password | Largest catalog, direct download |
| **annas** | Anna's Archive | API key (donation) | Aggregated sources, multiple mirrors |

`book.py` auto-detects which backend to use — it tries Z-Library first and falls back to
Anna's Archive — so most of the time you just search and download without naming one.

## Install

Hand one of these to your coding agent — **A** keeps the secret out of the conversation,
**B** trades that for one less round trip:

**A — install, fill in the config yourself:**

> Install the book-tools skill from https://github.com/ghbhiee/skills — copy the
> `book-tools/` directory into my agent skills folders, then run
> `python3 scripts/book.py preflight` and walk me through whatever it reports.

**B — values inline** (replace the placeholders; this puts the password in your transcript):

> Install the book-tools skill from https://github.com/ghbhiee/skills — copy the
> `book-tools/` directory into my agent skills folders. My Z-Library login is
> `<ZLIB_EMAIL>` / `<ZLIB_PASSWORD>`. Write them into `scripts/config.json` as
> `zlib.email` / `zlib.password`, run `python3 scripts/book.py preflight` to confirm it
> works, and don't echo the password back to me.

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

Credentials go in `scripts/config.json`, right next to the scripts:

```bash
cp ~/.claude/skills/book-tools/scripts/config.example.json \
   ~/.claude/skills/book-tools/scripts/config.json
```

```json
{
  "zlib": { "email": "you@example.com", "password": "your-z-library-password" },
  "annas": { "secret_key": "" }
}
```

`zlib.email` / `zlib.password` are what Z-Library needs; `annas.secret_key` is optional and
requires a donation to Anna's Archive. Add `zlib.domain` to pin a working EAPI domain instead
of letting the script probe for one. The file is gitignored, so your credentials never reach
a commit. Point `$BOOK_TOOLS_CONFIG` elsewhere if you would rather keep it outside the skill.

Re-run `preflight` to confirm. On first login the session tokens are cached back into the
same file (`zlib.remix_userid` / `zlib.remix_userkey`) — leave those alone; they are refreshed
from the email/password pair, so keep those rather than only pasting a token.

Installs that predate this layout kept credentials in `~/.codex/skills-data/book-tools/`.
Those are still read when `scripts/config.json` is absent, and the first write migrates them
into it.

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

## Not this skill

This skill finds and downloads books; it does not convert them. For a scanned PDF, or any
PDF you want as Markdown/JSON rather than as a file on disk, use
[pdf-extract](../pdf-extract/) — fully local, no API key.
