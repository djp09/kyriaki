# Routing Workflow

## Objective
Classify patient complexity before the agent loop starts to configure appropriate budget, model, and strategy hints.

## Classification Rules (deterministic, no API call)

### Category
- **pediatric**: age < 18
- **rare_adult**: cancer_type matches RARE_CANCERS list
- **common_adult**: everything else

### Complexity
- **complex**: pediatric OR rare cancer
- **moderate**: high therapy lines (≥3) OR many biomarkers (≥5) OR unknown cancer type
- **simple**: common cancer with standard profile

## Budget by Complexity

| Complexity | Max Iterations | Max Searches | Max Analyses |
|-----------|---------------|-------------|-------------|
| simple    | 5             | 3           | 20          |
| moderate  | 6             | 4           | 25          |
| complex   | 7             | 5           | 30          |

## Strategy Hints

Injected into orchestrator prompt as `{strategy_hint}`:
- **Pediatric**: search with pediatric-specific terms, check age criteria
- **Rare cancer**: broader searches, synonyms, search by cancer family
- **Heavily pre-treated**: focus on later-line trials, search 'refractory'
- **Complex biomarkers**: multiple searches per key biomarker
- **Standard**: targeted search by cancer type sufficient

## Tools
- `classify_patient(patient: PatientProfile) -> RouteConfig`

## Integration
Called at the start of `MatchingAgent.execute()` before `run_agent_loop()`.
RouteConfig.to_budget() produces the AgentBudget. strategy_hint injected into prompt_vars.
