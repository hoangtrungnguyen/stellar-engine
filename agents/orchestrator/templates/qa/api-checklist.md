# QA Checklist — REST API

## Functional
- [ ] Endpoint returns 200/201/204 on valid request
- [ ] Response body matches documented schema (field names, types, required fields)
- [ ] Pagination works (next cursor, limit respected)
- [ ] Filtering/sorting parameters work as documented

## Auth & Permissions
- [ ] 401 on missing or invalid token
- [ ] 403 on insufficient permissions (not 404 to avoid leaking resource existence)
- [ ] No data leaked in error responses (no stack traces, no internal details)

## Error Handling
- [ ] 400 on malformed request body (with field-level detail)
- [ ] 404 on missing resource (not 500)
- [ ] 422 on validation errors with clear field-level messages
- [ ] 429 on rate limit with `Retry-After` header set

## Regression
- [ ] Existing integration tests pass
- [ ] No breaking change to response schema (no removed fields)

## Performance
- [ ] p95 response time < 500ms under normal load
- [ ] No N+1 queries: single request does not trigger unbounded DB queries
