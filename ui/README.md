# Factory Control UI frontend

Static browser assets for the local Factory Control UI.

- `index.html` — four-view shell and Web Awesome markup
- `app.js` — Alpine CSP data/store, API adapter and adaptive polling
- `factory.css` — minimal layout/Kanban-specific CSS
- `vendor.lock.json` — exact browser dependency versions and extraction policy

Generated vendor assets live in `.tools/ui/vendor/` and are managed by `scripts/vendor_ui.py`; they are intentionally not committed.

See `docs/FACTORY_UI.md` for the architecture and operational contract.
