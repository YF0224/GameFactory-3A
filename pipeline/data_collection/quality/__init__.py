"""Read-only integrity, honest gap reporting, and direct training reads.

validator — schema checks (never modifies a trajectory); capture_audit —
reports demonstrable capture gaps instead of repairing them; loader —
request-scoped training samples straight from the trajectory files.
"""
