# Verification and automatic voice enforcement

New human members receive role `1572082428678373436`. Successful Bloxlink account checks remove that role and grant Community Member (`1572082425528459365`). Staff can post/update the Components V2 panel with `.verify`. A member with Manage Server can run `.verify lock` in the onboarding channel after linking their own account; this gates currently public community channels while preserving staff, bot, onboarding, and assistance access. Newly created channels need appropriate verified-role permissions too.

Automatic voice enforcement starts with the bot. It requires `BLOXLINK_API_KEY`, `ERLC_SERVER_KEY`, Discord voice-state intents, access to the command receipt channel, and access to jail-log channel `1572425299818450954`.

- Any voice channel in this Discord server counts, including muted/deafened members.
- Only an unambiguous Bloxlink guild mapping, confirmed by a forward account lookup, can be punished. Unknown/unlinked accounts are skipped.
- After 60 seconds continuously observed in game without VC, the bot sends `:jail` for the player's full username. Ambiguous username prefixes are skipped.
- It schedules `:unjail` 300 seconds after the successful jail request. The next 10-second poll performs the release. API rate limits, outages, a player being offline, or unavailable Discord state can delay release; offline players are released when observed back in game.
- Private Discord receipts retain pending actions and release times across Render restarts. Do not delete the receipts channel. Confirmed actions are logged in the jail channel; uncertain network results are not retried as new jail requests.
- One jail per continuous VC absence. A member joining voice or leaving the game after release rearms the check with a fresh grace period.
- Later manual jail/unjail commands targeting the same player cancel automatic release so staff can take over.
- ERLC activity logs remain limited to events exposed by its API.

Validation scripts (with the repository root on PYTHONPATH): `python tests/test_voice_guard.py` and `python tests/test_verification.py`. They use mocked game/Discord calls and do not jail live players.
