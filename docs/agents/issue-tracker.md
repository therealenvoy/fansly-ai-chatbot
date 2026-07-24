# Issue Tracker

Issues for this repo live as local markdown files under `.scratch/<feature>/`.

## Creating an issue

Create a directory under `.scratch/` named after the feature or bug:

```
.scratch/persona-engine/
  issue.md     # The issue description
  notes.md     # Research notes, decisions
  done.md      # (optional) resolution summary
```

## Reading issues

The `to-tickets`, `triage`, `to-spec`, and `qa` skills read from `.scratch/` by scanning for `issue.md` files.

## PRs as a request surface

Off. This repo has no remote — external PRs are not a workflow concern.