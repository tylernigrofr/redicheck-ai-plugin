# AEC-Bench: A Multimodal Benchmark for Agentic Systems in Architecture, Engineering, and Construction

**Authors:** Harsh Mankodiya (harsh@nomic.ai), Chase Gallik (chase@nomic.ai), Theodoros Galanos (theodoros.galanos@aurecongroup.com), Andriy Mulyar (andriy@nomic.ai)

**arXiv:** 2603.29199v1 [cs.AI] 31 Mar 2026
**Code/data:** https://github.com/nomic-ai/aec-bench (Apache 2)

> Source: converted from `AEC-Bench.pdf` (10 pages). This is a reference copy for use as redicheck-ai context; figures and tables are described in text only.

## Abstract

AEC-Bench is a multimodal benchmark for evaluating agentic systems on real-world tasks in the Architecture, Engineering, and Construction (AEC) domain. It covers tasks requiring drawing understanding, cross-sheet reasoning, and construction project-level coordination. The report describes the benchmark motivation, dataset taxonomy, evaluation protocol, and baseline results across several domain-specific foundation model harnesses. The authors use AEC-Bench to identify consistent tools and harness design techniques that uniformly improve performance across foundation models in their own base harnesses (Claude Code, Codex). Benchmark dataset, agent harness, and evaluation code are openly released under Apache 2.

## 1. Introduction

Foundation models with coding-agent harnesses do well in software engineering, where structured environments and verifiable execution enable multi-step reasoning and self-correction. AEC tasks instead require multimodal understanding: a single construction drawing sheet contains tightly packed annotations, callouts, line work, and cross-references distributed across highly multimodal documents, breaking text-search tools.

Standard tools in popular agent harnesses (text extraction) flatten spatial structure, while vision-based tools lack the quality needed for reliable geometric reasoning. Agents therefore retrieve incomplete or incorrect context, leading to compounding errors. AEC-Bench is built to study these limitations: a scaffolded collection of tasks drawn from coordination practices — intra-sheet review, cross-sheet navigation, and project-level document alignment.

**Figure 1 (described):** Mean reward by AEC-Bench category (Intra-Project, Intra-Drawing, Intra-Sheet) across Codex (H and H+), Claude (H and H+), and Nomic Agent. Representative numbers: Nomic Agent reaches 62 / 88.3 / 70.6 across the three categories; Codex H+ 57.2 / 77.2 / 50; Claude H+ 57.8 / 72.3 / 62.5.

**Figure 2 (described):** Example of a complex construction drawing PDF page — visually dense sheet with tightly packed annotations, callouts, and linework typical of real construction coordination artifacts.

### 1.1 Contributions

- Introduce AEC-Bench, a multimodal benchmark for agentic systems in engineering and construction, with a taxonomy spanning intra-sheet, intra-drawing, and intra-project reasoning.
- Domain-expert-curated benchmark with **196 instances across 9 task families**, grounded in construction coordination workflows and paired with automated evaluation.
- Show that general-purpose coding-agents partially generalize to AEC tasks but fail on visual grounding, exhaustive traversal, and cross-document coordination.
- Demonstrate that domain-specific tools like parsing improve performance on some retrieval-sensitive tasks, but further work is required for grounding and judgment-heavy tasks.

### 1.2 Related Work

AEC-Bench characterizes the boundary points of agent performance in high-value construction coordination. Coordination tasks require multimodal document understanding and context engineering over long horizons. Recent benchmarks (SWE-bench, GAIA, BFCL, AgentBench, WebArena) show tool use, scaffolding, and verifier design strongly influence measured capabilities.

Multimodal/document understanding line: DocVQA, InfographicVQA, DUDE, MMLongBench-Doc, LongDocURL, M-LongDoc, M3DocVQA, MMMU, ChartQA. Agent-document work: DocPrompting, ViDoRe.

Recent AEC-specific benchmarks: Liang et al. (2026) — hierarchical benchmark for LLM knowledge evaluation in AEC (focuses on knowledge, not tool-using agents). AECV-Bench (Kondratenko et al., 2026) — multimodal understanding of drawings (OCR, counting, spatial reasoning, QA over floor plans); finds current MM models can function as document assistants but lack robust drawing literacy, especially symbol-centric understanding. Galanos (2026) on benchmarking agents in real engineering environments.

AEC-Bench is closer to **workflow evaluation for agentic systems** than to static knowledge testing or document visual QA — success depends on retrieval, cross-sheet navigation, cross-document reasoning, and structured reporting under an execution harness.

### 1.3 Construction Coordination

Physical assets are designed and built by skilled professionals over years of training. Although designers use 3D tools (Revit, AutoCAD), most stages of design development, coordination, and delivery are coordinated through 2D construction drawing sets and related documents. A drawing set is a multi-page multimodal instruction package conveying meaning through plans, details, callouts, notes, and title blocks alongside related project specifications.

