# Sub-processors (draft)

DRAFT for review by a Kenyan advocate. The Privacy Policy (item 5) promises a published list. This is the list as the product stands, with what we cannot know yet marked **[TO FILL]**. Each one must be bound by written data protection terms before launch (masterplan 11.2 item 10) and the list published at an address the Privacy Policy names **[TO FILL]**.

| Purpose | Provider | Data it sees | Where | Status |
|---|---|---|---|---|
| Hosting: servers, database, file storage, backups | **[TO FILL]** (chosen at launch) | Everything the businesses store | **[TO FILL]**: in Kenya if possible, else the nearest region with adequate safeguards | Not chosen. Sprint 17. |
| Text messages (sign-in codes, reminders, alerts, driver messages) | Africa's Talking | Phone number and message text | **[TO FILL]** | Built from their documentation and tested against a mock only; not yet run with a live account. The API refuses to start in production without it. **[ADVOCATE]** confirm their data protection terms. |
| M-Pesa payments (clients paying businesses; businesses paying us) | Safaricom (Daraja) | Payer name and phone, amount, reference | Kenya | Written from the documentation; not yet run against the live service |
| Tax invoices | Kenya Revenue Authority (eTIMS) | Invoice, client and item details, the business's PIN | Kenya | Written from documentation; not yet registered |
| Reading documents and answering questions in plain English (AI) | Anthropic (Claude) **[ADVOCATE]** confirm the contract and its no-retention, no-training terms | A photo of a receipt, certificate, ticket or note; or a typed question and the figures looked up to answer it. Never passwords, other businesses' data, or location tracks. | **[TO FILL]** | Used when an API key is set; tested against a mock only |
| Route and distance suggestions | Google (Routes API) | Place names or coordinates of a pickup and a drop-off | **[TO FILL]** | Used when a key is set |
| Reports and invoices by email | **[TO FILL]** SMTP provider | Recipient email, the report or invoice | **[TO FILL]** | Not chosen |
| Reports, parts orders and payment reminders by WhatsApp | Meta (WhatsApp Business) | Recipient phone and name, the message or document (for an order: the supplier's name, the items and the quantities; for a reminder: the client's name, the invoice number and the amount), and whether it was delivered, read or answered | **[TO FILL]** | Used when a token is set; written from their documentation and tested against a mock only. Only the answer buttons are read back, never free text. |
| Card payments for subscriptions | Paystack | The paying owner's email and the amount and reference; the card number is entered on their page and never reaches us | **[TO FILL]** | Used when a key is set; written from their documentation and tested against a mock only. **[ADVOCATE]** confirm their data protection terms. |
| File storage (photos, data copies), if a bucket is used instead of the server's disk | **[TO FILL]** (any S3-compatible provider) | Every photo and data copy the businesses store | **[TO FILL]** | Optional (`STORAGE_BACKEND=s3`). Private bucket; nothing public; the API serves the files itself. |
| GPS tracker messages | Traccar (run by us, not a third party) | Positions and tracker events | Our hosting | Self-hosted |

Not sub-processors: the Expo and app-store services that deliver the phone app to a device carry no customer data.

A change to this list is notified to every business owner (Data Processing Agreement, item 4). How much notice, and whether the owner may object, is not yet written down: **[ADVOCATE]**.
