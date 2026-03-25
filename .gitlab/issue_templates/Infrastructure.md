<!-- Labels: type::chore, priority::low, status::triage -->

## What needs to be done?

<!-- Describe the infrastructure / maintenance task concisely. -->

## Why now?

<!-- Urgency or risk if left undone. Link to related alerts or CI failures. -->

## Affected areas

- Services: 
- Files: 
- Networks / volumes: 

## Validation

<!-- How do we confirm this is done correctly? -->

- [ ] Service restarts cleanly
- [ ] No regressions in `./start_all_safe.sh status`
- [ ] CI passes
- [ ] 

## Agent suitability

- [ ] **Yes** — config/code change only, no manual infra steps
- [ ] **Partial** — agent writes the code, human applies it
- [ ] **Human only** — requires server access, secret rotation, or physical intervention

/label ~"type::chore" ~"status::triage" ~"priority::low"