Coordination failures between architects, engineers, and construction teams are often the main drivers of scheduling delays and budget overruns. Many delays during pre-construction stem from inconsistencies in authoring/revising drawing sets and project documents. Industry teams therefore rely on standardized review and coordination workflows demanding deep professional experience and multimodal reasoning. Some checks need only a single sheet; others trace references across sets or coordinate information across multiple project artifacts. The benchmark taxonomy reflects this scope.

### 1.4 Task Taxonomy

Tasks are organized by how much context an agent needs.

- **Intra-Sheet** — completable from a single sheet (one PDF page). E.g., checking whether callouts match the elements they point to, verifying detail titles, reviewing a local assembly. Focus: understanding what is on the page and interpreting relationships between text and multimodal drawing elements.
- **Intra-Drawing** — requires reasoning across multiple sheets within the same drawing set. E.g., validating cross-references, comparing sheet indices, tracing details across views. Focus: navigating between pages, interpreting and storing multimodal information, tracking related information across the set.
- **Intra-Project** — involves multiple documents (drawings, specifications, submittals). E.g., identifying spec-vs-drawing conflicts, evaluating compliance across sources. Reflects real project-level coordination where information is distributed across documents.

### 1.5 Task Formulation

Each instance consists of a natural-language instruction, a sandboxed execution environment, and an automated verifier. The environment contains real construction documents (drawings, specifications, submittals) sourced from public-sector projects, with pre-installed utilities for PDF rendering and text extraction. Tasks use the **Harbor task format** and run inside the **Harbor harness** (Harbor Framework Team, 2026), which provides a consistent interface for agent interaction and supports tool-based execution through terminal-style commands.

The agent explores the document set, retrieves relevant information, and produces structured findings in a standardized JSONL output file. The framework is **outcome-driven**: agents are scored only on the correctness and completeness of their final output as graded by a professional engineer or architect — not on intermediate actions. Each instance is scored by a task-specific automated verifier against known ground truth: full credit for complete and correct findings, partial credit for partial outputs, zero for incorrect or unsupported results.

### 1.6 AEC-Bench Multimodal Subset

Constructed with a semi-automated pipeline: expert-authored task templates + structured extraction from real-world drawing packages sourced from publicly available PDFs. Disciplines covered: architectural, structural, civil, mechanical, electrical, plumbing.

Pipeline:
1. PDF toolchain breaks multi-page documents into structured, machine-readable data — text with layout, geometric regions, cross-sheet references. Artifacts cached with source coordinates for full traceability.
2. Domain experts select target pages and regions from the cache, then inject realistic, precisely localized artifacts (mismatched callout labels, broken cross-reference targets, swapped specification values) using **alignment-aware text editing** that preserves visual fidelity.
3. Each injected artifact is verified with text-level assertions and pixel-level differencing (before, after, diff) to confirm the edit is structurally sound and visually consistent.

**Figure 3 (described):** Before/after snapshots for two task families. (a)/(b) Cross-reference resolution — subtle reference-number inconsistencies requiring cross-sheet verification. (c)/(d) Note-callout accuracy — callout text changed while preserving leader geometry, testing precise text-to-geometry grounding. Edits are introduced with minimal visual disruption to maintain realistic context.

Final subset: **196 task instances, 9 task types, 3 scopes**.

## Table 1 — Dataset summary by task

| Category | Task | Description | Instances |
|---|---|---|---|
| Intra-Sheet | detail-technical-review | Answer localized technical questions about details. | 14 |
| Intra-Sheet | detail-title-accuracy | Verify whether detail titles match the drawn content. | 15 |
| Intra-Sheet | note-callout-accuracy | Verify whether callout text correctly describes the referenced element. | 14 |
| Intra-Drawing | cross-reference-resolution | Identify cross-references that do not resolve to valid targets. | 51 |
| Intra-Drawing | cross-reference-tracing | Find all source locations referencing a given target detail. | 24 |
| Intra-Drawing | sheet-index-consistency | Compare sheet index entries against title blocks for mismatches. | 14 |
| Intra-Project | drawing-navigation | Locate the correct file, sheet, and detail given a query. | 12 |
| Intra-Project | spec-drawing-sync | Identify conflicts between specifications and drawings. | 16 |
| Intra-Project | submittal-review | Evaluate submittals for compliance with specs and drawings. | 36 |
| **Total** | | | **196** |

## 2. Baseline Agent Evaluation Setup

Goal: understand how harness design shapes performance on AEC tasks, not to compare foundation models in isolation. Two general-purpose coding-agent harness families: **Codex** and **Claude Code**.

