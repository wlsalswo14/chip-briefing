import unittest

import send_telegram_archive as telegram_archive


class TelegramArchiveTests(unittest.TestCase):
    def test_split_message_keeps_blocks_under_limit(self):
        message = "\n\n".join([f"<b>section {index}</b>\n" + ("x" * 900) for index in range(6)])
        chunks = telegram_archive.split_telegram_message(message, limit=1900)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 1900 for chunk in chunks))
        self.assertEqual("\n\n".join(chunks), message)


if __name__ == "__main__":
    unittest.main()
