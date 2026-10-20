# TACTUSBALL — Product & Design Brief

## Product Purpose
TACTUSBALL is a football intelligence operating system that helps football clubs turn match evidence into better football decisions. It is NOT a news site, generic sports dashboard, or AI landing template.

## Core Product Areas & User Needs

| Area | Who Uses It | Decision They Make | Evidence Needed | Main Interaction | Emphasize | Real API Data | Required States |
|------|-------------|-------------------|-----------------|-----------------|-----------|---------------|-----------------|
| Match Library | Club staff, analysts | Which match to review | Match records, scores, status | Browse list, select match | Match identity, results, context | `/matches`, status, home/away, scores | Loading, empty, error |
| Video Ingestion | Match managers | Upload footage for analysis | Match authorization, video file | Select match, pick file, upload | Upload progress, processing status | `/matches/:id/videos` | Busy, success, error |
| Player Intelligence | Coaches, scouts | Assess player role & performance | Player records, positions, status | Select player, view detail | Identity, position, roster record | `/players`, `/teams` | Loading, empty, no selection |
| Tactical Intelligence | Analysts | Trace patterns in play phases | Recorded match events | Select match, view events | Event timeline, illustrative nature | `/matches/:id/events` | Loading, empty, idle |
| Counterfactual Lab | Coaches, analysts | Compare hypothetical vs baseline | Match ID, formations, player IDs | Choose match, formations, players, run | Baseline vs alternative, assumptions, limitations | `/counterfactual/simulate`, `/counterfactual/evaluate` | Loading, result, failure, unavailable |
| Club Memory | Club staff | Browse governed organizational knowledge | Memories with provenance, confidence | Filter, browse memory items | Provenance, timestamps, confidence, sensitivity | `/memory` | Loading, empty, filtered |
| Decision Replay | Club staff | Reconstruct decision-time context | Replays with AI rec + human decision | Browse replays, open detail | Timeline, evidence, decision vs recommendation | `/memory/decisions/replay` | Loading, empty, detail |
| AI Copilot (Muse) | Club staff | Get grounded answers to questions | Club memory, match evidence | Ask question, view answer + citations | Citations, grounding, warnings, honest unconfigured | `/ai/copilot/query` | Loading, unconfigured, session, failed, answer |
| Authentication | All users | Sign in / register | Email, password | Login modal, register toggle | Secure access, honest identity | `/auth/login`, `/auth/register`, `/auth/me` | Error, busy, success |

## Backend Constraints (Must Not Violate)
- Some CV, model calibration, and AI-provider capabilities are unconfigured or untrained
- Never present untrained model output as validated intelligence
- Never fabricate metrics, testimonials, or successful AI responses
- Copilot unconfigured state must remain honest (503 expected until provider configured)
- Preserve RBAC, authentication, and real API contracts
- No changes to backend schemas, migrations, or database contents

## Design Principles
- Graphite/obsidian foundations with disciplined electric-lime accents
- Cinematic football photography + pitch geometry visual language
- Oversized, controlled editorial typography (Barlow Condensed display, DM Sans body)
- Precise transitions, physical-feeling interactions
- Analytical interfaces with serious data density and clarity
- No generic AI SaaS gradients, rounded cards, glassmorphism, or pointless animation

## Creative Direction
**"The Beautiful Game, Decoded"** — cinematic football storytelling meets analytical precision.
