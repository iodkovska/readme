"""Telegram wiring: the button menu, the upload flow, and the memo handoff."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import ingest
from .analyst import Analyst
from .config import Config, load_config
from .docx_memo import build_docx, filename_for
from .memo import chunk, render_chat
from .state import (
    AWAIT_FIN_MODEL,
    AWAIT_NOTES,
    AWAIT_PITCH_DECK,
    AWAIT_WEBSITE,
    Attachment,
    Deal,
    DealStore,
)

log = logging.getLogger(__name__)

BTN_DECK = "📊 Add pitch deck"
BTN_MODEL = "💰 Add fin model"
BTN_WEBSITE = "🌐 Add website"
BTN_INFO = "📝 Additional info"
BTN_MEMO = "✅ Ready — generate memo"
BTN_STATUS = "📁 Status"
BTN_RESET = "♻️ New deal"

KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_DECK), KeyboardButton(BTN_MODEL)],
        [KeyboardButton(BTN_WEBSITE), KeyboardButton(BTN_INFO)],
        [KeyboardButton(BTN_MEMO)],
        [KeyboardButton(BTN_STATUS), KeyboardButton(BTN_RESET)],
    ],
    resize_keyboard=True,
    input_field_placeholder="Send a file, a link, or notes…",
)

PROMPTS = {
    AWAIT_PITCH_DECK: (
        "Send the pitch deck as a file — PDF works best (I read the slides as they "
        "look, charts included). PPTX and slide screenshots also work."
    ),
    AWAIT_FIN_MODEL: (
        "Send the financial model as a file. XLSX is best — I read both the numbers "
        "and the formulas behind them. CSV and PDF exports also work."
    ),
    AWAIT_WEBSITE: "Send the company's website URL.",
    AWAIT_NOTES: (
        "Send anything else worth knowing: call notes, founder bios, references, "
        "the round terms, why this came to you. Several messages are fine."
    ),
}


def _analysis_lock(context: ContextTypes.DEFAULT_TYPE) -> set[int]:
    return context.application.bot_data.setdefault("in_flight", set())


async def _guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Reject users outside the allowlist, when one is configured."""
    cfg: Config = context.application.bot_data["cfg"]
    user = update.effective_user
    if user and not cfg.is_allowed(user.id):
        await update.message.reply_text(
            f"This bot is private. Ask the owner to add your user ID ({user.id}) to "
            "ALLOWED_USER_IDS."
        )
        return False
    return True


