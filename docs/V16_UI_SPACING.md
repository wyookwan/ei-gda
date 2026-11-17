# UI spacing, border and radius standard

Defined at the top of `static/css/v16.css`. New UI uses these tokens; it does not use ad-hoc pixel values.
`SpacingStandardTests` in `tests/test_v16_domain.py` fails when the covered CSS uses a raw pixel value for padding, margin, gap or border-radius.

## Tokens

| Token | Value | Use |
|---|---|---|
| `--sp-1` | 4px | Tight: label to value, list bullet offset, gap in a number-and-label pair |
| `--sp-2` | 8px | Small: icon to text, rows in a list, padding of a dense row |
| `--sp-3` | 12px | Gap between sibling cards and tiles, control padding, button stack |
| `--sp-4` | 16px | Standard padding, gap between blocks |
| `--sp-5` | 24px | Roomy padding (card sides), page top |
| `--sp-6` | 32px | Page sides |
| `--sp-7` | 48px | Page bottom |
| `--bw` | 1px | Every box border and divider |
| `--r-xs` / `--r-sm` / `--r` / `--r-pill` | 4 / 8 / 12 / 999px | Small chip / controls and notices / cards and panels / pills |
| `--touch` | 44px | Minimum height of anything pressed |
| `--topbar-h` | 72px | Top bar of the app |

## Rules

- Padding of a card: `var(--sp-4) var(--sp-5)`. Gap between sibling cards or tiles: `--sp-3`. Gap between blocks: `--sp-4`.
- Top bar side padding equals page side padding (`--sp-6`), so the page title lines up with the content.
- Sidebar: 12px padding, 12px link padding, 24px icon box. The folded rail is 72px, so every icon, the logo and the status dot sit at x = 36px in both states.

## Covered and not covered

Covered: the app shell (top bar, page padding, sidebar), the sidebar fold and its tooltip, and the `/domains` chooser (`.dc-*` in `v16.css`).
Not covered yet: everything else in `v16.css` and `app.css` (panels, tables, wizard, taxonomy, dashboard, the pack detail pages, the contents of the top bar such as the search box and user chip). They keep their old values until they are migrated; the test does not look at them. New pages should be written with the tokens from the start.
