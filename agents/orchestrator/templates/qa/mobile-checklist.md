# QA Checklist — Mobile App

## Functional
- [ ] Core flow works on iOS Safari and Android Chrome (web renderer)
- [ ] Touch targets >= 44×44px
- [ ] Offline mode degrades gracefully (no crash, clear message)
- [ ] Back button behavior correct (Android hardware back)

## Visual
- [ ] Matches design spec (colors, typography, spacing tokens)
- [ ] No layout overflow on small screens (375px width)
- [ ] Dark mode renders correctly (if supported)
- [ ] Safe area insets respected (iOS notch, Android status bar)

## Performance
- [ ] App loads in < 3s on simulated 3G
- [ ] Smooth scroll and animation (no visible jank)
- [ ] No excessive re-renders on scroll

## Regression
- [ ] No existing widget or integration tests broken
- [ ] Build succeeds: `flutter build web --web-renderer html`
- [ ] No deprecation warnings in build output

## Platform
- [ ] Gestures work correctly (swipe, pinch, long-press as applicable)
- [ ] Keyboard avoidance: input fields visible when soft keyboard open
