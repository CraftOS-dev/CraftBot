# Stripe — Integration Reference

REST integration against `api.stripe.com/v1`. Covers customers, payment intents / charges / refunds, payment methods, products / prices, invoices + invoice items, subscriptions, checkout sessions, payment links, billing portal, coupons + promotion codes, disputes, payouts + balance, quotes, events + webhook endpoints, and file uploads (`files.stripe.com`).

## Essentials

- **Auth is a Bearer key, not OAuth.** Stripe Connect is deliberately not exposed: a shared CraftBot Connect platform would pool every user's merchant risk under one platform whose KYC obligations and suspension exposure cascade across the install base (same Q3 failure shape as Twitter). Each user supplies their own `sk_live_…` / `sk_test_…` (secret) or `rk_live_…` / `rk_test_…` (restricted) key. **Restricted keys are strongly preferred** — they're scoped per-resource and revocable independently. Publishable keys (`pk_…`) are rejected at login.
- **Test mode vs live mode is derived from the key prefix.** `*_test_*` → test mode, `*_live_*` → live mode. The credential records `livemode: bool` and `/stripe status` surfaces it. There is no runtime "switch to test mode" — connect a different key. **Restricted keys created in test mode CANNOT be used to manage live resources, and vice versa.** When an action 401s for "Invalid API key", the most likely cause is a test-vs-live mismatch.
- **All POST/PATCH/DELETE bodies are `application/x-www-form-urlencoded`, NOT JSON.** Stripe's quirk. The client owns this — every mutation routes through `_post` / `_delete`, which flatten nested params via `_flatten_params()` into Stripe's bracket notation:
  - `{"metadata": {"order_id": "6735"}}` → `metadata[order_id]=6735`
  - `{"expand": ["customer"]}` → `expand[0]=customer&expand[1]=…`
  - `{"items": [{"price": "price_xxx"}]}` → `items[0][price]=price_xxx`
  - `{"automatic_payment_methods": {"enabled": True}}` → `automatic_payment_methods[enabled]=true` (booleans lowercase, not `True`/`False`)

  Never bypass `_flatten_params` and pass `json=` to httpx — Stripe will reject the request as malformed even though the payload looks correct.
- **Pinned API version (`Stripe-Version: 2024-12-18.acacia`).** Pinning keeps field shapes stable when Stripe ships new releases. Bump deliberately with a regression pass — don't track the latest silently.
- **Pagination is cursor-based with `starting_after` / `ending_before`.** Every list returns `{data: [...], has_more, url, object: "list"}`. The cursor is the **ID of the last item in `data`** — there is no `next_cursor` field; the caller pulls `data[-1].id` and passes it as `starting_after` on the next request. `limit` defaults to 10 (NOT 30 like most APIs), capped at 100.
- **Search uses Stripe's query language, not `filterGroups`.** `query=email:'jane@example.com'`, `query=name~'jane'`, `query=metadata['order_id']:'42'`, combined with `AND` / `OR`. Only supported on `/customers/search`, `/payment_intents/search`, `/charges/search`, `/invoices/search`, `/subscriptions/search`, `/prices/search`, `/products/search`. Operators: `:` (equal), `~` (substring contains), `>`, `<`, `>=`, `<=`. Free-text search across all fields is NOT supported — every clause names a property.
- **Idempotency-Key support is automatic on mutations.** The client attaches a fresh UUID `Idempotency-Key` header on every POST/DELETE by default (configurable via `require_idempotency_key`). Pass an explicit `idempotency_key=` to chain retries to the SAME key — this is what you want when the agent retries on a network error. Stripe stores idempotent responses for 24h.
- **Amounts are integers in the smallest currency unit.** USD: cents. JPY: yen (no subunit). Currency-aware: GBP/EUR/USD are 2-decimal, BHD is 3-decimal, JPY/KRW are 0-decimal. The client does NOT convert — `amount: 1000` in USD = $10.00, `amount: 1000` in JPY = ¥1000.
- **Currency is lowercase ISO 4217 (`usd`, `eur`, `jpy`).** Anywhere the client accepts a currency it lowercases it before sending; the API rejects uppercase.
- **ID prefixes (use to identify object type from an ID at a glance):**

  | Prefix | Object |
  |--------|--------|
  | `acct_` | Account |
  | `ba_` | Bank account |
  | `card_` | Card |
  | `ch_` | Charge |
  | `cs_` | Checkout session |
  | `cus_` | Customer |
  | `di_` | Dispute |
  | `evt_` | Event |
  | `file_` | File |
  | `in_` | Invoice |
  | `ii_` | Invoice item |
  | `pi_` | Payment intent |
  | `pl_` | Payment link |
  | `pm_` | Payment method |
  | `po_` | Payout |
  | `price_` | Price |
  | `prod_` | Product |
  | `promo_` | Promotion code |
  | `qt_` | Quote |
  | `re_` | Refund |
  | `seti_` | Setup intent |
  | `sub_` | Subscription |
  | `si_` | Subscription item |
  | `txn_` | Balance transaction |
  | `we_` | Webhook endpoint |

  Coupon IDs are user-defined or `<random alphanumeric>` — no prefix.
