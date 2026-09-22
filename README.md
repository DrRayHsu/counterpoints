# Counterpoints

Two voices at once, and the objections to putting them together. A Bluesky bot that its readers train in public. Twice a day it posts two quotations side by side. Readers vote on whether each pairing holds. Once a week it says how those votes changed it. Readers can also add quotations of their own.

It starts with a collection about slavery, masters and machines. The name commits to the method, not the subject, so the collection can move wherever its readers take it.

It runs free on GitHub Actions and the Bluesky API.

## The rules (these are public, and are the point)

- **Voting.** Readers reply `=` if a pairing holds and `≠` if it breaks (`holds`, `breaks` and `!=` also count). Only the first word of a reply counts. Each account's latest vote on a post is the one that stands.
- **Seeking disagreement.** Quotes and pairs that split readers come back more often. Quotes and pairs everyone agrees on fade, but never disappear.
- **Changing modes with the mood.** Each week the bot reads the votes and switches how it pairs quotes:

  | What readers did | Mood | Next week's mode |
  |---|---|---|
  | Almost no one voted | quiet | random: anything with anything |
  | Mostly ≠ | objecting | same-strand: old against new, only where both quotes make the same argument |
  | Mostly = | agreeing | cross-strand: old against new, only where the quotes share no argument |
  | Split | contested | cross-era: old against new, weighted toward what divided readers |

  If readers replied but hardly voted, the mode stays the same. Each account counts at most 5 times per week toward the mood, so a few accounts can't steer it.
- **The weekly report.** A short thread each week gives the vote counts, the mood, the new mode and why, the pairing that split readers most, and the quotations added by readers, crediting who found them.
- **Readers writing the poem.** Anyone can reply to the bot or mention it with `#found “the exact words” — Speaker, Work (year)` and a link. Each submission becomes a GitHub issue for you to review. Nothing is posted without your approval. Approved quotes appear soon after, credited with "found by @handle."

The strands used by the same-strand and cross-strand modes are tags on each quote: `labor`, `status` (personhood, moral standing), `master` (control, what ownership does to owners), `naming` and `voice`. You set them in `quotes.json`, and for new submissions when you approve them.

## Setup (about 15 minutes)

1. **Create the Bluesky account**, as counterpoints.bsky.social (unregistered as of Sep 22, 2026), with the display name Counterpoints. Then create an app password under Settings → Privacy and security → App passwords.
2. **Write the bio**, for example:
   > Two quotations at a time, paired by rules, not by hand. Reply = if a pairing holds, ≠ if it breaks, and I change. #found adds a quotation.
3. **Upload these files to a public GitHub repo.**
4. **Add secrets** under Settings → Secrets and variables → Actions:
   - `BSKY_HANDLE`
   - `BSKY_APP_PASSWORD`
   - `VOTE_SALT`: any long random string. Voters are stored only as salted hashes, and the salt keeps those hashes from being matched back to accounts.
5. **Give the workflow write access.** Under Settings → Actions → General → Workflow permissions, choose "Read and write permissions".
6. **Check the setup:** Actions → post → Run workflow, with "Only check the setup" ticked (the default). It logs in to Bluesky and GitHub, reports what works, and posts nothing. If anything fails, the log says which secret or setting to fix.
7. **Post the first pair:** Run workflow again with the box unticked. After that it posts on its own at 8am and 6pm Pacific. The first weekly report comes seven days after that first post.
8. **Post the explainer and pin it**, for example:
   > How this works: twice a day, two quotations. Reply = if the pairing holds, ≠ if it breaks. Pairings that divide you come back more often. Each week I post how your votes changed me, and switch how I pair things. Add a quotation with #found “exact words” — source (year) and a link. I review every one.

## Reviewing submissions

Each `#found` submission opens an issue labeled `found`. The bot has already filled in a JSON block by parsing the post, but it only guesses. To approve one:

1. Check the wording against the original source.
2. Fix `id`, `year`, `text`, `attribution`, `short` and `url`, and set `strands`.
3. Add the `approved` label.

On its next run, the bot adds the quote to `quotes.json`, comments and closes the issue. To reject a submission, close the issue.

## Settings (`config.json`)

- `mood_modes`: which mode each mood leads to.
- `mood`:
  - `min_votes`: fewer votes than this in a week reads as quiet or unclear.
  - `lopsided`: the share of votes (0.65) at which the mood reads as objecting or agreeing.
  - `max_votes_per_account`: the cap per account per week.
- `weights`:
  - `quote_contest`, `pair_contest`: how hard to chase disagreement.
  - `unseen`: bonus for pairs not yet posted.
  - `fresh`: bonus for new reader submissions.
  - `floor`: keeps every pair possible.
  - `no_repeat`: gap between repeats of the same pair.
- `mode_override`: set a mode by hand and ignore the mood.
- `blocklist`: pairs never to post, e.g. `[["taney", "suleyman"]]`.
- `curated`: pairs used when the mode is `curated`.

## Files

- `bot.py`: runs each step: approved submissions → reading replies → weekly report → posting.
- `logic.py`: votes, submissions, weighting and mood. No network.
- `services.py`: Bluesky and GitHub.
- `render.py`: draws the card.
- `simulate.py`: runs five simulated weeks offline (`python simulate.py`) so you can watch it adapt.
- `data/`: what it has learned so far. The post log, vote tallies and mood history are committed after every run, so the whole history is public in the repo. These commits also keep GitHub from switching off the schedule.
- `fonts/`: EB Garamond, under the SIL Open Font License.
