# Concierge v1

Opens a signup page in a real browser and fills in whatever form fields it can match from `profile.json`, then pauses so you can review and submit it yourself.

## Run

1. Fill in your real details in `profile.json`.
2. `./start.sh https://example.com/signup`

Each run writes a record of what was filled to `logs/`.

Not yet built: Cerberus credential storage, email verification handling.
