# Spike 1: user agent over CDP

- Result: **PASS**
- Run at: 2026-11-22T20:34:18+00:00
- Required token: `Agent/ghostshopper`
- Echo endpoint: `https://httpbin.org/headers`
- Profile: `none`

| Page | navigator.userAgent | user-agent header | OK |
|---|---|---|---|
| first page | `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 Agent/ghostshopper` | `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 Agent/ghostshopper` | yes |
| popup | `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 Agent/ghostshopper` | `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 Agent/ghostshopper` | yes |
| new tab | `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 Agent/ghostshopper` | `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 Agent/ghostshopper` | yes |
