# Your fleet's real-world week

The Sprint 5 milestone, and the test nothing in the repository can stand in for: you run your own lorries on FleetTms for a full week and
write down everything that goes wrong. A week is long enough to meet fuel, expenses, a float, a delivery, an invoice and a payment at
least once, and short enough that you will actually finish it. Real problems beat planned features.

## Before day one (an evening)

- [ ] The business is signed up, two-step sign-in is on for the owner, and the subscription page shows the trial.
- [ ] Every lorry is in (Vehicles), with its current odometer and its documents (insurance, inspection, licence) and their expiry dates.
- [ ] Every driver (and turnboy) is invited and has signed in **on their own phone** once, with a real SMS code. Quick sign-in PIN is optional.
- [ ] Each lorry has a driver (and crew) assigned, and one or two real routes with their usual tolls and expected costs.
- [ ] Your real clients are in, with KRA PIN, billing method and rate. Suppliers you buy from are in, with a WhatsApp number.
- [ ] The M-Pesa Paybill or Till is saved in Payment settings (the real callback is only tested once Safaricom has your URLs: say so in the log).
- [ ] Fuel stations, the yard and your usual drop-off points are drawn as geofences, if you have the Standard plan.
- [ ] Brief the drivers in five minutes: inspect, start the trip, photograph the odometer at start and end, enter fuel and expenses as they
      happen, take the delivery photo. Everything works without a signal and sends later.
- [ ] Bring your usual paper records for the week, so you can compare. They are the answer key.

## Each day (15 minutes in the evening)

1. **Dashboard.** Does "needs attention" match what you know happened today? Anything red you did not expect, or missing that you did?
2. **Trips.** Open each trip. Distance, start and end odometer, fuel, expenses: do they match the odometer and the receipts in your hand?
3. **Reconciliation.** Approve the day for each driver, or write down why you could not.
4. **Alerts.** For each alert, say *true*, *false alarm* or *true but harmless*. This is the data to tune the thresholds with; keep the count.
5. **Money.** Was an invoice raised for each delivered trip? Is the amount what you would have charged? Did a payment match its invoice?
6. **Ask a driver** one question: what was annoying today?

## Once during the week

- A trip with no signal for part of it (does the offline queue catch up, and are the points in order?).
- A fuel purchase paid by M-Pesa and one in cash (are both on the right vehicle and trip?).
- A wrong entry on purpose, then a correction (is the audit trail clear about who changed what?).
- A part used from stock and a reorder to a supplier by WhatsApp.
- A service or a document reminder arriving by SMS at a sensible time.
- If you have a tracker: compare the live map with where the lorry really is.

## The problem log

One line per problem, written when it happens, not remembered at the end. A paste into the conversation is all that is needed.

| # | Day, time | Who | Where (screen) | What happened | What you expected | How bad |
|---|---|---|---|---|---|---|
| 1 | | | | | | blocks work / wrong number / annoying / idea |

"Wrong number" is the most important kind: a figure that differs from your paper records. Give both numbers.

## When the week is done

1. Paste the problem log. Sort the "wrong numbers" first.
2. Say how many alerts were true, false and harmless, per kind. The thresholds change on that, not on guesses.
3. Say what you stopped using by day four, and why.
4. Say what you would pay for, and what you would not.

Then tick the milestone in `docs/sprint-plan.md` (Sprint 5, the last acceptance criterion) yourself: it is yours to claim.
