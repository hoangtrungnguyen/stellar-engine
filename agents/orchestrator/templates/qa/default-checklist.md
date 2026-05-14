# QA Checklist — General

## Functional
- [ ] Feature works as described in the issue/acceptance criteria
- [ ] Edge cases handled (empty input, large input, special characters, boundary values)
- [ ] No unhandled exceptions on error paths

## Regression
- [ ] Existing tests pass (unit, integration, E2E as applicable)
- [ ] No unintended side effects on adjacent features

## Security
- [ ] No secrets or credentials in code, logs, or error messages
- [ ] Input validated/sanitized before use
- [ ] No new attack surface introduced (auth checks, rate limits, CORS)

## Documentation
- [ ] Code comments accurate where logic is non-obvious
- [ ] README or user-facing docs updated if behaviour changed
- [ ] API schema / types updated if interface changed

## Review
- [ ] Implementation matches the spec in the issue
- [ ] Complexity appropriate for the problem (no over-engineering)
- [ ] No dead code or debug artifacts left behind
