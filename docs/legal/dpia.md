# Data Protection Impact Assessment (draft)

DRAFT for review by a Kenyan advocate. Not legal advice. Required before launch because FleetTms performs systematic location tracking of employees (masterplan 11.2 item 2). Review again whenever a feature that handles people's data is added.

Open items for the advocate are marked **[ADVOCATE]**; facts we cannot know are marked **[TO FILL]**.

## 1. What is being processed, and why

| | |
|---|---|
| Who decides how it is used | Each fleet owner is the controller of their staff, client and fleet data. Kastra Enterprises (FleetTms) is their processor, and the controller of account and subscription data. |
| Whose data | Drivers and turnboys; managers, supervisors, accountants and other staff; lessors' contacts; clients' contacts and delivery recipients (name, phone, signature). |
| Purpose | Running a lorry business: dispatch, safety, fuel and expense control, billing, and proving deliveries. |
| Data | Names, phone numbers, emails; licence numbers and expiry; salary; where a driver's phone is during a trip (position, speed, direction); odometer and receipt photos, which may show people and places; fuel and expenses entered; trip and delivery records; sign-in history and device checks; messages to drivers; SOS alerts with position. |
| Special categories | None are collected on purpose. Photos and free-text notes could show anything; staff are told not to photograph people. |
| Volume | A business of 5 to 300 vehicles: one position a minute per lorry on trip, about 40,000 to 13 million points a month at the top end, kept 12 months. |
| Recipients | The owner and the roles they give access to; lessors see only their own lorry and only what the lease allows; clients see one delivery's progress on a link; FleetTms staff see customer facts only, and a business's data only if it grants time-limited, logged support access. Sub-processors: see `sub-processors.md`. |
| Retention | See `retention-schedule.md`. |

## 2. Features that need particular care

- **Tracking drivers' phones.** Starts when a trip starts and stops when it ends. A notification shows while it is on. The driver sees a plain notice at first sign-in and must accept it. It does not run outside work.
- **Driver scorecards and alerts.** Safety, fuel use, punctuality, inspections and alerts are scored. The score is a coaching tool. Nothing is decided by the score alone: the monitoring notice says any disciplinary decision needs a human to review it, and each fuel or distance alert shows its working so the driver can explain it. **[ADVOCATE]** confirm this is enough under the Employment Act, 2007.
- **SOS.** A driver in danger presses one button and their position goes to the people the owner chose. It sends position only while an alert is open.
- **Fraud checks.** They look at the money and distance records a driver creates, not at the person. They flag; a person decides.
- **Remote immobiliser.** Owner only, stationary vehicle only, a confirmation step, full audit trail. It affects equipment, not personal data.
- **Plain-English questions and document reading (AI).** The question and the figures looked up to answer it, or a photographed receipt or certificate, go to a cloud AI service, for that business only. The provider is contractually barred from keeping it or training on it **[ADVOCATE]** (provider and terms to be named). A person always confirms what was read before it is kept, and the answers show their numbers.
- **Partners.** A GPS tracker installer who has joined the partner programme can see only the name of each business they referred, how it stands (trial, paying, overdue) and its number of vehicles, plus their own commission. They see no staff, no records and no money of the business. The key to their report is held as a hash and shown to them once.
- **Product analytics.** Counts of requests per part of the product per day, per business, under a pseudonym: no person, address, id, record or content. The sign-up funnel is worked out from what each business has done. Only platform admins see either. It can be switched off (`ANALYTICS_ENABLED`). **[ADVOCATE]** confirm that this needs only a line in the Privacy Policy.
- **Lessor portal.** A lessor sees the lease, its statements, service history and inspection status of their own lorry, and trips only if the lease says so and the drivers have been told.

## 3. Necessity and proportionality

- **Lawful basis.** For staff data, the employer's legitimate interest in running and securing its fleet and the employment contract; for delivery recipients, performance of the delivery contract. Consent is not relied on for staff (it is not freely given in employment). **[ADVOCATE]**
- **Minimisation.** Only what the features need. No contacts, personal photos or unrelated phone data are read. Location is only collected during a trip, and the live map shows each lorry's last position, not a history; a trip's full path is a separate screen for people with the live-map permission.
- **Accuracy.** People can see their own trips and entries; staff details are corrected by the owner (the correction request workflow).
- **Storage limits.** Enforced by daily jobs, tested one by one (see `retention-schedule.md`).
- **Transparency.** Monitoring notice at first sign-in; privacy policy; the in-app "Your data and your rights" screen.
- **Rights.** The data protection request workflow gives the owner a clock, a copy of everything held about a person in one click, removal, and a place to record a refusal with its reason.

## 4. Risks and what reduces them

| Risk to people | Likelihood | How it is reduced | What is left |
|---|---|---|---|
| Being tracked outside working hours | Low | Tracking only during a trip; stops at trip end; visible notification | A driver forgetting to end a trip. The owner can end it. |
| Unfair treatment from a score or an alert | Medium | Scores are advisory; evidence shown; human review required; thresholds are the owner's to set | Owners may over-rely on a score. Training material to be written. |
| Another business or a stranger seeing location or staff data | Low | Tenant isolation on every query, tested across all 94 tables and every route; rate limits; short-lived signed links; lessor and client views limited | A flaw in a new feature. Standing tests fail the build for a new table or route that has not been reviewed. |
| A breach at FleetTms or a sub-processor | Low | Encryption in transit; private storage; secrets never in code; dependency scanning; breach plan with a 72-hour clock and a register | Hosting and database encryption at rest depend on the chosen host **[TO FILL]**. |
| Data kept too long | Low | Daily retention jobs; the database refuses to delete an audit row under 5 years old | Backups hold deleted data until they expire (see the disaster recovery document). |
| Data sent abroad | Medium | Region choice **[TO FILL]**; sub-processor list; contractual terms | AI, maps and SMS providers may process outside Kenya. **[ADVOCATE]** |
| A former employee's data lingering | Low | Staff details removed and the person anonymised 5 years after leaving; removal on request | The business's own records of what they did are kept (tax law). |
| FleetTms staff seeing customer data | Low | Platform admins see customer facts only; access to a business's data needs its time-limited, logged grant | Trust in named staff **[TO FILL]**. |

## 5. Consultation

- Drivers or their representatives: **[TO FILL]** present the monitoring notice and the scoring to a group of drivers at the pilot customer and record what they say.
- Advocate: **[ADVOCATE]**
- Office of the Data Protection Commissioner: file with the registration **[TO FILL]**

## 6. Outcome and review

Outcome: **[ADVOCATE]** to confirm the processing can go ahead with the measures above. Review when: a new feature uses people's data in a new way (for example, driver facial checks, which are deliberately not built), a new sub-processor is added, after any breach, and at least once a year. Owner: **[TO FILL]**.
