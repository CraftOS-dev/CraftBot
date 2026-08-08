# Stripe

The Stripe integration connects the agent to your Stripe account with a secret or restricted API key. The agent can work with customers, payment intents, charges, refunds, payment methods, products, prices, invoices, subscriptions, checkout sessions, payment links, coupons, disputes, payouts, quotes, and webhook endpoints. Stripe has no event listener, so the agent acts when you ask it to.

## Requirements

| Requirement | Details |
|---|---|
| Stripe account | The agent acts as this account for every API call |
| Secret or restricted API key | Generate at [dashboard.stripe.com/apikeys](https://dashboard.stripe.com/apikeys). A restricted key with scoped permissions is recommended |
| Test mode vs live mode | Derived from the key prefix. `sk_test_`/`rk_test_` keys act on test data, `sk_live_`/`rk_live_` keys act on live money |
| Network access | CraftBot calls `api.stripe.com` over HTTPS, plus `files.stripe.com` for file uploads |

## Setup

1. Open [dashboard.stripe.com/apikeys](https://dashboard.stripe.com/apikeys). To rehearse safely first, turn on **Test mode** in the dashboard before you create the key. Test keys carry the `_test_` prefix and never touch live money.
2. Click **Create restricted key**, name it, and grant only the resource permissions the agent needs. This is the recommended option. To give the agent full account access instead, reveal your standard secret key on the same page.
3. Copy the key. Stripe shows the full secret or restricted value once.
4. In CraftBot, open **Settings → Integrations → Stripe**, paste the key into **Stripe API Key**, and connect. From chat, `/stripe login <api_key>` does the same thing.
5. Verify with `/stripe status`. It shows the connected account, whether the credential is a restricted or secret key, and whether it is in test or live mode.

`/stripe logout` removes the credential. Publishable keys (`pk_`) are rejected at login because they cannot authenticate server-side requests.

## How it connects

**Authentication.** Every API call sends your key as a bearer token to `api.stripe.com`. At login CraftBot validates the key against your account profile (falling back to your balance for a restricted key that lacks account access) and stores the key, account label, key kind, and live-mode flag in the credential store as `stripe.json`. See [Credentials](credentials.md).

**Test mode vs live mode.** The mode comes from the key prefix. A `_test_` key acts only on test data and a `_live_` key acts on live money. There is no runtime switch. To move between modes, connect a different key. A restricted test-mode key cannot manage live resources and the reverse is also true, so a 401 for "Invalid API key" is most often a test-versus-live mismatch.

**No event listener.** Stripe delivers events through webhooks, which need a public callback URL the integration cannot provide, so there is no polling listener. The agent still reads the event log with `list_stripe_events` and `get_stripe_event`, and it can register webhook endpoints for a separate system that receives them.

!!! warning "Money-moving actions apply immediately with no separate confirmation"
    Stripe applies refunds, payouts, voids, and deletes the moment the agent calls them, and the integration adds no confirmation gate of its own. The action source flags only four actions as irreversible in their descriptions: `void_stripe_invoice`, `close_stripe_dispute`, `update_stripe_dispute` when you submit evidence, and `delete_stripe_customer`. `create_stripe_refund` and `create_stripe_payout` move money but carry no irreversibility warning in the action itself, so state the exact amount and target when you ask. Connect a test-mode key first to rehearse anything that moves money.

## What the agent can do

The 99 Stripe actions are grouped into action sets (`stripe_customers`, `stripe_payments`, `stripe_invoices`, and so on) that the agent loads as a task needs them. See [Actions and action sets](../core/concepts/actions-and-action-sets.md).

### Customers

| Action | Purpose |
|---|---|
| `list_stripe_customers` | List customers, filterable by email or created window |
| `get_stripe_customer` | Retrieve a customer by ID |
| `create_stripe_customer` | Create a customer record |
| `update_stripe_customer` | Update a customer from a properties dict |
| `delete_stripe_customer` | Permanently delete a customer (irreversible; charges and invoices are preserved) |
| `search_stripe_customers` | Search customers with Stripe's query language |

### Payment intents

| Action | Purpose |
|---|---|
| `list_stripe_payment_intents` | List payment intents, filterable by customer or created window |
| `get_stripe_payment_intent` | Retrieve a payment intent by ID |
| `create_stripe_payment_intent` | Create a payment intent (amount in the smallest currency unit) |
| `update_stripe_payment_intent` | Update a payment intent's properties |
| `confirm_stripe_payment_intent` | Confirm a payment intent server-side for off-session or SCA flows |
| `capture_stripe_payment_intent` | Capture funds authorized with manual capture, optionally partial |
| `cancel_stripe_payment_intent` | Cancel a payment intent while it is in a cancelable state |
| `search_stripe_payment_intents` | Search payment intents with Stripe's query language |

### Charges and refunds

| Action | Purpose |
|---|---|
| `list_stripe_charges` | List charges, filterable by customer, payment intent, or transfer group |
| `get_stripe_charge` | Retrieve a charge by ID |
| `create_stripe_refund` | Refund a payment intent or charge (omit the amount for a full refund) |
| `get_stripe_refund` | Retrieve a refund by ID |
| `list_stripe_refunds` | List refunds, optionally scoped to a payment intent or charge |

### Payment methods

| Action | Purpose |
|---|---|
| `list_stripe_payment_methods` | List payment methods for a customer or account-wide |
| `get_stripe_payment_method` | Retrieve a payment method by ID |
| `attach_stripe_payment_method` | Attach a payment method to a customer for future charges |
| `detach_stripe_payment_method` | Detach a payment method from its customer |
| `update_stripe_payment_method` | Update a payment method's metadata or billing details |

### Products and prices

| Action | Purpose |
|---|---|
| `list_stripe_products` | List products, filterable by active flag or explicit IDs |
| `get_stripe_product` | Retrieve a product by ID |
| `create_stripe_product` | Create a product, optionally with an inline first price |
| `update_stripe_product` | Update a product's properties |
| `delete_stripe_product` | Delete a product that has no prices |
| `list_stripe_prices` | List prices, optionally scoped to a product |
| `get_stripe_price` | Retrieve a price by ID |
| `create_stripe_price` | Create a recurring or one-time price for a product |
| `update_stripe_price` | Update a price's nickname, active flag, metadata, or tax behavior |

### Invoices and invoice items

| Action | Purpose |
|---|---|
| `list_stripe_invoices` | List invoices, filterable by customer, subscription, status, or created window |
| `get_stripe_invoice` | Retrieve an invoice by ID |
| `create_stripe_invoice` | Create a draft invoice for a customer |
| `update_stripe_invoice` | Update an invoice, mostly while it is a draft |
| `delete_stripe_invoice` | Permanently delete a draft invoice |
| `finalize_stripe_invoice` | Finalize a draft invoice, locking its line items and totals |
| `send_stripe_invoice` | Email a finalized send-invoice invoice to the customer |
| `pay_stripe_invoice` | Attempt payment on an open invoice |
| `void_stripe_invoice` | Void a finalized open invoice (irreversible) |
| `mark_stripe_invoice_uncollectible` | Mark an open invoice as a write-off |
| `get_stripe_upcoming_invoice` | Preview the next invoice for a customer or subscription without writing |
| `list_stripe_invoice_items` | List invoice items for a customer, invoice, or pending set |
| `create_stripe_invoice_item` | Create an invoice item for a customer |
| `delete_stripe_invoice_item` | Delete a pending invoice item |

### Subscriptions

| Action | Purpose |
|---|---|
| `list_stripe_subscriptions` | List subscriptions, filterable by customer, price, or status |
| `get_stripe_subscription` | Retrieve a subscription by ID |
| `create_stripe_subscription` | Create a subscription for a customer |
| `update_stripe_subscription` | Update a subscription's items or cancel-at-period-end flag |
| `cancel_stripe_subscription` | Cancel a subscription immediately |
| `resume_stripe_subscription` | Resume a paused subscription |

### Checkout sessions

| Action | Purpose |
|---|---|
| `list_stripe_checkout_sessions` | List checkout sessions, filterable by customer, payment intent, subscription, or status |
| `get_stripe_checkout_session` | Retrieve a checkout session by ID |
| `create_stripe_checkout_session` | Create a hosted checkout session and return its page URL |
| `expire_stripe_checkout_session` | Expire an open checkout session and invalidate its URL |
| `list_stripe_checkout_line_items` | List the line items on a checkout session |

### Payment links

| Action | Purpose |
|---|---|
| `list_stripe_payment_links` | List payment links |
| `get_stripe_payment_link` | Retrieve a payment link by ID |
| `create_stripe_payment_link` | Create a shareable payment link to hosted checkout |
| `update_stripe_payment_link` | Update a payment link's active flag or quantities |

### Billing portal

| Action | Purpose |
|---|---|
| `create_stripe_billing_portal_session` | Create a short-lived customer portal session URL |

### Coupons and promotion codes

| Action | Purpose |
|---|---|
| `list_stripe_coupons` | List coupons |
| `get_stripe_coupon` | Retrieve a coupon by ID |
| `create_stripe_coupon` | Create a coupon with an amount off or percent off |
| `update_stripe_coupon` | Update a coupon's name or metadata (other fields are write-once) |
| `delete_stripe_coupon` | Delete a coupon (existing redemptions are unaffected) |
| `list_stripe_promotion_codes` | List promotion codes, filterable by active flag, code, coupon, or customer |
| `create_stripe_promotion_code` | Create a customer-facing promotion code for a coupon |
| `update_stripe_promotion_code` | Update a promotion code's active flag or metadata |

### Disputes

| Action | Purpose |
|---|---|
| `list_stripe_disputes` | List disputes, filterable by charge or payment intent |
| `get_stripe_dispute` | Retrieve a dispute by ID |
| `update_stripe_dispute` | Save dispute evidence as a draft, or submit it to the card network (submitting is irreversible) |
| `close_stripe_dispute` | Forfeit a dispute and accept the chargeback (cannot be reopened) |

### Payouts, balance, and transactions

| Action | Purpose |
|---|---|
| `list_stripe_payouts` | List payouts to the merchant's bank account |
| `get_stripe_payout` | Retrieve a payout by ID |
| `create_stripe_payout` | Trigger a standard or instant payout from the Stripe balance |
| `cancel_stripe_payout` | Cancel a payout while it is still pending |
| `get_stripe_balance` | Get the current available and pending balance per currency |
| `list_stripe_balance_transactions` | List balance transactions for every money movement |

### Quotes

| Action | Purpose |
|---|---|
| `list_stripe_quotes` | List quotes, filterable by customer or status |
| `get_stripe_quote` | Retrieve a quote by ID |
| `create_stripe_quote` | Create a draft quote for a customer |
| `update_stripe_quote` | Update a draft quote |
| `finalize_stripe_quote` | Finalize a draft quote to open |
| `accept_stripe_quote` | Accept an open quote, creating the invoice or subscription |
| `cancel_stripe_quote` | Cancel a draft or open quote |

### Events and webhook endpoints

| Action | Purpose |
|---|---|
| `list_stripe_events` | List events from the account event log |
| `get_stripe_event` | Retrieve a single event by ID |
| `list_stripe_webhook_endpoints` | List registered webhook endpoints |
| `get_stripe_webhook_endpoint` | Retrieve a webhook endpoint by ID |
| `create_stripe_webhook_endpoint` | Register a webhook endpoint and return its signing secret |
| `update_stripe_webhook_endpoint` | Update a webhook endpoint's URL, events, or disabled flag |
| `delete_stripe_webhook_endpoint` | Delete a webhook endpoint so Stripe stops posting to it |

### Files

| Action | Purpose |
|---|---|
| `upload_stripe_file` | Upload a file to Stripe, for example dispute evidence |
| `get_stripe_file` | Retrieve a file metadata record by ID |
| `list_stripe_files` | List uploaded files, filterable by purpose |

### Account

| Action | Purpose |
|---|---|
| `get_stripe_account` | Retrieve the connected Stripe account's profile |

## Example requests

```
Find the customer with email jane@example.com and list their last five charges.
```

```
Create a product called "Pro plan" with a $20 per month recurring price.
```

```
Refund the most recent charge on payment intent pi_123 in full.
```

```
Draft an invoice for customer cus_456 with one line item for 3 hours of consulting at $150 each, then finalize it.
```

```
Create a shareable payment link for the Pro plan price and send me the URL.
```

```
Show my current Stripe balance and the payouts from the last 30 days.
```

## Configuration

These settings live in **Settings → Integrations → Stripe** and are stored in `stripe_config.json` next to the credential. They fill in defaults when an action omits the matching field.

| Setting | Type | Default | Effect |
|---|---|---|---|
| Default currency (`default_currency`) | ISO 4217 lowercase code, e.g. `usd` | empty | Currency used when a `create_*` action omits `currency`. Amounts are integers in the smallest unit (cents for USD) |
| Default expand fields (`default_expand`) | list of field paths | empty | Field paths auto-added to `expand[]` on every retrieve and list, so nested objects come back hydrated |
| Auto-attach idempotency key (`require_idempotency_key`) | checkbox | on | Sends a fresh idempotency key on every POST and DELETE so a retry does not double-create resources |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "Invalid API key" or 401 | Test-mode key used against live resources, or the reverse | Check `/stripe status` for the mode, and connect a key that matches the data you are working with |
| Login rejected with a publishable-key message | You pasted a `pk_` key | Create a restricted (`rk_`) or secret (`sk_`) key at [dashboard.stripe.com/apikeys](https://dashboard.stripe.com/apikeys) |
| 403 or a permission error on a specific action | The restricted key was not granted that resource permission | Edit the restricted key in Stripe to add the permission, or connect a secret key. Retrying the same call does not help |
| `finalize_stripe_invoice` or `pay_stripe_invoice` fails with a state error | The invoice is not in the required state (draft to finalize, open to pay or void) | Check the invoice status first and apply the transition that matches it |
| `create_stripe_webhook_endpoint` fails | The URL is not publicly reachable, or `enabled_events` was left empty | Supply a public HTTPS URL and list the event types explicitly, or `["*"]` for all |
| Rate limit or 429 errors | Stripe allows about 100 reads and 100 writes per second | Wait for the window to reset and batch the work. The integration does not auto-retry on 429 |

## Next

- [HubSpot](hubspot.md): CRM objects and marketing on the same key-based, no-listener pattern
- [Credentials](credentials.md): where the key is stored and how `/cred status` reports it
- [Actions and action sets](../core/concepts/actions-and-action-sets.md): how the agent loads Stripe actions on demand
