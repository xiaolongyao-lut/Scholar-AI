---
applyTo: '**'
description: 'Comprehensive web performance standards based on Core Web Vitals (LCP, INP, CLS), with 50+ anti-patterns, detection regex, framework-specific fixes for modern web frameworks, and modern API guidance.'
---

# Performance Standards

Comprehensive performance rules for web application development. Every anti-pattern includes a severity classification, detection method, Core Web Vitals metric impacted, and corrective code examples.

**Severity levels:**

- **CRITICAL** — Directly degrades a Core Web Vital past the "poor" threshold. Must be fixed before merge.
- **IMPORTANT** — Measurably impacts user experience. Fix in same sprint.
- **SUGGESTION** — Optimization opportunity. Plan for a future iteration.

---

## Core Web Vitals Quick Reference

### LCP (Largest Contentful Paint)

**Good: < 2.5s | Needs Improvement: 2.5-4s | Poor: > 4s**

Measures when the largest visible content element finishes rendering. Four sequential phases:

| Phase | Target | What It Measures |
|-------|--------|-----------------|
| TTFB | ~40% of budget | Server response time |
| Resource Load Delay | < 10% | Time between TTFB and LCP resource fetch start |
| Resource Load Duration | ~40% | Download time for the LCP resource |
| Element Render Delay | < 10% | Time between download and paint |

### INP (Interaction to Next Paint)

**Good: < 200ms | Needs Improvement: 200-500ms | Poor: > 500ms**

Measures latency of all user interactions, reports the worst. Three phases:

| Phase | Optimization |
|-------|-------------|
| Input Delay | Break long tasks, yield to browser |
| Processing Time | Keep handlers < 50ms |
| Presentation Delay | Minimize DOM size, avoid forced layout |

> **Diagnostic tool:** Use the Long Animation Frames (LoAF) API (Chrome 123+) to debug INP issues.

### CLS (Cumulative Layout Shift)

**Good: < 0.1 | Needs Improvement: 0.1-0.25 | Poor: > 0.25**

Layout shift sources: images without dimensions, dynamically injected content, web font FOUT, late-loading ads. Shifts within 500ms of user interaction are exempt.

---

## Loading and LCP Anti-Patterns (L1-L10)

### L1: Render-Blocking CSS Without Critical Extraction

- **Severity**: CRITICAL
- **Detection**: `<link.*rel="stylesheet"` in `<head>` loading large CSS
- **CWV**: LCP

```html
<!-- BAD -->
<link rel="stylesheet" href="/styles/main.css" />

<!-- GOOD — inline critical CSS, preload the rest -->
<style>/* critical above-fold CSS, inlined by a tool like Critters/Beasties */</style>
<link rel="preload" href="/styles/main.css" as="style" />
<link rel="stylesheet" href="/styles/main.css" />
```

### L2: Render-Blocking Synchronous Script

- **Severity**: CRITICAL
- **Detection**: `<script.*src=` without `async|defer|type="module"`
- **CWV**: LCP

```html
<!-- BAD -->
<script src="/vendor/analytics.js"></script>

<!-- GOOD -->
<script src="/vendor/analytics.js" defer></script>
```

### L3: Missing Preconnect to Critical Origins

- **Severity**: IMPORTANT
- **Detection**: Third-party API/CDN URLs without `<link rel="preconnect">`
- **CWV**: LCP

```html
<link rel="preconnect" href="https://api.example.com" />
<link rel="dns-prefetch" href="https://analytics.example.com" />
```

### L4: Missing Preload for LCP Resource

- **Severity**: CRITICAL
- **Detection**: LCP image/font not preloaded
- **CWV**: LCP

```html
<link rel="preload" as="image" href="/hero.webp" fetchpriority="high" />
```

### L5: Client-Side Data Fetching for Main Content

- **Severity**: CRITICAL
- **Detection**: `useEffect.*fetch|useEffect.*axios|ngOnInit.*subscribe`
- **CWV**: LCP

```tsx
// BAD — content appears after JS execution + API call
'use client';
function Page() {
  const [data, setData] = useState(null);
  useEffect(() => { fetch('/api/data').then(r => r.json()).then(setData); }, []);
  return <div>{data?.title}</div>;
}

// GOOD — Server Component fetches data before HTML is sent
async function Page() {
  const data = await fetch('https://api.example.com/data').then(r => r.json());
  return <div>{data.title}</div>;
}
```

