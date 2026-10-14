export interface HelpArticle {
  slug: string;
  title: string;
  summary: string;
  body: string[];
}

/** The help pages. They say what the product does today; when a screen changes, change the article in the same commit. */
export const helpArticles: HelpArticle[] = [
  {
    slug: "get-started",
    title: "Getting started in about 15 minutes",
    summary: "From sign-up to your first job on the road.",
    body: [
      "Sign up with your business name, your name and an email, and turn on two-step sign-in when asked. You get a free trial of the Standard plan with no payment details.",
      "Open Getting started. It walks you through three short steps: add your first vehicle (registration is enough to begin), invite a driver by phone number, and make your first job (who it is for, where from and to, and what they pay). Nothing else needs filling in first.",
      'Want to look around before using your own records? Choose "Add sample data". It adds one lorry, one client, one route and one job, all marked as samples, and you can remove them in one click as long as nothing has been started on them.',
      "Your driver signs in on the phone app with a one-time code sent to their number. They do not need a password.",
    ],
  },
  {
    slug: "vehicles-and-staff",
    title: "Adding vehicles and people",
    summary: "One at a time, or many from Excel.",
    body: [
      "Under Vehicles you can add a lorry by hand with its make, capacity, tank size and the consumption you expect when loaded and empty. Those figures are what fuel checks start from until a vehicle has its own history.",
      "To add many at once, use Settings, Import from Excel. Download the template, fill it in, upload it, and fix any rows the screen points out. Vehicles and staff can be imported.",
      "Invite people under Settings, People. Drivers and turnboys sign in with a phone number and a code. Managers, supervisors and accountants use a password and a second step. Each role sees only what it needs: a driver sees their own trips, an accountant sees the money but not the live map.",
      "Put a driver and a turnboy on a vehicle with Crew. The history of who crewed what is kept.",
    ],
  },
  {
    slug: "running-a-trip",
    title: "Running a trip",
    summary: "Inspection, start, load, deliver, end.",
    body: [
      "Before a trip the driver does the vehicle inspection on the phone. A critical fault stops the trip from starting until a manager clears it.",
      "To start, the driver photographs the odometer. The reading is checked against the photo and the last reading, so a wrong or repeated photo is flagged. Photos must be fresh: a picture from last week is refused.",
      "The driver records loading (and the weight if there is a weighbridge ticket), then delivery with proof: a one-time code sent to the client's phone, or a signature, and photos of the cargo and any damage. At the end another odometer photo closes the trip and gives the distance.",
      "No signal? The phone keeps everything safely and sends it when it can. A small badge shows what is waiting.",
      "The trip is one round: it ends when the lorry is back where it parks, and the closing odometer photo is taken there. The distance is split at the delivery, so the trip shows how many kilometres were driven loaded and how many empty on the way back (this needs GPS from the phone or the tracker; without it the trip shows the total only). If the lorry picks up a return load, make that a new trip for the new client instead.",
      "Map your depot under Settings, Mapped areas, as a depot. After a delivery the phone then tells the driver where to take the lorry and says when they are back. If a driver ends the trip somewhere else the trip is noted, with the reason if they gave one. The trip is never blocked.",
      "When the driver makes a trip on the phone they can choose who it is for from your clients, and where at that client. If the client is not on the list they can type a new name; it shows under Clients as added by a driver until you check it and save it.",
      "When a trip is for a client and nobody knows where that client takes deliveries, the phone asks at delivery: Save this place? The place is kept under Clients, on the client, in Delivery places, and the next driver is guided to it. A place a driver saved waits for you to press Confirm. Until then it only guides: a delivery away from it is not flagged. Once you confirm it, a delivery away from it is flagged. A place saved from a delivery the client confirmed with their SMS code is marked as such.",
      "If a lorry's odometer is faulty or stuck, open the lorry under Vehicles, edit it, and under Distance comes from choose GPS. Its trips then take their distance from the driver's phone (or the tracker, when it has one) instead of the dial, and the lorry's running kilometres, service reminders and tyre mileage follow that. The driver still photographs the odometer, but whatever it shows is kept only as a record. A trip with no GPS has no distance rather than a wrong one. GPS reads a little short on winding roads, so keep the odometer for lorries where it works.",
      "Under Settings, Trip documents, the owner chooses what happens when a driver's licence or a lorry's insurance (or inspection and other permits, if you tick them) has run out: Off, Warn, or Block. A document is valid through its expiry date and counts as run out from the next day. On Warn the trip and the driver's phone say what has run out, and the trip can still start. On Block the trip cannot start until the new date is entered, and a driver or lorry with no such document recorded is stopped too, so record them first. When a start is refused, the owner and managers get a text and a notification. Only the owner can allow one blocked trip, from the trip's page, with a reason that is kept in the audit trail; the next trip is checked again. A trip already on the road is never stopped. The driver and the lorry's crew are reminded before a document runs out, as the owner and managers are.",
      "To clear a block the right way, the driver sends the renewal with its proof: on the phone, Send my licence renewal on the trip (a photo, or a PDF or picture chosen from the phone, of the payment receipt for the 3-year renewal, which NTSA renews as soon as it is paid, or of the digital licence NTSA sends for the 1-year renewal), or a manager does it under Renewals for a licence or for the lorry's insurance (a photo, screenshot or PDF). The proof is read by a program when it arrives and what it says is shown next to what was typed (the date, the lorry's plate or the person's name); that is a help for looking, not a decision, since a read can be wrong and a faked file can read perfectly. The owner or a manager looks at the proof and the date, can correct the date, and approves; only then does the date on the record change and the block lift. Nobody but the owner approves a renewal they sent themselves, and the sender is told the result by text and notification.",
      "The Fuel use screen shows, for each lorry, driver and route, the litres per 100 km, the kilometres per litre and the shillings per kilometre, month by month. A lorry is marked when it uses more than the allowed margin above the consumption you entered for it. Drivers and routes count only fuel that can be tied to a trip, so give them a few trips before comparing.",
    ],
  },
  {
    slug: "fuel-and-expenses",
    title: "Fuel and expenses",
    summary: "What drivers record, and the checks on it.",
    body: [
      "Drivers record fuel (litres, price, total, a photo of the receipt and the M-Pesa code) and expenses such as tolls and parking. On the phone, a fuel receipt photo can fill in the form for you; you check it and confirm.",
      "Money given to a driver in advance is a float. What they spend comes out of it, and at the end of the day they reconcile what is left.",
      "Owners and managers can do the daily money on the phone too: the Money tab lists expenses that went over a limit and the drivers' end-of-day reports to approve or send back, and records a float you have sent by M-Pesa.",
      "You can set spending limits. An expense over the limit waits for approval. The system also notices a claim that is much bigger than usual for that route, an M-Pesa code used twice, and a receipt photo submitted twice.",
      "These are flags to look at, not accusations. Each one shows the numbers behind it.",
    ],
  },
  {
    slug: "quotes-jobs-invoices",
    title: "Quotes, jobs and invoices",
    summary: "From a price to a paid invoice.",
    body: [
      "A quote works out the cost of a trip (fuel, tolls, crew, and for a hired-in lorry what the lease charges) and the profit after it, and shows how it was worked out. Fuel is estimated from that vehicle's own history when there is enough.",
      "A job is the work promised to a client. You can bill per trip, per tonne, per kilometre or as a monthly contract. A delivered trip makes an invoice; per-tonne jobs wait for the weighbridge weight.",
      "Invoices can be sent to the tax authority's eTIMS from the Clients area, and sent to the client by email or WhatsApp with a PDF.",
    ],
  },
  {
    slug: "getting-paid",
    title: "Getting paid and chasing debts",
    summary: "M-Pesa matching and the debtors list.",
    body: [
      "Connect your Paybill under Settings, Payments and tax. When a client pays, the payment is matched to the invoice it names. Payments that name nothing wait in a queue for you to match by hand.",
      "You can also upload an M-Pesa statement. It matches client payments, and adds fuel and expense lines it recognises.",
      "The debtors screen shows who owes you, grouped by how late they are, and sends reminders by text or email.",
    ],
  },
  {
    slug: "tracking",
    title: "GPS tracking and the live map",
    summary: "Phone tracking, trackers, and what stops it.",
    body: [
      "On the Starter plan, the driver's phone records the lorry's position while a trip is running. A notification shows while tracking is on, and it stops when the trip ends. It does not run outside work.",
      "With GPS trackers fitted to the lorry (Standard plan and above), positions arrive all the time. The live map shows each lorry's last position and whether it is moving, idle, parked or has gone quiet. Trip replay shows the path it took.",
      "Draw areas such as your depot or a client's site under Settings so that stops there are not flagged and arrivals can be recorded.",
      "Raw positions are kept 12 months, then only the trip totals are kept.",
    ],
  },
  {
    slug: "alerts",
    title: "Alerts and fraud checks",
    summary: "What each alert means and what to do.",
    body: [
      "The Alerts screen lists what the checks found: fuel far above what the lorry normally uses (idling is allowed for), distance that the odometer, phone and tracker disagree about, a long unexplained stop, a tracker unplugged and then the lorry moved, fuel taken while parked, and more.",
      "Each alert shows its evidence: the numbers, times and places. You can mark it explained (with a note) or confirmed. Over time the screen shows how often each kind of alert turned out to be right, so you can adjust the limits to suit your business.",
      "An alert is a reason to ask a question, not proof. Please talk to the driver before deciding anything, and remember scores and alerts are a coaching tool.",
    ],
  },
  {
    slug: "subscription",
    title: "Your subscription",
    summary: "Trial, plans, paying, and what happens if you stop.",
    body: [
      "Every business starts with a 14 day trial of the Standard plan with no payment details. Prices are per vehicle per month, and each vehicle can be on a different plan. See the prices on the Subscription page or on the front page.",
      "To pay, choose Subscription, Pay, and approve the M-Pesa prompt on your phone. Paying for a year costs 10 months. Bigger fleets get a discount, and very large fleets are priced by agreement.",
      "If a payment is missed, everything keeps working for 7 days. After that the account becomes read-only: you can see and export everything, and pay, but not add new records. Nothing is deleted, and paying brings full access back straight away.",
      "To end the subscription, use Cancel under Subscription. The account becomes read-only straight away and you can take your data out for 90 days. After that, personal details and photos are deleted; records the law requires you to keep are kept for their own period.",
    ],
  },
  {
    slug: "your-data",
    title: "Your data and your people's rights",
    summary: "Taking everything out, and answering a request.",
    body: [
      "Settings, Your data makes a copy of everything your business has, as a zip of spreadsheets with a note explaining them. It works even when your account is read-only. A copy is kept for a week.",
      "Your staff can ask you what is held about them, to correct it, to take it away or to stop using it. Under Settings, Privacy requests you see each request with the date it must be answered by, download everything held about that person, remove them, or refuse with a written reason.",
      "How long things are kept: GPS points 12 months; photos 24 months unless tied to something still open; the audit trail 5 years; money records at least 5 years.",
    ],
  },
  {
    slug: "drivers-app",
    title: "For drivers: the phone app",
    summary: "Signing in, working offline, repairs, your pay and your privacy.",
    body: [
      "Sign in with your phone number and the code we text you. If you set a PIN, you can use it for quick sign-in on your own phone.",
      "The app works without signal. Your work is saved on the phone and sent when you are back online; a badge shows how much is waiting. Do not sign out with unsent work: the app will warn you.",
      "Messages from the office appear under Messages with a number showing how many are new.",
      "Something wrong with the vehicle that is not an emergency? On Home, choose Request a repair, say what it is (and which tyre), whether you can keep driving, and add a photo of the part. The workshop sees it at once, and Home shows how it is getting on. It works without signal too. For an accident or breakdown use Report a problem, and for danger use SOS.",
      "Under More, My trips and my pay shows the trips you have finished and, once your owner has approved a month, what you were paid, with any advances or fines taken off. You need a connection for this.",
      "Your phone's position is recorded only while a trip is running, a notification shows while it is on, and it stops when you end the trip. Under More, My data and my rights, you can ask your employer to show you, correct or delete what they hold about you.",
    ],
  },
  {
    slug: "trouble-signing-in",
    title: "I cannot sign in",
    summary: "The usual reasons, and how to reach us.",
    body: [
      "Drivers: ask for a new code and wait a minute before asking again. You can have five codes an hour. Check the number is the one the owner entered.",
      "Owners and managers: after five wrong passwords the account locks for 15 minutes. If you lost your authenticator app, ask the platform support team to help you set up again; we will check it is you first.",
      'A code that says "expired" lasts 5 minutes: ask for a new one.',
      "Still stuck? Use the contact details below and tell us your business name and what you see on the screen. Please never send us your password or a code.",
    ],
  },
];
