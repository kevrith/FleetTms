# Retention schedule and how it is enforced (draft)

Masterplan 11.3 (proposed) and the Privacy Policy item 7, with the code that carries each row out and the test that proves it. All of it runs from one daily worker job (`retention_job`, 03:50 Africa/Nairobi) apart from GPS (`gps_retention_job`, 03:30). **[ADVOCATE]** confirm the periods, especially for former staff.

| Data | Policy | What happens | Code | Verified by |
|---|---|---|---|---|
| Raw GPS points | 12 months, then only the trip totals | Trip distance totals are finalised, then the raw points are deleted | `tracking_jobs.purge_old_points` | `test_tracking.py` |
| Odometer, receipt and other photos | 24 months, or longer if tied to an open dispute or alert | The picture file is deleted and the place it was taken is cleared; the record of the photo (when, by whom, checks, hash) stays. Kept while tied to an open incident, an unsettled insurance claim, or an open or confirmed fraud alert | `retention.purge_old_photos` | `test_retention.py`: an old photo loses its picture; one tied to an open incident or alert is kept; nothing is purged twice |
| Audit trail | 5 years | Entries older than 5 years are deleted. The database itself refuses to delete anything younger, or anything at all unless the job says so, and never allows editing | `retention.purge_old_audit`, trigger `audit_logs_immutable` (migration 0020) | `test_retention.py`: the database refuses a recent row even with the switch on, and an old row without it |
| Financial records (invoices, payments, expenses, fuel, payroll, leases, loans) | At least 5 years, then deleted or anonymised | Never deleted on a timer while the business is open. After a business cancels they are kept 5 years, then erased with the rest | `retention.erase_business` | `test_retention.py` |
| Former employees | Only as long as employment and tax law require | 5 years after they left (`FORMER_STAFF_RETENTION_DAYS`): staff details and personal documents deleted; the person made anonymous if they work for no other business. What they did stays under the anonymous name | `retention.anonymise_former_staff` | `test_retention.py`: 6 years yes, 1 year no; a person with another employer is not made anonymous |
| A person's own request to delete | On request, where the law allows | Same removal, at once, by the owner; refusal needs a written reason | `routers/data_requests.py` | `test_data_requests.py` |
| Cancelled businesses | Read-only 90 days for export, then permanently deleted except what the law requires | The owner cancels: read-only at once, nothing else changes. After 90 days: every photo file, tracking, messages, questions, exports, document readings, SOS and tracker alerts, staff details and personal documents are removed and the people made anonymous. After 5 years from cancelling: the whole business, including its audit trail, is erased | `retention.process_cancelled` | `test_retention.py`: nothing at 89 days; stage one at 91; erasure after 5 years leaves other businesses untouched |
| Data copies made for owners | 7 days | Deleted | `data_export.purge_expired` | `test_data_export.py` |

## Not covered, and why

- **Backups** keep what was deleted until they expire (see `docs/disaster-recovery.md`: 7 daily base backups and the WAL since the oldest). Deleted data therefore lives on in a backup for up to about a week; it is not restored into the live system except in a disaster, and the retention job runs again after a restore. **[ADVOCATE]** confirm this is acceptable.
- **Sub-processor copies** (a text delivered, a document sent to the AI service) are theirs to delete under their terms.
- **Records the law requires** for a cancelled business are kept in full, including the names of the people in them, as anonymous "Former user" entries once the 90 days have passed.
