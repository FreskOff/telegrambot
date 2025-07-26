# Crypto Analyst Bot

Telegram bot providing cryptocurrency analytics, education and portfolio tools.

This repository contains the bot sources and several modules with async
handlers.  All intents used by the AI classifier are stored in
`config/intents.json` and routed via a simple `IntentRouter`.

See [COMMANDS.md](COMMANDS.md) for the full list of available commands.

## API keys

Several features rely on external APIs. Create a `.env` file or set the
following environment variables:

- `CRYPTOPANIC_API_KEY` – access to CryptoPanic news
- `COINMARKETCAP_API_KEY` – required for CoinMarketCap endpoints and sent
  as `X-CMC_PRO_API_KEY` header

## Usage limits and settings

Free users can send up to 20 messages per day. After reaching the limit the bot
will suggest subscribing or waiting until the next day.

Recommendation hints can be toggled with `/hints on` or `/hints off`. The same
option is available via `/settings recommendations <on|off>`.
