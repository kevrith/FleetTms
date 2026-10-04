# Store submission (Play Store and App Store)

What is ready, what the stores will ask for, and what only you can do. Nothing here has been submitted: that needs your developer accounts.

## What the app is

Package and bundle id `com.kastra.fleettms`. One app, three kinds of people: drivers and turnboys (trips, odometer and receipt photos, fuel, expenses, SOS, messages), owners and managers (a lean dashboard, vehicles, the live map, workshop), and lessors (their own lease, via the web portal). Built with Expo (SDK 52). Android has been run on an emulator and a development build; **iOS has never been built or run**.

## State of the build configuration

| | |
|---|---|
| `apps/mobile/app.json` | name, slug, ids, version `0.1.0`, `versionCode` 1, `buildNumber` 1, permission wording for camera and location |
| `apps/mobile/eas.json` | `development`, `preview` (internal APK against staging) and `production` (app bundle, auto-incrementing version) profiles. The two `EXPO_PUBLIC_API_URL` addresses are placeholders: set them to your real hosts. |
| Build | `cd apps/mobile && eas build --profile production --platform android` (and `ios`) after `eas init`, which writes the project id. Needs an Expo account. |
| Not in the repo | the **app icon (1024 by 1024)**, adaptive icon, splash image, **screenshots**, a feature graphic for Google Play. There is no brand artwork yet. |

## Things the stores will check, and the answers

**Background location (the one most likely to be questioned).** The app records the lorry's position while a trip is running, including with the screen off (Android foreground service with a notification). Google Play needs the "Permissions declaration form" for background location with a short video showing the feature and the in-app disclosure; Apple needs the reason in review notes. The honest description: tracking starts when the driver starts a trip, a notification shows while it is on, it stops when they end the trip, it does not run outside work, and the employer sees the position. The app's permission text already says this (`app.json`), and drivers must accept the monitoring notice (`docs/legal/monitoring-notice.md`) before they can use the app. **[ADVOCATE]** the notice must be final before submission.

**Camera.** Odometer, cargo, receipts and faults.

**Data safety (Google) and privacy nutrition label (Apple), draft answers.**

| Data | Collected | Linked to the person | Why | Shared with |
|---|---|---|---|---|
| Precise location | Yes, only during a trip | Yes (the driver, shown to their employer) | Fleet operation, safety, proof of delivery | The employer; map and route providers only receive place names, not tracks |
| Photos | Yes | Yes | Odometer and receipt evidence, proof of delivery | The employer |
| Name, phone number, email | Yes | Yes | Account and sign-in | The employer; the SMS gateway (phone number and a code) |
| Financial info (expenses, fuel, payments) | Yes | Yes | Business records | The employer; Safaricom for payments |
| Device or other IDs | A device check (mock location, clock) | Yes | Detect false data | The employer |
| App activity | Counts of which parts of the product a business uses; no person | No | Improve the product | Nobody |

Data is encrypted in transit. Offline data on the phone is encrypted. A person can ask their employer to delete their data (in the app: More, My data and my rights); the employer is the controller. **[ADVOCATE]** confirm the wording and the privacy policy address.

**Account deletion.** Google Play requires a way to request deletion from inside the app and from a web page. The in-app route is "My data and my rights" (a deletion request answered by the employer); the web page for it is the privacy policy page, which must say how. **[TO FILL]** the public URL.

**Sign-in for the reviewers.** Drivers sign in with a code sent by text, which a reviewer cannot receive. Do not add a secret back door. Give the reviewers a demo owner account (password and an authenticator secret in the review notes, kept out of the repository), made with sample data, and describe the driver flow with a screen recording. **[TO FILL]** make the demo account.

**Content rating.** A business tool; no user-generated public content; the questionnaire answers are "no" except for location sharing.

**Target audience.** Adults who work in transport. Not for children.

## Listing text (drafts)

- Name: FleetTms
- Short description (80 characters): Run your lorries from your phone: trips, fuel, expenses and tracking.
- Long description: FleetTms is for Kenyan transport businesses. Drivers photograph the odometer and receipts, record fuel and expenses, and work even with no signal. Owners see every trip, what each lorry earns, where it is, and anything that does not add up, with the evidence. Quotes, invoices, M-Pesa payments and eTIMS in one place. Free for 14 days.
- Category: Business (Android), Business (iOS). Support URL and privacy policy URL: **[TO FILL]**. Contact email: **[TO FILL]**.

## Before pressing submit

- [ ] Developer accounts: Google Play Console (a one-off fee), Apple Developer Program (an annual fee), an Expo account.
- [ ] Production API address set in `eas.json`, and the API live with a real SMS gateway (drivers cannot sign in without it).
- [ ] Icon, splash and screenshots made.
- [ ] Final legal documents approved and published at real addresses; the app's accepted versions bumped (`docs/legal/README.md`).
- [ ] Background-location declaration video recorded; reviewer account made.
- [ ] An internal Play track build installed on two real phones and a whole day of use checked: tracking, offline queue, photo upload, receipt reading. Only an emulator has been used so far.
- [ ] An iOS build made and run on a real iPhone (never done), including background location behaviour.
- [ ] Crash and error reporting chosen (none is installed; add one that does not collect personal data).

Review takes days, and a first rejection is common: submit well before the launch date.