- **Base setting (H):** Agents operate in a sandboxed environment with terminal (Bash) access and standard utilities for navigating document space, including CLI-based PDF tools. Agents are free to write and execute their own code to process documents, create intermediate cache files, and search across files. Reflects typical coding-agent workflows — documents treated as files to search, parse, manipulate via CLI, often supplemented with rendered images.
- **Augmented (H+):** Same harness, but agents are also provided structured representations of drawings — extracted text, layout elements, reference relationships — generated using Nomic tools (**Nomic Parse**, **Nomic Embeddings**; Nussbaum et al., 2025).

This isolates the effect of representation and orchestration on agent performance by holding the environment and tasks constant. Tests two hypotheses: (a) whether general-purpose coding-agent harnesses transfer to AEC tasks, (b) whether structured parsing improves performance, and (c) whether domain-aware orchestration can overcome the limitations of general-purpose systems.

## 3. Results

Mean reward 0–100 (higher better) by task in three categories (Intra-Sheet, Intra-Drawing, Intra-Project). Task-specific accuracy metrics scored on structured JSON output. Single trial per instance; reward computed directly from the verifier without averaging. Reward functions evaluate multiple findings per task instance, capturing correctness and completeness for acceptance by a trained architect/engineer.

## Table 2 — Mean reward by task, model, and setup

Bold (omitted here) marks the higher score for each model–task pair.

| Category | Task | GPT-5.4 H | GPT-5.4 H+ | GPT-5.2 H | GPT-5.2 H+ | Opus 4.6 H | Opus 4.6 H+ | Sonnet 4.6 H | Sonnet 4.6 H+ |
|---|---|---|---|---|---|---|---|---|---|
| Intra-Sheet | detail-technical-review | 35.7 | 71.4 | 60.7 | 85.7 | 35.7 | 78.6 | 53.6 | 78.6 |
| Intra-Sheet | detail-title-accuracy | 60.0 | 60.0 | 60.0 | 40.0 | 46.7 | 73.3 | 86.7 | 73.3 |
| Intra-Sheet | note-callout-accuracy | 28.6 | 28.6 | 28.6 | 14.3 | 0.0 | 35.7 | 42.9 | 35.7 |
| Intra-Drawing | cross-reference-resolution | 84.3 | 77.5 | 61.0 | 67.6 | 79.0 | 72.5 | 73.9 | 68.6 |
| Intra-Drawing | sheet-index-consistency | 97.6 | 81.9 | 82.1 | 85.0 | 71.4 | 85.5 | 72.6 | 76.0 |
| Intra-Drawing | cross-reference-tracing | 89.2 | 77.1 | 79.5 | 73.8 | 56.4 | 62.0 | 59.2 | 69.3 |
| Intra-Project | spec-drawing-sync | 55.0 | 71.8 | 44.0 | 50.0 | 29.0 | 51.3 | 26.0 | 64.1 |
| Intra-Project | drawing-navigation | 66.7 | 100.0 | 83.3 | 83.3 | 75.0 | 100.0 | 75.0 | 91.7 |
| Intra-Project | submittal-review | 15.0 | 19.0 | 11.8 | 19.0 | 17.1 | 16.7 | 6.5 | 23.1 |

## 4. Discussion

A central finding: multimodal AEC tasks **tightly couple retrieval and reasoning, and retrieval is frequently the primary bottleneck**. Agents often fail before reaching the core reasoning step because they cannot reliably locate the relevant sheet, detail, or document. Once correct context is retrieved, performance improves substantially.

Under H+, substantial average gains appear on retrieval-sensitive tasks:
- **detail-technical-review: +32.2%** points average across models.
- **spec-drawing-sync: +20.8%**.
- **drawing-navigation: +18.75%**.

These tasks primarily depend on locating the correct sheet/detail/document before reasoning can proceed. Better structured/retrievable context translates directly into higher task performance.

Parsing provides **targeted benefits, not uniform gains**. On visual-spatially grounded tasks parsing can hurt:
- note-callout-accuracy: **−3.6%** points avg
- cross-reference-resolution: **−2.4%** points
- sheet-index-consistency: **−0.1%**
- cross-reference-tracing: **−0.53%**

note-callout-accuracy and cross-reference-tracing both require precise localization and text-to-geometry alignment. The model must trace leader lines and related geometry purely visually — a concrete failure mode for current foundation-model harnesses. Even when evidence exists in the parse, agents fail to localize it accurately; added parsed context can introduce more material the agent must navigate, also increasing token usage.

