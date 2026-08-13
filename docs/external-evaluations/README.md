# External Evaluation Submissions

Place the two unmodified qualifying JSON bundles in this directory only after
independent evaluator teams have completed the documented workflow. Do not add
sample, synthetic, locally generated, or hand-edited PASS artifacts.

Strict release validation is:

```bash
python oms/validate_external_evaluations.py
```

The absence of JSON files is intentionally a failing release gate.
