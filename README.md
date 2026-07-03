# HutchStack Cortex

Cortex is an append-only, immutable commitment ledger that forms the kernel of truth for the HutchStack ecosystem. It is designed to track reality (Observations, Evidence, Claims, Decisions) without permitting mutation or deletion.

## Version
`0.9.0-beta.1`

## Setup Instructions

### Option 1: Docker (Recommended)
You can run Cortex instantly using Docker:
```bash
docker build -t cortex-core .
docker run -p 8000:8000 cortex-core
```
The API will be available at `http://localhost:8000/docs`.

### Option 2: Local Python Setup
Ensure you have Python 3.11+ installed.

1. Install dependencies:
   ```bash
   pip install -r backend/requirements.txt
   ```
2. Run the server:
   ```bash
   cd backend
   uvicorn main:app --reload
   ```

## Running Tests

To run the test suite, ensure your dependencies are installed, then from the root of the repository run:
```bash
pytest
```
The `pytest.ini` automatically sets the python path and locates the tests in `backend/tests`.

## Beta Limitations
Please review `SECURITY.md` for current limitations. Most notably, cryptographic signature validation is currently mocked in the Beta release.
