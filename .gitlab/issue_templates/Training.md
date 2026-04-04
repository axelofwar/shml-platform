<!-- Labels: type::training, priority::medium, status::triage, component::autoresearch -->

## Training Goal

<!-- What model, task, or capability are we improving? -->

## Model & Dataset

- **Model**:
- **Dataset**:
- **Framework**: Ray / SHL-Nano / other

## Target Metric

<!-- e.g. "val_loss < 0.05", "mAP > 0.85 on validation set" -->

## Resource Estimate

- **GPU**: RTX 3090 Ti (cuda:0) / RTX 2070 (cuda:1) / both
- **Estimated VRAM**:
- **Estimated wall-clock time**:
- **Competing workloads**: check with `task gpu`

## Success Criteria

- [ ]
- [ ] Model checkpoint saved to `models/`
- [ ] MLflow run logged with final metrics
- [ ] No OOM / LPE errors in logs

## Notes

<!-- Data preprocessing, hyperparameter rationale, related experiments. -->

## Agent suitability

- [ ] **No** — training jobs are hardware-bound and managed by the SHL-Nano pipeline
- [ ] **Partial** — agent can write the training script; human runs it

/label ~"type::training" ~"status::triage" ~"priority::medium" ~"component::autoresearch"
