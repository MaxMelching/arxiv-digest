# arXiv digest

***Note from Max:*** This repository is entirely vibecoded with Claude Opus 5.5. It works well for me personally, which is why I thought I would make it public. But I deserve no credit for any of the code (just the idea) and at the same time won't take responsibility if something goes wrong with it.

A daily email with the new arXiv papers in your categories, ranked by similarity to
your Zotero library.

```
arXiv RSS (today's announcement) ──┐
                                   ├─ SPECTER embeddings ─ rank ─ cutoff ─ HTML email
Zotero web API (your library) ─────┘   (local, no API key)
```

* **Ranking**: each paper's score is the mean cosine similarity between its
  title+abstract and the *k* most similar papers in your library (default k = 5).
  Optional author/keyword boosts are added on top.
* **Cutoff**: the top 20 % (at least 5, at most 25) are shown as full cards; the rest
  are compact one-line entries. Once you've seen a few days of scores you can switch to
  a fixed `min_score`.
* **Email**: TeX in titles and abstracts is converted to Unicode (no MathJax in mail
  clients). Each card shows which of your saved papers it is closest to.
* **Runs** on GitHub Actions Mon–Fri at 13:17 UTC, after arXiv's evening announcement.
  It only sends once per announcement and skips holidays.

## Setup

1. **Repository**: create a *private* GitHub repo and push this folder to it.
2. **Zotero key**: at <https://www.zotero.org/settings/keys> note your numeric
   *userID*, then *Create new private key* with **read-only** library access.
3. **Sender account**: with Gmail, turn on 2-step verification and create an
   *app password* at <https://myaccount.google.com/apppasswords>. A separate Gmail
   address just for sending works well.
4. **Secrets**: in the repo, go to *Settings → Secrets and variables → Actions → New repository secret*.

   | Secret | Value |
   |---|---|
   | `ZOTERO_USER_ID` | numeric userID from step 2 |
   | `ZOTERO_API_KEY` | key from step 2 |
   | `SMTP_USER` | sender address, e.g. `my.digest@gmail.com` |
   | `SMTP_PASSWORD` | the app password |
   | `EMAIL_TO` | where the digest goes (comma-separate several) |
   | `SMTP_HOST`, `SMTP_PORT`, `EMAIL_FROM` | *optional*; defaults are `smtp.gmail.com`, `587`, `SMTP_USER` |

   Leaving `EMAIL_FROM` unset is the safest choice. A display name that looks like an
   organisation (e.g. "arXiv digest") sent from a personal Gmail address can be flagged as
   impersonation by Microsoft 365 / Outlook filters and silently quarantined.

5. **First run**: go to *Actions → arXiv digest → Run workflow* and tick **force**
   (needed on weekends, because the latest feed is then older than 36 h). The first run
   takes longer because it downloads the model (~440 MB) and embeds your whole library;
   both are cached for later runs. Every run's rendered email is also attached to
   the run as a downloadable artifact.

## Tuning (`config.yaml`)

* `categories`, `announce_types`: what to fetch. Add `replace` to include revised papers.
* `zotero.collections`: restrict to specific collections (the key is the 8-character ID
  in the collection's zotero.org URL).
* `interests`: free-text sentences, each treated as an extra saved paper. Useful for
  topics that are new or thin in your library.
* `ranking.cutoff.min_score`: scores within a narrow field cluster tightly
  (e.g. 0.78–0.90). After a week, pick the score below which nothing was useful.
* `ranking.boosts`: e.g. `authors: {"Jane Doe": 0.05}`, `keywords: {"ringdown": 0.02}`.
  Because scores cluster, a small boost of 0.02–0.05 is already a big jump in rank.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
export ZOTERO_USER_ID=... ZOTERO_API_KEY=...
python -m digest --dry-run --force        # writes out/digest.html, sends nothing
open out/digest.html
```

Offline smoke test (no model download, no Zotero; uses a crude word-hash embedder):

```bash
python -m digest --feed-file tests/fixtures/sample_feed.xml \
  --library-file tests/fixtures/library.json --embedder hash --dry-run --force
```

## Notes

* Cost: about 3–5 min of Actions time per run, roughly 100 min/month, well within the
  free allowance for private repos.
* Gmail clips HTML emails over about 100 KB. On very busy days the below-cutoff list is
  shortened to fit; the plain-text part always contains every paper.
* GitHub evicts caches unused for 7 days. After a long pause, the next run just
  re-embeds the library.
* Scheduled workflows run from the default branch only.
