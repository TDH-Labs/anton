# Progress — AUTHZ-SPEC build (harbor-sas)

## Review

- **Correct:** `docs/AUTHZ-SPEC.md` (v1.1) integrates all three adversarial
  reviews into 40 MUST/SHOULD requirements across 10 control domains, plus
  the binding convergence threshold (CONV-1) and NIST AI RMF / SOC2
  CC6.1/CC6.3 mapping (CONV-2). Every requirement carries a finding trace
  and a named adversarial CI test; Appendix A is a complete finding→REQ
  coverage matrix (all R1-F1..12, R2-I1..7, R2-N1..7, R3-O1..16 mapped).
- **Hostile self-critique pass found 5 issues, all fixed in v1.1:**
  - MAJOR: credential-broker attestation was undefined → specified as
    broker-issued execution lease + SO_PEERCRED uid check (REQ-CRED-02).
  - MAJOR: confirmation-fatigue budget had no mechanism → per-principal
    daily budget converting to hard-block + Approver routing (REQ-EGRESS-03).
  - MAJOR: single-operator mode implied trigger drops contradicting the
    schema-hash invariant → triggers write to pending-actions table with
    delay window; schema invariant set identical in both modes (REQ-APPR-05).
  - MAJOR: reverse-proxy/header trust boundary unaddressed (R1-F12 gap) →
    added REQ-DEPLOY-01 with trusted-proxy allowlist + CI test.
  - MAJOR: recovery re-key semantics ambiguous → broker master-key rotation
    + forced token refresh with surfaced degraded period (REQ-APPR-04).
- **Note:** Spec is a document deliverable only — no code exists yet for
  any REQ; convergence (CONV-1: two consecutive independent PROCEED
  verdicts, zero BLOCKER/MAJOR) cannot be claimed until implementation +
  hostile-test corpus exist. OPEN items (SSO, budgets, session heuristics,
  second audit container, k calibration) are tracked in Appendix B.

Commits: 648f714 (v1.0), 5ebab33 (v1.1). Both pushed to main.
