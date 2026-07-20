# DESIGN — Editorial Training Cockpit

## Stance

A focused private study instrument, not a generic SaaS dashboard. The visual language combines an editorial study journal with a technical algorithm trace.

## Themes

### Ink

- Canvas `#0B0C0D`
- Surface `#15181A`
- Text `#F1EEE7`
- Muted `#A4A39D`
- Action blue `#8EC9FF`
- Review amber `#E8B86A`
- Lapse coral `#FF766D`
- Success mint `#78D6A3`

### Paper

- Canvas `#EEEADF`
- Surface `#F8F4EA`
- Text `#1A1B1A`
- Muted `#66655F`
- Action blue `#146CA4`

## Typography

- Display: system editorial serif (`Iowan Old Style`, `Charter`, Georgia fallback)
- UI: system sans
- Algorithm state only: monospace

## Information hierarchy

1. Today's learning obligation
2. Action: begin/resume attempt
3. Review load and previous evidence
4. Queue and review inbox for high-volume maintenance
5. Problem detail for history, lesson, and memory evidence
6. Public profile context

## Components

Use ruled sections and whitespace before boxed cards. One dominant action per view. Monospace labels are small and sparse. Accent color is semantic, never decorative.

Cards are reserved for the focused daily obligation. Collections use compact ruled rows, server-side filters, and 25-row pagination. A visualization belongs inside its matching problem workspace rather than global navigation.

## Motion

- View transitions: 300–450ms, opacity + 12px translation
- Graph events: 450ms stroke/fill transitions
- Timer: continuous conic progress
- No counting animations for metrics
- Honor `prefers-reduced-motion`

## Accessibility

- WCAG AA text contrast
- Semantic hidden hints until explicit reveal
- Focus moved on route changes
- All visualizer steps operable by keyboard
- Color never carries outcome meaning alone
