# TACTUSBALL frontend

## Run locally

```powershell
Copy-Item .env.example .env.local
npm install
npm run dev
```

The Vite server runs at `http://localhost:3000`, matching the backend's local CORS example. Set `VITE_API_BASE_URL` in `.env.local` when the API runs elsewhere. Start the FastAPI app separately from `nexus-backend/`.

## Current backend connections

- `GET /api/v1/health` — public connection status.
- `POST /api/v1/auth/login`, `GET /api/v1/auth/me` — sign-in and server-verified session.
- `GET /api/v1/matches` — authenticated match list.
- `POST /api/v1/matches/{match_id}/videos` — authenticated video ingestion for authorized match managers.
- `GET /api/v1/memory` — governed memory list.
- `GET /api/v1/memory/decisions/replay` — decision replay records.
- `POST /api/v1/ai/copilot/query` — governed Copilot question and evidence citations.

Match video is ingested, but vision processing needs a real pitch calibration and configured detector. Tactical models remain untrained; the landing page pitch is explicitly illustrative. Counterfactual simulation and dedicated tactical-workspace interactions are not wired into this first frontend slice. The Copilot reports backend provider/configuration failures directly instead of inventing a response.

The public site uses the custom scalable crest in `public/tactusball-mark.svg`. The opening includes an animated SVG footballer, CSS ball flight and goal impact, a skip action, reduced-motion handling, and a ball path linked to reversible page scrolling. The public Copilot launcher opens the authenticated backend flow.

The intelligence-system section has six generated editorial visuals in `public/images/`. Hover or keyboard-focus a capability to update the image and explanation; on touch layouts, selecting a row brings its preview into view. The homepage and first-touch scene use the generated `hero-match.jpg` instead of the previous remote stadium photo.
