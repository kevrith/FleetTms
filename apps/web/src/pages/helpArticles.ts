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
    ],
  },
  {
    slug: "fuel-and-expenses",
    title: "Fuel and expenses",
    summary: "What drivers record, and the checks on it.",
    body: [
      "Drivers record fuel (litres, price, total, a photo of the receipt and the M-Pesa code) and expenses such as tolls and parking. On the phone, a fuel receipt photo can fill in the form for you; you check it and confirm.",
      "Money given to a driver in advance is a float. What they spend comes out of it, and at the end of the day they reconcile what is left.",
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
    summary: "Signing in, working offline, messages and your privacy.",
    body: [
      "Sign in with your phone number and the code we text you. If you set a PIN, you can use it for quick sign-in on your own phone.",
      "The app works without signal. Your work is saved on the phone and sent when you are back online; a badge shows how much is waiting. Do not sign out with unsent work: the app will warn you.",
      "Messages from the office appear under Messages with a number showing how many are new.",
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
