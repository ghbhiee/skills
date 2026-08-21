# pdf-translate

Translate academic / professional PDFs **without destroying the layout**.

Most PDF translators either hand you a wall of plain text, or re-render the page and lose
the colors, the tables and the diagram labels. This one parses the PDF into an intermediate
representation, translates the text blocks, and reflows the translation back into the
original coordinates.

What survives the round trip:

- **Tables** — cell by cell, borders intact.
- **Figures and flowcharts** — the text inside them is translated; the artwork is not touched.
- **Text color and styling** — a green pull-quote stays a green pull-quote.
- **Formulas and images** — passed through as-is, never re-typeset.

And one thing that is easy to get wrong: **acronyms**. Before translating, the engine makes a
whole-document pass to extract a glossary, so an abbreviation is resolved from context and
stays consistent across pages — in a Michigan cohort study, `MI` comes out as 密歇根州 rather
than 心肌梗死. Pass `--context "..."` to make that even more reliable, or `--glossary CSV`
to force specific terms.

## Output

For `paper.pdf` you get three files in `<pdf-dir>/translated/`:

| File | What |
|------|------|
| `paper.no_watermark.zh.mono.pdf` | translation only |
| `paper.no_watermark.zh.dual.pdf` | bilingual — **alternating pages** by default (1 page source, 1 page translation), which prints better than side-by-side; use `--side-by-side` to switch |
| `paper.no_watermark.zh.glossary.csv` | the auto-extracted term list, so you can audit and reuse it |

## Install

Hand this to your coding agent:

> Install the pdf-translate skill from https://github.com/ghbhiee/skills, install BabelDOC, and tell me where to put my API key.

Or do it by hand:

```bash
git clone https://github.com/ghbhiee/skills.git /tmp/skills
mkdir -p ~/.claude/skills
cp -r /tmp/skills/pdf-translate ~/.claude/skills/pdf-translate
chmod +x ~/.claude/skills/pdf-translate/scripts/*.sh
```

Then install the engine and set the key:

```bash
# translation engine (BabelDOC) — lands in ~/.local/bin/babeldoc
uv tool install BabelDOC

# credentials
cp ~/.claude/skills/pdf-translate/scripts/config.example.json \
   ~/.claude/skills/pdf-translate/scripts/config.json
# then edit config.json and paste your api_key
```

`config.json` is gitignored. The key is also read from `$DEEPSEEK_API_KEY`, or from an
interactive zsh that sources `~/.zshrc`, if you would rather keep it in the environment —
but the config file is what makes the skill work in non-interactive shells and other runtimes.

Any OpenAI-compatible endpoint works. The default is DeepSeek (`deepseek-chat` at
`https://api.deepseek.com`), which is cheap enough that a 20-page paper costs pennies;
change `base_url` / `model` in `config.json` (or `--base-url` / `--model`) to point elsewhere.

First run downloads the DocLayout ONNX model and the full Source Han / Noto CJK font set
(~100–200 MB, once).

## Usage

```bash
S=~/.claude/skills/pdf-translate/scripts/pdf-translate.sh

# whole paper, English -> Chinese
bash $S paper.pdf

# try 3 pages first to check quality and cost before spending tokens on 40
bash $S -p 1-3 paper.pdf

# context cuts abbreviation errors more than any other flag — use it
bash $S --context "review on anticoagulation after cardiac surgery" paper.pdf

# other directions, custom output dir
bash $S -li en -lo ja -o ~/out paper.pdf

# force terminology
bash $S --glossary terms.csv paper.pdf        # columns: source,target,tgt_lng
```

`--help` lists everything. Translations are cached, so re-rendering the dual PDF in a
different layout is a cache hit and costs no extra tokens.

## Engines

| Engine | Flag | Notes |
|--------|------|-------|
| **BabelDOC** | default | The one to use. |
| pdf2zh | `--engine pdf2zh` | The original PDFMathTranslate. Kept as a fallback only — on real papers it reset text to black, skipped tables and flowcharts as if they were images, overlapped lines when the Chinese ran longer than the English, and mistranslated abbreviations. Every one of those is why BabelDOC is the default. |

## Limits

- **Scanned / image-only PDFs have no text layer** and this skill is weak on them. Extract
  the text first with [pdf-extract](../pdf-extract/), which OCRs them.
- A Chinese filename does not mean Chinese content — check the actual direction before
  running, or you will translate a document into the language it is already in.
