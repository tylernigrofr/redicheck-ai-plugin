---
title: Structured (getstructured.ai)
source: https://getstructured.ai/
captured: 2026-05-22
status: triaged
tags: [competitor, qa-qc, mep, drawing-review, yc]
---

# Structured

**Closest known competitor to redicheck-ai's product vision.** YC-backed, focused on QA/QC automation for AEC firms on MEP / civil / structural drawings. Where Buildcheck and Helonic chase breadth (all disciplines), Structured chases firm-specific custom checks — the same workflow redicheck-ai is built around.

## What they do

AI-powered drawing review. Parses large compliance documents in minutes, flags issues with **exact page, location, and remediation**. Custom checks aligned with firm-specific standards plus building codes, fire, accessibility, and coordination requirements.

## Product surface

- **QA/QC Compliance Checks** — parse compliance docs; identify issues with page + location + remediation.
- **Document Chat** — query drawings, get sourced answers linked back to specific sheets.
- **Custom Checks** — plain-English prompts tested against drawing sets (workflow-as-prompt-engineering).
- **Adjacencies:** version comparison, code/compliance browsing, annotations, takeoffs.

## Positioning quote

> "A deterministic list your team can act on and sign off on" — explicitly *against* the confidence-percentage UX that Helonic, Buildcheck, etc. lean on.

## Tech / security claims

- Bank-grade encryption, SOC 2.
- **On-premise deployment available** — significant for firms with strict IP / client-confidentiality requirements.
- Integrations: **Revit, Bluebeam, Procore, SharePoint, Google Drive, Microsoft**.

## Backing

- **Y Combinator** + Zero Prime Ventures + Airtree + Microsoft for Startups.
- Team includes architects/engineers + Oxford AI research backing.
- Self-reported published research in CV and AI agents (specifics not surfaced from landing page).

## Customers (named on site)

- **Syska Hennessy Group** — major US MEP engineering firm (relevant: this is the customer profile redicheck-ai would target).
- Auld & White Constructors.
- GPD Group.

## Press

Forbes, WSJ, Business Insider, AEC Magazine.

## Pricing

Not disclosed — demo-gated.

## Implications for redicheck-ai

1. **They're already where we want to be.** Bluebeam + Revit + Procore integrations, on-prem option, real MEP-firm customers. Treat as the **benchmark for product surface area**, not just an info point.
2. **The "deterministic list" framing is well-chosen** — it matches our ADR direction (skills emit explicit findings via PyMuPDF markups per ADR-0012; we're not surfacing model confidence to the Reviewer either). Worth borrowing the language.
3. **Custom checks as a plain-English DSL** — they appear to let firms author their own checks. Our current model is skill-author-driven (Python code + ADRs). Open question: do we eventually expose a Reviewer-authored check surface? If yes, what's the smallest version of that?
4. **On-prem option** — for firms working on confidential projects (defense, healthcare, large landlord clients), on-prem may be table stakes. Worth watching.
5. **Oxford AI research backing + "published research"** — if they publish methods, those are direct technical inputs for us. Add a follow-up task: find their actual publications.
6. **Gap to exploit:** they appear general-discipline ("MEP, civil, structural"). redicheck-ai's current ADR direction is **vertical-slice per check type** (door check, drawing index, spec index). Whether vertical depth beats horizontal breadth is the strategic question.

## Open follow-ups

- Find Structured's published research — methods, not marketing.
- Try a demo if possible to see check-authoring UX firsthand.
- Watch for AEC-Bench score publication from them — they're the most likely competitor to run on it.
- Linear issue: capture firm-specific-custom-checks as a roadmap consideration (currently implicit; ADR worth writing if we commit).
