# HRIS Import: Diversio Exercise Preview

## Setup and run

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
uvicorn hris_import.web:app --reload
```

Open http://127.0.0.1:8000 and upload a CSV (try `sample_hris.csv`).

## Tests and lint

```bash
pytest -v
ruff check .
```

## Framework choice

- Django is preferred by the exercise, but I used FastAPI.
- FastAPI is what I actually have hands-on experience with (built two backend projects on it).
- The core logic (parsing, validation, graph) is plain Python with no framework dependency. The framework only affects `web.py` and the template rendering.

## Assumptions

- Both manager fields blank = a real root. This is different from an employee whose manager reference just failed to resolve.
- An employee with a manager error is still "accepted," but isn't a root and doesn't produce a reporting edge.
- If both `manager_id` and `manager_email` are given, they must point to the same person. If either can't be found, or they disagree, that's an error.
- Only employees strictly inside a cycle are flagged as cyclic. Someone reporting into a cycle is not counted as cyclic themselves.
- Duplicate employee_id/email rows are dropped entirely from the hierarchy, on both sides: they can't be someone's manager, and their own manager isn't resolved either.

## Complexity

- Parsing: O(n), single pass.
- Identity validation: O(n) using Counters for duplicate detection.
- Manager resolution: O(n) using dicts for O(1) lookups, not list scanning.
- Cycle detection: O(n) total. Each employee has only one manager, so this is a "functional graph," not a general graph. A visiting/done state map means every node is checked once, not once per starting point.
- At 100k employees, all of this stays linear. The real bottleneck would be holding the whole file in memory — a streaming parser would be the next step if files got much bigger.

## Known limitations

- No persistence, per the spec.
- Minimal HTML, no styling, as instructed.
- Full file is read into memory before parsing; no true streaming.

## Time spent

- ~90 minutes on the initial build.
- ~15-20 more minutes in a follow-up session fixing a bug (see below).
- Excludes this README and the recording.

## AI tools used

- Used an AI assistant to scaffold the FastAPI/Jinja2 boilerplate and talk through the cycle-detection approach before writing it myself.
- Wrote and understood the validation and cycle-detection logic directly. Verified it by hand against the sample CSV (traced the cycle, conflict, and unresolved-manager cases manually) before writing tests.
- While writing the parser, I missed lowercasing `email` and `manager_email` consistently. This silently broke manager resolution for any row with an uppercase email. My tests didn't catch it, since I hadn't written a mixed-case test.
- Found it through manual testing against the real sample CSV. Used Claude Code in VS Code to help pinpoint the exact line. Understood and verified the fix myself, then re-ran the sample data and full test suite to confirm.