# Card payments for subscriptions

An owner can pay a subscription invoice by card as well as by M-Pesa. The card is entered on **Paystack's hosted page**: FleetTms sends the
owner there with the amount and a reference, and never sees or stores a card number (so FleetTms stays out of the heavy card-data rules).

## Setting it up

1. Create a Paystack business account for the platform and get the **live secret key** (Settings, API keys).
2. Set `PAYSTACK_SECRET_KEY` where the API runs. With no key, development uses a stand-in and production hides the button.
3. In the Paystack dashboard, set the **webhook URL** to `https://<your API address>/hooks/paystack`.

## How a payment settles

1. The owner presses **Pay by card** on the open invoice. FleetTms records the attempt and sends them to Paystack's page.
2. Paystack tells FleetTms the result **twice over**, so a lost message cannot lose a payment: its signed webhook, and a check FleetTms
   makes when the owner comes back to the page. Whichever arrives first marks the invoice paid; the other finds it already done.
3. The webhook is believed only with a valid signature, a reference that FleetTms issued, the invoice's currency (KES) and an amount at
   least the invoice's. Anything else changes nothing.
4. Paying switches the account on at once, exactly as an M-Pesa payment does, queues the tax invoice for KRA and credits any partner.

## Things to know

- Paystack's fee is taken from what the platform receives; the invoice amount is what the customer pays.
- If a card payment arrives for an invoice that was meanwhile paid another way, the invoice is not paid twice. The attempt is marked
  *needs a refund* and the business's audit trail records `subscription.duplicate_card_payment`: refund it in the Paystack dashboard.
- The owner needs an email address on their profile (Paystack sends the receipt there).
- Never tried against Paystack's live service: it was written from their documentation and tested against stand-ins. Do one real
  small payment (and a refund) before announcing it.
