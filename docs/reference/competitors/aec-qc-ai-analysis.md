# The AI Plan-Review Landscape, 2026: Competitive Teardown + an Open-Source Build Stack for RediCheck

## TL;DR
- The AI plan-review market has consolidated around three architectures: (a) **LLM-over-spec-text + light vision** (Document Crunch, Part3, BuildSync, Provision), (b) **purpose-trained computer-vision + LLM reasoning** (Togal, Buildcheck, Firmus, Helonic, TwinKnowledge, Beam AI), and (c) **rules/codes-as-a-graph + LLM citation engines** (CivCheck, CodeComply, AutoReview.AI, PlanCheckPro). For Tyler's RediCheck use case — interdisciplinary coordination on RCPs with Bluebeam-compatible output — the winning pattern combines vector-PDF parsing + a fine-tuned symbol detector + a vision-language model for semantic checks, orchestrated through Claude Code/MCP.
- No competitor has published a defensible moat on raw model quality; the moats are (1) **proprietary labeled drawing data**, (2) **construction-specific evaluation harnesses** (Document Crunch's "ConstructBench"), and (3) **integrations** (Procore, Autodesk Construction Cloud, Bluebeam). A solo/small-team builder using Claude Code can plausibly reach feature parity with the YC-stage entrants (Helonic, InspectMind) on a narrow vertical (RCP coordination) within ~3 months, provided they invest early in eval infrastructure and labeled data.
- The pragmatic open-source stack for late-2025/2026 is: **PyMuPDF + pypdfium2** for vector parsing → **DocLayout-YOLO + Surya OCR** for layout/text → **fine-tuned YOLOv11 / Grounding DINO 1.6 + SAM 2.1** for symbol detection → **Qwen2.5-VL-7B or InternVL3-8B** locally (or Claude Sonnet/GPT-4o via API) for semantic reasoning → **ColQwen2** + **Qdrant** for cross-sheet retrieval → **LangGraph or Pydantic AI** for orchestration → **XFDF + PyMuPDF** for Bluebeam-compatible output.

## Key Findings

1. **The space is crowded but shallow.** 17 companies, with notable disclosed funding in the last 18 months (Buildcheck $5.9M seed Dec 9, 2025; Provision $7M USD; TwinKnowledge $3.7M Series Seed Apr 2025; Togal cumulative $22.65M per CB Insights, with the latest round a $10.41M Convertible Note II on Aug 27, 2025; Trimble announced a signed agreement to acquire Document Crunch on Apr 2, 2026, expected to close Q2 2026; Clariti acquired CivCheck Oct 7, 2025). Most companies converge on similar marketing claims (10-35x ROI, 90% time reduction, 95-97% accuracy) without publishing methodology.
2. **OpenAI + Anthropic dominate the LLM layer.** Document Crunch explicitly says they "build upon state-of-the-art LLMs like OpenAI's GPT and Anthropic's Claude" combined with a "proprietary RAG architecture." Togal partnered with ChatGPT for its Togal.CHAT product. RIB SpecLink uses Azure OpenAI. None of the construction-AI companies have publicly disclosed using open-source LLMs in production.
3. **Two computer-vision strategies are visible.** (a) **Custom-trained CV from scratch** (Togal, Buildcheck, Helonic, TwinKnowledge — explicitly say "proprietary," "trained specifically on construction drawings"); (b) **Foundation VLMs + LLM orchestration** (InspectMind, Provision, Part3, BuildSync, Document Crunch). The first path requires multi-million-dollar investment and a labeling pipeline; the second is reachable with API calls.
4. **Buildcheck is the strongest direct competitor to a "RediCheck-style" coordination QA product.** $5.9M (Dec 9, 2025) led by Uncork Capital with Peterson Ventures and Xfund, plus angel investments from founders/executives at OpenAI, Opendoor, CBRE, and Zillow. Per Uncork partner Amy Saper: *"Construction is a $12 trillion market where design errors create more than $200 billion in waste each year."* 200+ checks across all disciplines, MILA/AMII research partnerships, customers including AvalonBay and Novo. They explicitly market "drawings are the language of the business" and reject text-only competitors.
5. **TwinKnowledge has published the most technical detail.** The AWS Physical AI blog post (2025) describes their hybrid CV+LLM pipeline running on Amazon SageMaker with fine-tuned models, chunking graphical info into text for LLM ingestion. This is the closest public "reference architecture" in the space.
6. **Bluebeam-compatible markup output is an underexploited differentiator.** Most platforms export to PDF (annotated rasters) or push to Procore/ACC via API. Native XFDF export with full markup fidelity (including custom subject types, count tools, calibrated measurements) is rare and would set a tool apart for estimators and QA managers who live in Bluebeam Revu.

## Details

### Competitor Profiles

**1. SpecSet (specset.com)** — *Stealth/early-stage.* Markets itself as "the AI platform for high-stakes construction" automating "review across Project Manuals, Drawing Sheets, and Shop Drawings in seconds." Metadata emphasizes **UFGS compliance** (Unified Facilities Guide Specifications — DoD/USACE/NAVFAC/AFCEC), Asset Management Logic, and Infrastructure AI, suggesting a federal/defense-vertical focus. **No public team, funding, blog, careers, or technical disclosure exist** as of May 2026. JS-rendered single-page site with negligible search index footprint. Treat as a watch-list company; technology stack is unknown.

**2. Firmus AI (firmus.ai)** — *Constructability QA via proprietary CV.* Founded by CEO Shir Abecasis. Pre-construction AI design review using "proprietary AI algorithms" on PDF drawing sets to flag scope gaps, missing info, and cross-discipline discrepancies. Marketed products: **Firmus AI-REVIEW** (issue detection across hundreds of sheets) and **Firmus AI-MATCH** (drawing set comparison between revisions). Customer wins include Flintco (Memphis), Nibbi Brothers (SF), RO. Case studies cite curtainwall-vs-spandrel-glass mismatches and MEP-RCP coordination as catches. Tech disclosure is thin — they describe "machine learning" that adapts to recurring drawing-set structures (e.g., learning to suppress redundant comments on unit plans). LinkedIn followers: ~3,670. No public funding disclosure found.

**3. Buildcheck AI (buildcheck.ai)** — *$5.9M seed Dec 9, 2025 — strongest direct competitor.* Founded by Alexander Michalatos (CEO, ex-EllisDon/Stantec/QuadReal, UBC mechanical engineering), Andrei Molchynsky, and Alex Gureev (AI lead). Customers: **AvalonBay Communities, Novo Construction**, 50+ paying. Funding led by Uncork Capital with Peterson Ventures and Xfund; angel investors include founders/executives at OpenAI, Opendoor, CBRE, and Zillow (per GlobeNewswire press release Dec 9, 2025); advisors from OpenAI, ServiceNow, Oxford. Research partnerships with **MILA (Quebec) and AMII (Alberta)** — strong signals of custom-trained vision models. Performs **200+ checks across architectural, structural, civil, MEP**. Reports **10–35× ROI**. Awards: Cemex 2025, EllisDon ConTech Accelerator 2025. Quote from co-founder Molchynsky: *"We've really been focused on this [drawing] use case, perhaps some of the other folks in our space more going after text-based documents. We're really focused from the beginning on drawings."* Filed multiple patents. This is the company a RediCheck-style product most directly competes against.

**4. CodeComply (codecomply.ai)** — *Code-compliance plan review for AHJs and architects.* Now distributed via **CivicPlus** partnership (Mar 2026 announcement). President: Patrick Hughes. Checks plans against **IBC, IMC, IPC, IRC, ADA, FHA, UFC, State Amended Building Codes, NFPA 101/70/72/13/14**. Features: VersionVue (revision compare), Plan Chat, Readiness Reports, intelligent comment management. Sold as decision-support, not decision-making ("final compliance determinations remain the responsibility of qualified reviewers" — legal disclaimer). SOC 2 audited. AI approach not publicly disclosed beyond "AI-powered compliance assessments."

**5. CivCheck (civcheck.ai / ComplyAI)** — *Acquired by Clariti Oct 7, 2025.* Founded 2023; CEO **Dheekshita Kumar**. "Guided AI Plan Review" platform — applicant pre-screening + city reviewer copilot. Customers: **Honolulu (Dec 8, 2025 launch), Denver (five-year $4.6M contract approved by City Council 10-1 vote on Mar 9, 2026, with District 7 Councilmember Flor Alvidrez as the sole dissenter, per Colorado Politics), Bellevue WA, Louisville KY**. Self-reported metrics: 97%+ accuracy, 80%+ permit time reduction, plan reviews dropping from 60–90 min to 15–20 min in Honolulu pilot. PDF-native; accepts hand-drawn plans. Explicit human-in-the-loop philosophy: *"AI doesn't make decisions — it helps you make them faster."* Backed by E14 Fund, Four Acres, GS Futures, Hyde Park Venture Partners, MassChallenge.

**6. InspectMind (inspectmind.ai)** — *Y Combinator W24; small team (~3 employees).* Founders: **Aakash Prasad (UC Berkeley EECS, ex-Google research)** and Shuangling Yin. Self-serve plan check from **$50–$100 per check**, $1/drawing sheet at scale, ~hours turnaround. **Money-back guarantee: refund if fewer than 5 issues found.** Reviews against **IBC, CBC, ADA, Title 24, NFPA**, plus custom standards. OCR supports scanned legacy PDFs. Excel export → Procore/ACC/Fieldwire/Smartsheet. Reports 250k+ issues caught, 600+ companies. Separate **Field Reports** mobile product ($100/user/month) with multilingual voice-to-text. Customer data not used for AI training (explicit). Tech stack not disclosed but small team + YC + Berkeley EECS founder suggests heavy reliance on frontier-LLM APIs (likely GPT-4o or Claude Sonnet) plus vector RAG over codes.

**7. BuildSync (buildsync.ai)** — *AI submittal review.* Compares submittals against project specs, extracts technical characteristics, generates compliance reports with source-document citations. Self-reported **95%+ accuracy** on technical compliance checking. Targets GCs reviewing sub submittals and subs preparing packages. Pilot conversion rate claimed at 70%. Bulk of marketing is CSI-division-aware checklists. Limited public tech disclosure; LLM-over-extracted-spec-text architecture is the most plausible inference.

**8. Document Crunch (documentcrunch.com)** — *Trimble announced a signed agreement to acquire Document Crunch on April 2, 2026; expected to close Q2 2026 (per Trimble press release; financial terms not disclosed).* COO: Trent Miskelly. Originally built for contract risk review; expanded to **CrunchAI for Specifications** Aug 2025. Won the 2024 **AI Breakthrough Award in the LLM category** (the same OpenAI won in 2023). Architecture (per their own blog): *"We build upon state-of-the-art LLMs like OpenAI's GPT and Anthropic's Claude, combining them with our own custom, construction-specific models and proprietary RAG architecture."* They emphasize a **"patented, proprietary pre-processing technology"** that handles multi-format PDFs blending text, tables, schematics, symbols. Internal benchmark called **"ConstructBench."** Recognitions: Cemex 2021 #1, Venture Atlanta 2024 #1 Growth Stage, Inc. Best Places to Work 2025.

**9. Helonic (helonic.com)** — *YC-backed AI drawing analysis.* Works directly on 2D PDFs (no BIM required). One-click **Procore + Autodesk OAuth integrations**. Self-reported metrics: **1,000+ reviews, 100k+ pages, 150k+ issues, $30M+ rework prevented**. Architecture (from their site): *"Our proprietary AI model — trained specifically on construction drawings… A quality gate filters out false positives. Each issue is assigned a confidence score based on the model's domain knowledge and evidence strength."* This is the cleanest articulation of a confidence-gated pipeline in the public market. 10 issue categories with severity ratings and exact page coordinates.

**10. TwinKnowledge (twinknowledge.com)** — *$3.7M Series Seed Apr 2025 (Camber Creek led, Great Wave Ventures).* **Most technically transparent company in the cohort.** AWS Physical AI Blog (2025) describes their stack: **Amazon SageMaker MLOps** for fine-tuning custom CV models; pipeline ingests drawings, runs specially trained CV models to chunk graphical info, transforms it into textual representations preserving structure, then LLMs reason over it. Mission: "AI copilots" + cognitive digital twins for AEC. Customer portfolio projected to double.

**11. AutoReview.AI (autoreview.ai)** — *Founded 2021, UF spin-out, Gainesville FL.* CEO: **Rob Christy**. Co-founder: **Nawari Nawari (UF architecture professor)**. The first US AI plan-review system in production with cities (Gainesville, Pasco County, Hernando County, Altamonte Springs, Titusville). Approach is **semantic NLP + ML over the entire Florida Building Code (800+ pages)** plus geometric checks (counting trees, measuring setbacks, identifying stairways/corridors/walls). Accepts DWG, Revit, PDF inputs. Reduces 3-week review to 24–48 hours. *Note: One source (Williams 2025) reports the Altamonte Springs pilot ended and suggests the company may no longer be operating, though their LinkedIn was active through IBS 2024 and city contracts in Hernando/Pasco/Titusville were live in 2024. Status as of mid-2026 is uncertain.*

**12. PlanCheckPro (plancheckpro.ai)** — *Built by Pacifica Engineering Services.* Same-day reviews against **NEC, NFPA, ADA, local codes**, 50-state coverage. Trained on "thousands of code interpretations." Explicitly positioned to comply with **Florida HB 683 (effective July 1, 2025)** which authorizes licensed private providers to use software for plan review. Reports run with code citations, corrective actions, digital seal by licensed reviewer. Currently offering unlimited free uploads during onboarding. Cloud-only browser app. Architecture not disclosed; the "proprietary algorithms and machine learning" language and licensed-engineer-curated training data suggest a RAG-over-codes + LLM-citation approach with a manual licensed-PE sign-off layer.

**13. Provision (provision.com)** — *$7M USD raise.* Toronto-based, founded 2022 by **Luigi La Corte (CEO)** and **Brendan Ardagh (CTO, ex-Jem HR CTO, DigsConnect co-founder, quantity surveyor by training)**. Customers: **Acciona, Bird Construction, Colas, EllisDon, PCL Construction, Cleveland Construction, NAC**. Self-reported: ~$100B in projects reviewed, 10x ARR growth in past year to ~$1M ARR, 10-person team scaling to ~18. SOC 2 Type II. Architecture (per founder interview): *"developing our own models for specialized tasks that existing large language models are incapable of addressing effectively"* — domain-specific products are **Project Review, Chat Agent, and Scope Agent**. Focus: contract review + scope gap detection + risk scoring (pre-construction). Their blog explicitly calls out *"Provision is trained on construction drawings, specifications, contracts, and standards. We OCR scan drawings, understand construction symbols and notation, and cross-reference between document types."*

**14. Togal.AI (togal.ai)** — *$22.65M cumulative (CB Insights), with the most recent round a $10.41M Convertible Note II on Aug 27, 2025; prior rounds include a $5M pre-Series A SAFE in March 2023 led by Florida Funders.* Founded 2019 by **Patrick Murphy (CEO, ex-US Congressman FL-18, EVP of Coastal Construction)** with co-founders Patrick Hughes and Karlie Fike (COO). Customers: DPR, Clark Construction, Total Flooring, Coastal Construction. **Built on AWS** with Tribe AI development partnership. Custom labeled dataset and proprietary CNN-based segmentation for room/wall/door/window detection on architectural plans; 97-98% accuracy claim. **Togal.CHAT integrates ChatGPT/OpenAI** for natural-language plan querying — they explicitly call themselves "one of the first to bring ChatGPT to construction." A University of Kansas study by Victoria V. Marulanda S. (CEAE/ARCE) found **"up to 76% time savings with Togal.AI" specifically versus On-Screen Takeoff** on a Fire Station case study, "maintaining a percentage difference within 5% compared to the On-Screen Takeoff results." Sold via **eTakeoff/SnapAI partnership** integration. ConstructConnect partnership. Per the Tribe AI case study, Togal built a ground-up ML system rather than wrapping Google/Microsoft vision APIs.

**15. Beam AI / iBeam (ibeam.ai)** — *Powered by Attentive.ai.* Founders: **Shiva Dhawan (CEO)** and **Rishabhjit Singh** — both IIT Delhi engineers. **Hybrid done-for-you + automated takeoff** model: AI scans plans + QA team reviews before delivery within 24–72 hours. Per their Mar 2026 announcement, **1,200+ contractors, 500k+ takeoffs, 20M+ hours saved**. Customer wins reported (Tactical Construction 2× bid volume; HVAC contractor doubled revenue $6M→$12M; Guardian Roofing 60% turnaround reduction). All trades (HVAC, electrical, plumbing, concrete, steel, civil, etc.). Pricing: annual license by trade. Outputs Excel + PDF + shareable view link with ±1% in-house accuracy claim. Tech stack not publicly disclosed but the human-in-the-loop QA layer is the most defensible feature claim.

**16. Takeoff Boost / On-Screen Takeoff (oncenter.com / ConstructConnect)** — *Mature incumbent; OST since the early 2000s, AI added 2023.* Owned by ConstructConnect since 2016. **Windows desktop app** (Win 8.1/10/Win 7 64-bit supported). Takeoff Boost is the AI module: auto-detects building outline, room areas, doors/plumbing/elevators (objects), wall type symbols → conditions, takeoffs of unlabeled windows. Improvements rolled out Mar 2025 centered takeoff lines on walls; ceiling-area boundaries fixed. The OST data model is the underlying value — Quick Bid integration, Multi-Condition takeoff (patented). The AI is bolt-on to an established workflow tool rather than the core. Closest analogue in the cohort to Bluebeam's Markup→Quantity workflow.

**17. Part3 (part3.io)** — *Construction administration platform for architects/engineers.* Submittal Assistant compares submittals against project spec manuals, generates submittal logs by scanning the spec book for the words "submittal," "mock-up," "sample" across all CSI divisions. **Procore integration** for import/export. Free spec-log generator tool outside Part3. Customer wins: IDEA Inc. (Canadian architecture firm) — reduced contract admin tasks from hours/days to ~5 min per document. Not focused on drawing analysis; spec-document NLP only.

### A) Common AI Patterns

Three architectures cover essentially all 17 companies:

1. **LLM-over-extracted-text + RAG (most common, lowest cost).** Used by Document Crunch, Part3, BuildSync, Provision (for contracts/specs), CodeComply, PlanCheckPro, CivCheck. Pipeline = OCR/PDF parse → chunk → embed → vector store → retrieval → LLM (GPT-4o or Claude) → citation-bearing answer. Differentiators here are checklist taxonomies, prompt templates, and proprietary evaluation harnesses ("ConstructBench").

2. **Custom-trained CV + LLM hybrid (most defensible, highest cost).** Used by Togal, Buildcheck, Helonic, Firmus, TwinKnowledge. Pipeline = raster PDF → custom CNN/transformer for symbol/room/wall detection → text/symbol token stream → LLM for reasoning about coordination and code. TwinKnowledge's published architecture (CV chunks graphical info → textual representation preserving structure → LLM analysis) is the canonical pattern.

3. **Code-graph + LLM citation (regulatory niche).** Used by AutoReview.AI, CodeComply, CivCheck, PlanCheckPro. The differentiator is encoding the actual code corpus (IBC, NFPA, IRC, local amendments) as structured rules with citations, then having the LLM map plan features to rule predicates. AutoReview.AI's UF research origin is the academic genealogy of this approach.

Convergence: **everyone uses OpenAI/Anthropic LLMs**, **everyone uses RAG**, **the differentiator is the front-end of the pipeline** (how cleanly drawings get parsed) and **the back-end** (evaluation harness, customer integrations, human-in-the-loop UX). No company has demonstrated a meaningful moat on raw model quality.

### B) Computer Vision Specifically

The CV tasks involved in plan review:

- **Sheet indexing** — auto-naming and classifying sheets (architectural floor plan, RCP, electrical, structural framing, etc.). OST, Togal, Buildcheck, InspectMind all advertise this. Typical approach: OCR the titleblock → match against CSI/AIA conventions.
- **Symbol/object detection** — doors, windows, plumbing fixtures, electrical outlets, structural columns, sprinkler heads, light fixtures. Togal targets architectural symbols; Beam AI targets trade-specific (HVAC, rebar). Approach varies: from synthetic-data-trained YOLO (likely Togal's path based on the Tribe AI case study's mention of "state-of-the-art" CV) to vision-language zero-shot (newer entrants).
- **Wall/line detection** — vector parse + heuristics (when PDFs are vector) or semantic segmentation (when rasterized). Togal's wall detection appears to use a custom semantic segmentation model trained on AIA standard floor plans.
- **Dimension extraction** — OCR + line/arrow detection. Underserved publicly; most platforms do not advertise dimension verification.
- **Schedule/table extraction** — door schedules, finish schedules, fixture schedules. Document Crunch's "patented pre-processing" likely handles this; Buildcheck explicitly checks schedules.
- **Cross-sheet referencing** — callout bubbles pointing to detail sheets, schedules referenced from floor plans. Helonic explicitly markets this as "cross-discipline relationships."
- **Drawing comparison/version diff** — Firmus AI-MATCH, OST overlay, CodeComply VersionVue. Typically pixel-level diff or vector-element diff (when both versions are vector PDF).

**Foundation VLMs in use:** No company publicly confirms using GPT-4V, Claude with vision, or Gemini Vision as the primary CV engine for drawings — the consensus is that off-the-shelf VLMs lack the spatial precision for AEC drawings. TwinKnowledge explicitly says *"off-the-shelf multi-modal AI models proved insufficient for graphical information processing."* This is the strongest public signal that purpose-trained CV is still required for accuracy on engineering drawings.

### C) Reliability Techniques

- **Confidence scoring + quality gates.** Helonic explicitly: "A quality gate filters out false positives. Each issue is assigned a confidence score." Buildcheck groups similar items and severity-prioritizes. CivCheck requires staff to approve every AI interpretation.
- **Human-in-the-loop as a product feature, not a bug.** CivCheck, CodeComply, PlanCheckPro, Beam AI all explicitly market human review as integral. Beam AI has a literal QA team between AI output and customer delivery (24–72 hr turnaround).
- **Domain-specific evaluation harnesses.** Document Crunch ConstructBench is the only named one. The lack of public benchmarks is the industry's worst-kept secret — there is no equivalent of "MMLU for construction drawings."
- **Issue grouping and severity ratings.** All players group multiple instances of the same issue (Buildcheck explicitly) and tag by severity. This is a UX-level reliability trick: false positives are tolerable if they cluster and can be dismissed in bulk.
- **Source citations.** Document Crunch, CodeComply, PlanCheckPro, Civils.ai, Helonic all tie every flagged issue to a specific page/section/sheet — this is the table-stakes pattern for trust.
- **Per-customer/per-project adaptation.** Firmus learned to suppress redundant comments on residential unit plans through machine learning over the customer's history. This kind of project-context adaptation is rarely advertised but appears to drive customer retention.

### D) Best Open-Source Stack to Build a Similar System (Late 2025 / 2026)

#### Symbol/object detection on drawings

- **YOLOv11 (Ultralytics, released Sep 2024)** — current best speed/accuracy tradeoff in the YOLO line. Use case: fine-tuned on AEC symbol corpus (electrical outlets, plumbing fixtures, door tags). **YOLOv12** released in early 2025 is also viable. License: AGPL-3.0 (commercial license required for paid products).
- **RT-DETR-v2 (Baidu, 2024)** — transformer-based, NMS-free, often outperforms YOLO on dense small objects (which AEC symbols are). Apache-2.0.
- **DocLayout-YOLO (OpenDataLab, arXiv:2410.12628, Oct 2024)** — purpose-trained for document layout on YOLOv10 with a GL-CRM (Global-to-Local Controllable Receptive Module); pre-trained on DocSynth-300K. SOTA on D4LA/DocLayNet/DocStructBench among unimodal DLA methods; beats LayoutLMv3 and DIT on accuracy while matching YOLOv10 speed. The right backbone for **titleblock + schedule + drawing-area segmentation**.
- **Grounding DINO 1.6 Pro (IDEA Research, 2024)** — 55.4 AP COCO, 57.7 AP LVIS-minival zero-shot. Edge variant 75.2 FPS @ TensorRT, 36.2 AP LVIS-minival. Apache-2.0 base, paid 1.6 Pro tier. **Use for cold-start zero-shot symbol detection before you have labels.** Pair with text prompts like "circular electrical outlet symbol with internal hatch."
- **SAM 2.1 (Meta, late 2024)** — segment-anything, 6× faster than SAM v1, box-prompted from Grounding DINO outputs. ~58.9 mIoU on SA-23 at 1-click. Apache-2.0.
- **OWL-ViTv2** — viable for open-vocabulary but generally inferior to Grounding DINO 1.6 on small dense objects.

**Bootstrapping training data:**
- **Synthetic generation:** Render synthetic floor plans via Blender + procedural AIA-style symbol libraries; the SESYD dataset method (Delalandre 2010) is the original recipe.
- **Weak labeling:** Run Grounding DINO 1.6 with text prompts → manually verify the top-confidence detections → use as positive samples; this is the standard active-learning loop.
- **Existing public datasets:** **CubiCasa5K** (5,000 Finnish residential FPs, polygon-annotated, >80 categories, CC BY-NC 4.0 — research-only; arXiv:1904.01920); **FloorPlanCAD** (>10,000 commercial+residential vector CAD SVGs, panoptic symbol spotting, 30 categories, ICCV 2021, arXiv:2105.07147); **SESYD** (1,000 synthetic vector FPs, 16 symbol classes, GREC standard); **ArchCAD-400K** (arXiv 2025, large-scale architectural CAD); **CADSpotting / LS-CAD** (arXiv 2024 — larger plans avg ~1,000 m² coverage); **ResPlan** (arXiv 2508.14006, Aug 2025, 17,000 residential vector graphs); **RPLAN** (80,788 raster Asian residential plans, 256×256); **R2V/R3D** (Liu et al., ICCV 2017); **Modified Swiss Dwellings (MSD)** (5,300 multi-unit floorplates, 18,900 apartments). For commercial use, build proprietary labels via Roboflow or Label Studio over your own drawing sets.

#### Text/spec extraction (OCR + layout understanding)

- **Surya OCR (Datalab / Vik Paruchuri, github.com/datalab-to/surya)** — 90+ languages, line-level detection + recognition + layout + reading order + table recognition. PyPI `surya-ocr` (v0.17.1 cited 2025). >5k GitHub stars. **First choice for engineering drawing OCR in 2026.** Strong on rotated text and complex layouts.
- **PaddleOCR / PaddleOCR-VL 1.5 (Baidu, 2025)** — best raw OCR accuracy on dense text, including the new VL variant for visual document understanding. Heavier dependency footprint (PaddlePaddle).
- **docTR (Mindee)** — db_resnet50 + crnn_vgg16_bn. Good for forms and titleblocks; weak on rotated dimension text.
- **TrOCR (Microsoft)** — transformer encoder/decoder; fine-tunable but slower.
- **Tesseract** — fallback only. Inferior to Surya in 2026.
- **Marker / MinerU (OpenDataLab)** — PDF→Markdown. Marker uses Surya + texify + tabled. MinerU integrates LayoutLMv3 + YOLOv8/DocLayout-YOLO + UniMERNet, 61.7k GitHub stars by early 2026, MCP server added Mar 2026. Optimized for narrative docs; less effective on pure engineering drawings but **excellent for spec book ingestion**.

**Handling rotated text / dimensions:** Surya handles rotation natively. For dimension-line text specifically, post-process with a line/arrow detector (custom YOLO or vector parse) to associate text tokens with the line they label. PaddleOCR's text-direction classifier is also strong here.

#### Document layout / table extraction

- **DocLayout-YOLO** — as above, the layout backbone of choice for 2026.
- **LayoutLMv3 (Microsoft)** — transformer over text+image+layout; still useful for fine-tuned spec-table extraction.
- **Qwen2.5-VL (Alibaba, arXiv:2502.13923, Mar 2025)** — 3B/7B/72B. **DocVQA 96.4% (72B, currently #1 on the DocVQA leaderboard), 95.7% (7B), ChartQA 89.5%, OCRBench 88.8%, OmniDocBench NED EN/ZH 0.226/0.324, CountBench 93.6%.** Native dynamic-resolution ViT (trained from scratch), window attention, MRoPE. Best open VLM for documents as of mid-2025.
- **InternVL3 (OpenGVLab, Apr 11, 2025, arXiv:2504.10479)** — 1B–78B, Qwen2.5 LLM backbone, dynamic 448×448 tiling, V2PE positional encoding. **OCRBench 906, MMMU 72.2 (78B beats GPT-4o 70.7), MathVista ~79.0.** InternVL3.5 (Aug 2025) with MoE follows; InternVL3.5-241B-A28B variant + CascadeRL training code released 2025/08/30.
- **Florence-2 (Microsoft, 2024)** — strong on small-object detection/OCR; viable for fine-tuned drawing tasks.
- **GOT-OCR2** — general OCR transformer for formulas/tables/sheet music; less needed if you have Qwen2.5-VL.
- **Pix2Struct / Donut** — older; superseded for most tasks by Qwen2.5-VL.

#### Vector PDF processing

- **PyMuPDF (fitz)** — the workhorse. Extracts vector primitives (lines, curves, fills, text with bbox), rasterizes pages at arbitrary DPI, writes annotations. **Required for both reading and writing Bluebeam-compatible markups.** AGPL (commercial license needed for paid product) or buy a commercial license from Artifex.
- **pypdfium2** — Apache-2.0, PDFium-based; faster rasterization. Use for speed-critical raster output.
- **pdfplumber** — best for table/text extraction from non-scanned PDFs; slower for vector graphics.
- **pdf.js (Mozilla)** — frontend only.

**Vector vs raster decision rule:** Always attempt vector parse first (PyMuPDF). Drop to raster + OCR only when vector text extraction returns empty or when you need pixel-level CV (symbol detection on stylized symbols where the vector representation is too fragmented). For RediCheck-style RCP coordination, **both paths are needed in parallel**: vector for clean text + lines + dimension extraction, raster (300 DPI) for symbol detection.

#### Multi-sheet cross-referencing

- **ColQwen2 (Vidore, arXiv:2407.01449, July 2024)** — current best visual document retrieval. Method: VLM encoder → patch embeddings → linear projection → ColBERT-style late-interaction multi-vector retrieval. Backbone for ColQwen2 = Qwen2-VL-2B. HuggingFace: `vidore/colqwen2-v0.1`, `vidore/colqwen2-v1.0`, `vidore/colqwen2-v1.0-hf` (Transformers ≥4.46 native), `vidore/colqwen2-base`. Engine: `colpali-engine` (≥0.3.4 for ColQwen2-v1.0). Trained on 127,460 query-page pairs (63% academic + 37% synthetic w/ Claude-3-Sonnet pseudo-queries). Backbone Apache-2.0; some adapters CC BY-NC 4.0. Benchmark: **ViDoRe** — ColPali beats text-pipeline baselines including Claude-Sonnet-captioned retrieval on visually-rich tasks (InfographicVQA, ArxivQA, TabFQuAD). **Use this to retrieve "the detail sheet that matches callout 3/A-501" from a 400-page drawing set.**
- **ColPali v1.3** — PaliGemma-3B backbone alternative (`vidore/colpali-v1.3`).
- **BGE-M3** — best general-purpose text embedding for spec-book + code corpus RAG.
- **nomic-embed-text v1.5** — fast, 768-dim, good for keyword-heavy AEC text.
- **Qdrant** — recommended vector DB for production; gRPC, hybrid search, supports multi-vector for ColQwen2 natively. Apache-2.0.
- **LanceDB** — great for embedded / single-node setups; columnar storage, can hold PDF page rasters alongside vectors.
- **pgvector** — choose if you already run Postgres (which Tyler does, via Prisma).
- **Neo4j** — overkill for this use case; use only if you need explicit cross-sheet graphs (callout → detail → schedule → spec section).

**Entity resolution pattern:** Each PDF "page" gets a node with (sheet_number, sheet_title, discipline, raster_hash, vector_embedding, text_embedding). Callouts are edges with (origin_sheet, origin_bbox, target_sheet_number, target_detail_number). This is straightforward in Postgres/Prisma — no graph DB needed for the 80-item interdisciplinary checklist scope.

#### Vision-language models (late 2025 / early 2026)

| Model | Size | DocVQA | OCRBench | Notes |
|---|---|---|---|---|
| **Qwen2.5-VL-72B** | 72B | 96.4 | 88.8 | Best open VLM for docs (Alibaba, Mar 2025) |
| **Qwen2.5-VL-7B** | 7B | 95.7 | — | Best size/perf ratio for self-hosting |
| **InternVL3-78B** | 78B | — | 906 | MMMU 72.2 beats GPT-4o 70.7 (OpenGVLab, Apr 2025) |
| **InternVL3-8B** | 8B | — | — | AI2D 92.6 |
| **MiniCPM-V 2.6** | 8B | — | — | Strong tiny model |
| **Pixtral 12B** | 12B | — | — | Mistral, weaker on docs |
| **Llama 3.2 Vision** | 11B/90B | — | — | Meta, weaker on dense OCR |

For RediCheck, **Qwen2.5-VL-7B running on a single A100 (or via vLLM on Modal/Runpod)** is the recommended self-hosted default. For maximum quality, API-call **Claude Sonnet 4.5 or GPT-4o** for the semantic-reasoning step over CV-extracted features. Note: all VLM benchmark numbers cited above are self-reported on model cards and llm-stats.com leaderboards; independent verification is sparse.

#### Orchestration

- **LangGraph (LangChain)** — best for the deterministic multi-step pipeline RediCheck needs (ingest → preprocess → CV → OCR → semantic check → annotation). State machine is explicit; easy to add human-in-the-loop checkpoints.
- **Pydantic AI** — newer (2024), strong typing, great fit if you want Anthropic-first development with Claude Code. Recommended for a solo Claude Code workflow.
- **DSPy (Stanford)** — for systematic prompt optimization; useful once you have a labeled eval set.
- **LlamaIndex** — overkill if you're not doing pure RAG; their query engines are nice but the abstraction cost is high.
- **Letta (formerly MemGPT)** — only if you need long-running agent memory; not needed for plan-check.
- **Haystack** — slower-moving than the above; skip.

**Recommendation for Tyler:** Pydantic AI as the orchestration layer + LangGraph for the explicit multi-step DAG. Both work natively with MCP tools and Claude Code.

#### Training infrastructure (only if custom CV)

- **PyTorch 2.5 + Lightning 2.4** — default.
- **Hugging Face Transformers** — for fine-tuning VLMs (Qwen2.5-VL has full HF support).
- **Ultralytics (YOLO)** — fastest path from labeled box data to a deployed detector.
- **MMDetection v3** — research-grade detector zoo; harder to deploy but more flexible.
- **Detectron2** — Meta-maintained; fine for fine-tuned Mask R-CNN or RT-DETR.
- **Roboflow** — labeling + training-data versioning + dataset augmentation. Use this for the proprietary AEC symbol corpus.
- **Label Studio** — open-source alternative.

#### Deployment / serving

- **vLLM 0.6+** — fastest open LLM/VLM serving; supports Qwen2.5-VL natively.
- **TGI (HuggingFace)** — second choice.
- **Ollama** — great for local dev; production-suitable for small VLMs (Qwen2.5-VL-3B / 7B).
- **LiteLLM** — routing across providers; recommended for fallback (Claude primary, GPT-4o secondary).
- **ONNX Runtime** — export YOLO/RT-DETR detectors here for edge deployment.

#### Evaluation

- **Inspect AI (UK AISI)** — the rising standard for safety/capability evals in 2025-2026; works for structured output evals.
- **Promptfoo** — simplest for prompt iteration with golden test sets.
- **LangSmith** — best if you're on LangGraph; trace-level eval.
- **Weights & Biases** — for fine-tuning experiment tracking.
- **Custom eval harness:** Build a `pytest`-based suite that runs the full pipeline on ~50 historical RediCheck projects with hand-labeled "ground-truth issue lists" and measures (precision, recall, F1) per checklist item type. This is the moat — it's what Document Crunch calls ConstructBench.

#### Datasets

- **CubiCasa5K** (5k Finnish residential, CC BY-NC 4.0, arXiv:1904.01920)
- **FloorPlanCAD** (10k+ commercial+residential vector CAD, panoptic, ICCV 2021)
- **SESYD** (1k synthetic, 16 symbol classes, GREC standard benchmark)
- **ArchCAD-400K** (2025, large-scale architectural CAD)
- **CADSpotting / LS-CAD** (2024, large-area plans)
- **RPLAN** (80k Asian residential)
- **Raster-to-Vector / R2V / R3D** (Liu et al., ICCV 2017)
- **ResPlan** (Aug 2025, 17k residential vector graphs)
- **Modified Swiss Dwellings (MSD)** (5,300 multi-unit floorplates)
- **FPLAN-POLY** (42 vectorized DXF floor plans)

For RediCheck, none of these are perfect (US commercial, MEP-RCP coordination is the gap). **Build a proprietary dataset from the family business's project archive** — 200–500 labeled drawings will outperform any public dataset for the specific 80-item checklist.

Notable academic OSS for vector-CAD parsing: **CADTransformer (CVPR 2022, github.com/VITA-Group/CADTransformer)** — ViT-based panoptic symbol spotting on FloorPlanCAD, lifted FloorPlanCAD SOTA PQ 0.595→0.685; **GAT-CADNet (CVPR 2022)** — graph-attention; **VectorFloorSeg (CVPR 2023)** — two-stream GAT; **Symbol as Points (ICLR 2024)**; **CADSpotting (arXiv 2024)** — sliding-window for large drawings. Curated list at github.com/bertjiazheng/Awesome-CAD.

### E) "How I Would Build It" — Reference Architecture for RediCheck

A practical solo-builder architecture that respects what Tyler already has (PDF rasterization + symbol detection + coordinate transformation + Bluebeam annotation output Python scripts, MCP plugin orientation, Claude Code as primary dev tool).

```
┌─────────────────────────────────────────────────────────────────────┐
│                     RediCheck Pipeline (MCP-native)                  │
└─────────────────────────────────────────────────────────────────────┘

  [Ingest]                  Next.js + Vite/React/TS frontend
       │                    Upload sheet set (PDF) → S3 / R2
       ▼
  [Preprocess]              Python service (FastAPI)
       │                    • PyMuPDF: extract per-page vector data
       │                      + rasterize @ 300 DPI
       │                    • pypdfium2: fast raster fallback
       │                    • Detect vector vs scanned
       ▼
  [Sheet Indexing]          • DocLayout-YOLO: titleblock + drawing
       │                      area + schedule region detection
       │                    • Surya OCR over titleblock crop
       │                    • LLM (Claude Haiku) classifies sheet
       │                      type (A-, S-, M-, E-, P-, RCP)
       │                    • Persist: Postgres + Prisma
       ▼
  [Symbol Detection]        • Fine-tuned YOLOv11 for AEC symbols
       │                      (electrical outlets, sprinkler heads,
       │                       diffusers, lights, etc.)
       │                    • Grounding DINO 1.6 + SAM 2.1 fallback
       │                      for zero-shot rare symbols
       │                    • Coordinate transform: PDF user space
       │                      → page raster pixels → sheet "logical"
       │                      coords (using titleblock scale bar OCR)
       ▼
  [Text + Dimension OCR]    • Surya OCR over drawing area
       │                    • Vector text extraction via PyMuPDF
       │                      (preferred when available)
       │                    • Dimension association: tie text
       │                      tokens to line segments via geometry
       ▼
  [Schedule Extraction]     • DocLayout-YOLO + Qwen2.5-VL-7B
       │                      over schedule regions
       │                    • Output: structured JSON per row
       │                      (Door schedule, Finish schedule,
       │                       Fixture schedule, RCP legend)
       ▼
  [Cross-Sheet Indexing]    • Per-page embeddings via ColQwen2-v1.0
       │                    • Store in Qdrant
       │                    • Build callout graph in Postgres
       │                      (callout_bubble → detail_sheet)
       ▼
  [Rule Evaluation]         • 80-item checklist as Pydantic models
       │                    • Each rule = a Python function that
       │                      queries the structured data + invokes
       │                      Claude Sonnet 4.5 for semantic checks
       │                      (e.g., "Does the diffuser in RCP at
       │                       coords match the M-sheet diffuser
       │                       schedule type, and does the ceiling
       │                       height match the architectural RCP?")
       │                    • LangGraph DAG orchestrates rule runs
       │                    • Pydantic AI tool defs for Claude Code
       ▼
  [Human-in-the-Loop]       • Web UI shows flagged issues sorted by
       │                      severity + confidence
       │                    • Reviewer accepts/rejects → feedback
       │                      stored for active learning
       ▼
  [Annotation Output]       • Generate XFDF with markup geometry
       │                      mapped back to original PDF coords
       │                    • PyMuPDF writes inline PDF annotations
       │                      (FreeText, Polygon, Square) for users
       │                      who want a single annotated PDF
       │                    • Both Bluebeam Studio Session import
       │                      AND single-PDF download paths
       ▼
  [Export]                  • Excel issue list (Procore-importable)
                            • XFDF file → Bluebeam Markups List import
                            • Annotated PDF
                            • JSON for programmatic consumers
```

**Library choices with reasoning:**

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js + Vite/React/TS | Tyler's stack; minimal new learning |
| API | FastAPI (Python) | Async, type-safe; great Claude Code support |
| DB | Postgres + Prisma + pgvector | Already in stack; pgvector handles ColQwen2 vectors fine at sub-100k page scale |
| Vector DB (scale-out) | Qdrant | Move from pgvector → Qdrant when >100k pages |
| Vector PDF | PyMuPDF | Best vector extraction + annotation write; license-aware |
| Raster fallback | pypdfium2 | Faster than PyMuPDF for raster-only; Apache-2.0 |
| Layout detect | DocLayout-YOLO | SOTA for 2026; titleblock/schedule/drawing-area |
| Symbol detection | YOLOv11 (fine-tuned) + Grounding DINO 1.6 + SAM 2.1 | Fine-tuned for known symbols; zero-shot for long-tail |
| OCR | Surya | Best open OCR 2026; multilingual rotation-safe |
| Schedule | Qwen2.5-VL-7B (vLLM) | Open VLM, run on Modal or RTX 4090 |
| Semantic checks | Claude Sonnet 4.5 via API | Highest quality reasoning; Anthropic positioning ~mid-2026 |
| Retrieval | ColQwen2-v1.0 (vidore) | SOTA visual page retrieval |
| Orchestration | Pydantic AI + LangGraph | Pydantic AI for Claude/MCP-native dev; LangGraph for explicit DAG |
| MCP server | Anthropic MCP SDK (Python) | Wrap RediCheck tools (run_check, annotate_pdf, query_set) for Claude Code |
| Annotation output | PyMuPDF (XFDF + inline) | Open and Bluebeam-compatible (with caveats below) |
| Eval | Inspect AI + custom pytest | Ground-truth issue lists from family archive |
| Serving | Modal (preferred) or Runpod | GPU on demand; no idle cost |

**Tradeoffs:**
- **Latency vs accuracy:** Vector parse → Qwen2.5-VL is ~3 sec/page on an A100. Claude Sonnet 4.5 semantic check is ~2 sec/rule. A 200-sheet set with 80 checklist items takes ~5-15 min per run on Modal — fast enough for overnight QA, slow for live editing.
- **Cloud vs local:** Self-host CV (YOLOv11, DocLayout-YOLO, Surya) on Modal; API-call LLMs (Claude/GPT-4o). Avoid trying to run a 70B VLM locally on commodity hardware.
- **Open vs API LLMs:** Use Claude Sonnet 4.5 for semantic reasoning (best quality, MCP-native). Use Qwen2.5-VL-7B locally for high-volume schedule extraction (cheaper per page). Use LiteLLM to route and fall back.
- **MIT vs AGPL:** PyMuPDF AGPL means you either open-source RediCheck or buy an Artifex license. For a family-business SaaS, buy the license ($2k-5k/year typical).

**Bluebeam-compatible annotation output — practical guidance:**

Bluebeam Revu stores markups as standard PDF annotation objects (FreeText, Polygon, PolyLine, Circle/Ellipse, Square, Line, Ink, Stamp) with **custom Bluebeam-specific keys** in the annotation dictionary (subject codes, custom appearance streams, scale data). Interchange formats: **FDF** (form-field data, binary/encoded as Bluebeam emits it); **XFDF** (XML, available via Revu Export Data → XML; supports AcroForm + static XFA but not dynamic XFA); and the proprietary **.bax** tool sets / **Studio Sessions** for live collaboration.

- **What you can reliably round-trip with PyMuPDF:** Square, Polygon, FreeText (without callout arrows), Ink, Line. These render correctly in Bluebeam.
- **What does not round-trip cleanly:** Cloud+ markups (Bluebeam-specific subject), Measurement / Calibrate annotations (require scale metadata), Count tool symbols, custom stamps, image stamps. PyMuPDF will write the geometry but Bluebeam may not recognize them as their native subject type. PyMuPDF supports only 5 FreeText fonts (Helvetica, Times-Roman, Courier, ZapfDingbats, Symbol — no bold/italic), does not support callout arrows on FreeText, and recreated annotations may exhibit coordinate-system "jumps" after Bluebeam color/status changes (forum.mupdf.com).
- **Recommended path for RediCheck:**
  1. Generate **XFDF** with standard annotation types (Square boxes around flagged areas, FreeText callouts with issue descriptions, Polygon for irregular regions, color-coded by discipline).
  2. Populate `/T` (author = "RediCheck AI"), `/Subj` (e.g., "Coordination Issue"), `/Contents` (issue text), `/M` (modification timestamp), `/NM` (unique ID), `/C` (color RGB).
  3. Provide **two outputs**: (a) XFDF file users import via Bluebeam Markups List → Import, (b) annotated PDF for users who don't have Bluebeam.
  4. If higher fidelity is needed (Cloud+, measurements), evaluate **Apryse/PDFTron SDK** ($$$$) or **Nutrient (formerly PSPDFKit)**. For a family-business solo build, stick with PyMuPDF and accept the standard-types-only constraint.

**Human-in-the-loop checkpoints (where they belong):**
1. After **sheet indexing** — let user confirm sheet discipline classification before downstream rules fire.
2. After **symbol detection** — let user inspect a sample sheet and adjust confidence thresholds per discipline.
3. After **rule evaluation** — bulk accept/reject panel sorted by severity × confidence; rejected issues feed back as negative training data.
4. Before **XFDF export** — final review and severity demotion option.

**MCP plugin design (matches Tyler's direction):** Wrap each pipeline step as an MCP tool callable from Claude Code:
- `redicheck.ingest(pdf_url)` → returns sheet_set_id
- `redicheck.run_symbol_detection(sheet_set_id, sheet_id)` → returns detections
- `redicheck.run_rule(rule_id, sheet_set_id)` → returns issues
- `redicheck.export_xfdf(sheet_set_id, filter)` → returns XFDF blob
- `redicheck.preview_issue(issue_id)` → returns annotated raster crop

This gives Tyler the ability to develop the pipeline iteratively in Claude Code, debugging individual sheets by hand while the orchestration layer (LangGraph) drives the full-set runs.

## Recommendations

**Stage 1 (Weeks 0-4): Foundation + Eval Harness.**
- Lock in PyMuPDF + pypdfium2 + Postgres/Prisma/pgvector + FastAPI base.
- Hand-label 30 historical RediCheck projects against the 80-item checklist. This is the **single most important investment**; without it, you cannot measure improvement.
- Stand up Inspect AI / pytest harness running the current Python scripts end-to-end on the labeled set.
- Benchmark: target ≥0.6 F1 with current scripts as baseline. Anything below means the scripts have bugs, not that the AI is wrong.

**Stage 2 (Weeks 4-12): CV + OCR layer.**
- Integrate DocLayout-YOLO for layout, Surya for OCR, fine-tune YOLOv11 on the most-common 10 symbol types from the family archive.
- Add Grounding DINO 1.6 + SAM 2.1 for zero-shot long-tail.
- Target: 0.75 F1 on the labeled set, with symbol detection precision ≥0.9.

**Stage 3 (Weeks 12-20): Semantic + Cross-Sheet.**
- ColQwen2 + Qdrant for retrieval; Claude Sonnet 4.5 for semantic checks; LangGraph DAG.
- Target: 0.85 F1 on labeled set.
- Build MCP tools for Claude Code workflow.

**Stage 4 (Weeks 20-28): Bluebeam Output + Productization.**
- XFDF generator + annotated-PDF export.
- Next.js UI with HITL accept/reject panel.
- Pilot with 3 family-business projects live; measure (a) issues caught, (b) false-positive rate per discipline, (c) time saved.

**Decision thresholds:**
- If F1 plateaus below 0.75 after Stage 2 → invest in **more labeled data** (jump to 200+ projects); the CV layer is data-limited, not architecture-limited.
- If false positives in semantic checks exceed 30% → switch to **two-stage verification** (cheap LLM proposes → expensive LLM verifies → only emit if both agree). This is the pattern Helonic's "quality gate" implements.
- If latency exceeds 30 min per project → push symbol detection and OCR onto Modal GPU; move LLM calls to Anthropic batch API for non-realtime runs.
- If a customer asks "can we use this on a 1000-page set" → that's the signal to move from pgvector to Qdrant and from in-process LangGraph to a queued worker (Celery/RQ on Postgres).

**Defensive moves vs. the named competitors:**
- Buildcheck and Helonic are the direct threats. Their moat is breadth (200+ checks, all disciplines). Tyler's moat should be **depth on RCP-MEP coordination + Bluebeam-native output**. Don't compete on breadth.
- Document Crunch's "ConstructBench" is the right pattern — build and publish (or at least internally maintain) a RediCheck benchmark.
- Beam AI's QA-team-in-the-loop is differentiated; consider a "RediCheck Pro" tier that includes human review for $$ projects.

## Caveats

- All accuracy numbers cited (97% Togal, 95% BuildSync, 97%+ CivCheck) are **self-reported on company marketing pages**; there is no industry-standard benchmark or independent third-party audit. The University of Kansas study cited for Togal is a single case study (Fire Station) comparing only against On-Screen Takeoff, not the full takeoff-software market.
- **SpecSet** has essentially no public footprint; the company may be stealth or may already be defunct. Treat the profile as a placeholder.
- **AutoReview.AI** has one cited source (Williams 2025) reporting the Altamonte Springs pilot ended and suggesting the company may no longer be operating; their LinkedIn was active through IBS 2024 and city contracts in Hernando/Pasco/Titusville were live in 2024. Status as of mid-2026 is **uncertain**.
- VLM benchmark numbers (Qwen2.5-VL DocVQA 96.4%, InternVL3 OCRBench 906) are **self-reported on model cards and llm-stats.com**; independent verification is sparse (llm-stats.com listed 0 verified / 26 self-reported on DocVQA as of search).
- Funding figures from Crunchbase/PitchBook/CB Insights are point-in-time and may be stale. The **Trimble–Document Crunch acquisition is a signed agreement announced Apr 2, 2026, with expected close in Q2 2026 — the deal is not yet closed and financial terms are undisclosed.** CivCheck's acquisition by Clariti (Oct 7, 2025) is closed; financials undisclosed.
- The recommendation to use **Claude Sonnet 4.5** for semantic reasoning is based on current Anthropic positioning as of May 2026; if pricing or quality shifts, GPT-4o (or its successor) and Gemini 2.5 Pro are drop-in alternatives via LiteLLM routing.
- **PyMuPDF AGPL** licensing is a real constraint for a commercial SaaS. The Artifex commercial license is necessary; budget $2-5k/year.
- The architecture above assumes ~200-page typical project sets. At 1,000+ pages, several components (retrieval, symbol detection batching) need re-architecting.
- The CubiCasa5K license is **CC BY-NC 4.0 — research-only**. Do not train commercial models directly on it; use it for benchmarking only or replicate the labeling approach on a proprietary corpus.