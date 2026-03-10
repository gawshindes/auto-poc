# UI Design System — Apply to Every Demo

Every demo must follow this design system without exception. Consistent demos = professional agency.

---

## Core Philosophy

- **Always light theme.** Page background is always `#faf9f5`. Never dark backgrounds.
- **Warm neutrals, not cold grays.** Anthropic-inspired palette — organic, not sterile.
- **One accent color:** orange `#d97757` for buttons, active states, and key highlights.
- **No box shadows.** Use `1px solid #e8e6dc` borders instead.
- **Generous whitespace.** 24px card padding. Breathing room between all elements.
- **Max content width:** 1100px, centered, with 40px 24px page padding.

---

## Color Palette

```
Page background:   #faf9f5
Card / surface:    #ffffff
Subtle surface:    #f0efe9   (hover states, secondary panels)
Border:            #e8e6dc
Border strong:     #d4d2c9

Text primary:      #141413   (headings, important content)
Text body:         #4a4845   (paragraphs, table cells)
Text muted:        #b0aea5   (captions, labels, placeholders)

Orange (primary):  #d97757   ← CTA buttons, active states, highlights
Orange light:      #f5e6df   ← orange badge background, hover fill
Orange dark:       #b85e3a   ← orange button hover state

Blue (info):       #6a9bcc   ← links, info badges
Blue light:        #e3eef7   ← info badge background

Green (success):   #788c5d
Green light:       #e8eddf

Warning:           #c4973a   bg: #fdf3dd
Error:             #c0463a   bg: #fce8e7
```

---

## Typography

Always load from Google Fonts — include this in every HTML `<head>`:
```html
<link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&family=Open+Sans:ital,wght@0,400;0,600;1,400&display=swap" rel="stylesheet">
```

| Element | Font | Size | Weight | Color |
|---------|------|------|--------|-------|
| Page title | Roboto | 28–32px | 700 | `#141413` |
| Section heading | Roboto | 20–24px | 600 | `#141413` |
| Card title | Roboto | 15–17px | 600 | `#141413` |
| Section label | Roboto | 11px | 600 | `#b0aea5` UPPERCASE |
| Body / description | Open Sans | 15px | 400 | `#4a4845` |
| Table header | Roboto | 11px | 600 | `#b0aea5` UPPERCASE |
| Table cell | Open Sans | 14px | 400 | `#4a4845` |
| Button | Roboto | 14px | 600 | — |
| IDs / codes / prices | monospace | 13px | 400 | `#141413` |

Rules:
- **Roboto** → all UI chrome: nav, buttons, labels, headings
- **Open Sans** → all content: body text, descriptions, table cells
- **Uppercase + letter-spacing** → only on 11px section labels
- IDs, prices, timestamps, codes → always monospace

---

## Base CSS — Paste at the top of every HTML demo

```css
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&family=Open+Sans:ital,wght@0,400;0,600;1,400&display=swap');

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: 'Open Sans', sans-serif;
  background: #faf9f5;
  color: #4a4845;
  min-height: 100vh;
}

h1, h2, h3, h4, h5, button, label, .label, nav, .badge, th {
  font-family: 'Roboto', sans-serif;
}

.container {
  max-width: 1100px;
  margin: 0 auto;
  padding: 40px 24px;
}
```

---

## Component Patterns

### Cards
```css
.card {
  background: #ffffff;
  border: 1px solid #e8e6dc;
  border-radius: 12px;
  padding: 24px;
}
.card-subtle {
  background: #f0efe9;
  border-radius: 12px;
  padding: 24px;
}
```

### Buttons
```css
/* Primary — orange CTA */
.btn-primary {
  background: #d97757;
  color: #ffffff;
  border: none;
  border-radius: 8px;
  padding: 10px 22px;
  font-family: 'Roboto', sans-serif;
  font-weight: 600;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-primary:hover { background: #b85e3a; }
.btn-primary:disabled { opacity: 0.45; cursor: not-allowed; }

/* Secondary */
.btn-secondary {
  background: #f0efe9;
  color: #141413;
  border: 1px solid #e8e6dc;
  border-radius: 8px;
  padding: 10px 22px;
  font-family: 'Roboto', sans-serif;
  font-weight: 600;
  font-size: 14px;
  cursor: pointer;
}
.btn-secondary:hover { background: #e8e6dc; }
```

### Inputs, Selects, Textareas
```css
input, select, textarea {
  background: #ffffff;
  border: 1px solid #e8e6dc;
  border-radius: 8px;
  padding: 10px 14px;
  font-family: 'Open Sans', sans-serif;
  font-size: 14px;
  color: #141413;
  width: 100%;
  outline: none;
}
input:focus, select:focus, textarea:focus {
  border-color: #d97757;
}
::placeholder { color: #b0aea5; }
```

