# ============================================================================
# DEVFORGE — Metrics CSV Format Specification
# Append one row after every validation pipeline run. No dashboards — spreadsheet only.
# ============================================================================

# HEADER (first row of metrics.csv):
# run_id,timestamp,tick_budget_ms,tick_baseline_ms,tick_delta_ms,boundary_violations_caught,boundary_violations_30d,repair_loop_depth,max_repair_attempts,plan_conformance_flagged,scope_files_estimated,scope_files_actual,scope_accuracy_pct,decision_log_word_count,risk_score,risk_tier,gate1_pass,gate2_pass,gate3_pass

# FIELD DEFINITIONS:
#
# run_id                      — DF-MMDD-NNNN format, matches decision log
# timestamp                   — ISO 8601
# tick_budget_ms              — Absolute tick time measured this run (ms)
# tick_baseline_ms            — Current approved baseline tick time (ms)
# tick_delta_ms               — tick_budget_ms - tick_baseline_ms
# boundary_violations_caught  — Count of Gate 1 violations this run
# boundary_violations_30d     — Rolling 30-day violation count (triggers contract review at 3+ same-type)
# repair_loop_depth           — Number of automated repair attempts before pass or escalation (0-2)
# max_repair_attempts         — Always 2. Included for schema completeness.
# plan_conformance_flagged    — 1 if unplanned patterns detected, 0 otherwise
# scope_files_estimated       — Number of files in scope lock
# scope_files_actual          — Number of files actually modified
# scope_accuracy_pct          — (matched / max(estimated, actual)) * 100
# decision_log_word_count     — Word count of human_rationale field in decision log entry
# risk_score                  — Computed risk score
# risk_tier                   — low / medium / high / critical
# gate1_pass                  — 1 / 0 / null (null if not run)
# gate2_pass                  — 1 / 0 / null
# gate3_pass                  — 1 / 0 / null
