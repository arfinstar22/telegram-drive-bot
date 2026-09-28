"""Telegram Drive Bot — main entry point."""

import logging

from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from config import BOT_TOKEN, WEBHOOK_URL, PORT
from handlers import menu, folders, files, settings

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)


async def noop(update, context):
    await update.callback_query.answer()


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # ── Commands ───────────────────────────────────────
    app.add_handler(CommandHandler("start", menu.start))

    # ── Reply Keyboard buttons ─────────────────────────
    app.add_handler(MessageHandler(filters.Regex(r"^📁 My Files$"), folders.my_files))
    app.add_handler(MessageHandler(filters.Regex(r"^📤 Upload$"), files.upload_menu))
    app.add_handler(MessageHandler(filters.Regex(r"^🔍 Search$"), files.search_prompt))
    app.add_handler(MessageHandler(filters.Regex(r"^⚙️ Settings$"), settings.settings_menu))
    app.add_handler(MessageHandler(filters.Regex(r"^✅ Done$"), files.done_uploading))
    app.add_handler(MessageHandler(filters.Regex(r"^❌ Cancel$"), menu.cancel))
    app.add_handler(MessageHandler(filters.Regex(r"^🏠 Home$"), menu.go_home))

    # ── Folder callbacks ───────────────────────────────
    app.add_handler(CallbackQueryHandler(folders.open_folder, pattern=r"^f:\d+$"))
    app.add_handler(CallbackQueryHandler(folders.create_folder_prompt, pattern=r"^cf:"))
    app.add_handler(CallbackQueryHandler(folders.rename_folder_prompt, pattern=r"^dr:"))
    app.add_handler(CallbackQueryHandler(folders.delete_folder_prompt, pattern=r"^dx:\d+$"))
    app.add_handler(CallbackQueryHandler(folders.confirm_delete_folder, pattern=r"^dxc:"))
    app.add_handler(CallbackQueryHandler(folders.file_page, pattern=r"^fp:"))

    # ── File callbacks ─────────────────────────────────
    app.add_handler(CallbackQueryHandler(files.preview_file, pattern=r"^fi:"))
    app.add_handler(CallbackQueryHandler(files.download_file, pattern=r"^fdl:"))
    app.add_handler(CallbackQueryHandler(files.rename_file_prompt, pattern=r"^fr:"))
    app.add_handler(CallbackQueryHandler(files.move_file_picker, pattern=r"^fm:"))
    app.add_handler(CallbackQueryHandler(files.move_to_folder, pattern=r"^fmt:"))
    app.add_handler(CallbackQueryHandler(files.delete_file_prompt, pattern=r"^fx:\d+$"))
    app.add_handler(CallbackQueryHandler(files.confirm_delete_file, pattern=r"^fxc:"))
    app.add_handler(CallbackQueryHandler(files.upload_to_folder, pattern=r"^up:"))
    app.add_handler(CallbackQueryHandler(files.back_to_folder, pattern=r"^fb:"))
    app.add_handler(CallbackQueryHandler(files.quick_upload_to_folder, pattern=r"^qup:"))
    app.add_handler(CallbackQueryHandler(files.cancel_pick, pattern=r"^cancel_pick$"))

    # ── Settings & Trash callbacks ─────────────────────
    app.add_handler(CallbackQueryHandler(settings.storage_info, pattern=r"^si$"))
    app.add_handler(CallbackQueryHandler(settings.sort_cycle, pattern=r"^ss:"))
    app.add_handler(CallbackQueryHandler(settings.settings_back, pattern=r"^sb$"))
    app.add_handler(CallbackQueryHandler(settings.trash_view, pattern=r"^tv$"))
    app.add_handler(CallbackQueryHandler(settings.trash_restore, pattern=r"^tr:"))
    app.add_handler(CallbackQueryHandler(settings.trash_permanent_delete, pattern=r"^tp:"))
    app.add_handler(CallbackQueryHandler(settings.trash_empty_prompt, pattern=r"^te$"))
    app.add_handler(CallbackQueryHandler(settings.trash_empty_confirm, pattern=r"^tec$"))

    # ── No-op ──────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(noop, pattern=r"^noop$"))

    # ── File uploads ───────────────────────────────────
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.Document.ALL | filters.VIDEO |
        filters.AUDIO | filters.VOICE | filters.ANIMATION | filters.VIDEO_NOTE,
        files.handle_file_upload,
    ))

    # ── Free text input (folder names, search, rename) ─
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu.handle_text_input))

    # ── Run ────────────────────────────────────────────
    if WEBHOOK_URL:
        url = WEBHOOK_URL.rstrip("/")
        log.info("Starting webhook mode at %s", url)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"{url}/webhook",
            url_path="/webhook",
        )
    else:
        log.info("Starting polling mode")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
