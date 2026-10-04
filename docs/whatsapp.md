# WhatsApp Business: setting up automatic messages

FleetTms can send a parts order to a supplier and a payment reminder to a client on WhatsApp by itself, and show the owner when the
message arrived, was read and (for an order) what the supplier answered. The free "send by WhatsApp link" button stays as it is, for
anyone who has not set this up.

It uses Meta's official WhatsApp Business (Cloud) API. A business can only start a conversation with a **template** Meta has approved,
so the two below must be created and approved first (WhatsApp Manager, Message templates; category **Utility**, language **English**).

## What to set where the API runs

| Setting | What it is |
|---|---|
| `WHATSAPP_TOKEN` | the permanent access token of a system user |
| `WHATSAPP_PHONE_NUMBER_ID` | the id of the sending number (not the number itself) |
| `WHATSAPP_APP_SECRET` | the Meta app's secret: every report and reply is signed with it, and nothing unsigned is believed |
| `WHATSAPP_VERIFY_TOKEN` | any long random text you choose; Meta sends it once when you register the address |
| `WHATSAPP_ORDER_TEMPLATE` | the name of the approved parts order template |
| `WHATSAPP_REMINDER_TEMPLATE` | the name of the approved payment reminder template |
| `WHATSAPP_TEMPLATE_LANGUAGE` | `en` unless you made the templates in another language |

In the Meta app, subscribe the WhatsApp Business Account to **messages** and set the webhook to
`https://<your API address>/hooks/whatsapp` with the verify token above.

## The two templates

Variables may not contain line breaks, so FleetTms writes each as one line.

**Parts order** (name it what you like, then put the name in `WHATSAPP_ORDER_TEMPLATE`). Add two **Quick reply** buttons: `Confirm` and
`Cannot supply`, in that order (FleetTms sends their answers back to itself; the order of the buttons matters).

> Hello {{1}}, new parts order {{2}} from {{3}}: {{4}} {{5}}

**Payment reminder** (no buttons):

> Hello {{1}}, a message from {{2}}: invoice {{3}} for {{4}} {{5}}. {{6}}

## What happens

- **Order.** Open Suppliers, Orders, press *Send on WhatsApp*. The order is marked sent. The order card then shows *sent*, *delivered*,
  *read*. When the supplier presses **Confirm** the order becomes confirmed (the audit trail records that the supplier did it, not a
  person); **Cannot supply** leaves it as it is and texts the owner and managers.
- **Reminders.** Payment settings, tick WhatsApp. Reminders go out on the same days as the SMS and email ones, once each, and a failed one
  is tried up to three times.
- Only the number an order was sent to can answer it, and only with one of the two buttons. Free-text replies are not read or kept.

## Cost

Meta charges per conversation (utility template messages cost a few shillings each). That is the platform's cost, not counted in the
business's text-message bundle. Passing it on, as the masterplan describes, is a pricing decision still to be made.

## Without it

With no token set, development uses an in-memory stand-in (nothing leaves the machine). In production the *Send on WhatsApp* button is
hidden and the link button is the only one.
