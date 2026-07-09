"""Finding kinds for the foodservice-vs-electrical schedule check."""

from __future__ import annotations

FS_ELEC_FINDING_KINDS = (
    "fs_elec_field_mismatch",        # a value differs (volts/phase/amps/kw/conn/height)
    "fs_elec_nominal_voltage_variance",  # 115V vs 120V class (equivalent, low sev)
    "fs_elec_qty_mismatch",          # FS QTY != distinct electrical units
    "fs_item_missing_in_electrical",  # FS item has electrical data, no electrical mark
    "fs_item_no_elec_data",          # electrical mark exists but FS row shows no power
    "elec_mark_missing_in_fs",       # electrical mark resolves to no FS item
)

# The electrical-relevant fields compared between the two schedules.
COMPARE_FIELDS = ("volts", "phase", "amps", "kw", "elec_conn_type", "elec_rough_in_aff")
