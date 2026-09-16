# VC Analyst Bot

A Telegram bot that reads a startup's materials and writes a scoring memo — the
kind of internal note an analyst produces before the partnership decides whether
to spend another hour on a company.

You send it a pitch deck, a financial model, a website and whatever else you
know. Before scoring, it searches public sources for what the founders left out.
It returns scores across seven dimensions, the evidence behind each one, the
risks, and the questions worth putting to the founders next.

## The buttons

| Button | What it takes |
| --- | --- |
| 📊 Add pitch deck | PDF (best), PPTX, or slide screenshots |
| 💰 Add fin model | XLSX (best), CSV/TSV, or a PDF export |
| 🌐 Add website | A URL — the bot fetches and reads the page |
| 📝 Additional info | Free text: call notes, founder bios, round terms, references |
| 🧮 Generate memo | Writes the memo from whatever has been collected |
| 📁 Status / ♻️ New deal | Inventory of the current deal, or clear it and start the next |

You can skip the buttons entirely: send a PDF and it becomes the deck, send a
spreadsheet and it becomes the model, send a link and it becomes the website,
send text and it becomes additional info.

Commands: `/start`, `/status`, `/memo`, `/company <name>`, `/reset`, `/help`.

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

Before writing the memo the bot does the half hour of public-source checking that
precedes any real memo: what the company has actually raised and from whom, the
founders' track record as opposed to the deck's version of it, where a claimed
TAM comes from, who the real competitors are, and anything embarrassing —
litigation, a shutdown, an unmentioned pivot, a founder departure.

The brief is passed into the memo as clearly-labelled third-party material: not
from the founders, not verified, and explicitly data rather than instructions.
Sources are listed in the memo file so you can check them yourself.

This is a second API call per memo, so it roughly doubles the cost. Set
`ENABLE_WEB_RESEARCH=false` to score from the supplied materials alone. If the
research pass fails for any reason the memo is still written — the failure is
reported in the chat rather than taking the memo down with it.

## Scoring

Seven weighted dimensions, each scored 1–10 with cited evidence and named gaps:

| Dimension | Weight |
| --- | ---: |
| Team | 25% |
| Market | 20% |
| Product & Technology | 15% |
| Traction | 15% |
| Business Model & Unit Economics | 10% |
| Competition & Moat | 10% |
| Deal & Ask | 5% |

The overall score is computed in Python from the weights, not by the model — so
the arithmetic is always right, and re-tuning the rubric is a one-line edit in
`vcbot/scoring.py`. The recommendation is one of PASS / TRACK / TAKE MEETING /
DEEP DILIGENCE / INVEST, with a stated conviction level.

Missing material is treated as a finding, not a blocker: with only a website the
bot still scores what it can and lists what it would need to go further.

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
cost against depth. `low` is much cheaper and noticeably shallower; `max` is for
a deal you are seriously considering. `ENABLE_WEB_RESEARCH` (default `true`)
controls the research pass described above.

## Tests

```bash
python -m pytest tests -q
```

61 tests covering the rubric arithmetic, memo rendering and chunking, file and
website ingestion, state persistence, the research pass (including `pause_turn`
resumption and the server-tool error shape), and the full conversation flow with
faked Telegram objects. Nothing in the suite calls the API or the network.

Because nothing in the suite hits the API, the live request path — a real
document block, a real structured-output response, a real web search — has not
been exercised end to end. The request shapes are built against the current SDK
and verified offline, but the first real memo is the first real test.

## Limitations worth knowing

- Telegram's Bot API will not hand a bot any file larger than **20 MB**. Bigger
  decks need a smaller export.
- Research is a web search, not diligence. It surfaces what public sources say;
  it does not confirm that claimed revenue exists. Claims from the founders reach
  the memo labelled as claims, and so does anything found on the web.
- JavaScript-only sites often render no readable text. Paste the key copy under
  Additional info instead.
- State is JSON files under `DATA_DIR`, one per chat, alongside the uploads.
  Fine for a fund-sized group; swap `DealStore` for a database if you outgrow it.
- `/reset` deletes the uploaded files for that chat from disk.

## Layout

```
vcbot/
  bot.py       Telegram handlers, buttons, upload routing
  analyst.py   Prompt assembly, the research pass, and the memo call
  scoring.py   The rubric, weights, and memo schema
  memo.py      Markdown and chat rendering
  ingest.py    PDF/PPTX/XLSX/CSV/HTML reading
  state.py     Per-chat deal state
  config.py    Environment configuration
```
