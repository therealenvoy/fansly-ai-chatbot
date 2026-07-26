# Sunny Charm dashboard redesign

## Design authority

The first supplied reference is the visual source of truth:

- near-black framed application shell
- stable left navigation and slim global top bar
- dense but legible rounded cards
- violet selection states and soft neon edge light
- a central multicolour intelligence object
- small operational labels around high-contrast numbers
- quiet surfaces; colour is concentrated in state and focus

The other supplied references are an idea backlog, not approved screens to
copy. The approved MVP uses only the jobs that fit this bot and its verified
provider contract: operations, conversations, audience, truthful analytics,
simple persona editing, durable script editing, draft flows, and a local media
registry.

## Information architecture

| Destination | Operator job | Read sources | Write sources |
| --- | --- | --- | --- |
| Dashboard | See revenue, audience, launch readiness, and queue health | `/api/kpis`, `/api/conversations`, `/api/bot/status`, `/api/operations` | None |
| Messages | Review a conversation with durable fan context | `/api/conversations`, `/api/conversations/{fan_id}` | None |
| Audience | Inspect fan value, memory, preferences, and boundaries | `/api/fans`, `/api/conversations/{fan_id}` | None |
| Analytics | Review only durable and attributable performance metrics | `/api/kpis` | None |
| Scripts | Create and edit durable conversation playbooks | `/api/scripts` | Script create/update/delete |
| Flows | Create and edit provider-aware PPV sequence drafts | `/api/sequences`, `/api/media-assets` | Sequence create/update/delete |
| Vault | Browse bot-known provider media and local inventory | `/api/media-assets`, `/api/vault` | Media registration/removal |
| Settings | Verify the provider and manage persona/reference content | `/api/connection`, `/api/persona`, `/api/brand-bible` | Connection test, persona and reference saves |

## Non-negotiable data rules

1. Never invent missing revenue, subscriptions, conversion rates, or delivery
   status. Render `N/A` or a precise unavailable explanation.
2. Keep aggregate wallet balance separate from attributed fan revenue.
3. Keep local files visibly distinct from OnlyFansAPI provider media IDs.
4. Keep paid message activation blocked when the provider capability is absent.
5. Render bot state from `/api/bot/status`; never assume the toggle succeeded.
6. Preserve the controlled-launch allowlist and all backend launch guards.
7. All Fansly provider work continues through OnlyFansAPI.

## Component plan

### 1. Foundation

- Extract the active SPA presentation into `src/web/dashboard_shell.html`.
- Keep `DASHBOARD_HTML` as the stable Python import used by the server and
  tests.
- Define one dark token system for colour, spacing, borders, radii, shadows,
  state, and responsive behaviour.
- Keep all JavaScript within the per-response CSP nonce.

### 2. Global shell

- Add the reference-style framed application container.
- Add grouped navigation for overview, revenue tools, and workspace settings.
- Add a global provider workspace indicator, service-health link, refresh
  control, operator avatar, and truthful bot state control.
- Keep the controlled-launch summary visible in the desktop rail.

### 3. Dashboard

- Combine four existing read APIs instead of creating a second analytics
  contract.
- Use the central gradient intelligence object as the visual focal point.
- Show durable audience, revenue, purchase, outbound, response, and pipeline
  information.
- Label the activity matrix as an operational pulse, not historical revenue.

### 4. Work screens

- Messages: two-pane conversation browser with search and durable detail.
- Audience: compact value table and full profile drawer.
- Analytics: revenue card system matching the functional reference.
- Scripts: categorised playbook inventory and simple durable editor.
- Flows: preserve the full draft editor, capability guard, media selection,
  save, and delete behaviour.
- Vault: searchable local registry of provider-ready IDs plus local inventory;
  it never claims to be the complete native Fansly vault.
- Settings: provider status, structured persona controls, and brand-reference
  panels.

### 5. Responsive and accessible behaviour

- Desktop uses the stable left rail from the reference.
- Mobile converts the same destinations into a horizontally scrollable bottom
  navigation; no core destination disappears.
- Messages switch from two panes to list/detail mode on small screens.
- Preserve semantic buttons, visible focus, Escape-to-close, reduced motion,
  and minimum touch targets.

### 6. Verification

- Import and security-header regression tests.
- Dashboard API and bot-control tests.
- Full Python suite.
- Desktop screenshots at 1440 × 1000 and mobile screenshots at 390 × 844.
- Browser console and failed-request inspection.
- Visual comparison against the first reference for shell, density, colour,
  hierarchy, and focal composition.

## Completion criteria

- The first reference is recognisable in the application shell and dashboard
  composition without copying its product identity.
- Every functional destination above is present and connected to its current
  backend contract.
- Existing write paths retain CSRF protection and provider capability guards.
- No unavailable metric is rendered as a fact.
- Desktop and mobile layouts have no clipped primary actions or hidden core
  navigation.
- Automated tests and browser verification pass.
