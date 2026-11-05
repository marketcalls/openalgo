# Version 2.0.3.1 Released

**Date: 30th October 2026**

**Security fixes and Fyers live data: an expired login can no longer read your OpenAlgo API key, OpenAlgo now checks the mail server's certificate before it sends your mail password or a password reset link, Fyers live prices arrive complete and on time, and tornado moves to 6.6 for three advisories. Every install should upgrade.**

6 commits since v2.0.3.0, excluding automated frontend build commits and
including this release. The platform version moves from 2.0.3.0 to 2.0.3.1.
The pinned `openalgo` Python SDK remains 2.0.5. This release adds no database
migration.

**Highlights**

- **An expired login can no longer read your API key (`e2bdd061e`).** Every
  page turned away a login cookie from before the daily 3 AM IST expiry, but
  the connections the trading terminal, the charts and the WebSocket test pages
  use to fetch your API key and the live data settings still accepted one, and
  kept it alive each time it was used. Someone who had copied an old cookie,
  from a shared browser profile or a saved network log, could have read your
  API key with it, and the API key places orders. These connections now require
  a current login, like every other page. Separately, between midnight and
  3 AM IST a login of any age counted as current; a login now counts only if it
  was made after the most recent 3 AM expiry. Thirty tests pin this; 25 of them
  fail on the previous code.
- **Email checks the mail server's certificate (`af5d5f2cc`).** Every
  connection OpenAlgo made to your mail server accepted any certificate.
  Someone able to intercept the traffic between your OpenAlgo server and your
  mail server could present a certificate of their own and read your mail
  password, and any password reset link OpenAlgo sent. Password reset, the test
  email, the SMTP connection check and the SMTP debug tool now all verify the
  certificate and the server's name, and stop before sending anything if either
  does not check out. Twenty tests pin this; they fail on the previous code.
- **The SMTP debug tool no longer writes your mail password to the server
  log.** It printed the whole mail server conversation, and the login line in
  it carries the password.
- **Gmail relay advice that works on your server.** When Google Workspace's
  SMTP relay refused an email, OpenAlgo told every install to allow one fixed
  IP address, which belonged to a single machine. It now asks you to allow the
  public IP address of your own OpenAlgo server, or to use smtp.gmail.com on
  port 587 with an app password.
- **Fyers live data arrives complete (`8d2bece9d`, #2323).** LTP was on time
  but every other field (volume, bid, ask) was one update behind, and an update
  that moved only bid, ask or volume was dropped. Each update is now published
  whole. Change and change percent are filled from the previous close instead
  of reading 0, a depth update no longer reports the bid and ask midpoint as
  the LTP, and an index no longer shows five made-up depth levels.

**What to check after upgrading**

- **A tab left open overnight.** After 3 AM, a tab still open from the day
  before has to log in again before it can fetch the API key or the live data
  settings, as every other page already required. Nothing changes while you
  are logged in.
- **If you think an old login cookie of yours may have been copied,** generate
  a new key with Regenerate on the API Key page. The old key stops working.
- **Email with an IP address or a private mail server.** If your SMTP host is
  entered as an IP address, or your own mail server uses a self-signed
  certificate, email now stops with "The mail server's security certificate
  could not be verified". Enter the host by its name, for example
  `smtp.gmail.com`, and give a private mail server a certificate from a
  recognised authority. Gmail, Outlook, Zoho and the other public providers
  need no change.
- **Consider requiring your authenticator app for password reset.** On the
  Profile page, open the TOTP tab and, under 2FA Enforcement, switch on
  Password reset. The email reset path is then off, so an email alone can
  never reset your password.

**Dependencies**

- `tornado` 6.5.10 to 6.6 (`c244ceaf5`; GHSA-pcg2-g6cj-q92c and
  GHSA-r4j5-9xpp-3985, medium; GHSA-pw9p-v7r6-gx4p, low): slow parsing of
  folded HTTP headers, memory and event-loop use from bodies sent in many small
  chunks, and an open redirect. OpenAlgo does not import tornado or serve HTTP
  with it; it is installed for the Jupyter kernel packages. A kernel was
  started and ran code on 6.6. No behaviour change is expected.
- The pinned `openalgo` Python SDK remains 2.0.5.

**Contributors**

- **@marketcalls** - the expired-login fix, mail server certificate
  verification, the SMTP debug log fix, the Gmail relay message, the tornado
  security update and the release.
- **@Kalaiviswa** - complete and timely Fyers live data (#2323).
- **@carfeii** - reported that an expired login could still read the API key.
- **@ParzivalHack** - reported the mail server certificate issue.

**Links**

- [Repository](https://github.com/marketcalls/openalgo)
- [Documentation](https://docs.openalgo.in/)
- [Python SDK](https://pypi.org/project/openalgo/)
- [Community](https://www.openalgo.in/discord)
- [Videos](https://www.youtube.com/@openalgo)
- [Issue tracker](https://github.com/marketcalls/openalgo/issues)
