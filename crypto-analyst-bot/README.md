# Crypto Analyst Bot

Telegram bot providing cryptocurrency analytics, education and portfolio tools.

This repository contains the bot sources and several modules with async
handlers.  All intents used by the AI classifier are stored in
`config/intents.json` and routed via a simple `IntentRouter`.

See [COMMANDS.md](COMMANDS.md) for the full list of available commands.

## API keys

Several features rely on external APIs and bot configuration provided via
environment variables. Copy `.env.example` to `.env` and fill in the values for
your deployment. The most important variables are:

- `CRYPTOPANIC_API_KEY` – access to CryptoPanic news
- `COINMARKETCAP_API_KEY` – required for CoinMarketCap endpoints and sent
  as `X-CMC_PRO_API_KEY` header

## Usage limits and settings

Free users can send up to 20 messages per day. After reaching the limit the bot
will suggest subscribing or waiting until the next day.

Recommendation hints can be toggled with `/hints on` or `/hints off`. The same
option is available via `/settings recommendations <on|off>`.

## Performance tips

For production deployments run several Uvicorn workers to handle webhooks in
parallel:

```bash
uvicorn main:app --workers 2
```

The bot caches frequent requests such as prices and news in Redis to minimise
external API calls.