**submittal-review** is a distinct failure mode: consistently low across all models and setups (best reward 23.1) even with parse available. Parsing improves text access but doesn't resolve the need for higher-level judgment or sufficiently reduce the search space in long trajectories. Agents over-generate findings → high false-positive rate. The task also has inherent subjectivity — correct outputs depend on domain-specific judgment and prioritization consistent with professional review standards, making evaluation sensitive to human interpretation.

### Tool-call patterns

- **Codex-based agents (GPT-5.2 / 5.4):** rely entirely on Bash (100% of interactions). Avoid higher-level abstractions like structured read/write tools — treat AEC documents as source code.
- **Claude-based agents:** more diverse (53% Bash, 35% Read), but still predominantly CLI-style.
- **77% of trajectories invoke `pdftotext`** — strong convergence on a pdftotext extraction pipeline. Enables efficient keyword search but collapses spatial layout and geometric relationships into linear text, discarding visual structure.
- **Codex agents rasterize via `pdftoppm` 96% of runs; Claude only 32%.** More image rendering does NOT translate to better performance on visually grounded tasks — access to images alone is insufficient without the ability to interpret spatial relationships.

Coding-agents apply their existing CLI search/text-extract/image-render paradigm rather than adapting to the multimodal structure of construction documents, leading to systematic failures on tasks requiring geometric reasoning and precise spatial grounding.

### Visual vs. text-catchable defects in note-callout-accuracy

Of 14 instances × 4 models = 56 runs:
- **Text-catchable cases (2 instances):** mean reward **100%**.
- **Visual-required cases (10 instances):** mean reward **5%**, meaningful outputs primarily from Claude Sonnet; no success from other models.
- **Clean cases (2 instances).**

Failures aren't due to lack of visual access (trajectories show extensive image rendering and inspection) but inability to translate visual input into structured, spatially grounded judgments.

### 4.1 Limitations

Limited number of documents and a subset of tasks per category/discipline — may constrain statistical robustness and capability coverage. Tasks don't fully capture the breadth of modern LLM-harness abilities, and some families rely on curated/controlled defects that may not reflect full real-world diversity. Most tasks use deterministic verifiers checking specific keywords or structured outputs — scalable and reproducible but may not capture nuanced human judgments of engineering correctness or practical relevance.

### 4.2 Replicability and License

Benchmark, agent harnesses, and evaluation code at https://github.com/Nomic-ai/aec-bench. Apache 2.

### 4.3 Future Directions

- Expand scale/diversity — larger drawing sets, more disciplines, more task families.
- Better evaluation methods — verifiers that assess evidence grounding and reasoning steps, not just unidirectional static matching.
- Agentic systems designed specifically for document navigation: iteratively explore drawing sets, maintain spatial memory on sheets, retrieve evidence regions prior to reasoning.
- Stronger domain knowledge built into multimodal models for tasks needing engineering judgment.

## 5. Conclusion

AEC-Bench evaluates multimodal, agentic reasoning in construction-document coordination workflows grounded in real-world design and engineering practice. Framing tasks around common review activities (reference tracing, navigation, coordination across drawings and specifications) reflects practical AEC coordination workflows; outputs are graded by domain experts.

Findings: multimodal data representation and context engineering play a central role in shaping AEC agent performance within current harnesses. Coding-agent systems transfer meaningfully to this domain for tasks addressable through retrieval and structured reasoning, but become inconsistent when spatial grounding or domain-sensitive judgment is required. Both visual inputs and structured parsing improve information access, but neither is sufficient in isolation — effective performance emerges from how modalities are coordinated and surfaced within the agent loop. The work points to the importance of domain-aware system design that orchestrates multiple capabilities to match task demands.

## References (selected)

- Chia et al., 2025 — M-LongDoc.
- Cho et al., 2025 — M3DocVQA.
- Deng et al., 2025 — LongDocURL.
- Galanos, 2026 — Benchmarking agents on real engineering work (theharness.blog).
- Harbor Framework Team, 2026 — Harbor: framework for evaluating and optimizing agents and models in container environments.
- Jimenez et al., 2024 — SWE-bench.
- Kondratenko et al., 2026 — AECV-Bench.
- Landeghem et al., 2023 — DUDE.
- Liang et al., 2026 — AECBench (hierarchical knowledge evaluation in AEC). *Advanced Engineering Informatics*, 71:104314.
- Liu et al., 2024 — AgentBench.
- Loison et al., 2026 — ViDoRe v3.
- Ma et al., 2024 — MMLongBench-Doc.
- Masry et al., 2022 — ChartQA.
- Mathew et al., 2021 — DocVQA.
- Mialon et al., 2023 — GAIA.
- Nussbaum et al., 2025 — Nomic Embed.
- Patil et al., 2025 — BFCL.
- Yue et al., 2024 — MMMU.
- Zhou et al., 2023 — WebArena.
- Zhou et al., 2024 — DocPrompting.
