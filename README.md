# HRIS Import: Diversio Exercise Preview

## Setup and run

```bash
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn python-multipart jinja2 pytest
uvicorn main:app --reload
```

Open http://127.0.0.1:8000 and upload a CSV.

## Tests

```bash
pip install httpx  # only needed if you also run the FastAPI TestClient
python3 -m pytest tests/ -v
```

## Framework choice

Django is preferred by the exercise, but I used FastAPI instead because
it's the framework I have direct, hands-on production experience with
(built two backend projects on it). The core parsing/validation/graph
logic is plain Python with no framework dependency, so the choice of
web layer only affects `main.py` and the template rendering, not the
actual hierarchy analysis.

## Assumptions

- "Both manager fields blank" means a literal root, distinct from an
  employee whose manager reference failed to resolve. An employee with
  a manager error stays "accepted" (per the spec) but is excluded from
  both the root list and the manager-count table, since they don't
  produce a valid reporting edge.
- When both `manager_id` and `manager_email` are supplied, both must
  resolve to the same employee. If either can't be found at all, or
  they resolve to different people, it's an error.
- Cycle membership is limited to employees that are strictly part of
  the cycle. An employee reporting into a cycle (but not part of it)
  is not flagged as cyclic.
- Duplicate employee_id/email rows are excluded from hierarchy
  participation entirely, on both sides: they can't be a manager
  reference for anyone else, and their own manager reference is not
  resolved.

## Complexity

- Parsing: O(n) over the file, single pass.
- Identity validation: O(n) using two Counters (employee_id, email) to
  find duplicates, plus one more O(n) pass to build the accepted list.
- Manager resolution: O(n) using two dicts (by_id, by_email) for O(1)
  lookups instead of scanning the employee list per row.
- Cycle detection: O(n) total. Each employee has at most one outgoing
  edge (their manager), so the reporting structure is a "functional
  graph," not a general graph. A state map (visiting/done) ensures
  every node is traversed at most once across all starting points,
  rather than a fresh DFS per employee.

At 100,000 employees, all of the above stay linear and dict-based, so
the approach should scale without algorithmic changes. The main
real-world bottleneck at that scale would be holding the whole parsed
file in memory at once; a streaming/chunked parser would be the next
improvement if files grew much larger than this.

## Known limitations

- No persistence -- results exist only for the current request/response,
  per the spec.
- Minimal HTML/no styling, as instructed.
- Large files are read fully into memory before parsing; true
  constant-memory streaming isn't implemented.

## Time spent

Approximately 90 minutes on implementation (excluding this README and
the recording).

## AI tools used

Used an AI assistant to help scaffold the FastAPI/Jinja2 boilerplate
and talk through the cycle-detection approach for a functional graph
before implementing it myself. I wrote and understood the validation
and cycle-detection logic directly, and verified all of it by hand
against the provided sample CSV (traced the expected cycle, conflict,
and unresolved-manager cases manually, then confirmed the code
produced matching output) before writing the automated tests.