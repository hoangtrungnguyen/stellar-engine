# QA Checklist — CLI Commands

## Functional
- [ ] Command executes without error on valid input
- [ ] Command returns non-zero exit code on invalid input
- [ ] Help text is accurate and complete (`--help`)
- [ ] All documented flags work as described
- [ ] Output format matches spec (JSON, table, plain)
- [ ] Pipe-safe: output parseable by jq/grep when `--json` passed

## Error Handling
- [ ] Meaningful error messages on bad input (written to stderr, not stdout)
- [ ] No stack traces leaked to user on expected errors
- [ ] Graceful handling of missing dependencies or unavailable services

## Regression
- [ ] No existing tests broken
- [ ] Edge cases from bug history covered (check issue history)

## UX
- [ ] Output is human-readable in terminal
- [ ] Colors/formatting degrade gracefully without TTY (`NO_COLOR`, `--no-color`)
- [ ] Performance: completes within 10s on typical input
- [ ] Progress indicator for long-running operations
