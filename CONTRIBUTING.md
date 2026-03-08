# Contributing to AFM

Thank you for contributing to Acuity-First Middleware.

> **Critical**: AFM processes clinical data. All contributions must maintain patient safety, data privacy, and the AI-disclaimer requirements defined in `requirements.md` (Req 13).

---

## Getting Started

```bash
git clone https://github.com/YOUR_ORG/swathyahita.git
cd swathyahita
uv sync --dev
cp .env.example .env
```

Tests run entirely with mocked AWS (no real credentials needed):

```bash
uv run pytest tests/ -v
```

---

## Development Workflow

1. **Fork** the repository and create a feature branch from `main`
   ```bash
   git checkout -b feat/my-feature
   ```

2. **Write tests first** — every change to `app/services/` should have corresponding tests in `tests/unit/` or `tests/properties/`

3. **Run the full test suite** before pushing:
   ```bash
   uv run pytest tests/ -v --tb=short
   ```

4. **Open a Pull Request** using the PR template — CI must pass

---

## Code Standards

### Required for every PR

- All existing tests must pass (`50/50`)
- New service logic must have unit tests
- Changes to scoring/classification must have property-based tests (Hypothesis)
- `AI-generated flags for review only` disclaimer must be present in all report API responses
- Every clinician action must produce an audit log entry

### Naming conventions

- Services: `app/services/<service_name>.py` — one concern per file
- Tests: `tests/unit/test_<service_name>.py` — mirrors service file
- Property tests: include the property reference comment:
  ```python
  # Feature: acuity-first-middleware, Property 7: Urgency Score Range
  # Validates: Requirements 4.1
  ```

### AWS service calls

- All boto3 calls go through `app/aws/clients.py` singletons (enables moto mocking)
- Never import `boto3` directly in service files — use `from app.aws.clients import get_*`
- All AWS calls must be inside `try/except` with graceful degradation

---

## Testing

| Test type | Location | Command |
|---|---|---|
| Unit | `tests/unit/` | `uv run pytest tests/unit/ -v` |
| Property-based | `tests/properties/` | `uv run pytest tests/properties/ -v` |
| All | `tests/` | `uv run pytest tests/ -v` |

AWS is mocked via [moto](https://docs.getmoto.org/) — the `conftest.py` sets this up automatically. **Never use real AWS credentials in tests.**

---

## Adding a New AWS Service

1. Add the boto3 client singleton to `app/aws/clients.py`
2. Add the config variables to `app/config.py` and `.env.example`
3. Add moto mock to `tests/conftest.py` `aws_mock` fixture
4. Document new env vars in `docs/DEPLOYMENT.md`

---

## Clinical Logic Changes

Changes to `scoring.py`, `contextual_bridge.py`, or `classifier.py` (the clinical core) require:

- Review from `@YOUR_ORG/clinical-team` (see `CODEOWNERS`)
- Updated property-based tests covering the new behavior
- Reference to the requirement number in comments

---

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(scoring): add pathology-specific scoring rules (Req 12.5)
fix(classifier): handle empty Bedrock response on retry
docs(api): add presigned URL field to report detail response
test(props): add property test for contextual bridge adjustment range
```

---

## No Real Patient Data

**Never** commit, log, or include real patient data anywhere in this repository. Use synthetic test data only.
