# skills

Agent skills, one directory per skill at the top level of this repo. Each directory is
complete and self-contained: drop it into your agent's skills folder and it works.

Compatible with Claude Code, Codex, OpenClaw, Hermes, WorkBuddy — anything that reads a
`SKILL.md` from a skills directory.

## Skills

Install only what you want — each one stands alone.

| Skill | What it does |
|-------|--------------|
| [**fileshare**](fileshare/) | Turns a local file, folder, Markdown note, or HTML page into a temporary, login-free public link |
| [**pdf-translate**](pdf-translate/) | Translates academic and professional PDFs without destroying the layout |
| [**pdf-extract**](pdf-extract/) | Converts PDFs to clean Markdown or JSON for LLMs and RAG |
| [**book-tools**](book-tools/) | Searches and downloads books, and OCRs scanned book PDFs |

## Install

Pick a skill below and hand a prompt to your coding agent. It clones the repo, copies that
directory into whichever runtimes it finds on the machine, and installs the tools the skill
needs. You do not have to tell it how.

Each skill that needs credentials offers two prompts. **A** installs first and asks you
afterwards, so no secret ever enters the conversation. **B** carries the values inline —
replace the `<PLACEHOLDERS>` before sending — which is one step instead of two, at the cost
of putting the secret in that session's transcript (and whatever stores it). Convenience or
containment is your call, per skill and per machine.

### fileshare

Temporary, login-free public links for local files. Markdown renders as a styled page, a
self-contained `.html` renders in the browser, and a folder with an `index.html` runs as a
web app. Links expire on their own. You point it at a server **you** control — the
self-hosted backend lives in [`fileshare/server/`](fileshare/server/).

**A — install, fill in the config yourself:**

> Install the fileshare skill from https://github.com/ghbhiee/skills — copy the `fileshare/`
> directory into my agent skills folders, create `scripts/config.json` from the example, and
> tell me where to put my server host and admin token.

**B — values inline:**

> Install the fileshare skill from https://github.com/ghbhiee/skills — copy the `fileshare/`
> directory into my agent skills folders. My server is `<https://files.example.com>` and the
> admin token is `<FILESHARE_ADMIN_TOKEN>`. Write both into `scripts/config.json`, verify the
> skill loads, and don't echo the token back to me.

Needs: `fileshare/scripts/config.json` — `host` (your server's base URL) and `token` (its
admin token). Optional `ttl_days`. The scripts refuse to run while `host` is still the
placeholder, so they can never point at someone else's server by accident.

### pdf-translate

Layout-preserving translation of papers and other professional PDFs. Tables, flowchart
labels, text color and formulas all survive the round trip. It extracts a whole-document
glossary before translating, so an acronym is resolved from context and stays consistent —
in a Michigan cohort study `MI` comes out as 密歇根州, not 心肌梗死. Outputs a
translation-only PDF, a bilingual one, and the glossary as CSV.

**A — install, fill in the config yourself:**

> Install the pdf-translate skill from https://github.com/ghbhiee/skills — copy the
> `pdf-translate/` directory into my agent skills folders, install the BabelDOC engine
> (`uv tool install BabelDOC`), create `scripts/config.json` from the example, and tell me
> where to put my API key.

**B — values inline:**

> Install the pdf-translate skill from https://github.com/ghbhiee/skills — copy the
> `pdf-translate/` directory into my agent skills folders and install the BabelDOC engine
> (`uv tool install BabelDOC`). My API key is `<DEEPSEEK_API_KEY>`. Write it into
> `scripts/config.json`, verify the skill loads, and don't echo the key back to me.

Needs: `pdf-translate/scripts/config.json` — `api_key` for any OpenAI-compatible endpoint.
Optional `base_url` / `model`; the default is DeepSeek, which costs pennies for a 20-page
paper. To use another provider, add `and set base_url to <URL> and model to <NAME>` to
prompt B.

### pdf-extract

PDFs to clean Markdown or JSON for feeding an LLM or building a RAG index — reading order,
heading hierarchy, tables, bounding boxes. It routes each file itself: a fast local engine
for anything with a text layer, OCR for scans, and a fallback chain around two known engine
crashes so you get output instead of a silent 0-byte file.

One prompt only — there is nothing to configure.

> Install the pdf-extract skill from https://github.com/ghbhiee/skills — copy the
> `pdf-extract/` directory into my agent skills folders and run its `scripts/setup.sh`.

Needs: nothing. No credentials, no network — it all runs locally. `setup.sh` installs Java
and the Python deps, and asks before pulling the large OCR extras.

### book-tools

Book search and download across Z-Library and Anna's Archive behind one CLI, plus OCR of
scanned book PDFs into text and EPUB.

**A — install, fill in the config yourself:**

> Install the book-tools skill from https://github.com/ghbhiee/skills — copy the
> `book-tools/` directory into my agent skills folders, then run
> `python3 scripts/book.py preflight` and walk me through whatever it reports.

**B — values inline:**

> Install the book-tools skill from https://github.com/ghbhiee/skills — copy the
> `book-tools/` directory into my agent skills folders. My Z-Library login is
> `<ZLIB_EMAIL>` / `<ZLIB_PASSWORD>`. Write them into `scripts/config.json` as
> `zlib.email` / `zlib.password`, run `python3 scripts/book.py preflight` to confirm it
> works, and don't echo the password back to me.

Needs: `book-tools/scripts/config.json` — `zlib.email` and `zlib.password`;
`annas.secret_key` is optional and needs a donation. `preflight` tells you exactly what is
still missing. The OCR script additionally wants `OPENAI_API_KEY` and calls a paid API.

### Want all four

> Install every skill from https://github.com/ghbhiee/skills into my agent skills folders,
> then tell me which config files I still need to fill in.

Add the credentials inline the same way if you would rather not be asked:

> ...My fileshare server is `<https://files.example.com>` with admin token `<TOKEN>`, and my
> translation API key is `<DEEPSEEK_API_KEY>`. Write them into the right config files and
> don't echo them back to me.

### Where credentials live

Every skill reads its credentials from a file, never a global environment variable, so it
keeps working in non-interactive shells and across runtimes. Each `config.json` / `.env` is
gitignored and the committed `*.example.*` file is its template — your keys never end up in
a commit, whichever prompt you used to write them.

## Conventions

New projects in this repo follow the same shape:

```
<skill-name>/
├── SKILL.md                  # required: YAML front matter (name, description) + instructions
├── README.md                 # human-facing project overview
├── scripts/                  # executables the agent runs
│   ├── config.example.json   # committed template
│   └── config.json           # real credentials — gitignored, never committed
├── references/               # optional: deeper docs the agent loads on demand
├── tests/                    # optional
└── server/                   # optional: self-hosted backend
    ├── src/                  #   service code
    ├── deploy/               #   deploy script + unit files + web server config
    ├── tests/                #   stdlib-only, no test framework to install
    └── docs/                 #   runbook
```

Rules:

- **Credentials live in a file, not in environment variables.** A gitignored `scripts/config.json` (or `.env`), created from a committed `*.example.*` template. This keeps the skill portable across runtimes and non-interactive shells, where user-level env vars are often absent. Where a skill still reads an env var, it is a fallback behind the config file.
- **`SKILL.md` `description` is the trigger surface.** Write it so an agent can tell from the description alone whether the skill applies.
- **Never print secrets.** Scripts read the config themselves; agents report results, not tokens.
- **A skill directory is the unit of install.** Anything the skill needs at runtime lives inside it.