# --------------------------------------------------------------------------- commands


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    store: DealStore = context.application.bot_data["store"]
    deal = store.load(update.effective_chat.id)
    deal.awaiting = None
    store.save(deal)

    await update.message.reply_text(
        "I'm a VC analyst. Give me what you have on a startup and I'll fill in "
        "the fund's scoring memo — ten categories scored out of 30, the deal "
        "facts, pros and risks, and the nine detail sections — returned as a "
        "Word document.\n\n"
        "Before scoring I search public sources for market sizing, product "
        "positioning, team qualifications and competitors.\n\n"
        "Use the buttons below, or just send me files and links directly:\n"
        f"  {BTN_DECK} — PDF, PPTX, or slide images\n"
        f"  {BTN_MODEL} — XLSX, CSV, or a PDF export\n"
        f"  {BTN_WEBSITE} — I'll read the site\n"
        f"  {BTN_INFO} — call notes, bios, terms, anything\n"
        f"  {BTN_MEMO} — when you're done adding material\n\n"
        "Nothing is required except one piece of material. The memo says what's "
        "missing rather than refusing to score.",
        reply_markup=KEYBOARD,
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    store: DealStore = context.application.bot_data["store"]
    deal = store.load(update.effective_chat.id)
    header = f"Current deal: {deal.company}" if deal.company else "Current deal"
    body = "\n".join(deal.summary_lines())
    tail = (
        f"\n\nReady when you are — hit {BTN_MEMO}."
        if deal.has_material()
        else "\n\nNothing collected yet."
    )
    await update.message.reply_text(f"{header}\n\n{body}{tail}", reply_markup=KEYBOARD)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    store: DealStore = context.application.bot_data["store"]
    cfg: Config = context.application.bot_data["cfg"]
    chat_id = update.effective_chat.id
    store.reset(chat_id)

    chat_files = cfg.files_dir / str(chat_id)
    if chat_files.exists():
        for path in chat_files.iterdir():
            path.unlink(missing_ok=True)

    await update.message.reply_text(
        "Cleared. Send material for the next company.", reply_markup=KEYBOARD
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Commands:\n"
        "/start — the menu\n"
        "/status — what I've collected for this deal\n"
        "/memo — write the scoring memo now\n"
        "/company <name> — name the company\n"
        "/reset — clear everything and start a new deal\n\n"
        "You can also send files and links without pressing anything: PDFs and "
        "PPTX become the deck, spreadsheets become the model, URLs become the "
        "website, and plain text becomes additional info.",
        reply_markup=KEYBOARD,
    )


async def cmd_company(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    store: DealStore = context.application.bot_data["store"]
    deal = store.load(update.effective_chat.id)
    name = " ".join(context.args).strip()
    if not name:
        await update.message.reply_text("Usage: /company Acme Robotics")
        return
    deal.company = name
    store.save(deal)
    await update.message.reply_text(f"Deal named: {name}", reply_markup=KEYBOARD)


# ------------------------------------------------------------------------- collecting


async def _ask_for(update: Update, store: DealStore, deal: Deal, kind: str) -> None:
    deal.awaiting = kind
    store.save(deal)
    await update.message.reply_text(PROMPTS[kind], reply_markup=KEYBOARD)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    store: DealStore = context.application.bot_data["store"]
    deal = store.load(update.effective_chat.id)
    text = (update.message.text or "").strip()

    # Button presses arrive as ordinary text messages.
    if text == BTN_DECK:
        return await _ask_for(update, store, deal, AWAIT_PITCH_DECK)
    if text == BTN_MODEL:
        return await _ask_for(update, store, deal, AWAIT_FIN_MODEL)
    if text == BTN_WEBSITE:
        return await _ask_for(update, store, deal, AWAIT_WEBSITE)
    if text == BTN_INFO:
        return await _ask_for(update, store, deal, AWAIT_NOTES)
    if text == BTN_STATUS:
        return await cmd_status(update, context)
    if text == BTN_RESET:
        return await cmd_reset(update, context)
    if text == BTN_MEMO:
        return await generate_memo(update, context)

    awaiting = deal.awaiting

    if awaiting in (AWAIT_PITCH_DECK, AWAIT_FIN_MODEL):
        what = "pitch deck" if awaiting == AWAIT_PITCH_DECK else "financial model"
        await update.message.reply_text(
            f"I need the {what} as an attached file. Saving that as additional info "
            "instead — send the file when you have it."
        )
        deal.notes.append(text)
        deal.awaiting = None
        store.save(deal)
        return

    if awaiting == AWAIT_WEBSITE:
        return await _save_website(update, store, deal, text)

    if awaiting == AWAIT_NOTES:
        deal.notes.append(text)
        deal.awaiting = None
        store.save(deal)
        await update.message.reply_text(
            f"Noted ({len(deal.notes)} note(s) on file).", reply_markup=KEYBOARD
        )
        return

    # Nothing pending: route by what the message looks like.
    url = ingest.find_url(text)
    if url and len(text.split()) <= 3:
        return await _save_website(update, store, deal, text)

    deal.notes.append(text)
    store.save(deal)
    await update.message.reply_text(
        f"Saved under additional info ({len(deal.notes)} note(s)).", reply_markup=KEYBOARD
    )


async def _save_website(update: Update, store: DealStore, deal: Deal, text: str) -> None:
    url = ingest.find_url(text)
    if not url:
        await update.message.reply_text(
            "That doesn't look like a URL. Send something like https://acme.com"
        )
        return
    if url in deal.websites:
        await update.message.reply_text(f"Already have {url}.", reply_markup=KEYBOARD)
        return

    deal.websites.append(url)
    deal.awaiting = None
    store.save(deal)
    await update.message.reply_text(
        f"🌐 {url} saved — I'll read it when writing the memo.", reply_markup=KEYBOARD
    )


async def on_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    cfg: Config = context.application.bot_data["cfg"]
    store: DealStore = context.application.bot_data["store"]
    deal = store.load(update.effective_chat.id)
    message = update.message

    if message.document:
        tg_file = message.document
        file_name = tg_file.file_name or f"upload_{int(time.time())}"
        mime = tg_file.mime_type or ""
    else:  # a photo — most likely a screenshotted slide
        tg_file = message.photo[-1]
        file_name = f"slide_{int(time.time())}.jpg"
        mime = "image/jpeg"

    size = getattr(tg_file, "file_size", 0) or 0
    if size > cfg.max_file_bytes:
        await message.reply_text(
            f"{file_name} is {size / 1e6:.1f} MB. Telegram only lets bots download "
            "files up to 20 MB — send a smaller export or split it."
        )
        return

    # A pressed button wins; otherwise guess from the extension. `kind is None`
    # means "keep it as additional info", which only plain text files earn.
    if deal.awaiting in (AWAIT_PITCH_DECK, AWAIT_FIN_MODEL):
        kind = deal.awaiting
    else:
        guess = ingest.classify(file_name)
        if guess is None:
            await message.reply_text(
                f"I'm not sure what {file_name} is. Press {BTN_DECK} or {BTN_MODEL} "
                "first, then send it again."
            )
            return
        kind = None if guess == "notes" else guess

    chat_dir = cfg.files_dir / str(update.effective_chat.id)
    chat_dir.mkdir(parents=True, exist_ok=True)
    dest = chat_dir / f"{int(time.time())}_{Path(file_name).name}"

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    handle = await tg_file.get_file()
    await handle.download_to_drive(custom_path=str(dest))

    # A text file with nothing pending is additional info, not a deck.
    if kind is None:
        try:
            deal.notes.append(ingest.extract_file(dest))
        except ingest.IngestError as exc:
            await message.reply_text(str(exc))
            return
        deal.awaiting = None
        store.save(deal)
        await message.reply_text(
            f"📝 {file_name} saved under additional info.", reply_markup=KEYBOARD
        )
        return

    attachment = Attachment(
        kind=kind,
        file_name=file_name,
        path=str(dest),
        mime=mime,
        size=size or dest.stat().st_size,
    )

    if kind == AWAIT_PITCH_DECK:
        deal.decks.append(attachment)
        label = "📊 Pitch deck"
    else:
        deal.models.append(attachment)
        label = "💰 Financial model"

    deal.awaiting = None
    store.save(deal)

    missing = []
    if not deal.models:
        missing.append(BTN_MODEL)
    if not deal.websites:
        missing.append(BTN_WEBSITE)
    hint = f"\n\nStill missing: {', '.join(missing)}" if missing else ""

    await message.reply_text(
        f"{label} saved: {file_name}{hint}\n\nHit {BTN_MEMO} whenever you're ready.",
        reply_markup=KEYBOARD,
    )


# ----------------------------------------------------------------------------- memo


async def generate_memo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    store: DealStore = context.application.bot_data["store"]
    analyst: Analyst = context.application.bot_data["analyst"]
    chat_id = update.effective_chat.id
    deal = store.load(chat_id)

    if not deal.has_material():
        await update.message.reply_text(
            "I have nothing to score yet. Send a deck, a model, a website or some "
            "notes first.",
            reply_markup=KEYBOARD,
        )
        return

    in_flight = _analysis_lock(context)
    if chat_id in in_flight:
        await update.message.reply_text("Still working on the last memo — one moment.")
        return
    in_flight.add(chat_id)

    cfg: Config = context.application.bot_data["cfg"]
    opening = (
        "Reading everything, checking public sources, and scoring it. This takes a "
        "couple of minutes for a full deck plus model…"
        if cfg.enable_web_research
        else "Reading everything and scoring it. This takes a minute or two for a "
        "full deck plus model…"
    )
    status = await update.message.reply_text(opening)
    typing = asyncio.create_task(_keep_typing(context, chat_id))

    try:
        result = await asyncio.to_thread(analyst.score, deal)
    except Exception as exc:  # noqa: BLE001 - every failure path ends in a chat message
        log.exception("memo generation failed for chat %s", chat_id)
        await status.edit_text(f"❌ Couldn't finish the memo.\n\n{exc}")
        return
    finally:
        typing.cancel()
        in_flight.discard(chat_id)

    await status.delete()

    memo = result.memo
    if result.warnings:
        await update.message.reply_text(
            "⚠️ Some material couldn't be read and was left out:\n"
            + "\n".join(f"• {w}" for w in result.warnings)
        )

    for part in chunk(render_chat(memo)):
        await update.message.reply_text(part)

    document = build_docx(memo, research=result.research, sources=result.sources)
    name = filename_for(memo)
    await update.message.reply_document(
        document=document,
        filename=name,
        caption=(
            f"Scoring memo — {memo.company_name} · {memo.scoring_line()}"
            + (f"\n{len(result.sources)} web source(s) consulted." if result.sources else "")
        ),
        reply_markup=KEYBOARD,
    )

    if not deal.company:
        deal.company = memo.company_name
        store.save(deal)


async def _keep_typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Hold the typing indicator while the model works; Telegram expires it every ~5s."""
    try:
        while True:
            await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("unhandled error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "Something went wrong on my side. Try that again — /status shows what "
            "I still have."
        )


def build_application(cfg: Config) -> Application:
    app = Application.builder().token(cfg.telegram_token).build()
    app.bot_data["cfg"] = cfg
    app.bot_data["store"] = DealStore(cfg.deals_dir)
    app.bot_data["analyst"] = Analyst(cfg)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("company", cmd_company))
    app.add_handler(CommandHandler("memo", generate_memo))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, on_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cfg = load_config()
    app = build_application(cfg)
    log.info("VC analyst bot starting (model: %s)", cfg.model)
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
