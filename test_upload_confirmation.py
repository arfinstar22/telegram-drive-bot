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


if __name__ == "__main__":
    unittest.main()