### L6: Excessive Redirect Chains

- **Severity**: IMPORTANT
- **Detection**: Multiple sequential redirects (HTTP 301/302 chains)
- **CWV**: LCP

Each redirect adds 200-300ms. Maximum one redirect.

### L7: Missing fetchpriority on LCP Element

- **Severity**: IMPORTANT
- **Detection**: Above-fold hero image without `fetchpriority="high"` or `priority` prop
- **CWV**: LCP

```tsx
// Next.js
<Image src="/hero.webp" alt="Hero" width={1200} height={600} priority />

// Plain HTML
<img src="/hero.webp" alt="Hero" width="1200" height="600" fetchpriority="high" />
```

### L8: Third-Party Scripts in Head Without Async/Defer

- **Severity**: IMPORTANT
- **Detection**: `<script.*src="https://` without `async|defer`
- **CWV**: LCP

Defer non-essential scripts. Use facade pattern for chat widgets.

### L9: Oversized Initial HTML (>14KB)

- **Severity**: SUGGESTION
- **Detection**: Server-rendered HTML larger than 14KB
- **CWV**: LCP

Reduce inline CSS/JS, remove whitespace, use streaming SSR with Suspense boundaries.

### L10: Missing Compression

- **Severity**: IMPORTANT
- **Detection**: Server not returning `content-encoding: br` or `gzip`
- **CWV**: LCP

Enable Brotli (15-25% better than gzip) at CDN/server level.

---

## Rendering and Hydration Anti-Patterns (R1-R8)

### R1: Entire Component Tree Marked "use client"

- **Severity**: CRITICAL
- **Detection**: `"use client"` at top-level layout or page component
- **CWV**: LCP + INP

Push `"use client"` down to leaf components that need interactivity.

### R2: Missing Suspense Boundaries for Async Data

- **Severity**: IMPORTANT
- **Detection**: Server Components doing data fetching without `<Suspense>`
- **CWV**: LCP

```tsx
// GOOD — stream shell immediately, fill in data progressively
async function Page() {
  const user = await getUser();
  return (
    <div>
      <Header user={user} />
      <Suspense fallback={<PostsSkeleton />}>
        <Posts />
      </Suspense>
    </div>
  );
}
```

### R3: Hydration Mismatch from Dynamic Client Content

- **Severity**: IMPORTANT
- **Detection**: `Date.now()|Math.random()|window\.innerWidth` in SSR components
- **CWV**: CLS

Use `useEffect` for client-only values, or `suppressHydrationWarning` for known differences.

### R4: Missing Streaming for Slow Data Sources

- **Severity**: IMPORTANT
- **Detection**: Page awaiting all data before sending HTML
- **CWV**: LCP (TTFB)

Use streaming SSR with Suspense boundaries. Shell streams immediately; slow data fills in progressively.

### R5: Unstable References Causing Re-renders

- **Severity**: IMPORTANT
- **Detection**: `style=\{\{|onClick=\{\(\) =>` inline in JSX
- **CWV**: INP

React 19+ with React Compiler: auto-memoized. Without Compiler: extract or memoize with `useMemo`/`useCallback`.

### R6: Missing Virtualization for Long Lists

- **Severity**: IMPORTANT
- **Detection**: `.map(` rendering >100 items without virtual scrolling
- **CWV**: INP

Use TanStack Virtual, react-window, or vue-virtual-scroller.

### R7: SSR of Immediately-Hidden Content

- **Severity**: SUGGESTION
- **Detection**: Server-rendering `display: none` components
- **CWV**: LCP (TTFB)

Use client-side rendering for modals, drawers, dropdowns. React: `React.lazy`.

### R8: Missing `key` Prop on List Items

- **Severity**: IMPORTANT
- **Detection**: `.map(` without `key=` prop
- **CWV**: INP

```tsx
// GOOD — stable unique key
{items.map(item => <Row key={item.id} data={item} />)}
```

Never use array index as key if list can reorder.

---

## JavaScript Runtime and INP Anti-Patterns (J1-J8)

### J1: Long Synchronous Task in Event Handler

