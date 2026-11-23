# e2e/ — Playwright smoke tests

The specs land with the map and the React UI (Turn 3). Playwright is installed
and `playwright.config.ts` is wired to `vite preview`, so `make frontend-e2e`
needs no further setup once a spec exists here.

Nothing is asserted yet on purpose: a smoke test of the Milestone 1 placeholder
page would prove the placeholder renders, not that the app works.