- **`expand[]` is how you fetch nested objects in one round-trip.** Stripe lists return IDs by default — `subscription.latest_invoice` is the string `"in_xxx"`, not the object. Pass `expand=["latest_invoice", "customer", "default_payment_method"]` to hydrate them. Up to 4 levels deep. The handler's `default_expand` config knob auto-attaches a list of fields to every read — useful when downstream actions always need the same hydration.
- **PaymentIntent confirmation flow.** Modern integrations use **Automatic Payment Methods**: `create_payment_intent` with no `payment_method_types` / `payment_method` defaults to `automatic_payment_methods={"enabled": True}` and Stripe picks the methods that match. To collect the payment, hand the `client_secret` to a frontend Stripe Elements / Checkout flow — the agent can't complete payment from server-side alone unless the customer's payment method is already saved (`off_session=True`) and SCA/3DS is not triggered. If `confirm=True` is passed at creation and SCA is needed, the PI returns `status="requires_action"` with a `next_action` payload — surface it to the caller.
- **Subscriptions cancel via DELETE, not POST.** `cancel_subscription` sends `DELETE /v1/subscriptions/{id}` with optional body params (`invoice_now`, `prorate`, `cancellation_details`). Stripe accepts a body on DELETE only for this endpoint; the helper handles it. To "cancel at end of period" without immediate cancellation, use `update_subscription(properties={"cancel_at_period_end": True})` instead.
- **Invoice lifecycle gates.** Draft (created) → finalized → paid / void / uncollectible. Specific transitions only fire on specific states: `finalize_invoice` requires `status: draft`, `pay_invoice` / `void_invoice` require `status: open`, `delete_invoice` only works on drafts. Outside the matching state the API returns `400 invoice_not_in_draft_state` / `invoice_not_finalized` / etc. `mark_invoice_uncollectible` flips an open invoice to write-off and is the modern alternative to `void_invoice` for "we're not collecting this".
- **Disputes evidence must be 'submitted', not just saved.** `update_dispute(evidence={...})` saves a draft (you can iterate). `update_dispute(evidence={...}, submit=True)` finalizes and submits to the card network — irreversible. Stripe also auto-submits draft evidence at the `evidence_due_by` deadline. `close_dispute` is for forfeiting the dispute (accepts the chargeback) — once closed it cannot be reopened.
- **Refunds reference EITHER a charge or a payment_intent, not both.** Pass exactly one. `create_refund(payment_intent="pi_…")` refunds the most recent successful charge on that PI; `create_refund(charge="ch_…")` refunds the specific charge. `amount` omitted → full refund of the remaining capturable amount.
- **Coupon IDs are user-chosen and immutable.** If you pass `id="SUMMER25"` to `create_coupon` you get a coupon at `coupons/SUMMER25`. Updates can change `name` and `metadata` only — duration / amount_off / percent_off / currency / etc. are write-once. To change the discount you delete the coupon and create a new one (existing redemptions are unaffected; the old coupon stays on subscriptions that already used it).
- **Promotion codes are the customer-facing wrapper for coupons.** A coupon defines the discount; a promotion code defines the redeemable string + redemption limits (`restrictions.first_time_transaction`, `restrictions.minimum_amount`, `max_redemptions`, `expires_at`, `customer` allowlist). The same coupon can have many promotion codes.
- **File uploads go to a different host.** `files.stripe.com/v1/files`, multipart-encoded. `purpose` is required and constrains downstream use: `dispute_evidence` is the most common — once uploaded the resulting `file_id` becomes part of the `evidence` object on `update_dispute`. The client uses `_post` only for the main API host; `upload_file` routes to `STRIPE_FILES_API` directly.
- **Webhook endpoints need a publicly reachable URL.** Stripe validates the URL before creation (HEAD request). Localhost won't work — use `stripe listen --forward-to` (Stripe CLI) for development. `enabled_events` defaults to NOTHING — you must explicitly list each event type or `["*"]` for all. Test the signature verification with `whsec_…` before relying on live deliveries.
- **Connect (`Stripe-Account: acct_…` header) is supported per-call, not as the default.** Every client method takes an optional `connect_account` kwarg that injects the header. We do NOT pre-resolve a Connect account because the package isn't a Connect platform; this is for the rare case where a user's standalone account happens to have one Connect link they want to act on.
- **Rate limits: 100 read + 100 write per second in test, 100 read + 100 write per second in live (burst up to 1000 over 5s).** 429 responses include `Retry-After`. The package does not auto-retry on 429 — wrap multi-call actions in `with_client` and respect the header if you write one.
- **No listener / streaming surface.** Stripe is webhook-driven; receiving events requires a public callback URL the package can't provide. The client exposes `list_events` / `get_event` / `webhook_endpoints` CRUD so an agent can poll and a host can manage subscriptions, but `start_listening` / `stop_listening` are no-ops inherited from the base class.
