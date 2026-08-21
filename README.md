# skills

Agent skills, one directory per skill at the top level of this repo. Each directory is
complete and self-contained: drop it into your agent's skills folder and it works.

Compatible with Claude Code, Codex, OpenClaw, Hermes, WorkBuddy — anything that reads a
`SKILL.md` from a skills directory.

## Skills

| Skill | What it does | Setup |
|-------|--------------|-------|
| [**fileshare**](fileshare/) | Turns a local file, folder, Markdown note, or HTML page into a temporary, login-free public link. Markdown renders as a page; folders with `index.html` run as web apps. Includes the self-hosted [server](fileshare/server/). | `scripts/config.json` — server host + admin token |
| [**pdf-translate**](pdf-translate/) | Translates academic and professional PDFs while preserving the layout — tables, flowchart labels, text color and formulas all survive. Auto-extracts a document glossary first so acronyms stay consistent. Outputs mono + bilingual PDFs and the glossary. | `scripts/config.json` — OpenAI-compatible API key; plus `uv tool install BabelDOC` |
| [**pdf-extract**](pdf-extract/) | Converts PDFs to clean Markdown or JSON for LLMs and RAG — reading order, headings, tables, bounding boxes. Auto-routes between a fast local engine and OCR for scans, with a fallback chain around two known engine crashes. | `scripts/setup.sh` — Java + Python deps. No credentials, fully local |
| [**book-tools**](book-tools/) | Searches and downloads books from Z-Library and Anna's Archive, and OCRs scanned book PDFs into text and EPUB. | `~/.codex/skills-data/book-tools/.env` — Z-Library login, optional Anna's Archive key |

The two PDF skills are complements, not alternatives: `pdf-translate` keeps the page and
swaps the language, `pdf-extract` throws the page away and keeps the structure. A scanned PDF
has no text layer, so it goes through `pdf-extract` first.

## Install

Give your coding agent the link and one line:

> Install the skills from https://github.com/ghbhiee/skills, then tell me which config files I need to fill in.

That is the whole thing. The agent clones the repo, copies each skill directory
into whatever runtimes it finds on the machine, installs the tools each skill needs, and
reports back what still needs a credential.

To skip the round trip, hand it the values up front:

> Install the skills from https://github.com/ghbhiee/skills. My DeepSeek API key is `sk-...`,
> my fileshare server is `https://files.example.com` with admin token `...`. Write them into
> the right config files, and don't echo them back to me.

(Anything you paste into a prompt lands in that session's transcript — if you would rather it
did not, use the first form and fill in the files yourself.)

## Configuration

After install, each skill needs its own file filled in. Nothing reads a global env var.

| Skill | File | Fill in |
|-------|------|---------|
| **fileshare** | `<skill>/scripts/config.json` (from `config.example.json`) | `host` — your server's base URL; `token` — its admin token. Optional `ttl_days`. |
| **pdf-translate** | `<skill>/scripts/config.json` (from `config.example.json`) | `api_key` for any OpenAI-compatible endpoint. Optional `base_url` / `model` (defaults to DeepSeek). Also needs `uv tool install BabelDOC`. |
| **pdf-extract** | — | Nothing. Fully local. Run `scripts/setup.sh` once for Java + Python deps. |
| **book-tools** | `~/.codex/skills-data/book-tools/.env` (from `scripts/.env.example`) | `ZLIB_EMAIL` / `ZLIB_PASSWORD`; optional `ANNAS_SECRET_KEY`. Run `scripts/book.py preflight` to check. |

`config.json` and `.env` are gitignored — the committed `*.example.*` files are templates, so
your credentials never end up in a commit. `fileshare` also needs a server you control; see
[`fileshare/server/`](fileshare/server/).

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
