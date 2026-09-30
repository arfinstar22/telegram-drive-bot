import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from handlers import files, folders


class TestUploadConfirmation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        files._upload_batches.clear()

    def tearDown(self):
        files._upload_batches.clear()

    @patch("handlers.files.db")
    async def test_upload_in_custom_folder_sets_target_and_waits_for_confirmation(self, mock_db):
        mock_db.get_folder.return_value = {"id": 12, "name": "12 Semester 6", "is_system": False}
        mock_db.find_duplicate_file.return_value = None
        mock_db.save_file.return_value = {"id": 101, "folder_id": 12}

        update = MagicMock()
        update.effective_user.id = 999
        update.effective_chat.id = 888
        update.message.delete = AsyncMock()
        update.message.document.file_name = "Tugas.docx"
        update.message.document.file_size = 1024
        update.message.document.mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        update.message.document.file_id = "doc123"
        update.message.document.file_unique_id = "uniq123"
        update.message.photo = None
        update.message.video = None
        update.message.animation = None
        update.message.audio = None

        context = MagicMock()
        context.user_data = {
            "state": "idle",
            "current_folder_id": 12,
        }
        context.bot.send_message = AsyncMock()
        mock_sent_msg = MagicMock()
        mock_sent_msg.message_id = 555
        context.bot.send_message.return_value = mock_sent_msg

        # User uploads file
        await files.handle_file_upload(update, context)

        # Verify file saved to custom folder 12
        mock_db.save_file.assert_called_once()
        self.assertEqual(mock_db.save_file.call_args[0][1], 12)

        # Verify progress message was sent with inline button "✅ Selesai Upload"
        context.bot.send_message.assert_called_once()
        sent_call = context.bot.send_message.call_args
        self.assertIn("12 Semester 6", sent_call.kwargs["text"])
        self.assertIn("Sedang Mengunggah", sent_call.kwargs["text"])

        markup = sent_call.kwargs["reply_markup"]
        btn_data = markup.inline_keyboard[0][0].callback_data
        self.assertEqual(btn_data, "upload_finish:999")

        # Verify batch is still active in memory (not flushed after 1.8s)
        self.assertIn(999, files._upload_batches)
        self.assertEqual(files._upload_batches[999]["folder_id"], 12)
        self.assertFalse(files._upload_batches[999]["is_inbox"])

        # User clicks "✅ Selesai Upload"
        query_update = MagicMock()
        query_update.callback_query.answer = AsyncMock()
        query_update.callback_query.from_user.id = 999
        query_update.callback_query.message.reply_text = AsyncMock()
        context.bot.edit_message_text = AsyncMock()

        await files.btn_done_uploading(query_update, context)

        # Verify batch is flushed and final notification sent to edit_message_text
        self.assertNotIn(999, files._upload_batches)
        context.bot.edit_message_text.assert_called_once()
        final_call = context.bot.edit_message_text.call_args
        self.assertIn("Batch Upload Selesai!", final_call.kwargs["text"])
        self.assertIn("12 Semester 6", final_call.kwargs["text"])

        # Verify Smart Sort is NOT present for custom folder
        final_markup = final_call.kwargs["reply_markup"]
        all_cb = [b.callback_data for row in final_markup.inline_keyboard for b in row]
        self.assertFalse(any(cb.startswith("bsm:") for cb in all_cb))

    @patch("handlers.files.db")
    async def test_upload_without_folder_defaults_to_inbox_with_smart_sort(self, mock_db):
        mock_db.get_or_create_inbox_folder.return_value = {"id": 1, "name": "📥 File Masuk", "is_system": True}
        mock_db.find_duplicate_file.return_value = None
        mock_db.save_file.return_value = {"id": 102, "folder_id": 1}

        update = MagicMock()
        update.effective_user.id = 777
        update.effective_chat.id = 666
        update.message.delete = AsyncMock()
        update.message.document.file_name = "Catatan.pdf"
        update.message.document.file_size = 2048
        update.message.document.mime_type = "application/pdf"
        update.message.document.file_id = "doc456"
        update.message.document.file_unique_id = "uniq456"
        update.message.photo = None
        update.message.video = None
        update.message.animation = None
        update.message.audio = None

        context = MagicMock()
        context.user_data = {
            "state": "idle",
        }
        context.bot.send_message = AsyncMock()
        mock_sent_msg = MagicMock()
        mock_sent_msg.message_id = 7771
        context.bot.send_message.return_value = mock_sent_msg

        await files.handle_file_upload(update, context)

        self.assertEqual(mock_db.save_file.call_args[0][1], 1)
        self.assertTrue(files._upload_batches[777]["is_inbox"])

        query_update = MagicMock()
        query_update.callback_query.answer = AsyncMock()
        query_update.callback_query.from_user.id = 777
        query_update.callback_query.message.reply_text = AsyncMock()
        context.bot.edit_message_text = AsyncMock()

        await files.btn_done_uploading(query_update, context)

        # Verify Smart Sort is present for inbox upload
        final_markup = context.bot.edit_message_text.call_args.kwargs["reply_markup"]
        all_cb = [b.callback_data for row in final_markup.inline_keyboard for b in row]
        self.assertTrue(any(cb.startswith("bsm:") for cb in all_cb))

    @patch("handlers.files.db")
    async def test_upload_to_folder_no_duplicate_reply_keyboard(self, mock_db):
        mock_db.get_folder.return_value = {"id": 88, "name": "KKN Desa Rahia 2026"}

        query_update = MagicMock()
        query_update.callback_query.answer = AsyncMock()
        query_update.callback_query.data = "up:88"
        query_update.callback_query.from_user.id = 555
        query_update.callback_query.edit_message_text = AsyncMock()
        query_update.callback_query.message.reply_text = AsyncMock()

        context = MagicMock()
        context.user_data = {}

        await files.upload_to_folder(query_update, context)

        # Verified state & folder tracking
        self.assertEqual(context.user_data["state"], "uploading")
        self.assertEqual(context.user_data["upload_folder_id"], 88)
        self.assertEqual(context.user_data["current_folder_id"], 88)

        # Verified single edit_message_text called
        query_update.callback_query.edit_message_text.assert_called_once()
        text_arg = query_update.callback_query.edit_message_text.call_args[0][0]
        self.assertIn("KKN Desa Rahia 2026", text_arg)
        self.assertIn("Mode Upload", text_arg)

        # Verified NO duplicate reply_text sent (which caused duplicate bottom keyboard)
        query_update.callback_query.message.reply_text.assert_not_called()

    def test_extract_file_info_detects_photo_in_document(self):
        from utils import extract_file_info
        msg = MagicMock()
        msg.photo = None
        msg.video = None
        msg.animation = None
        msg.audio = None
        msg.voice = None
        msg.video_note = None
        msg.document.file_name = "foto_resolusi_tinggi.png"
        msg.document.file_size = 15728640  # 15 MB
        msg.document.mime_type = "image/png"
        msg.document.file_id = "doc_full_res_123"
        msg.document.file_unique_id = "uniq_doc_123"
        msg.document.thumbnail.file_id = "thumb_photo_456"

        info = extract_file_info(msg)
        self.assertIsNotNone(info)
        self.assertEqual(info["file_type"], "photo")
        self.assertEqual(info["file_size"], 15728640)
        self.assertEqual(info["file_id"], "doc_full_res_123")
        self.assertEqual(info["thumbnail_file_id"], "thumb_photo_456")

    @patch("handlers.files.db")
    async def test_preview_photo_document_uses_thumbnail_for_photo_preview(self, mock_db):
        mock_db.get_file_for_user.return_value = {
            "id": 99,
            "folder_id": 10,
            "file_id": "doc_full_res_123",
            "file_name": "foto_resolusi_tinggi.png",
            "file_type": "photo",
            "file_size": 15728640,
            "thumbnail_file_id": "thumb_photo_456",
            "created_at": "2026-10-01T00:00:00",
            "mime_type": "image/png",
        }

        query_update = MagicMock()
        query_update.callback_query.answer = AsyncMock()
        query_update.callback_query.data = "fi:99"
        query_update.callback_query.from_user.id = 555
        # Simulating that reply_photo with doc_full_res_123 fails (as Telegram Bot API does for doc IDs),
        # but succeeds with thumb_photo_456
        async def mock_reply_photo(target, **kwargs):
            if target == "doc_full_res_123":
                raise Exception("Wrong file identifier")
            return MagicMock()

        query_update.callback_query.message.reply_photo = AsyncMock(side_effect=mock_reply_photo)
        query_update.callback_query.message.reply_document = AsyncMock()

        context = MagicMock()

        await files.preview_file(query_update, context)

        # Verified reply_photo called with the Photo thumbnail
        query_update.callback_query.message.reply_photo.assert_called()
        last_call_target = query_update.callback_query.message.reply_photo.call_args[0][0]
        self.assertEqual(last_call_target, "thumb_photo_456")
        # And reply_document was NOT used because photo preview succeeded
        query_update.callback_query.message.reply_document.assert_not_called()


if __name__ == "__main__":
    unittest.main()
