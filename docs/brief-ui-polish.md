# Synapse: UI polish brief (requirements only)

Audience: the editor agent. This is a product brief, not a ticket list. Turn it into small, checkable Issues
(Goal, Acceptance criteria, Out of scope, Depends on) per `agents/PROTOCOL.md`. The reporter implements,
copydesk reviews against the criteria, factcheck runs the page in a browser. Humans do not write the code.

Baseline: the page that was merged in PR #10 (T4). Every statement below is an outcome to be checked, not an
instruction about how to write the code.

## Need

A first-time visitor, for example a reviewer who opens the public link once, should see a product that looks
finished and trustworthy within a few seconds, can scan the stories quickly, and can use it on a phone. The page
already works; the goal is production-grade look, feel and robustness.

## Requirements

### 1. Identity and hierarchy
- One product name and one tagline, defined in a single place in the code and used consistently in the header,
  page title, footer and RSS feed. (Current choice: **Synapse**, "Every AI story, in one line".)
- Clear visual hierarchy: the newest or top story is visually emphasised; the rest are scannable cards.
- Each story shows, in this order of importance: headline, one-line summary, topic tag, source, age, source link.
- Consistent spacing scale (multiples of 4 or 8 px), a limited type scale, and a readable measure for body text
  (no line longer than about 75 characters).

### 2. Themes and contrast
- Light and dark themes. Default to the visitor's system preference, offer a visible toggle, remember the choice.
- Text contrast meets WCAG AA: 4.5:1 for body text, 3:1 for large text and UI controls, in both themes.
- Colour is never the only carrier of meaning (tags and statuses also have text).

### 3. Responsive layout
- No horizontal scrolling at any width from 320 px to 1920 px, on every page.
- One column on phones, a multi-column grid from tablet width up, fluid headline size.
- Touch targets are at least 44 x 44 px on touch screens.
- Very long headlines, long source names and unbroken strings never overflow or break the layout.

### 4. Motion
- Motion is purposeful and subtle: content eases in on load and on scroll, interactive elements give hover and
  focus feedback, and an optional ambient background (for example a neural-network motif that suits an AI
  newsroom) may run behind the content.
- Feedback animations last 100 to 300 ms; entrance animations no more than about 800 ms.
- No layout shift caused by animation.
- When the visitor has "reduce motion" turned on, all non-essential motion is off and content is fully visible.
- Ambient animation pauses when the tab is hidden and never blocks interaction or hurts text readability.

### 5. Accessibility
- Semantic landmarks (header, main, footer, nav), one `h1` per page, ordered headings.
- Everything works with the keyboard alone; focus is always visible; a "skip to content" link exists.
- Decorative graphics are hidden from assistive technology; controls have accessible names.
- Form fields (search) have labels.

### 6. Consistency across pages
- Every page (home, any run-history page, feed page, error pages) shares the same header, footer, theme and
  typography.
- Unknown URLs show a branded 404 page rather than raw JSON when requested by a browser.
- Empty, pending ("Summary pending") and error states are all designed, not left as defaults.

### 7. Performance and safety
- No third-party JavaScript libraries; at most one external font family pair, with sensible fallbacks.
- First paint does not depend on JavaScript; content is readable if scripts fail.
- All user-supplied text (search terms, headlines, summaries) is escaped; nothing is injected as HTML.

### 8. RSS feed correctness (the channel link is already Issue #12 / PR #13)
- The feed's channel title and description use the product name and tagline, not an old project name.
- The channel link is the site's real public address, with a safe local fallback (Issue #12).
- The feed declares its language and includes a `rel="self"` link to its own address, so feed validators
  report no warnings.
- Every item has a title, absolute link, unique guid, RFC 822 date, description and category, and
  `feedparser` reports no errors for the live feed.
- People who open the feed address in a browser see a readable page in the site's design; feed readers still
  receive XML (content negotiation, with a `?format=xml` escape hatch). Do not rely on XSLT: browsers are
  removing support and already show a warning banner.

## Out of scope
New data sources, backend or schema changes, deployment, authentication, and analytics.

## How a tester proves it (for factcheck)
- Load every page at 320, 375, 768, 1024 and 1440 px in a real browser; assert `scrollWidth <= innerWidth`.
- Toggle dark and light; check contrast with a tool such as axe or Lighthouse; accessibility score 95 or higher.
- Emulate `prefers-reduced-motion: reduce`; confirm nothing animates and all content is visible.
- Tab through the page: every control reachable, focus ring visible, skip link works.
- Search for `<script>alert(1)</script>`; confirm it is displayed as text and not executed.
- Run the existing test suite and lint; add automated checks for the layout and branding requirements.

## Suggested slicing (the editor's call)
1. Design tokens, themes, contrast, and the shared layout.
2. Responsive grid, card design, hierarchy, long-text handling.
3. Motion system, ambient background, reduced-motion support.
4. Accessibility pass and automated layout and accessibility checks.
