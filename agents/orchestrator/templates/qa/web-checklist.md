# QA Checklist — Web UI/UX

## Functional
- [ ] Core user flow completes without errors
- [ ] Form validation shows field-level error messages
- [ ] Loading states shown for async operations
- [ ] Success/error feedback visible to user (toast, banner, etc.)
- [ ] Empty states handled gracefully (not blank page)

## Accessibility
- [ ] Keyboard navigation works (Tab, Enter, Escape, arrow keys)
- [ ] `aria-label` / `aria-describedby` present on interactive elements
- [ ] Color contrast meets WCAG AA (4.5:1 text, 3:1 large text/UI)
- [ ] Focus visible on interactive elements

## Responsive
- [ ] Layout correct at 375px (mobile), 768px (tablet), 1280px (desktop)
- [ ] No horizontal scroll on mobile

## Regression
- [ ] No existing E2E or integration tests broken
- [ ] No console errors on happy path

## Performance
- [ ] LCP < 2.5s on simulated 4G load
- [ ] No visible layout shift (CLS < 0.1)
- [ ] No memory leak (no unbounded listener accumulation)
