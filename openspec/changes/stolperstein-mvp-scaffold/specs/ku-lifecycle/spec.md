## ADDED Requirements

### Requirement: KU state machine

Each KU SHALL have a `status` field following this state machine: `draft` -> `active` -> `stale` -> `archived`. Additionally, any non-archived KU can transition to `disputed`. Transitions SHALL be: draft->active (on first confirmation), active->stale (on staleness threshold breach), stale->active (on re-confirmation), active->disputed (on flag), disputed->active (on sufficient re-confirmations), any->archived (on flag with reason `superseded` or manual archive).

#### Scenario: KU graduates from draft to active

- **WHEN** a KU in `draft` status receives its first `confirm` call
- **THEN** the server SHALL transition the KU to `active` status

#### Scenario: KU decays to stale

- **WHEN** a KU in `active` status has not been confirmed or queried for longer than its `staleness_policy` threshold (default 90 days)
- **THEN** the server SHALL transition the KU to `stale` and begin confidence decay

#### Scenario: Stale KU revived by confirmation

- **WHEN** a KU in `stale` status receives a `confirm` call
- **THEN** the server SHALL transition back to `active`, reset the staleness timer, and recalculate confidence upward

### Requirement: Confidence scoring algorithm

The confidence score SHALL be a float between 0.0 and 1.0, calculated as: base confidence (0.5 on creation) adjusted by confirmations (weighted by organizational diversity), temporal decay (linear decay after staleness threshold), and dispute penalty (capped at 0.5 when disputed). The formula SHALL weight diversity of confirming sources over raw confirmation count.

#### Scenario: Confidence increases with diverse confirmations

- **WHEN** a KU receives confirmations from 3 different agents across 2 different projects
- **THEN** the confidence SHALL increase more than if 3 confirmations came from the same agent on the same project

#### Scenario: Confidence decays over time without activity

- **WHEN** a KU has not been confirmed or queried for 90+ days
- **THEN** the confidence SHALL decrease linearly, at a rate of 0.01 per day past the threshold, until reaching a floor of 0.1

#### Scenario: Disputed KU confidence is capped

- **WHEN** a KU is flagged as `incorrect` or `dangerous`
- **THEN** the confidence SHALL be immediately capped at 0.5 regardless of prior confirmations

### Requirement: Staleness policy is configurable per KU

Each KU SHALL have a `staleness_policy` field (default: `confirm_or_decay_after_90d`) that defines the decay threshold in days. The policy SHALL be settable at propose time and modifiable via a future admin tool.

#### Scenario: KU with custom staleness policy

- **WHEN** a KU is proposed with `staleness_policy: "confirm_or_decay_after_30d"`
- **THEN** the staleness timer SHALL use 30 days instead of the default 90

#### Scenario: Staleness check runs on query

- **WHEN** a `query` or `status` call is made
- **THEN** the server SHALL evaluate staleness for returned/counted KUs based on current time vs. `last_confirmed` + policy threshold, transitioning any newly-stale KUs before returning results