### Form Labels (above inputs)
```css
.field-label {
  display: block;
  font-family: 'Roboto', sans-serif;
  font-size: 11px;
  font-weight: 600;
  color: #b0aea5;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 7px;
}
```

### Section Labels (above a card or block)
```css
.section-label {
  font-family: 'Roboto', sans-serif;
  font-size: 11px;
  font-weight: 600;
  color: #b0aea5;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-bottom: 14px;
}
```

### Status Badges
```css
.badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 20px;
  font-family: 'Roboto', sans-serif;
  font-weight: 600;
  font-size: 12px;
}
.badge-green  { color: #788c5d; background: #e8eddf; }
.badge-orange { color: #d97757; background: #f5e6df; }
.badge-blue   { color: #6a9bcc; background: #e3eef7; }
.badge-yellow { color: #c4973a; background: #fdf3dd; }
.badge-red    { color: #c0463a; background: #fce8e7; }
.badge-gray   { color: #b0aea5; background: #f0efe9; }
```

### Tables
```css
.table-wrapper {
  background: #ffffff;
  border: 1px solid #e8e6dc;
  border-radius: 12px;
  overflow: hidden;
}
table { width: 100%; border-collapse: collapse; }
th {
  font-family: 'Roboto', sans-serif;
  font-size: 11px;
  font-weight: 600;
  color: #b0aea5;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 10px 16px;
  text-align: left;
  border-bottom: 1px solid #e8e6dc;
  background: #faf9f5;
}
td {
  padding: 13px 16px;
  font-size: 14px;
  font-family: 'Open Sans', sans-serif;
  border-bottom: 1px solid #f0efe9;
  color: #4a4845;
}
tr:last-child td { border-bottom: none; }
```

### Divider
```css
hr { border: none; border-top: 1px solid #e8e6dc; margin: 24px 0; }
```

### AI Loading State
```html
<div class="loading-state">
  <div style="font-size:32px; margin-bottom:12px;">⏳</div>
  Processing with AI...
</div>
```
```css
.loading-state {
  text-align: center;
  color: #d97757;
  padding: 48px;
  font-family: 'Open Sans', sans-serif;
  font-size: 15px;
}
```

### Empty State
```html
<div class="empty-state">No results yet. Fill in the form above to get started.</div>
```
```css
.empty-state {
  text-align: center;
  color: #b0aea5;
  padding: 48px;
  font-family: 'Open Sans', sans-serif;
  font-size: 14px;
}
```

### Alert / Info Row
```css
.alert {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 8px;
  font-family: 'Open Sans', sans-serif;
  font-size: 14px;
}
.alert-info    { background: #e3eef7; border: 1px solid #b8d4eb; color: #4a6a8a; }
.alert-success { background: #e8eddf; border: 1px solid #b8ccaa; color: #4a6a3a; }
.alert-warning { background: #fdf3dd; border: 1px solid #f0dba0; color: #7a5a1a; }
.alert-error   { background: #fce8e7; border: 1px solid #e0b0ae; color: #7a2a2a; }
```

---

## Layout Patterns

### Standard app shell
```html
<body>
  <header class="app-header"><!-- logo, nav --></header>
  <main class="container">
    <!-- page content -->
  </main>
</body>
```
```css
.app-header {
  background: #ffffff;
  border-bottom: 1px solid #e8e6dc;
  padding: 0 24px;
  height: 56px;
  display: flex;
  align-items: center;
  font-family: 'Roboto', sans-serif;
  font-weight: 700;
  color: #141413;
}
```

### Two-column layout
```css
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.three-col { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
```

### Metric / KPI cards row
```html
<div class="metrics-row">
  <div class="card">
    <div class="section-label">Total Processed</div>
    <div style="font-size:32px; font-family:'Roboto',sans-serif; font-weight:700; color:#141413;">142</div>
    <div style="font-size:13px; color:#b0aea5; margin-top:4px;">last 30 days</div>
  </div>
  <!-- repeat -->
</div>
```
```css
.metrics-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }
```

---

## Hard Rules — Never Break These

| Never do | Do instead |
|----------|------------|
| Dark backgrounds (`#1a1a2e`, `#0d0d0d`, etc.) | Use `#faf9f5` always |
| `box-shadow` anywhere | Use `1px solid #e8e6dc` borders |
| Cool gray palette (`#6b7280`, etc.) | Warm neutrals from the palette above |
| Multiple accent colors | Orange `#d97757` only |
| Bootstrap CDN or Tailwind CDN | Write CSS directly using this system |
| Poppins, Lora, DM Sans, or other fonts | Roboto + Open Sans only |
| Lorem Ipsum placeholder text | Customer's real company name and industry vocabulary |
| Inline style soup without structure | Use the CSS classes defined above |
