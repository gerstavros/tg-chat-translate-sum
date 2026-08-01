# Chat Translator and Summarizer for Telegram

This is a simple app that I made for my own use. It reads all Telegram channels, chats and groups, and either translates them or summarizes them to your language (currently supporting only English and Greek, but you can add any language by adding a file).

I made it in Python because of existing libraries (telethon, unread), and used Tkinter for the UI to be simple and portable to any OS (and because it's my first time creating a full-scale desktop UI). I added also CustomTkinter to make it a bit less ugly.

## Features

- 📡 View all your Telegram chats with unread counts
- 🌐 Translate messages to your language using OpenAI API
- 📖 Create summaries using [unread](https://github.com/maxbolgarin/unread)
- 🖼️ Inline photo display with click-to-view full size (needs improvement)
- 🎬 Video playback via VLC (embedded player in new window)
- 👍 Emoji reactions to messages (needs much improvement)
- 🔍 Chat search and filtering
- 🌍 Multi-language UI (Greek / English only yet)

## Requirements

- Telegram API credentials (api_id + api_hash) from [my.telegram.org](https://my.telegram.org)
- OpenAI API key

## Quick Start

- There are ready to use binaries and packages: 

## License

Apache 2.0.

This project uses:
- [unread](https://github.com/maxbolgarin/unread) (Apache 2.0) for AI summaries
- [Telethon](https://github.com/LonamiWebs/Telethon) (MIT) for Telegram API access
- [OpenAI](https://openai.com/) for translation
