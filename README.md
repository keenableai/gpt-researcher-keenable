# gpt-researcher-keenable

[Keenable](https://keenable.ai) web search as a
[GPT Researcher](https://github.com/assafelovic/gpt-researcher) retriever plugin.
It works without an API key.

```bash
pip install gpt-researcher-keenable
export RETRIEVER=keenable
```

That's the whole setup. GPT Researcher (0.16.1 or later) finds the plugin via the
`gpt_researcher.retrievers` entry point, so nothing in GPT Researcher changes. It
combines with built-in retrievers like any other name, e.g.
`RETRIEVER=keenable,arxiv`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `KEENABLE_API_KEY` | unset | Optional. Without it the public endpoint is used; a key from the [Keenable console](https://keenable.ai/console) lifts the rate limits. |
| `KEENABLE_API_URL` | `https://api.keenable.ai` | Override for a proxy or self-hosted gateway. Must be `https://` (plain `http://` only for localhost). |

## Behaviour

- Results come back as `{"title", "href", "body"}` with `requires_scraping = True`:
  `body` is a single-line preview capped at 500 characters, and GPT Researcher
  scrapes each page for its content, the same as with the built-in web retrievers.
- `max_results` from GPT Researcher (`MAX_SEARCH_RESULTS_PER_QUERY`) is passed to
  the API, clamped to its 1-50 range.
- With `query_domains`, the search is restricted to the first domain.
- Any network, HTTP or parsing failure, and an invalid `KEENABLE_API_URL`, is
  logged and yields `[]`, so one provider cannot abort a research run.

## Development

```bash
uv sync
uv run pytest
KEENABLE_LIVE_TESTS=1 uv run pytest -k live   # hits the keyless endpoint
```

## License

MIT
