# Version 1.1.1 Released

**Date: 4th November 2026**

**Contact release: a Telegram support link on every page and on the public site, configurable per installation.**

2 commits since 1.1.0. No database migration, no new required setting and no
change to the API, the SDK or webhooks.

**Highlights**

- **Telegram support link (`09614978f`)** - the footer on every page now reads
  "Contact: email · Telegram", and the About page has a "Message us on Telegram"
  button beside "Get support". The static site in `static/` shows the same link
  in its hero and footer.
- **Configurable, not hard-coded (`09614978f`)** - the default
  (`https://t.me/RanjT55`) is `supportTelegramUrl` in
  `frontend/src/brand/brand.ts` and `SUPPORT_TELEGRAM_URL` in `utils/brand.py`.
  One installation can point it elsewhere by adding
  `"supportTelegramUrl": "https://t.me/<username>"` to `custom_brand/brand.json`,
  with no rebuild or restart. Only an `https://t.me/` username link is accepted;
  anything else falls back to the default. The static site reads the link from
  `static/site-config.js` and hides it when the value is empty.
- **Frontend rebuilt (`2438e5a5d`)** - `frontend/dist` built locally and committed.

**Upgrading**

`git pull` on `main`. No migration is needed.

**Dependencies**

No dependencies changed.

**Contributors**

- **@ranjeetthorat** - the Telegram support link and its configuration
  (`09614978f`, `2438e5a5d`).

**Links**

- Repository: https://github.com/ranjeetthorat/ai-algo
- Product site: https://fastalgo.tinycompute.site
- Support: https://www.tinycompute.site
- Telegram: https://t.me/RanjT55
