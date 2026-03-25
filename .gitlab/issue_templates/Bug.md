<!-- Labels: type::bug, priority::medium, status::triage -->

































/label ~"type::training" ~"status::triage" ~"priority::medium" ~"component::autoresearch"<!-- arXiv links, prior runs (MLflow URLs), related training issues -->## References- [ ] Model saved to standard path- [ ] MLflow run logged at `http://localhost:8080`- [ ] No OOM during training- [ ] Metric target reached: ## Success criteria- **Block z-image during run:** Yes / No- **Estimated runtime:** - **Estimated VRAM:** GB (must be ≤ 23 GB on RTX 3090 Ti)## Hardware plan<!-- Algorithm, architecture, hyperparameter changes, or curriculum update. -->## Approach- **GPU:** RTX 3090 Ti (cuda:0) — RTX 2070 (cuda:1) unavailable for training- **Target metric:** - **Dataset:** - **Model:** <!-- What model / task is being trained? What metric are we optimising? -->## Training goal## What happened?

<!-- Clear, one-sentence description of the bug. -->

## Expected behaviour

<!-- What should have happened? -->

## Actual behaviour

<!-- What actually happened? Include error messages verbatim. -->

## Steps to reproduce

1. 
2. 
3. 

## Environment

- **Service / container:** 
- **GPU:** RTX 3090 Ti (cuda:0) / RTX 2070 (cuda:1) / N/A
- **Commit / version:** 
- **Logs:** (paste relevant lines or link to `docker logs <container>`)

## Severity

- [ ] **Critical** — system down / data loss
- [ ] **High** — major feature broken, no workaround
- [ ] **Medium** — partial breakage, workaround exists
- [ ] **Low** — cosmetic or minor inconvenience

## Agent suitability

<!-- Can this be fixed autonomously by Qwen3.5? -->
- [ ] **Yes** — isolated fix, < 5 files, clear root cause
- [ ] **Needs review** — > 5 files or cross-service change
- [ ] **Human only** — requires infrastructure access or credentials

/label ~"type::bug" ~"status::triage" ~"priority::medium"