- **Severity**: CRITICAL
- **Detection**: Event handlers with heavy computation (>50ms)
- **CWV**: INP

```typescript
// GOOD — yield to browser
async function handleClick() {
  setLoading(true);
  await (globalThis.scheduler?.yield?.() ?? new Promise(r => setTimeout(r, 0)));
  const result = expensiveComputation(data);
  setResult(result);
}
```

### J2: Layout Thrashing

- **Severity**: CRITICAL
- **Detection**: `offsetHeight|offsetWidth|getBoundingClientRect|clientHeight` in loops
- **CWV**: INP

```typescript
// GOOD — batch reads then batch writes
const heights = elements.map(el => el.offsetHeight);
elements.forEach((el, i) => { el.style.height = `${heights[i] + 10}px`; });
```

### J3: setInterval/setTimeout Without Cleanup

- **Severity**: IMPORTANT
- **Detection**: `setInterval|setTimeout` without cleanup
- **Impact**: Memory

```tsx
useEffect(() => {
  const id = setInterval(() => fetchData(), 5000);
  return () => clearInterval(id);
}, []);
```

### J4: addEventListener Without removeEventListener

- **Severity**: IMPORTANT
- **Detection**: `addEventListener` without cleanup
- **Impact**: Memory

```tsx
useEffect(() => {
  const controller = new AbortController();
  window.addEventListener('resize', handleResize, { signal: controller.signal });
  return () => controller.abort();
}, []);
```

### J5: Detached DOM Node References

- **Severity**: SUGGESTION
- **Detection**: Variables holding references to removed DOM elements
- **Impact**: Memory

Set references to `null` when elements are removed.

### J6: Synchronous XHR

- **Severity**: CRITICAL
- **Detection**: `XMLHttpRequest` with synchronous flag
- **CWV**: INP

Use `fetch()` (always async).

### J7: Heavy Computation on Main Thread

- **Severity**: IMPORTANT
- **Detection**: CPU-intensive operations in component code
- **CWV**: INP

Move to Web Worker or break into chunks with `scheduler.yield()`.

### J8: Missing Effect Cleanup

- **Severity**: IMPORTANT
- **Detection**: `useEffect` without return cleanup; `subscribe` without unsubscribe
- **Impact**: Memory

React: return cleanup from `useEffect`.

---

## CSS Performance Anti-Patterns (C1-C7)

### C1: Animation Using Layout-Triggering Properties

- **Severity**: CRITICAL
- **Detection**: `animation:|transition:` with `top|left|width|height|margin|padding`
- **CWV**: INP

```css
/* BAD — main thread, <60fps */
.card { transition: width 0.3s, height 0.3s; }

/* GOOD — GPU compositor, 60fps */
.card { transition: transform 0.3s, opacity 0.3s; }
.card:hover { transform: scale(1.05); }
```

### C2: Missing content-visibility for Off-Screen Sections

- **Severity**: SUGGESTION
- **Detection**: Long pages without `content-visibility: auto`
- **CWV**: INP

```css
.below-fold-section {
  content-visibility: auto;
  contain-intrinsic-size: auto 500px;
}
```

### C3: will-change Applied Permanently

- **Severity**: SUGGESTION
- **Detection**: `will-change:` in base CSS (not `:hover|:focus`)
- **Impact**: Memory

Apply on interaction only or let browser optimize automatically.

### C4: Large Unused CSS

- **Severity**: IMPORTANT
- **Detection**: CSS where >50% of rules are unused
- **CWV**: LCP

Use PurgeCSS, Tailwind purge, or critters. Code-split CSS per route.

### C5: Universal Selector in Hot Paths

- **Severity**: SUGGESTION
- **Detection**: `\* \{` in CSS
- **CWV**: INP

```css
/* GOOD — zero-specificity reset */
:where(*, *::before, *::after) { box-sizing: border-box; }
```

### C6: Missing CSS Containment

- **Severity**: SUGGESTION
- **Detection**: Complex components without `contain` property
- **CWV**: INP

```css
.sidebar { contain: layout style paint; }
```

### C7: Route Transitions Without View Transitions API

- **Severity**: SUGGESTION
- **Detection**: SPA route changes without View Transitions API
- **CWV**: CLS (perceived)

