# Personal data breach response plan (draft)

DRAFT for review by a Kenyan advocate. Not legal advice. Masterplan 11.2 item 8: tell the Data Protection Commissioner within 72 hours of becoming aware of a breach likely to put people at risk, tell the affected businesses and individuals without undue delay, and keep a register of every incident.

## Who does what (**[TO FILL]** names and phone numbers)

| Role | Person | Does |
|---|---|---|
| Incident lead | | Runs the response, decides severity, owns the register entry |
| Technical lead | | Contains and investigates; preserves evidence |
| Privacy contact (DPO) | | Decides whether the Commissioner must be told; writes the notices |
| Communications | | Messages to businesses, and a draft for them to send to their people |
| Advocate | | On call for the notification wording |

## The first hour

1. **Write it down now.** Platform console, Data breaches, "Write a breach down". The moment we become aware starts the 72 hours, so do it before the investigation is finished and correct it later. The register shows the deadline and turns red when it is missed.
2. **Contain.** Revoke the sessions or keys involved (`/auth/logout-all` for a user; rotate `JWT_SECRET`, which signs everyone out and changes every callback address, then register the new ones); suspend the business or feature if needed; turn off the leaking route.
3. **Keep evidence.** Do not delete logs. The audit trail is append-only. Copy the relevant logs and take a snapshot of the database.

## Within 24 hours

4. **Assess.** What data, whose, how many, was it read or only exposed, is it still exposed, is there a risk of harm to people (identity misuse, safety of a driver whose location was exposed, financial loss). Record it in the register (`risk_to_people`).
5. **Decide whether the Commissioner must be told.** If it is likely to put people at risk: yes. If unsure, ask the advocate and lean to telling.

## Within 72 hours

6. **Tell the Commissioner**, then record it in the register ("The Commissioner has been told"; the register notes if that was after the deadline). The notice says: what happened and when, the kinds of data and roughly how many people, what the likely consequences are, what we have done and will do, and who to contact. Where something is not yet known, say so and send the rest later.
7. **Tell the affected businesses.** Register entry, "Tell the businesses": it texts each affected business's owners and writes a line in each business's own audit trail, so they can show when they were told. As processor we must tell the controller without undue delay, so do this as soon as we know whose data it was, not at 72 hours.
8. **Help them tell their people.** The business is the controller of its staff's data and tells the individuals if the risk is high. We provide a plain-language draft and the list of who was affected. Record when it has been done.

## After

9. **Find the cause, fix it, and write it up** in the register: root cause, actions taken. Add a standing test for it if it can be tested.
10. **Close** the entry when it is contained, the notices are done and the fix is released.
11. **Review** the plan after every incident, and practise it twice a year with a made-up incident (the same cadence as the restore drill).

## What counts

Any loss, theft, unauthorised access, change or disclosure of personal data, by us or a sub-processor, accidental or deliberate: a stolen laptop with a signed-in console; a bug that showed one business another's records; a leaked backup; a sub-processor telling us it was breached; a message sent to the wrong person with personal data in it.
