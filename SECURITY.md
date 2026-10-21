# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Report them privately using
GitHub's [private vulnerability reporting](https://github.com/Maz2580/geospark/security/advisories/new),
and include steps to reproduce. You should hear back within a week.

## Supported versions

Security fixes go into the latest release on PyPI (`geospark-ai`) and the hosted API at
geospark.terrascout.app.

## Deployment model

The hosted API is intentionally public. See [deploy/DEPLOY.md](deploy/DEPLOY.md#security) for
which routes need the operator token and the limits applied to public callers.
