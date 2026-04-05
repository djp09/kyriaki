# Security Policy

Kyriaki handles protected health information (PHI) for cancer patients
searching for clinical trials. Reports that expose patient data, break the
PHI boundary, or weaken audit integrity are treated as top priority.

## Supported Versions

Kyriaki is pre-1.0. Only the `main` branch receives security fixes at this
stage. Once a tagged release exists, the table below will track supported
versions.

| Version | Supported |
|---------|-----------|
| `main`  | Yes       |

## Reporting a Vulnerability

Please **do not** open a public issue for security reports.

Use GitHub's private vulnerability reporting:
<https://github.com/anthropics/kyriaki/security/advisories/new>

What to include:

- A clear description of the issue and its impact.
- Steps to reproduce (a minimal proof-of-concept is ideal).
- The commit SHA or branch you reproduced against.
- Whether the issue involves real or synthetic PHI. **Never attach real
  patient data.** Use the synthetic patients under `backend/eval/` or
  fabricated examples only.

We will acknowledge receipt within three business days and aim to issue a
fix or mitigation plan within thirty days for high-severity issues.

## Scope

In scope:

- The PHI boundary (`backend/phi/boundary.py`, `backend/phi/deidentify.py`).
- At-rest encryption and key handling (`backend/phi/crypto.py`,
  `backend/phi/keys.py`, `backend/phi/profile_storage.py`).
- The audit log and chain verifier (`backend/phi/audit.py`,
  `scripts/verify-audit-chain.py`).
- Backend API endpoints that touch patient profiles or match sessions.
- Dependencies: any direct dependency listed in `backend/requirements.txt`
  or `frontend/package.json` with a known CVE.

Out of scope:

- Self-hosted deployments running outside the reference configuration.
- Findings that depend on a malicious operator of your own instance
  (operators already hold the keys).
- Social engineering of project maintainers or users.

## HIPAA Implementation Guide

Running Kyriaki against real PHI requires a HIPAA-compliant deployment.
See [`docs/hipaa-implementation-guide.md`](docs/hipaa-implementation-guide.md)
(stub, in progress) and
[ADR-004](.claude/ADRs.md#adr-004--data-security-phi-handling--compliance-posture)
for the full posture.

Minimum checklist before accepting real PHI:

1. Signed Business Associate Agreement (BAA) with the model provider
   (Anthropic) and every infrastructure vendor that touches PHI.
2. `KYRIAKI_PHI_ENCRYPTION_KEYS` and `KYRIAKI_PHI_ACTIVE_KEY_ID` set from
   a managed key store (AWS KMS, GCP KMS, HashiCorp Vault).
3. `scripts/check-phi-boundary.sh` passing in CI.
4. `scripts/verify-audit-chain.py` scheduled nightly.
5. TLS 1.3 everywhere; storage encrypted at rest at the disk layer too.
6. Documented incident response runbook and tested break-glass procedure.

Until those are in place, use synthetic patients only.