```javascript
if (document.startViewTransition) {
  document.startViewTransition(() => { /* update DOM / navigate */ });
} else {
  // fallback: update DOM directly
}
```

---

## Images, Media and Fonts Anti-Patterns (I1-I8)

### I1: Images Without Dimensions

- **Severity**: CRITICAL
- **Detection**: `<img` without `width=` and `height=`
- **CWV**: CLS

Always set `width` and `height` on images, or use `aspect-ratio` in CSS.

### I2: Lazy Loading Above-Fold Images

- **Severity**: CRITICAL
- **Detection**: `loading="lazy"` on hero/banner images
- **CWV**: LCP

```html
<!-- GOOD — eager load with high priority -->
<img src="/hero.webp" alt="Hero" fetchpriority="high" />
```

### I3: Legacy Format Only (JPEG/PNG)

- **Severity**: IMPORTANT
- **Detection**: Images without WebP/AVIF alternatives
- **CWV**: LCP

```html
<picture>
  <source srcset="/hero.avif" type="image/avif" />
  <source srcset="/hero.webp" type="image/webp" />
  <img src="/hero.jpg" alt="Hero" width="1200" height="600" />
</picture>
```

### I4: Missing Responsive srcset/sizes

- **Severity**: IMPORTANT
- **Detection**: `<img` without `srcset`
- **CWV**: LCP

```html
<img src="/hero-800.jpg" alt="Hero"
     srcset="/hero-400.jpg 400w, /hero-800.jpg 800w, /hero-1200.jpg 1200w"
     sizes="(max-width: 600px) 400px, (max-width: 1024px) 800px, 1200px" />
```

### I5: Font Without font-display

- **Severity**: IMPORTANT
- **Detection**: `@font-face` without `font-display`
- **CWV**: CLS

```css
@font-face {
  font-family: 'CustomFont';
  src: url('/fonts/custom.woff2') format('woff2');
  font-display: swap; /* or "optional" for best CLS */
}
```

### I6: Critical Font Not Preloaded

- **Severity**: IMPORTANT
- **Detection**: Custom font without `<link rel="preload">`
- **CWV**: LCP + CLS

```html
<link rel="preload" href="/fonts/main.woff2" as="font" type="font/woff2" crossorigin />
```

### I7: Full Font Loaded When Subset Suffices

- **Severity**: SUGGESTION
- **Detection**: Font files > 50KB WOFF2
- **CWV**: LCP

Use `unicode-range`, subset with glyphhanger, or `next/font`.

### I8: Unoptimized SVGs

- **Severity**: SUGGESTION
- **Detection**: SVGs with editor metadata
- **CWV**: LCP (minor)

```bash
npx svgo input.svg -o output.svg
```

---

## Bundle and Tree Shaking Anti-Patterns (B1-B6)

### B1: Barrel File Importing Entire Module

- **Severity**: IMPORTANT
- **Detection**: `from '\.\/(?:.*\/index|components)'`
- **CWV**: INP

```typescript
// BAD
import { Button } from './components';

// GOOD — direct import
import { Button } from './components/Button';
```

### B2: CommonJS require() Preventing Tree Shaking

- **Severity**: IMPORTANT
- **Detection**: `require(` in frontend code
- **CWV**: INP

Use ESM `import/export`. Replace `require` with `import`.

### B3: Large Dependency for Small Utility

- **Severity**: IMPORTANT
- **Detection**: `from "moment"|from "lodash"` (full imports)
- **CWV**: INP

```typescript
// GOOD — tree-shakeable alternatives
import { format } from 'date-fns';
import { pick } from 'lodash-es';

// BEST — native JS
const formatted = new Intl.DateTimeFormat('en').format(date);
```

### B4: Missing Dynamic Import for Route Splitting

- **Severity**: CRITICAL
- **Detection**: All route components imported statically
- **CWV**: INP

```tsx
// React:
const Page = React.lazy(() => import('./pages/Page'));
```

### B5: Missing sideEffects in package.json

- **Severity**: SUGGESTION
- **Detection**: Library package.json without `"sideEffects"` field
- **CWV**: INP

```json
{ "sideEffects": false }
```

### B6: Duplicate Dependencies

- **Severity**: SUGGESTION
- **Detection**: Same library at multiple versions
- **CWV**: INP

