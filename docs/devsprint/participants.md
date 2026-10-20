# DevSprint Participants

A place for devsprint contributors to make their very first pull request to
OpenAlgo. The change is trivial on purpose. The point is to practise the workflow
(fork, branch, conventional commit, push, pull request, review, rebase) before the
event, so that on the day you spend your time on real code instead of on Git.

## How to add yourself

1. Make sure you have completed section 5 of the
   [contributor prep guide](README.md).
2. Create a branch, add one row to the table below, and open a pull request:

```bash
git checkout main
git pull upstream main
git checkout -b docs/add-<yourname>-devsprint
# edit this file, append one row to the end of the table
git add docs/devsprint/participants.md
git commit -m "docs: add <Your Name> to devsprint participants"
git push origin docs/add-<yourname>-devsprint
```

3. Open the pull request against `marketcalls/openalgo:main`.

Rules for the row:

- Append to the **end** of the table. Do not reorder existing rows.
- One row per person, one pull request per person.
- The interest column is a hint to the maintainers about what to point you at.
  Use something like `python`, `react`, `docs`, `testing`, `websockets`, or
  `broker integration`.
- No emoji. Plain text only, same as everywhere else in this repository.

If your pull request conflicts because someone else merged first, that is a
feature of this exercise, not a bug. Rebase and push again:

```bash
git fetch upstream
git rebase upstream/main
# resolve the conflict by keeping both rows
git add docs/devsprint/participants.md
git rebase --continue
git push --force-with-lease
```

## Participants

| Name | GitHub | Interested in |
| --- | --- | --- |
| Rajandran R | [@marketcalls](https://github.com/marketcalls) | maintainer |
|Padma Balaji L| [@PadmaBalajiL](https://github.com/PadmaBalajiL)|python|
|Niranjan | [@cracker314](https://github.com/cracker314)|python|
| Navadeep Marella | [@NavadeepDj](https://github.com/NavadeepDj) | python, backtesting |
