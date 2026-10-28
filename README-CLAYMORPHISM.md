# Salary Negotiation Agent — Claymorphism responsive update

This update applies a pastel Claymorphism visual theme to the existing application and restores the existing functional dashboard page, including game history, negotiation flow, AI Coach report, and performance panel.

## Files updated
- `frontend/app/globals.css` — Claymorphism palette, soft surfaces, mobile layout safeguards, overflow handling, focus states.
- `frontend/app/page.tsx` — restores the existing interactive page implementation and applies a pastel palette to its Tailwind utility classes.
- `frontend/app/performance-panel.tsx` — adjusts performance metrics panel to match the new theme.
- `frontend/app/layout.tsx` — application title and description.

## Run
1. Copy your existing private root `.env` file back into the project root. It is intentionally not included in this ZIP.
2. Keep your existing `frontend/.env.local` locally if you use it; it is intentionally not included in this ZIP.
3. From the project root, run:
   ```powershell
   docker compose up -d --build
   docker compose ps
   ```
4. Open `http://localhost:3000`.

## Responsive QA
Test at 320×568, 375×812, 768×1024, 1024×768, and 1440×900. Check game history, chat, AI Coach reports, and performance metrics. Tables may scroll inside their own wrapper, but the whole page should not scroll horizontally.

## Notes
- The backend, LangGraph flow, PostgreSQL persistence, Redis cache/rate limiting, and Docker definitions were not modified.
- The sample `clay-dashboard.tsx` remains in the repository but is not used by the main page; the main page uses the existing live application logic.
- A full Docker/browser build was not run in this environment. Validate with your local Docker setup before deployment.
- The private `.env` files were excluded from the output archive. Restore your existing local files before running Compose.
