# VC Analyst Bot

A Telegram bot that reads a startup's materials, checks public sources, and
fills in the fund's scoring memo template as a Word document.

You send it a pitch deck, a financial model, a website and whatever else you
know. It extracts the deal facts, researches what the founders left out, scores
ten categories out of 30, and returns the completed `.docx`.

## The buttons

| Button | What it takes |
| --- | --- |
| 📊 Add pitch deck | PDF (best), PPTX, or slide screenshots |
| 💰 Add fin model | XLSX (best), CSV/TSV, or a PDF export |
| 🌐 Add website | A URL — the bot fetches and reads the page |
| 📝 Additional info | Free text: call notes, founder bios, round terms, references |
| ✅ Ready — generate memo | Researches, scores, and returns the filled template |
| 📁 Status / ♻️ New deal | Inventory of the current deal, or clear it and start the next |

You can skip the buttons entirely: send a PDF and it becomes the deck, send a
spreadsheet and it becomes the model, send a link and it becomes the website,
send text and it becomes additional info.

Commands: `/start`, `/status`, `/memo`, `/company <name>`, `/reset`, `/help`.

## What comes back

The fund's own template (`vcbot/templates/scoring_template.docx`), filled in:

- **Deal facts header** — round size and terms, closed/soft/open, use of funds,
  cap table, previous funding, URL, industry, stage, TA type, revenue and R&D
  geography, deal breakers, IP, last month's revenue.
- **Scoring table** — ten categories at 0–3 each, totalling out of 30: Market,
  Product, Business Model, Traction, Sales & Marketing, Competition, Team, Tech,
  Deal, Financials.
- **Pros and cons/risks**, each labelled with the category it belongs to.
- **Forwarding summary** — round terms, source, deadline, score.
- **The nine detail sections** — Product, Business model, Traction, Team, Go to
  market, Market, Competitors, Technology, Deal/Ask.
- **An appendix** the template doesn't have: the rationale behind each score,
  what information was missing, the research brief, and the sources consulted.

Fields that are the fund's own workflow data — VP, GP, Contacts, Commitment Date,
Money Transfer Date, the Dropbox and Pipedrive links — are deliberately left
blank. The bot does not invent them.

The total is computed in Python from the ten scores, so the arithmetic is always
right and it agrees in all three places the template prints it.

## How the material is read

- **PDFs go to the model untouched**, as document blocks. Claude sees the
  rendered pages, so charts, diagrams and layout survive — a deck is mostly
  pictures, and text extraction throws that away.
- **Spreadsheets are sent twice**: once with computed values and once with the
  underlying formulas. That is deliberate. A model whose revenue line is a
  typed-in hockey stick reads very differently from one driven by real inputs,
  and you cannot tell the difference from values alone.
- **PPTX and CSV** are flattened to text; **websites** are fetched and stripped
  to readable copy.
- Anything unreadable is reported in the chat rather than silently dropped.

## The research pass

Before scoring, the bot searches public sources for four things specifically:

1. **Market sizing** — real figures with their source and date, and whether a
   claimed TAM survives a bottom-up sanity check.
2. **Product positioning** — what category buyers actually put this in, and
   whether the claimed differentiation is real or table stakes.
3. **Team qualifications** — verifiable history, prior companies and outcomes,
   and where the public record diverges from the deck.
4. **Competitors** — leaders and closest competitors by name, with funding and
   stage where findable, including the incumbent everyone forgets.

It also flags anything that would embarrass the fund: litigation, shutdowns,
regulatory action, an unmentioned pivot, an omitted prior round.

The brief enters the memo as clearly-labelled third-party material: not from the
founders, not verified, and explicitly data rather than instructions. Sources are
listed in the appendix so you can check them.

This is a second API call per memo, so it roughly doubles the cost. Set
`ENABLE_WEB_RESEARCH=false` to score from the supplied materials alone. If the
research pass fails, the memo is still written and the failure is reported.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # then fill it in
python -m vcbot.bot
```

You need two things in `.env`:

- `TELEGRAM_BOT_TOKEN` — talk to [@BotFather](https://t.me/BotFather), `/newbot`.
- `ANTHROPIC_API_KEY` — from the [Anthropic Console](https://console.anthropic.com/settings/keys).

Worth setting `ALLOWED_USER_IDS` to your own Telegram user ID before the bot
meets the internet; every memo spends API credits, and by default anyone who
finds the bot can spend them. Message the bot once without it set and the
rejection notice tells you your ID.

`ANTHROPIC_EFFORT` (`low`/`medium`/`high`/`xhigh`/`max`, default `high`) trades
cost against depth.

## Changing the template or the rubric

The Word template and the schema have to agree. If the fund changes the template:

- **New or reordered scoring categories** → edit `CATEGORIES` in
  `vcbot/scoring.py`. It drives the column order of the scoring table, the
  prompt, and the chat summary.
- **New header fields** → edit `FACT_LABELS_LEFT` / `FACT_LABELS_RIGHT` in
  `vcbot/scoring.py` and the row mapping in `vcbot/docx_memo.py`.
- **New detail sections** → edit `SECTIONS` in `vcbot/scoring.py` and
  `SECTION_TABLES` in `vcbot/docx_memo.py`, which maps template table indices to
  section keys.
- **A new template file** → drop it in `vcbot/templates/scoring_template.docx`.
  The renderer addresses tables by index, so re-check those indices; the tests in
  `tests/test_docx_memo.py` will tell you if they moved.

### A constraint worth knowing about

Structured outputs compile to a grammar, and the grammar has a size limit. An
earlier version of the schema modelled the deal facts and each detail section as
their own nested objects; the API rejected it with *"the compiled grammar is too
large"*. Measured against the live API: 60 flat string fields pass, as do 40
fields carrying 14KB of descriptions — **descriptions are free, structure is
not**. The schema is therefore deliberately shallow (36 properties, 4 nested
models), and the widest blocks — deal facts and score rationales — are returned
as `Label: value` lines that the renderer parses back. If you add fields and
start seeing that error, flatten something rather than splitting the call.

## Tests

```bash
python -m pytest tests -q
```

82 tests covering the rubric arithmetic, the filled Word document (right values
in the right cells, and no example data from the template surviving into a real
memo), file and website ingestion, state persistence, the research pass
including `pause_turn` resumption and the server-tool error shape, and the full
conversation flow with faked Telegram objects. Nothing in the suite calls the
API or the network.

## Limitations worth knowing

- Telegram's Bot API will not hand a bot any file larger than **20 MB**.
- Research is a web search, not diligence. It surfaces what public sources say;
  it does not confirm that claimed revenue exists. Founder claims reach the memo
  labelled as claims, and so does anything found on the web.
- JavaScript-only sites often render no readable text. Paste the key copy under
  Additional info instead.
- State is JSON files under `DATA_DIR`, one per chat, alongside the uploads.
  `/reset` deletes that chat's uploads from disk.

## Layout

```
vcbot/
  bot.py        Telegram handlers, buttons, upload routing
  analyst.py    Prompt assembly, the research pass, and the memo call
  scoring.py    The rubric, the template's field names, and the memo schema
  docx_memo.py  Filling the Word template
  memo.py       The chat summary
  ingest.py     PDF/PPTX/XLSX/CSV/HTML reading
  state.py      Per-chat deal state
  config.py     Environment configuration
  templates/    The fund's scoring memo template
```
