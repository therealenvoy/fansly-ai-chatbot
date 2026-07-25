# Sunny Charm dashboard redesign

## Product goal

Make the dashboard understandable in under a minute: the operator should always
know whether the bot is running, where to find each workflow, and what to do
when a section has no data.

## Design principles

1. **Status first.** Keep bot state visible in the top bar on every screen.
2. **One job per view.** Each tab has a plain title, one-line purpose, and one
   primary action at most.
3. **Calm by default.** Use system typography, neutral surfaces, restrained
   color, generous spacing, and subtle depth. Color communicates state rather
   than decoration.
4. **Reachable everywhere.** Use a desktop sidebar and a persistent mobile tab
   bar. Never hide a core destination at a responsive breakpoint.
5. **Progressive disclosure.** Keep lists scannable and open fan details in a
   focused drawer instead of crowding the main view.
6. **Clear empty states.** Explain what is missing, how it will appear, and the
   next action where one exists.

## Information architecture

- **Funnel:** live conversations and current buying stage
- **Vault:** offer-ready media
- **Fans:** memory, preferences, and customer value
- **Scripts:** reusable conversation playbooks
- **KPIs:** revenue and engagement performance
- **Flows:** PPV sequences and automation
- **Settings:** API connection, persona, and brand rules

## Interaction model

- Desktop uses a stable left rail with 44 px navigation targets.
- Mobile uses a fixed seven-destination bottom bar with the same ordering.
- The top-right bot control reports and changes live state from every view.
- Tables scroll horizontally on narrow screens instead of clipping data.
- Fan rows open a full-height detail drawer; on mobile it becomes full width.
- Focus rings, semantic buttons, accessible labels, and reduced-motion support
  are included in the base system.

## Visual system

- Native system font stack; no remote font dependency
- Off-white workspace, white cards, fine gray borders, soft shadows
- Apple-like blue for actions and selection
- Green, amber, and red reserved for status and performance
- 18–24 px surface radii and pill-shaped controls
- Compact data typography with generous surrounding whitespace

## Delivery phases

1. **Foundation:** responsive shell, navigation, top-level status, tokens
2. **Clarity:** descriptive subtitles, empty states, action hierarchy
3. **Data views:** responsive tables, cards, forms, and detail drawer
4. **Validation:** desktop/mobile browser review, keyboard checks, regression
   tests, and full automated test suite

## Success criteria

- Every primary destination is visible and usable at 390 px width.
- Bot state remains visible on every destination.
- No existing dashboard API route or control is removed.
- Empty views explain what happens next.
- Controls have visible keyboard focus and at least 38–44 px targets.
- Dashboard tests and the full application test suite pass.
