# Contributing

Use a branch or fork for your own development. User installations never publish automatically. The author-only Windows watcher must be explicitly enabled and is separate from startup updates.

Keep runtime projects, media, models, secrets and service credentials outside this source tree. Add tests for updater/publication behavior; run child Skill suites in separate Python processes because their legacy modules share names. Document each capability as implemented, Agent-assisted, dependency-required or planned. Do not claim V2 UI integration based on a standalone child CLI test.
