"""Controlled revoke of V4 daily_sim_probe approval for PUBG: Black Budget."""
from __future__ import annotations

import sqlite3

from . import config
from .approval import LANE_STAGING, ApprovalStore


def main() -> None:
    # Init schema (adds approval_class / lane columns) before SELECT.
    store = ApprovalStore(lane=LANE_STAGING)
    con = sqlite3.connect(config.STAGING_DB)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT igdb_id, name, staging_status, approval_note, approval_class "
        "FROM discovery_candidates WHERE igdb_id=370112"
    ).fetchone()
    print("before", dict(row) if row else None)
    if row and row["approval_note"] == "daily_sim_probe":
        con.execute(
            "UPDATE discovery_candidates SET approval_class=?, approval_lane=?, "
            "approval_actor=? WHERE igdb_id=370112",
            ("simulation", "staging", "local_reviewer"),
        )
        con.commit()
    con.close()
    result = store.revoke_simulation_approval(
        370112,
        note=(
            "V5 controlled revoke: approval was created solely by daily_sim_probe; "
            "history retained in discovery_approval_log; not a human decision."
        ),
        actor="v5_controlled_revoke",
    )
    print("revoke", result)
    after = store.get_candidate(370112)
    print(
        "after",
        {
            "status": after.get("staging_status") if after else None,
            "class": after.get("approval_class") if after else None,
            "lane": after.get("approval_lane") if after else None,
            "note": after.get("approval_note") if after else None,
        },
    )
    for entry in store.recent_log(10):
        if entry["igdb_id"] == 370112:
            print("log", entry)


if __name__ == "__main__":
    main()
