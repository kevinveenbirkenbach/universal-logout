# E2E Cookie Clearing Tests

This test suite validates cookie deletion strategies across HTTP and HTTPS:

- Clear-Site-Data only
- Set-Cookie deletion (host-only + domain + multiple paths)
- Combined strategy

## Run

From repo root:

```bash
make test-e2e
```

The stack runs the service image `universal-logout:e2e`; `make test-e2e` builds it first.

The `runner` container executes Playwright tests and exits with a non-zero code on failure.

## Notes

* HTTPS uses a self-signed wildcard certificate for `*.test.local`.
* Playwright is configured to ignore HTTPS errors.
* `Clear-Site-Data` is not reliable on HTTP in browsers; HTTPS is the contract.
