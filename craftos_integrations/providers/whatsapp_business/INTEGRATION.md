# WhatsApp Business — Integration Reference

WhatsApp Business Cloud API (Meta Graph). Enterprise integration with access token + `phone_number_id` — completely different from the QR-based `whatsapp_web`.

## Essentials

- **Not `whatsapp_web`.** No QR scan, no browser bridge. Outbound only via the Cloud API; incoming requires Meta webhook setup (not auto-listened by this integration). Don't confuse the two.
- **`phone_number_id` is a Meta numeric ID, NOT a phone number.** The router should never ask the user for "your WhatsApp number" — `cred.phone_number_id` is the From identity, resolved from the Meta dashboard at connect time.
- **Recipients are bare E.164 phone numbers** (e.g. `"14155552671"`). No `@c.us` / `@lid` JID format like `whatsapp_web`. Pass the digits only — no `+`, no formatting.
- **24-hour customer-service window.** Free-form text via `send_whatsapp_business_text` only works if the recipient sent you a message in the last 24h. Outside that window you MUST use `send_whatsapp_business_template` with a pre-approved template (created in Meta dashboard).
- **Templates need `template_name`, `language_code`, and components** (placeholder fills). The template itself must already exist in the user's Meta Business account — the router can't create templates on the fly.
- **No contact search, no chat history.** Unlike `whatsapp_web`, there are no `search_contact` / `get_chat_messages` actions. The recipient phone must come from the user or from an incoming webhook payload — not from a stored contact list.