```bash
npm dedupe
```

---

## Framework-Specific: React (RX1-RX4)

### RX1: Missing React Compiler Adoption

- **Severity**: SUGGESTION
- **Detection**: Manual `useMemo|useCallback` in React 19+ project
- **CWV**: INP

Enable React Compiler (v19+) for auto-memoization. Remove manual wrappers.

### RX2: Missing useTransition for Expensive Updates

- **Severity**: IMPORTANT
- **Detection**: State updates causing expensive re-renders without `useTransition`
- **CWV**: INP

```tsx
const [isPending, startTransition] = useTransition();
function handleFilter(value) {
  startTransition(() => setFilter(value));
}
```

### RX3: Missing useDeferredValue for Expensive Rendering

- **Severity**: IMPORTANT
- **Detection**: Expensive rendering from rapidly-changing input
- **CWV**: INP

```tsx
const deferredQuery = useDeferredValue(query);
const results = expensiveFilter(items, deferredQuery);
```

### RX4: Missing React.lazy for Route Splitting

- **Severity**: IMPORTANT
- **Detection**: Route components imported statically
- **CWV**: INP

```tsx
const Settings = React.lazy(() => import('./pages/Settings'));
```

---

## Resource Hints Quick Reference

| Hint | Purpose | When to Use |
|------|---------|-------------|
| `preconnect` | DNS + TCP + TLS early | Critical third-party origins (API, CDN, fonts) |
| `preload` | Fetch immediately, high priority | LCP image, critical font |
| `prefetch` | Low priority for future navigation | Next-page assets |
| `dns-prefetch` | DNS resolution only | Non-critical third-party origins |
| `modulepreload` | Preload + parse ES module | Critical JS modules |

---

## Image Optimization Quick Reference

| Aspect | Recommendation |
|--------|---------------|
| Format | WebP (25-34% smaller), AVIF (50% smaller) |
| LCP image | `fetchpriority="high"` or framework `priority` prop |
| Below-fold | `loading="lazy"` |
| Dimensions | Always set `width` + `height` |
| Responsive | `srcset` + `sizes` or framework Image component |
| Compression | Quality 75-85 for photos |

---

## Font Loading Quick Reference

| Strategy | Best For | CLS Impact |
|----------|---------|-----------|
| `font-display: swap` | Body text | Slight FOUT, minimal CLS |
| `font-display: optional` | All fonts (best CLS) | No FOUT, no CLS |
| `next/font` | Next.js projects | Zero CLS |
| Variable fonts | Multiple weights | Single file for all weights |

Rules: preload 1-2 critical fonts only, use WOFF2, subset to needed characters, self-host when possible.

---

## Performance Checklist (CWV)

### LCP (< 2.5s)
- [ ] LCP image has `fetchpriority="high"` or `priority` prop
- [ ] LCP image preloaded if not in HTML source
- [ ] No `loading="lazy"` on above-fold images
- [ ] Critical CSS inlined or extracted
- [ ] No render-blocking scripts (use `defer` or `async`)
- [ ] Preconnect to critical third-party origins
- [ ] Main content server-rendered (not client-side fetched)
- [ ] Images in modern format (WebP/AVIF) with responsive `srcset`
- [ ] Compression enabled (Brotli preferred)
- [ ] Fonts preloaded with `font-display: swap` or `optional`

### INP (< 200ms)
- [ ] Event handlers complete in < 50ms
- [ ] Long tasks broken into smaller chunks
- [ ] Route-based code splitting implemented
- [ ] Heavy computation moved to Web Workers
- [ ] Lists with > 100 items virtualized
- [ ] No barrel file imports (direct component imports)
- [ ] ESM imports used (not CommonJS `require`)
- [ ] `"use client"` only on components that need interactivity
- [ ] Layout-triggering CSS properties not animated
- [ ] Effect cleanup implemented (no leaking listeners/timers)

### CLS (< 0.1)
- [ ] All images have `width` and `height` attributes
- [ ] Fonts use `font-display: swap` or `optional`
- [ ] No content injected above existing content dynamically
- [ ] Ads/embeds have reserved space
- [ ] No hydration mismatches
- [ ] `content-visibility: auto` has `contain-intrinsic-size`
