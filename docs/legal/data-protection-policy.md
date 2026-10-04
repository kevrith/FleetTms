# Data Protection Policy for Kastra Enterprises (internal, draft)

DRAFT for review by a Kenyan advocate. Follows the outline in masterplan 11.6. Where a rule is carried out by the product, the section says where.

1. **Purpose and scope.** How Kastra Enterprises ("we") protects personal data in FleetTms, as controller of account and subscription data and processor of each business's data. Applies to everyone who works for us and every contractor who can reach production.
2. **Principles.** Lawful, fair and transparent (monitoring notice, privacy policy); limited to a purpose (features use only what they need); minimised; accurate (people can ask for corrections); kept only as long as needed (`retention-schedule.md`); secure (section 5); accountable (audit trail, breach register, this policy).
3. **Roles.** Privacy contact (DPO): **[TO FILL]**. Incident lead and technical lead: **[TO FILL]** (see the breach plan). Developers keep the standing security tests passing. Support staff see customer facts only.
4. **Classification.**
   - Public: prices, the privacy documents, the sub-processor list.
   - Internal: our code, runbooks, subscription figures.
   - Confidential: a business's records; staff names, phones and salaries.
   - Sensitive: location tracks, photos, sign-in secrets, payment details. Never in a log (a standing test fails the build if a log line names a phone, email, token or location).
5. **Access and least privilege.** In the product: a permission for each action, a role matrix tested for every role and route, lessors and clients limited to their own records, support access only on a business's time-limited grant and logged in its own audit trail. In our company: production access for named people only, with two-step sign-in **[TO FILL]**; secrets in the host's secret store, never in code or documents; people leave the list on the day they leave.
6. **Impact assessments.** Required before a feature that tracks, scores or profiles people, uses a new sub-processor, or moves data to a new country. Template: `dpia.md`.
7. **Retention and secure deletion.** `retention-schedule.md`; deletion removes files from storage and rows from the database; the audit trail is the one record that cannot be edited.
8. **Breaches.** `breach-response-plan.md`; register in the platform console; 72 hours to the Commissioner.
9. **People's requests.** A request goes to the business, which answers within `DSAR_DUE_DAYS` (30, to be confirmed). The product records the request, shows the deadline, produces the copy, performs removal and records a refusal's reason. If a person writes to us instead, we pass it to their employer the same day and tell them we have.
10. **Vendors and sub-processors.** Before a new one: the DPIA question, written terms (no training on, no keeping of customer data; breach notice to us; location), an entry in `sub-processors.md`, and notice to businesses.
11. **Training.** Everyone with production access reads this policy and the breach plan before access and once a year; the incident lead practises the breach plan twice a year. **[TO FILL]** dates.
12. **Review and audit.** Once a year, and after any breach: the policy, the DPIA, the sub-processor list, the access list, and a restore drill. Findings and dates are written in the progress log.
