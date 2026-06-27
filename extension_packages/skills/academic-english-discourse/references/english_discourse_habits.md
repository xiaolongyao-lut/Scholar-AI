# Academic English Discourse Habits

This reference defines the distilled English academic-writing habits used by Scholar AI before it retrieves phrase examples.

## Core Habit

Academic English is not only polished wording. It is a way of arranging claims so that the reader can see the discourse move, evidence base, certainty level, and scope.

Before rewriting or translating, identify the sentence function:

- `territory`: establish the topic or field.
- `gap`: mark what remains unresolved.
- `aim`: state what the paper, review, or section does.
- `method`: describe design, materials, data, procedure, or analytical approach.
- `citation`: attribute or synthesize prior work.
- `comparison`: show convergence, contrast, or extension.
- `causality`: express mechanisms, causes, effects, or pathways cautiously.
- `result`: report an observation or finding.
- `interpretation`: explain what a finding may mean.
- `limitation`: bound the inference.
- `implication`: state contribution or future direction.
- `transition`: move between claims, paragraphs, or sections.

## Information Flow

Prefer this order:

```text
known context -> focused claim -> evidence or method -> scope or implication
```

Chinese source prose often begins with broad background, conditions, and topic-comment chains. English academic prose usually needs a visible grammatical subject and an early research action.

Use this conversion:

```text
在...背景下，围绕...，本文...
-> This study examines {object} in {scope}, with particular attention to {focus}.
```

## Evidence And Certainty

Choose verbs by evidence strength:

- `may`, `might`, `could`, `appears to`: weak inference or limited evidence.
- `suggests`, `indicates`, `points to`: evidence supports an interpretation.
- `shows`, `reveals`, `was observed`: direct observation or reported result.
- `demonstrates`, `establishes`: strong design or repeated evidence.
- Avoid `proves` unless the task explicitly involves proof.

Do not hedge facts that are definitional or directly measured. Hedge inference, mechanism, generalization, and causal explanation.

## Literature Review Prose

A literature review paragraph should synthesize relations among studies. Prefer grouping studies by:

- shared claim;
- method or dataset;
- population or context;
- theoretical position;
- convergent or divergent findings.

Avoid this pattern:

```text
Study A found X. Study B found Y. Study C found Z.
```

Prefer this pattern:

```text
Prior studies converge on {shared claim}, but differ in {method/context/explanation}.
```

## Chinese-To-English Rewrite Rules

| Chinese pattern | Academic-English strategy |
| --- | --- |
| 说明 / 表明 / 证明 | Choose `suggests`, `indicates`, `shows`, or `demonstrates` by evidence strength. |
| 研究不足 / 尚不清楚 | State the exact gap: method, population, mechanism, dataset, theory, or context. |
| 具有重要意义 | Replace generic importance with a concrete implication. |
| 有研究表明 | Use a reporting verb and a source relation. |
| 然而 / 但是 | Name the relation: limitation, contrast, exception, or unresolved scope. |
| 随着 / 在...背景下 | Put the research object or problem into subject position early. |

## Acceptance Checks

A generated sentence passes only if:

- its discourse move is visible;
- the claim is attached to evidence or scope;
- certainty is calibrated;
- technical terms are stable;
- citations support the exact claim;
- connectors express real relations;
- the prose sounds like scholarly argument, not generic fluent English.
