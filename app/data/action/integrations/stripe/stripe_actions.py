"""Stripe action surface.

Mirrors the Stripe client in
``craftos_integrations/integrations/stripe/__init__.py`` 1:1. Sub-sets are
prefixed with ``stripe_`` per the action_set convention; the ``stripe``
umbrella tags the high-value 20% the agent should reach for by default.

Conventions:

- **Amounts are integers in the smallest currency unit.** $10.00 USD → 1000.
  See INTEGRATION.md for the per-currency exponent rules.
- **IDs are strings with stable prefixes.** ``cus_…`` (customer), ``pi_…``
  (payment intent), ``in_…`` (invoice), ``sub_…`` (subscription), etc. See
  INTEGRATION.md for the full prefix table.
- **``expand`` is comma-separated and resolves nested objects in one call**
  (``customer,latest_invoice,default_payment_method``).
- **Search uses Stripe's query language** (``email:'jane@example.com'``,
  ``metadata['order_id']:'42'``, ``status:'succeeded'``), NOT free-text. See
  INTEGRATION.md for the operator table.

Every helper import is inside the function body because the action framework
exec()'s each handler in a fresh namespace.
"""

from agent_core import action


# ==================================================================
# Customers (stripe_customers)
# ==================================================================


@action(
    name="list_stripe_customers",
    description="List Stripe customers. Filter by email, created window. Cursor pagination via 'starting_after' from previous response's data[-1].id.",
    action_sets=["stripe_customers", "stripe"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100, default 10).",
            "example": 10,
        },
        "starting_after": {
            "type": "string",
            "description": "Cursor — ID of the last item from the previous page.",
            "example": "cus_NffrFeUfNV2Hib",
        },
        "ending_before": {
            "type": "string",
            "description": "Cursor for backwards pagination.",
            "example": "",
        },
        "email": {
            "type": "string",
            "description": "Exact-match email filter.",
            "example": "jane@example.com",
        },
        "created_gte": {
            "type": "integer",
            "description": "Created at or after this UNIX timestamp.",
            "example": 1717200000,
        },
        "created_lte": {
            "type": "integer",
            "description": "Created at or before this UNIX timestamp.",
            "example": 1719792000,
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand (e.g. 'default_source,subscriptions').",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_customers(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_customers",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        email=input_data.get("email") or None,
        created_gte=input_data.get("created_gte"),
        created_lte=input_data.get("created_lte"),
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="get_stripe_customer",
    description="Retrieve a Stripe customer by ID.",
    action_sets=["stripe_customers", "stripe"],
    input_schema={
        "customer_id": {
            "type": "string",
            "description": "Customer ID.",
            "example": "cus_NffrFeUfNV2Hib",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "default_source,invoice_settings.default_payment_method",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_customer(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "get_customer",
        customer_id=input_data["customer_id"],
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="create_stripe_customer",
    description="Create a Stripe customer. At minimum pass email or name. Returns the new cus_… ID.",
    action_sets=["stripe_customers", "stripe"],
    input_schema={
        "email": {
            "type": "string",
            "description": "Customer email.",
            "example": "jane@example.com",
        },
        "name": {
            "type": "string",
            "description": "Customer full name.",
            "example": "Jane Doe",
        },
        "phone": {
            "type": "string",
            "description": "Phone number (E.164 recommended).",
            "example": "+15551234567",
        },
        "description": {
            "type": "string",
            "description": "Internal description / note.",
            "example": "Imported from CSV 2026-06-14",
        },
        "address": {
            "type": "object",
            "description": "Billing address (line1, line2, city, state, postal_code, country).",
            "example": {"line1": "1 Main St", "city": "Springfield", "country": "US"},
        },
        "shipping": {
            "type": "object",
            "description": "Shipping object: {name, phone, address}.",
            "example": {
                "name": "Jane Doe",
                "address": {"line1": "1 Main St", "country": "US"},
            },
        },
        "metadata": {
            "type": "object",
            "description": "Arbitrary key/value labels.",
            "example": {"crm_id": "12345"},
        },
        "payment_method": {
            "type": "string",
            "description": "Default payment method to attach.",
            "example": "",
        },
        "invoice_settings": {
            "type": "object",
            "description": "Defaults applied to future invoices.",
            "example": {"default_payment_method": "pm_xxx"},
        },
        "tax_exempt": {
            "type": "string",
            "description": "'none' | 'exempt' | 'reverse'.",
            "example": "none",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key — pass the same key on a retry to dedupe.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_stripe_customer(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "create_customer",
        email=input_data.get("email") or None,
        name=input_data.get("name") or None,
        phone=input_data.get("phone") or None,
        description=input_data.get("description") or None,
        address=input_data.get("address") or None,
        shipping=input_data.get("shipping") or None,
        metadata=input_data.get("metadata") or None,
        payment_method=input_data.get("payment_method") or None,
        invoice_settings=input_data.get("invoice_settings") or None,
        tax_exempt=input_data.get("tax_exempt") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="update_stripe_customer",
    description="Update a Stripe customer. 'properties' is the flat update dict (email, name, phone, address, metadata, …).",
    action_sets=["stripe_customers", "stripe"],
    input_schema={
        "customer_id": {
            "type": "string",
            "description": "Customer ID.",
            "example": "cus_NffrFeUfNV2Hib",
        },
        "properties": {
            "type": "object",
            "description": "Properties to update.",
            "example": {"email": "new@example.com", "metadata": {"vip": "true"}},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_stripe_customer(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "update_customer",
        customer_id=input_data["customer_id"],
        properties=input_data.get("properties") or {},
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="delete_stripe_customer",
    description="Permanently delete a Stripe customer. Charges and invoices already tied to the customer are preserved. This action is irreversible.",
    action_sets=["stripe_customers"],
    input_schema={
        "customer_id": {
            "type": "string",
            "description": "Customer ID.",
            "example": "cus_NffrFeUfNV2Hib",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_stripe_customer(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "delete_customer",
        customer_id=input_data["customer_id"],
    )


@action(
    name="search_stripe_customers",
    description="Search Stripe customers using Stripe's query language. Examples: \"email:'jane@example.com'\", \"name~'jane' AND metadata['vip']:'true'\". NOT free text — every clause names a property.",
    action_sets=["stripe_customers", "stripe"],
    input_schema={
        "query": {
            "type": "string",
            "description": "Stripe query language clause. Operators: ':' (equal), '~' (contains), AND, OR.",
            "example": "email:'jane@example.com'",
        },
        "limit": {
            "type": "integer",
            "description": "Max results (1-100, default 10).",
            "example": 10,
        },
        "page": {
            "type": "string",
            "description": "Pagination page token from previous response.next_page.",
            "example": "",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_stripe_customers(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "search_customers",
        query=input_data["query"],
        limit=input_data.get("limit", 10),
        page=input_data.get("page") or None,
        expand=_csv(input_data.get("expand")),
    )


# ==================================================================
# Payments — PaymentIntents, Charges, Refunds (stripe_payments)
# ==================================================================


@action(
    name="list_stripe_payment_intents",
    description="List PaymentIntents. Filter by customer, created window. Cursor pagination via 'starting_after'.",
    action_sets=["stripe_payments", "stripe"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100, default 10).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "customer": {
            "type": "string",
            "description": "Filter to a specific customer.",
            "example": "cus_NffrFeUfNV2Hib",
        },
        "created_gte": {
            "type": "integer",
            "description": "Created >= UNIX timestamp.",
            "example": 0,
        },
        "created_lte": {
            "type": "integer",
            "description": "Created <= UNIX timestamp.",
            "example": 0,
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "data.customer,data.latest_charge",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_payment_intents(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_payment_intents",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        customer=input_data.get("customer") or None,
        created_gte=input_data.get("created_gte") or None,
        created_lte=input_data.get("created_lte") or None,
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="get_stripe_payment_intent",
    description="Retrieve a PaymentIntent by ID.",
    action_sets=["stripe_payments"],
    input_schema={
        "payment_intent_id": {
            "type": "string",
            "description": "PaymentIntent ID.",
            "example": "pi_3MtwBwLkdIwHu7ix28a3tqPa",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "customer,latest_charge",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_payment_intent(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "get_payment_intent",
        payment_intent_id=input_data["payment_intent_id"],
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="create_stripe_payment_intent",
    description="Create a PaymentIntent. 'amount' is in the smallest currency unit ($10 USD = 1000). Defaults to automatic_payment_methods when neither payment_method nor payment_method_types is set.",
    action_sets=["stripe_payments", "stripe"],
    input_schema={
        "amount": {
            "type": "integer",
            "description": "Amount in smallest currency unit (cents for USD).",
            "example": 2000,
        },
        "currency": {
            "type": "string",
            "description": "ISO 4217 lowercase. Defaults to integration 'default_currency'.",
            "example": "usd",
        },
        "customer": {
            "type": "string",
            "description": "Customer ID for off-session future payments.",
            "example": "cus_NffrFeUfNV2Hib",
        },
        "payment_method": {
            "type": "string",
            "description": "Existing payment method to attach.",
            "example": "",
        },
        "payment_method_types": {
            "type": "array",
            "description": "Allowed payment method types. Mutually exclusive with automatic_payment_methods.",
            "example": ["card"],
        },
        "automatic_payment_methods": {
            "type": "object",
            "description": "Enable Stripe's automatic method picker.",
            "example": {"enabled": True},
        },
        "confirm": {
            "type": "boolean",
            "description": "Confirm immediately. Requires payment_method.",
            "example": False,
        },
        "capture_method": {
            "type": "string",
            "description": "'automatic' or 'manual' (capture later).",
            "example": "automatic",
        },
        "description": {
            "type": "string",
            "description": "Internal description.",
            "example": "Order #42",
        },
        "receipt_email": {
            "type": "string",
            "description": "Email to send receipt to on success.",
            "example": "",
        },
        "setup_future_usage": {
            "type": "string",
            "description": "'on_session' | 'off_session' — save method for later.",
            "example": "",
        },
        "statement_descriptor": {
            "type": "string",
            "description": "Appears on customer's bank statement.",
            "example": "",
        },
        "metadata": {
            "type": "object",
            "description": "Arbitrary key/value labels.",
            "example": {"order_id": "42"},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_stripe_payment_intent(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "create_payment_intent",
        amount=input_data["amount"],
        currency=input_data.get("currency") or None,
        customer=input_data.get("customer") or None,
        payment_method=input_data.get("payment_method") or None,
        payment_method_types=input_data.get("payment_method_types") or None,
        automatic_payment_methods=input_data.get("automatic_payment_methods") or None,
        confirm=input_data.get("confirm"),
        capture_method=input_data.get("capture_method") or None,
        description=input_data.get("description") or None,
        receipt_email=input_data.get("receipt_email") or None,
        setup_future_usage=input_data.get("setup_future_usage") or None,
        statement_descriptor=input_data.get("statement_descriptor") or None,
        metadata=input_data.get("metadata") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="update_stripe_payment_intent",
    description="Update a PaymentIntent's properties (amount, metadata, description, etc.). Cannot update once succeeded.",
    action_sets=["stripe_payments"],
    input_schema={
        "payment_intent_id": {
            "type": "string",
            "description": "PaymentIntent ID.",
            "example": "pi_…",
        },
        "properties": {
            "type": "object",
            "description": "Properties to update.",
            "example": {"amount": 3000, "metadata": {"updated_by": "agent"}},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_stripe_payment_intent(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "update_payment_intent",
        payment_intent_id=input_data["payment_intent_id"],
        properties=input_data.get("properties") or {},
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="confirm_stripe_payment_intent",
    description="Confirm a PaymentIntent server-side. For off-session repeat charges or completing a flow started client-side. May return 'requires_action' (3DS/SCA).",
    action_sets=["stripe_payments"],
    input_schema={
        "payment_intent_id": {
            "type": "string",
            "description": "PaymentIntent ID.",
            "example": "pi_…",
        },
        "payment_method": {
            "type": "string",
            "description": "Payment method to use.",
            "example": "pm_…",
        },
        "return_url": {
            "type": "string",
            "description": "URL to redirect to after authentication.",
            "example": "https://example.com/return",
        },
        "off_session": {
            "type": "boolean",
            "description": "True for charging a saved method without customer present.",
            "example": True,
        },
        "setup_future_usage": {
            "type": "string",
            "description": "'on_session' | 'off_session'.",
            "example": "",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def confirm_stripe_payment_intent(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "confirm_payment_intent",
        payment_intent_id=input_data["payment_intent_id"],
        payment_method=input_data.get("payment_method") or None,
        return_url=input_data.get("return_url") or None,
        off_session=input_data.get("off_session"),
        setup_future_usage=input_data.get("setup_future_usage") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="capture_stripe_payment_intent",
    description="Capture funds for a PaymentIntent previously authorized with capture_method='manual'. Optional partial capture via amount_to_capture.",
    action_sets=["stripe_payments", "stripe"],
    input_schema={
        "payment_intent_id": {
            "type": "string",
            "description": "PaymentIntent ID.",
            "example": "pi_…",
        },
        "amount_to_capture": {
            "type": "integer",
            "description": "Partial capture amount in smallest unit. Omit to capture the full amount.",
            "example": 0,
        },
        "statement_descriptor": {
            "type": "string",
            "description": "Override statement descriptor for this capture.",
            "example": "",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def capture_stripe_payment_intent(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "capture_payment_intent",
        payment_intent_id=input_data["payment_intent_id"],
        amount_to_capture=input_data.get("amount_to_capture") or None,
        statement_descriptor=input_data.get("statement_descriptor") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="cancel_stripe_payment_intent",
    description="Cancel a PaymentIntent. Only allowed for PIs in requires_payment_method, requires_capture, requires_confirmation, or requires_action.",
    action_sets=["stripe_payments"],
    input_schema={
        "payment_intent_id": {
            "type": "string",
            "description": "PaymentIntent ID.",
            "example": "pi_…",
        },
        "cancellation_reason": {
            "type": "string",
            "description": "'duplicate' | 'fraudulent' | 'requested_by_customer' | 'abandoned'.",
            "example": "requested_by_customer",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def cancel_stripe_payment_intent(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "cancel_payment_intent",
        payment_intent_id=input_data["payment_intent_id"],
        cancellation_reason=input_data.get("cancellation_reason") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="search_stripe_payment_intents",
    description="Search PaymentIntents with Stripe's query language. Example: \"status:'succeeded' AND amount>1000\".",
    action_sets=["stripe_payments"],
    input_schema={
        "query": {
            "type": "string",
            "description": "Stripe query clause.",
            "example": "status:'succeeded' AND amount>1000",
        },
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "page": {
            "type": "string",
            "description": "Pagination page token.",
            "example": "",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_stripe_payment_intents(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "search_payment_intents",
        query=input_data["query"],
        limit=input_data.get("limit", 10),
        page=input_data.get("page") or None,
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="list_stripe_charges",
    description="List Charges (legacy direct-charge view). Filter by customer, payment_intent, or transfer_group.",
    action_sets=["stripe_payments"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "customer": {
            "type": "string",
            "description": "Filter to a specific customer.",
            "example": "",
        },
        "payment_intent": {
            "type": "string",
            "description": "Filter to a specific PaymentIntent.",
            "example": "",
        },
        "transfer_group": {
            "type": "string",
            "description": "Filter to a transfer_group label.",
            "example": "",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_charges(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_charges",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        customer=input_data.get("customer") or None,
        payment_intent=input_data.get("payment_intent") or None,
        transfer_group=input_data.get("transfer_group") or None,
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="get_stripe_charge",
    description="Retrieve a Charge by ID.",
    action_sets=["stripe_payments"],
    input_schema={
        "charge_id": {
            "type": "string",
            "description": "Charge ID.",
            "example": "ch_3MtwBwLkdIwHu7ix28a3tqPa",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "customer,payment_intent",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_charge(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "get_charge",
        charge_id=input_data["charge_id"],
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="create_stripe_refund",
    description="Refund a PaymentIntent or Charge. Pass exactly ONE of payment_intent / charge. Omit 'amount' for a full refund.",
    action_sets=["stripe_payments", "stripe"],
    input_schema={
        "payment_intent": {
            "type": "string",
            "description": "PaymentIntent ID to refund. Mutually exclusive with 'charge'.",
            "example": "pi_…",
        },
        "charge": {
            "type": "string",
            "description": "Charge ID to refund. Mutually exclusive with 'payment_intent'.",
            "example": "",
        },
        "amount": {
            "type": "integer",
            "description": "Partial refund amount in smallest currency unit. Omit for full refund.",
            "example": 0,
        },
        "reason": {
            "type": "string",
            "description": "'duplicate' | 'fraudulent' | 'requested_by_customer'.",
            "example": "requested_by_customer",
        },
        "metadata": {
            "type": "object",
            "description": "Arbitrary labels.",
            "example": {"ticket_id": "T-42"},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_stripe_refund(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "create_refund",
        payment_intent=input_data.get("payment_intent") or None,
        charge=input_data.get("charge") or None,
        amount=input_data.get("amount") or None,
        reason=input_data.get("reason") or None,
        metadata=input_data.get("metadata") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="get_stripe_refund",
    description="Retrieve a Refund by ID.",
    action_sets=["stripe_payments"],
    input_schema={
        "refund_id": {
            "type": "string",
            "description": "Refund ID.",
            "example": "re_3MtwBwLkdIwHu7ix28a3tqPa",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_refund(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "get_refund",
        refund_id=input_data["refund_id"],
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="list_stripe_refunds",
    description="List Refunds, optionally scoped to a PaymentIntent or Charge.",
    action_sets=["stripe_payments"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "payment_intent": {
            "type": "string",
            "description": "Filter to a specific PaymentIntent.",
            "example": "",
        },
        "charge": {
            "type": "string",
            "description": "Filter to a specific Charge.",
            "example": "",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_refunds(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_refunds",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        payment_intent=input_data.get("payment_intent") or None,
        charge=input_data.get("charge") or None,
        expand=_csv(input_data.get("expand")),
    )


# ==================================================================
# Payment methods (stripe_payment_methods)
# ==================================================================


@action(
    name="list_stripe_payment_methods",
    description="List PaymentMethods. If customer is set, lists methods attached to that customer; otherwise lists across the account.",
    action_sets=["stripe_payment_methods"],
    input_schema={
        "customer": {
            "type": "string",
            "description": "Filter to a customer's attached methods.",
            "example": "cus_NffrFeUfNV2Hib",
        },
        "type": {
            "type": "string",
            "description": "Payment method type ('card', 'us_bank_account', 'sepa_debit', …). Default 'card'.",
            "example": "card",
        },
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_payment_methods(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_payment_methods",
        customer=input_data.get("customer") or None,
        type=input_data.get("type") or "card",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="get_stripe_payment_method",
    description="Retrieve a PaymentMethod by ID.",
    action_sets=["stripe_payment_methods"],
    input_schema={
        "payment_method_id": {
            "type": "string",
            "description": "PaymentMethod ID.",
            "example": "pm_…",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_payment_method(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "get_payment_method",
        payment_method_id=input_data["payment_method_id"],
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="attach_stripe_payment_method",
    description="Attach a PaymentMethod to a Customer so it can be used for future off-session charges.",
    action_sets=["stripe_payment_methods"],
    input_schema={
        "payment_method_id": {
            "type": "string",
            "description": "PaymentMethod ID.",
            "example": "pm_…",
        },
        "customer": {
            "type": "string",
            "description": "Customer to attach to.",
            "example": "cus_NffrFeUfNV2Hib",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def attach_stripe_payment_method(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "attach_payment_method",
        payment_method_id=input_data["payment_method_id"],
        customer=input_data["customer"],
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="detach_stripe_payment_method",
    description="Detach a PaymentMethod from its Customer. Future charges against it will fail.",
    action_sets=["stripe_payment_methods"],
    input_schema={
        "payment_method_id": {
            "type": "string",
            "description": "PaymentMethod ID.",
            "example": "pm_…",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def detach_stripe_payment_method(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "detach_payment_method",
        payment_method_id=input_data["payment_method_id"],
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="update_stripe_payment_method",
    description="Update a PaymentMethod's metadata or billing details. Card brand/number CANNOT be updated.",
    action_sets=["stripe_payment_methods"],
    input_schema={
        "payment_method_id": {
            "type": "string",
            "description": "PaymentMethod ID.",
            "example": "pm_…",
        },
        "properties": {
            "type": "object",
            "description": "Properties to update.",
            "example": {
                "billing_details": {"email": "new@example.com"},
                "metadata": {"label": "primary"},
            },
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_stripe_payment_method(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "update_payment_method",
        payment_method_id=input_data["payment_method_id"],
        properties=input_data.get("properties") or {},
        idempotency_key=input_data.get("idempotency_key") or None,
    )


# ==================================================================
# Products + prices (stripe_products)
# ==================================================================


@action(
    name="list_stripe_products",
    description="List Products. Filter by active flag or an explicit IDs list.",
    action_sets=["stripe_products", "stripe"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "active": {
            "type": "boolean",
            "description": "Only active or only inactive.",
            "example": True,
        },
        "ids": {
            "type": "array",
            "description": "Explicit list of product IDs to fetch.",
            "example": ["prod_…"],
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "data.default_price",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_products(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_products",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        active=input_data.get("active"),
        ids=input_data.get("ids") or None,
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="get_stripe_product",
    description="Retrieve a Product by ID.",
    action_sets=["stripe_products"],
    input_schema={
        "product_id": {
            "type": "string",
            "description": "Product ID.",
            "example": "prod_NWjs8kKbJWmuuc",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "default_price",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_product(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "get_product",
        product_id=input_data["product_id"],
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="create_stripe_product",
    description="Create a Product. Pass default_price_data to create the product and its first price atomically.",
    action_sets=["stripe_products", "stripe"],
    input_schema={
        "name": {
            "type": "string",
            "description": "Product name (required).",
            "example": "Standard Plan",
        },
        "description": {
            "type": "string",
            "description": "Marketing description.",
            "example": "Up to 5 seats",
        },
        "active": {
            "type": "boolean",
            "description": "Whether the product is active. Default True.",
            "example": True,
        },
        "images": {
            "type": "array",
            "description": "Image URLs.",
            "example": ["https://example.com/img.png"],
        },
        "metadata": {
            "type": "object",
            "description": "Arbitrary labels.",
            "example": {"sku": "SP-001"},
        },
        "default_price_data": {
            "type": "object",
            "description": "Inline price to create alongside the product.",
            "example": {
                "currency": "usd",
                "unit_amount": 1000,
                "recurring": {"interval": "month"},
            },
        },
        "shippable": {
            "type": "boolean",
            "description": "Whether the product is shippable.",
            "example": False,
        },
        "statement_descriptor": {
            "type": "string",
            "description": "Appears on bank statements.",
            "example": "",
        },
        "tax_code": {
            "type": "string",
            "description": "Stripe Tax code (txcd_…).",
            "example": "",
        },
        "unit_label": {
            "type": "string",
            "description": "Singular noun for a unit (e.g. 'seat').",
            "example": "seat",
        },
        "url": {"type": "string", "description": "Public product URL.", "example": ""},
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_stripe_product(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "create_product",
        name=input_data["name"],
        description=input_data.get("description") or None,
        active=input_data.get("active"),
        images=input_data.get("images") or None,
        metadata=input_data.get("metadata") or None,
        default_price_data=input_data.get("default_price_data") or None,
        shippable=input_data.get("shippable"),
        statement_descriptor=input_data.get("statement_descriptor") or None,
        tax_code=input_data.get("tax_code") or None,
        unit_label=input_data.get("unit_label") or None,
        url=input_data.get("url") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="update_stripe_product",
    description="Update a Product's properties.",
    action_sets=["stripe_products"],
    input_schema={
        "product_id": {
            "type": "string",
            "description": "Product ID.",
            "example": "prod_…",
        },
        "properties": {
            "type": "object",
            "description": "Properties to update.",
            "example": {"name": "Pro Plan", "active": True},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_stripe_product(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "update_product",
        product_id=input_data["product_id"],
        properties=input_data.get("properties") or {},
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="delete_stripe_product",
    description="Delete a Product. Only allowed if it has no associated Prices. Otherwise mark it active=False via update.",
    action_sets=["stripe_products"],
    input_schema={
        "product_id": {
            "type": "string",
            "description": "Product ID.",
            "example": "prod_…",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_stripe_product(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "delete_product",
        product_id=input_data["product_id"],
    )


@action(
    name="list_stripe_prices",
    description="List Prices, optionally scoped to a product. Filter recurring vs one_time via 'type', cadence via 'recurring_interval'.",
    action_sets=["stripe_products"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "active": {
            "type": "boolean",
            "description": "Only active or only inactive.",
            "example": True,
        },
        "product": {
            "type": "string",
            "description": "Filter to a specific product.",
            "example": "prod_…",
        },
        "currency": {
            "type": "string",
            "description": "ISO 4217 lowercase filter.",
            "example": "usd",
        },
        "type": {
            "type": "string",
            "description": "'one_time' | 'recurring'.",
            "example": "recurring",
        },
        "recurring_interval": {
            "type": "string",
            "description": "'day' | 'week' | 'month' | 'year'.",
            "example": "month",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "data.product",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_prices(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_prices",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        active=input_data.get("active"),
        product=input_data.get("product") or None,
        currency=input_data.get("currency") or None,
        type=input_data.get("type") or None,
        recurring_interval=input_data.get("recurring_interval") or None,
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="get_stripe_price",
    description="Retrieve a Price by ID.",
    action_sets=["stripe_products"],
    input_schema={
        "price_id": {
            "type": "string",
            "description": "Price ID.",
            "example": "price_1MoBy5LkdIwHu7ixZhnattbh",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "product",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_price(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "get_price",
        price_id=input_data["price_id"],
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="create_stripe_price",
    description="Create a Price for an existing Product (or set product_data inline). Pass 'recurring' for subscriptions, omit for one-time. unit_amount is in smallest currency unit.",
    action_sets=["stripe_products", "stripe"],
    input_schema={
        "currency": {
            "type": "string",
            "description": "ISO 4217 lowercase. Defaults to integration default_currency.",
            "example": "usd",
        },
        "product": {
            "type": "string",
            "description": "Existing Product ID. Mutually exclusive with product_data.",
            "example": "prod_…",
        },
        "product_data": {
            "type": "object",
            "description": "Inline product to create.",
            "example": {"name": "New product"},
        },
        "unit_amount": {
            "type": "integer",
            "description": "Price in smallest currency unit.",
            "example": 1000,
        },
        "unit_amount_decimal": {
            "type": "string",
            "description": "Decimal price (e.g. '1000.5'). Use when sub-cent precision is needed.",
            "example": "",
        },
        "active": {
            "type": "boolean",
            "description": "Whether the price is active.",
            "example": True,
        },
        "nickname": {
            "type": "string",
            "description": "Internal label.",
            "example": "Monthly Standard",
        },
        "recurring": {
            "type": "object",
            "description": "Recurring config: {interval: 'month', interval_count: 1, usage_type: 'licensed'}.",
            "example": {"interval": "month"},
        },
        "tax_behavior": {
            "type": "string",
            "description": "'inclusive' | 'exclusive' | 'unspecified'.",
            "example": "unspecified",
        },
        "billing_scheme": {
            "type": "string",
            "description": "'per_unit' | 'tiered'.",
            "example": "per_unit",
        },
        "metadata": {
            "type": "object",
            "description": "Arbitrary labels.",
            "example": {"plan_id": "monthly_v2"},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_stripe_price(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "create_price",
        currency=input_data.get("currency") or None,
        product=input_data.get("product") or None,
        product_data=input_data.get("product_data") or None,
        unit_amount=input_data.get("unit_amount") or None,
        unit_amount_decimal=input_data.get("unit_amount_decimal") or None,
        active=input_data.get("active"),
        nickname=input_data.get("nickname") or None,
        recurring=input_data.get("recurring") or None,
        tax_behavior=input_data.get("tax_behavior") or None,
        billing_scheme=input_data.get("billing_scheme") or None,
        metadata=input_data.get("metadata") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="update_stripe_price",
    description="Update a Price. Most fields are immutable; nickname, active, metadata, tax_behavior are updatable.",
    action_sets=["stripe_products"],
    input_schema={
        "price_id": {
            "type": "string",
            "description": "Price ID.",
            "example": "price_…",
        },
        "properties": {
            "type": "object",
            "description": "Properties to update.",
            "example": {"active": False, "nickname": "Legacy"},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_stripe_price(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "update_price",
        price_id=input_data["price_id"],
        properties=input_data.get("properties") or {},
        idempotency_key=input_data.get("idempotency_key") or None,
    )


# ==================================================================
# Invoices + invoice items (stripe_invoices)
# ==================================================================


@action(
    name="list_stripe_invoices",
    description="List Invoices. Filter by customer, subscription, status (draft/open/paid/void/uncollectible), or created window.",
    action_sets=["stripe_invoices", "stripe"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "customer": {
            "type": "string",
            "description": "Filter to a specific customer.",
            "example": "",
        },
        "subscription": {
            "type": "string",
            "description": "Filter to a specific subscription.",
            "example": "",
        },
        "status": {
            "type": "string",
            "description": "'draft' | 'open' | 'paid' | 'uncollectible' | 'void'.",
            "example": "open",
        },
        "collection_method": {
            "type": "string",
            "description": "'charge_automatically' | 'send_invoice'.",
            "example": "",
        },
        "created_gte": {
            "type": "integer",
            "description": "Created >= UNIX timestamp.",
            "example": 0,
        },
        "created_lte": {
            "type": "integer",
            "description": "Created <= UNIX timestamp.",
            "example": 0,
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "data.customer,data.subscription",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_invoices(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_invoices",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        customer=input_data.get("customer") or None,
        subscription=input_data.get("subscription") or None,
        status=input_data.get("status") or None,
        collection_method=input_data.get("collection_method") or None,
        created_gte=input_data.get("created_gte") or None,
        created_lte=input_data.get("created_lte") or None,
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="get_stripe_invoice",
    description="Retrieve an Invoice by ID.",
    action_sets=["stripe_invoices"],
    input_schema={
        "invoice_id": {
            "type": "string",
            "description": "Invoice ID.",
            "example": "in_1MtwBwLkdIwHu7ix28a3tqPa",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "customer,subscription,charge",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_invoice(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "get_invoice",
        invoice_id=input_data["invoice_id"],
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="create_stripe_invoice",
    description="Create a draft Invoice for a customer. Add line items first via create_stripe_invoice_item, then finalize via finalize_stripe_invoice.",
    action_sets=["stripe_invoices", "stripe"],
    input_schema={
        "customer": {
            "type": "string",
            "description": "Customer ID.",
            "example": "cus_NffrFeUfNV2Hib",
        },
        "auto_advance": {
            "type": "boolean",
            "description": "Stripe finalizes + collects automatically.",
            "example": False,
        },
        "collection_method": {
            "type": "string",
            "description": "'charge_automatically' | 'send_invoice'.",
            "example": "send_invoice",
        },
        "days_until_due": {
            "type": "integer",
            "description": "Required if collection_method='send_invoice'.",
            "example": 30,
        },
        "due_date": {
            "type": "integer",
            "description": "Explicit due date (UNIX timestamp). Alternative to days_until_due.",
            "example": 0,
        },
        "description": {
            "type": "string",
            "description": "Invoice description.",
            "example": "June consulting",
        },
        "footer": {
            "type": "string",
            "description": "Footer on the rendered invoice.",
            "example": "",
        },
        "default_payment_method": {
            "type": "string",
            "description": "PaymentMethod to use for charge_automatically.",
            "example": "",
        },
        "statement_descriptor": {
            "type": "string",
            "description": "Appears on bank statement.",
            "example": "",
        },
        "metadata": {
            "type": "object",
            "description": "Arbitrary labels.",
            "example": {"project_id": "P-42"},
        },
        "pending_invoice_items_behavior": {
            "type": "string",
            "description": "'include' | 'exclude' pending invoice items.",
            "example": "include",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_stripe_invoice(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "create_invoice",
        customer=input_data["customer"],
        auto_advance=input_data.get("auto_advance"),
        collection_method=input_data.get("collection_method") or None,
        days_until_due=input_data.get("days_until_due") or None,
        due_date=input_data.get("due_date") or None,
        description=input_data.get("description") or None,
        footer=input_data.get("footer") or None,
        default_payment_method=input_data.get("default_payment_method") or None,
        statement_descriptor=input_data.get("statement_descriptor") or None,
        metadata=input_data.get("metadata") or None,
        pending_invoice_items_behavior=input_data.get("pending_invoice_items_behavior")
        or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="update_stripe_invoice",
    description="Update an Invoice. Most fields are only mutable while the invoice is in 'draft' status.",
    action_sets=["stripe_invoices"],
    input_schema={
        "invoice_id": {
            "type": "string",
            "description": "Invoice ID.",
            "example": "in_…",
        },
        "properties": {
            "type": "object",
            "description": "Properties to update.",
            "example": {"description": "Updated", "metadata": {"updated_by": "agent"}},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_stripe_invoice(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "update_invoice",
        invoice_id=input_data["invoice_id"],
        properties=input_data.get("properties") or {},
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="delete_stripe_invoice",
    description="Permanently delete a DRAFT Invoice. Once finalized use void_stripe_invoice instead.",
    action_sets=["stripe_invoices"],
    input_schema={
        "invoice_id": {
            "type": "string",
            "description": "Invoice ID.",
            "example": "in_…",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_stripe_invoice(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "delete_invoice",
        invoice_id=input_data["invoice_id"],
    )


@action(
    name="finalize_stripe_invoice",
    description="Finalize a draft Invoice — locks line items and computes totals. Once finalized the invoice is open and can be sent or paid.",
    action_sets=["stripe_invoices", "stripe"],
    input_schema={
        "invoice_id": {
            "type": "string",
            "description": "Invoice ID (must be draft).",
            "example": "in_…",
        },
        "auto_advance": {
            "type": "boolean",
            "description": "After finalize, let Stripe handle collection automatically.",
            "example": True,
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def finalize_stripe_invoice(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "finalize_invoice",
        invoice_id=input_data["invoice_id"],
        auto_advance=input_data.get("auto_advance"),
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="send_stripe_invoice",
    description="Email a finalized Invoice to the customer. Only valid for invoices with collection_method='send_invoice'.",
    action_sets=["stripe_invoices", "stripe"],
    input_schema={
        "invoice_id": {
            "type": "string",
            "description": "Invoice ID (must be open / finalized).",
            "example": "in_…",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def send_stripe_invoice(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "send_invoice",
        invoice_id=input_data["invoice_id"],
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="pay_stripe_invoice",
    description="Attempt payment on an open Invoice. Optionally specify a payment method or mark paid_out_of_band for offline payments.",
    action_sets=["stripe_invoices"],
    input_schema={
        "invoice_id": {
            "type": "string",
            "description": "Invoice ID (must be open).",
            "example": "in_…",
        },
        "payment_method": {
            "type": "string",
            "description": "Override default payment method.",
            "example": "",
        },
        "off_session": {
            "type": "boolean",
            "description": "True for charging a saved method without customer present.",
            "example": True,
        },
        "paid_out_of_band": {
            "type": "boolean",
            "description": "Mark as paid without actually charging (offline payment).",
            "example": False,
        },
        "forgive": {
            "type": "boolean",
            "description": "Forgive any remaining balance after partial payment.",
            "example": False,
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def pay_stripe_invoice(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "pay_invoice",
        invoice_id=input_data["invoice_id"],
        payment_method=input_data.get("payment_method") or None,
        off_session=input_data.get("off_session"),
        paid_out_of_band=input_data.get("paid_out_of_band"),
        forgive=input_data.get("forgive"),
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="void_stripe_invoice",
    description="Void a finalized open Invoice. Irreversible. Use this to cancel a finalized invoice that should never be paid.",
    action_sets=["stripe_invoices"],
    input_schema={
        "invoice_id": {
            "type": "string",
            "description": "Invoice ID (must be open).",
            "example": "in_…",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def void_stripe_invoice(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "void_invoice",
        invoice_id=input_data["invoice_id"],
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="mark_stripe_invoice_uncollectible",
    description="Mark an open Invoice as uncollectible (write-off). The modern alternative to void for invoices you've decided not to collect.",
    action_sets=["stripe_invoices"],
    input_schema={
        "invoice_id": {
            "type": "string",
            "description": "Invoice ID (must be open).",
            "example": "in_…",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def mark_stripe_invoice_uncollectible(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "mark_invoice_uncollectible",
        invoice_id=input_data["invoice_id"],
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="get_stripe_upcoming_invoice",
    description="Preview the next invoice for a customer or subscription. Does NOT create anything in Stripe. Useful for showing 'what's next' or simulating subscription changes.",
    action_sets=["stripe_invoices"],
    input_schema={
        "customer": {
            "type": "string",
            "description": "Customer ID.",
            "example": "cus_…",
        },
        "subscription": {
            "type": "string",
            "description": "Subscription ID (alternative to customer).",
            "example": "",
        },
        "subscription_items": {
            "type": "array",
            "description": "Hypothetical items to simulate a change.",
            "example": [],
        },
        "coupon": {
            "type": "string",
            "description": "Coupon to apply to the simulated invoice.",
            "example": "",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_upcoming_invoice(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "get_upcoming_invoice",
        customer=input_data.get("customer") or None,
        subscription=input_data.get("subscription") or None,
        subscription_items=input_data.get("subscription_items") or None,
        coupon=input_data.get("coupon") or None,
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="list_stripe_invoice_items",
    description="List Invoice Items. Filter to a customer, an invoice, or pending (not yet attached to an invoice).",
    action_sets=["stripe_invoices"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "customer": {
            "type": "string",
            "description": "Filter to a specific customer.",
            "example": "",
        },
        "invoice": {
            "type": "string",
            "description": "Filter to a specific invoice.",
            "example": "",
        },
        "pending": {
            "type": "boolean",
            "description": "Only items not yet on an invoice.",
            "example": True,
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_invoice_items(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_invoice_items",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        customer=input_data.get("customer") or None,
        invoice=input_data.get("invoice") or None,
        pending=input_data.get("pending"),
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="create_stripe_invoice_item",
    description="Create an Invoice Item for a customer. If 'invoice' is set, attaches to that draft invoice; otherwise it's pending for the next invoice.",
    action_sets=["stripe_invoices", "stripe"],
    input_schema={
        "customer": {
            "type": "string",
            "description": "Customer ID.",
            "example": "cus_…",
        },
        "invoice": {
            "type": "string",
            "description": "Draft invoice to attach to. Omit for pending.",
            "example": "",
        },
        "amount": {
            "type": "integer",
            "description": "Amount in smallest currency unit. Mutually exclusive with price.",
            "example": 2500,
        },
        "currency": {
            "type": "string",
            "description": "ISO 4217 lowercase. Required when 'amount' is set.",
            "example": "usd",
        },
        "price": {
            "type": "string",
            "description": "Price ID. Mutually exclusive with amount.",
            "example": "",
        },
        "quantity": {
            "type": "integer",
            "description": "Quantity (default 1).",
            "example": 1,
        },
        "description": {
            "type": "string",
            "description": "Line item description.",
            "example": "Consulting hour",
        },
        "discountable": {
            "type": "boolean",
            "description": "Whether discounts apply.",
            "example": True,
        },
        "metadata": {
            "type": "object",
            "description": "Arbitrary labels.",
            "example": {},
        },
        "tax_rates": {
            "type": "array",
            "description": "Stripe tax rate IDs to apply.",
            "example": [],
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_stripe_invoice_item(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "create_invoice_item",
        customer=input_data["customer"],
        invoice=input_data.get("invoice") or None,
        amount=input_data.get("amount") or None,
        currency=input_data.get("currency") or None,
        price=input_data.get("price") or None,
        quantity=input_data.get("quantity") or None,
        description=input_data.get("description") or None,
        discountable=input_data.get("discountable"),
        metadata=input_data.get("metadata") or None,
        tax_rates=input_data.get("tax_rates") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="delete_stripe_invoice_item",
    description="Delete a pending Invoice Item (not yet finalized into an invoice).",
    action_sets=["stripe_invoices"],
    input_schema={
        "invoice_item_id": {
            "type": "string",
            "description": "Invoice Item ID.",
            "example": "ii_…",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_stripe_invoice_item(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "delete_invoice_item",
        invoice_item_id=input_data["invoice_item_id"],
    )


# ==================================================================
# Subscriptions (stripe_subscriptions)
# ==================================================================


@action(
    name="list_stripe_subscriptions",
    description="List Subscriptions. Filter by customer, price, status (active/past_due/canceled/etc.).",
    action_sets=["stripe_subscriptions", "stripe"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "customer": {
            "type": "string",
            "description": "Filter to a customer.",
            "example": "",
        },
        "price": {
            "type": "string",
            "description": "Filter to subscriptions containing a price.",
            "example": "",
        },
        "status": {
            "type": "string",
            "description": "'active' | 'past_due' | 'unpaid' | 'canceled' | 'incomplete' | 'incomplete_expired' | 'trialing' | 'paused' | 'all'.",
            "example": "active",
        },
        "collection_method": {
            "type": "string",
            "description": "'charge_automatically' | 'send_invoice'.",
            "example": "",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "data.customer,data.default_payment_method",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_subscriptions(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_subscriptions",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        customer=input_data.get("customer") or None,
        price=input_data.get("price") or None,
        status=input_data.get("status") or None,
        collection_method=input_data.get("collection_method") or None,
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="get_stripe_subscription",
    description="Retrieve a Subscription by ID.",
    action_sets=["stripe_subscriptions"],
    input_schema={
        "subscription_id": {
            "type": "string",
            "description": "Subscription ID.",
            "example": "sub_1MowQVLkdIwHu7ixeRlqHVzs",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "customer,latest_invoice,default_payment_method",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_subscription(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "get_subscription",
        subscription_id=input_data["subscription_id"],
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="create_stripe_subscription",
    description="Create a Subscription for a customer. 'items' is a list like [{price: 'price_xxx', quantity: 1}]. Requires the customer to have a default payment method or one provided.",
    action_sets=["stripe_subscriptions", "stripe"],
    input_schema={
        "customer": {
            "type": "string",
            "description": "Customer ID.",
            "example": "cus_NffrFeUfNV2Hib",
        },
        "items": {
            "type": "array",
            "description": "Line items: [{price, quantity}].",
            "example": [{"price": "price_xxx", "quantity": 1}],
        },
        "cancel_at_period_end": {
            "type": "boolean",
            "description": "Schedule cancellation at end of current period.",
            "example": False,
        },
        "collection_method": {
            "type": "string",
            "description": "'charge_automatically' | 'send_invoice'.",
            "example": "charge_automatically",
        },
        "days_until_due": {
            "type": "integer",
            "description": "Required if collection_method='send_invoice'.",
            "example": 0,
        },
        "default_payment_method": {
            "type": "string",
            "description": "PaymentMethod ID.",
            "example": "",
        },
        "default_tax_rates": {
            "type": "array",
            "description": "Tax rate IDs applied to all items.",
            "example": [],
        },
        "coupon": {
            "type": "string",
            "description": "Coupon code to apply.",
            "example": "",
        },
        "promotion_code": {
            "type": "string",
            "description": "Promotion code ID.",
            "example": "",
        },
        "trial_period_days": {
            "type": "integer",
            "description": "Trial length in days.",
            "example": 0,
        },
        "trial_end": {
            "type": "integer",
            "description": "Explicit trial end (UNIX timestamp).",
            "example": 0,
        },
        "payment_behavior": {
            "type": "string",
            "description": "'default_incomplete' | 'allow_incomplete' | 'error_if_incomplete' | 'pending_if_incomplete'.",
            "example": "default_incomplete",
        },
        "proration_behavior": {
            "type": "string",
            "description": "'create_prorations' | 'none' | 'always_invoice'.",
            "example": "",
        },
        "metadata": {
            "type": "object",
            "description": "Arbitrary labels.",
            "example": {},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_stripe_subscription(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "create_subscription",
        customer=input_data["customer"],
        items=input_data["items"],
        cancel_at_period_end=input_data.get("cancel_at_period_end"),
        collection_method=input_data.get("collection_method") or None,
        days_until_due=input_data.get("days_until_due") or None,
        default_payment_method=input_data.get("default_payment_method") or None,
        default_tax_rates=input_data.get("default_tax_rates") or None,
        coupon=input_data.get("coupon") or None,
        promotion_code=input_data.get("promotion_code") or None,
        trial_period_days=input_data.get("trial_period_days") or None,
        trial_end=input_data.get("trial_end") or None,
        payment_behavior=input_data.get("payment_behavior") or None,
        proration_behavior=input_data.get("proration_behavior") or None,
        metadata=input_data.get("metadata") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="update_stripe_subscription",
    description="Update a Subscription. To change items: pass items=[{id: 'si_…', price: 'price_xxx', quantity: 1}]. To schedule cancel at period end: properties={'cancel_at_period_end': true}.",
    action_sets=["stripe_subscriptions"],
    input_schema={
        "subscription_id": {
            "type": "string",
            "description": "Subscription ID.",
            "example": "sub_…",
        },
        "properties": {
            "type": "object",
            "description": "Properties to update.",
            "example": {"cancel_at_period_end": True},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_stripe_subscription(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "update_subscription",
        subscription_id=input_data["subscription_id"],
        properties=input_data.get("properties") or {},
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="cancel_stripe_subscription",
    description="Cancel a Subscription IMMEDIATELY (DELETE). For end-of-period cancellation use update_stripe_subscription({cancel_at_period_end: true}) instead.",
    action_sets=["stripe_subscriptions", "stripe"],
    input_schema={
        "subscription_id": {
            "type": "string",
            "description": "Subscription ID.",
            "example": "sub_…",
        },
        "invoice_now": {
            "type": "boolean",
            "description": "Invoice unbilled metered usage immediately.",
            "example": False,
        },
        "prorate": {
            "type": "boolean",
            "description": "Generate proration credits.",
            "example": True,
        },
        "cancellation_details": {
            "type": "object",
            "description": "{comment, feedback}.",
            "example": {"feedback": "too_expensive"},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def cancel_stripe_subscription(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "cancel_subscription",
        subscription_id=input_data["subscription_id"],
        invoice_now=input_data.get("invoice_now"),
        prorate=input_data.get("prorate"),
        cancellation_details=input_data.get("cancellation_details") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="resume_stripe_subscription",
    description="Resume a paused Subscription.",
    action_sets=["stripe_subscriptions"],
    input_schema={
        "subscription_id": {
            "type": "string",
            "description": "Subscription ID.",
            "example": "sub_…",
        },
        "billing_cycle_anchor": {
            "type": "string",
            "description": "'now' | 'unchanged'.",
            "example": "now",
        },
        "proration_behavior": {
            "type": "string",
            "description": "'create_prorations' | 'none' | 'always_invoice'.",
            "example": "create_prorations",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def resume_stripe_subscription(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "resume_subscription",
        subscription_id=input_data["subscription_id"],
        billing_cycle_anchor=input_data.get("billing_cycle_anchor") or None,
        proration_behavior=input_data.get("proration_behavior") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


# ==================================================================
# Checkout sessions (stripe_checkout)
# ==================================================================


@action(
    name="list_stripe_checkout_sessions",
    description="List Checkout Sessions. Filter by customer, payment_intent, subscription, or status.",
    action_sets=["stripe_checkout"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "customer": {
            "type": "string",
            "description": "Filter to a customer.",
            "example": "",
        },
        "payment_intent": {
            "type": "string",
            "description": "Filter to a PaymentIntent.",
            "example": "",
        },
        "subscription": {
            "type": "string",
            "description": "Filter to a subscription.",
            "example": "",
        },
        "status": {
            "type": "string",
            "description": "'open' | 'complete' | 'expired'.",
            "example": "complete",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_checkout_sessions(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_checkout_sessions",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        customer=input_data.get("customer") or None,
        payment_intent=input_data.get("payment_intent") or None,
        subscription=input_data.get("subscription") or None,
        status=input_data.get("status") or None,
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="get_stripe_checkout_session",
    description="Retrieve a Checkout Session by ID.",
    action_sets=["stripe_checkout"],
    input_schema={
        "session_id": {
            "type": "string",
            "description": "Checkout Session ID.",
            "example": "cs_test_…",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "line_items,customer",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_checkout_session(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "get_checkout_session",
        session_id=input_data["session_id"],
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="create_stripe_checkout_session",
    description="Create a hosted Checkout Session. 'mode' is 'payment' (one-time), 'subscription', or 'setup'. Returns the hosted page URL in 'url'.",
    action_sets=["stripe_checkout", "stripe"],
    input_schema={
        "mode": {
            "type": "string",
            "description": "'payment' | 'subscription' | 'setup'.",
            "example": "payment",
        },
        "line_items": {
            "type": "array",
            "description": "Line items: [{price: 'price_xxx', quantity: 1}] or [{price_data: {…}, quantity: 1}].",
            "example": [{"price": "price_xxx", "quantity": 1}],
        },
        "success_url": {
            "type": "string",
            "description": "Redirect on success. Use {CHECKOUT_SESSION_ID} placeholder for the session ID.",
            "example": "https://example.com/success?session_id={CHECKOUT_SESSION_ID}",
        },
        "cancel_url": {
            "type": "string",
            "description": "Redirect on cancel.",
            "example": "https://example.com/cancel",
        },
        "ui_mode": {
            "type": "string",
            "description": "'hosted' (default) | 'embedded'.",
            "example": "hosted",
        },
        "customer": {
            "type": "string",
            "description": "Existing customer to attach the session to.",
            "example": "",
        },
        "customer_email": {
            "type": "string",
            "description": "Pre-fill the customer's email.",
            "example": "",
        },
        "client_reference_id": {
            "type": "string",
            "description": "Your internal ID for reconciliation via webhook.",
            "example": "order_42",
        },
        "allow_promotion_codes": {
            "type": "boolean",
            "description": "Show a 'have a promo code' field.",
            "example": True,
        },
        "automatic_tax": {
            "type": "object",
            "description": "{enabled: true} to compute Stripe Tax.",
            "example": {"enabled": True},
        },
        "billing_address_collection": {
            "type": "string",
            "description": "'auto' | 'required'.",
            "example": "auto",
        },
        "payment_method_types": {
            "type": "array",
            "description": "Allowed payment method types.",
            "example": ["card"],
        },
        "metadata": {
            "type": "object",
            "description": "Arbitrary labels.",
            "example": {},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_stripe_checkout_session(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "create_checkout_session",
        mode=input_data["mode"],
        line_items=input_data.get("line_items") or None,
        success_url=input_data.get("success_url") or None,
        cancel_url=input_data.get("cancel_url") or None,
        ui_mode=input_data.get("ui_mode") or None,
        customer=input_data.get("customer") or None,
        customer_email=input_data.get("customer_email") or None,
        client_reference_id=input_data.get("client_reference_id") or None,
        allow_promotion_codes=input_data.get("allow_promotion_codes"),
        automatic_tax=input_data.get("automatic_tax") or None,
        billing_address_collection=input_data.get("billing_address_collection") or None,
        payment_method_types=input_data.get("payment_method_types") or None,
        metadata=input_data.get("metadata") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="expire_stripe_checkout_session",
    description="Expire an open Checkout Session — the URL becomes invalid for the customer.",
    action_sets=["stripe_checkout"],
    input_schema={
        "session_id": {
            "type": "string",
            "description": "Checkout Session ID.",
            "example": "cs_test_…",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def expire_stripe_checkout_session(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "expire_checkout_session",
        session_id=input_data["session_id"],
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="list_stripe_checkout_line_items",
    description="List line items on a Checkout Session.",
    action_sets=["stripe_checkout"],
    input_schema={
        "session_id": {
            "type": "string",
            "description": "Checkout Session ID.",
            "example": "cs_test_…",
        },
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_checkout_line_items(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_checkout_line_items",
        session_id=input_data["session_id"],
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        expand=_csv(input_data.get("expand")),
    )


# ==================================================================
# Payment links + billing portal (stripe_payment_links)
# ==================================================================


@action(
    name="list_stripe_payment_links",
    description="List Payment Links.",
    action_sets=["stripe_payment_links"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "active": {
            "type": "boolean",
            "description": "Only active or only inactive.",
            "example": True,
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_payment_links(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_payment_links",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        active=input_data.get("active"),
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="get_stripe_payment_link",
    description="Retrieve a Payment Link by ID.",
    action_sets=["stripe_payment_links"],
    input_schema={
        "payment_link_id": {
            "type": "string",
            "description": "Payment Link ID.",
            "example": "pl_1MoBy5LkdIwHu7ixZhnattbh",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "line_items",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_payment_link(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "get_payment_link",
        payment_link_id=input_data["payment_link_id"],
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="create_stripe_payment_link",
    description="Create a Payment Link — a shareable URL that opens Stripe's hosted checkout. Persists across sessions; useful for invoices, donations, embedded buttons.",
    action_sets=["stripe_payment_links", "stripe"],
    input_schema={
        "line_items": {
            "type": "array",
            "description": "Line items: [{price: 'price_xxx', quantity: 1}].",
            "example": [{"price": "price_xxx", "quantity": 1}],
        },
        "after_completion": {
            "type": "object",
            "description": "What happens after success: {type: 'redirect', redirect: {url: '…'}} or {type: 'hosted_confirmation', hosted_confirmation: {custom_message: '…'}}.",
            "example": {"type": "hosted_confirmation"},
        },
        "allow_promotion_codes": {
            "type": "boolean",
            "description": "Show a 'have a promo code' field.",
            "example": True,
        },
        "automatic_tax": {
            "type": "object",
            "description": "{enabled: true}.",
            "example": {"enabled": True},
        },
        "billing_address_collection": {
            "type": "string",
            "description": "'auto' | 'required'.",
            "example": "auto",
        },
        "customer_creation": {
            "type": "string",
            "description": "'always' | 'if_required'.",
            "example": "always",
        },
        "metadata": {
            "type": "object",
            "description": "Arbitrary labels.",
            "example": {},
        },
        "payment_method_types": {
            "type": "array",
            "description": "Allowed payment method types.",
            "example": [],
        },
        "shipping_address_collection": {
            "type": "object",
            "description": "{allowed_countries: [...]}.",
            "example": {},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_stripe_payment_link(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "create_payment_link",
        line_items=input_data["line_items"],
        after_completion=input_data.get("after_completion") or None,
        allow_promotion_codes=input_data.get("allow_promotion_codes"),
        automatic_tax=input_data.get("automatic_tax") or None,
        billing_address_collection=input_data.get("billing_address_collection") or None,
        customer_creation=input_data.get("customer_creation") or None,
        metadata=input_data.get("metadata") or None,
        payment_method_types=input_data.get("payment_method_types") or None,
        shipping_address_collection=input_data.get("shipping_address_collection")
        or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="update_stripe_payment_link",
    description="Update a Payment Link. Limited to active flag, line item quantities, after_completion, metadata, etc.",
    action_sets=["stripe_payment_links"],
    input_schema={
        "payment_link_id": {
            "type": "string",
            "description": "Payment Link ID.",
            "example": "pl_…",
        },
        "properties": {
            "type": "object",
            "description": "Properties to update.",
            "example": {"active": False},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_stripe_payment_link(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "update_payment_link",
        payment_link_id=input_data["payment_link_id"],
        properties=input_data.get("properties") or {},
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="create_stripe_billing_portal_session",
    description="Create a Stripe Customer Portal session — short-lived URL where the customer manages their own subscriptions, payment methods, and invoices.",
    action_sets=["stripe_payment_links"],
    input_schema={
        "customer": {
            "type": "string",
            "description": "Customer ID.",
            "example": "cus_…",
        },
        "return_url": {
            "type": "string",
            "description": "Where the customer returns when they're done.",
            "example": "https://example.com/account",
        },
        "configuration": {
            "type": "string",
            "description": "Specific portal configuration ID.",
            "example": "",
        },
        "locale": {
            "type": "string",
            "description": "BCP-47 locale (e.g. 'en', 'de-DE').",
            "example": "",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_stripe_billing_portal_session(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "create_billing_portal_session",
        customer=input_data["customer"],
        return_url=input_data.get("return_url") or None,
        configuration=input_data.get("configuration") or None,
        locale=input_data.get("locale") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


# ==================================================================
# Coupons + promotion codes (stripe_promotions)
# ==================================================================


@action(
    name="list_stripe_coupons",
    description="List Coupons.",
    action_sets=["stripe_promotions"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_coupons(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_coupons",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="get_stripe_coupon",
    description="Retrieve a Coupon by ID.",
    action_sets=["stripe_promotions"],
    input_schema={
        "coupon_id": {
            "type": "string",
            "description": "Coupon ID (user-chosen, e.g. 'SUMMER25').",
            "example": "SUMMER25",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_coupon(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "get_coupon",
        coupon_id=input_data["coupon_id"],
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="create_stripe_coupon",
    description="Create a Coupon. Pass exactly ONE of amount_off (with currency) or percent_off. duration='once' charges discount one period; 'repeating' requires duration_in_months; 'forever' lasts the subscription's lifetime.",
    action_sets=["stripe_promotions"],
    input_schema={
        "id": {
            "type": "string",
            "description": "Optional user-chosen ID (e.g. 'SUMMER25'). Auto-generated if omitted.",
            "example": "SUMMER25",
        },
        "name": {
            "type": "string",
            "description": "Customer-facing label.",
            "example": "Summer 25%",
        },
        "duration": {
            "type": "string",
            "description": "'once' | 'repeating' | 'forever'.",
            "example": "once",
        },
        "amount_off": {
            "type": "integer",
            "description": "Amount off in smallest currency unit. Mutually exclusive with percent_off.",
            "example": 0,
        },
        "percent_off": {
            "type": "number",
            "description": "Percentage off (e.g. 25 = 25%). Mutually exclusive with amount_off.",
            "example": 25,
        },
        "currency": {
            "type": "string",
            "description": "ISO 4217 lowercase. Required if amount_off is set.",
            "example": "usd",
        },
        "duration_in_months": {
            "type": "integer",
            "description": "Required if duration='repeating'.",
            "example": 3,
        },
        "max_redemptions": {
            "type": "integer",
            "description": "Cap on total redemptions across all customers.",
            "example": 0,
        },
        "redeem_by": {
            "type": "integer",
            "description": "UNIX timestamp after which the coupon can no longer be redeemed.",
            "example": 0,
        },
        "metadata": {
            "type": "object",
            "description": "Arbitrary labels.",
            "example": {},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_stripe_coupon(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "create_coupon",
        id=input_data.get("id") or None,
        name=input_data.get("name") or None,
        duration=input_data.get("duration") or "once",
        amount_off=input_data.get("amount_off") or None,
        percent_off=input_data.get("percent_off") or None,
        currency=input_data.get("currency") or None,
        duration_in_months=input_data.get("duration_in_months") or None,
        max_redemptions=input_data.get("max_redemptions") or None,
        redeem_by=input_data.get("redeem_by") or None,
        metadata=input_data.get("metadata") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="update_stripe_coupon",
    description="Update a Coupon. Only 'name' and 'metadata' are mutable — duration/amount/percent/currency are write-once.",
    action_sets=["stripe_promotions"],
    input_schema={
        "coupon_id": {
            "type": "string",
            "description": "Coupon ID.",
            "example": "SUMMER25",
        },
        "properties": {
            "type": "object",
            "description": "Mutable properties (name, metadata).",
            "example": {"name": "Summer (extended)"},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_stripe_coupon(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "update_coupon",
        coupon_id=input_data["coupon_id"],
        properties=input_data.get("properties") or {},
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="delete_stripe_coupon",
    description="Delete a Coupon. Existing subscriptions and invoices that already used it are unaffected.",
    action_sets=["stripe_promotions"],
    input_schema={
        "coupon_id": {
            "type": "string",
            "description": "Coupon ID.",
            "example": "SUMMER25",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_stripe_coupon(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "delete_coupon",
        coupon_id=input_data["coupon_id"],
    )


@action(
    name="list_stripe_promotion_codes",
    description="List Promotion Codes. Filter by active, exact code string, parent coupon, or customer allowlist.",
    action_sets=["stripe_promotions"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "active": {
            "type": "boolean",
            "description": "Only active or only inactive.",
            "example": True,
        },
        "code": {
            "type": "string",
            "description": "Exact code filter.",
            "example": "FRIENDS50",
        },
        "coupon": {"type": "string", "description": "Parent coupon ID.", "example": ""},
        "customer": {
            "type": "string",
            "description": "Promotion codes allowlisted to this customer.",
            "example": "",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_promotion_codes(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_promotion_codes",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        active=input_data.get("active"),
        code=input_data.get("code") or None,
        coupon=input_data.get("coupon") or None,
        customer=input_data.get("customer") or None,
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="create_stripe_promotion_code",
    description="Create a Promotion Code (customer-facing string) for an existing Coupon. Optionally restrict to a customer, first-time-only, expiry, max redemptions.",
    action_sets=["stripe_promotions"],
    input_schema={
        "coupon": {
            "type": "string",
            "description": "Parent Coupon ID.",
            "example": "SUMMER25",
        },
        "code": {
            "type": "string",
            "description": "Code string. Auto-generated if omitted.",
            "example": "FRIENDS50",
        },
        "customer": {
            "type": "string",
            "description": "Restrict to a specific customer.",
            "example": "",
        },
        "active": {
            "type": "boolean",
            "description": "Whether the code is redeemable.",
            "example": True,
        },
        "expires_at": {
            "type": "integer",
            "description": "UNIX timestamp expiry.",
            "example": 0,
        },
        "max_redemptions": {
            "type": "integer",
            "description": "Total redemption cap.",
            "example": 0,
        },
        "restrictions": {
            "type": "object",
            "description": "{first_time_transaction: bool, minimum_amount: int, minimum_amount_currency: str}.",
            "example": {"first_time_transaction": True},
        },
        "metadata": {
            "type": "object",
            "description": "Arbitrary labels.",
            "example": {},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_stripe_promotion_code(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "create_promotion_code",
        coupon=input_data["coupon"],
        code=input_data.get("code") or None,
        customer=input_data.get("customer") or None,
        active=input_data.get("active"),
        expires_at=input_data.get("expires_at") or None,
        max_redemptions=input_data.get("max_redemptions") or None,
        restrictions=input_data.get("restrictions") or None,
        metadata=input_data.get("metadata") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="update_stripe_promotion_code",
    description="Update a Promotion Code. Only active and metadata are mutable.",
    action_sets=["stripe_promotions"],
    input_schema={
        "promotion_code_id": {
            "type": "string",
            "description": "Promotion Code ID.",
            "example": "promo_…",
        },
        "properties": {
            "type": "object",
            "description": "Properties to update.",
            "example": {"active": False},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_stripe_promotion_code(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "update_promotion_code",
        promotion_code_id=input_data["promotion_code_id"],
        properties=input_data.get("properties") or {},
        idempotency_key=input_data.get("idempotency_key") or None,
    )


# ==================================================================
# Disputes (stripe_disputes)
# ==================================================================


@action(
    name="list_stripe_disputes",
    description="List Disputes (chargebacks + inquiries). Filter by charge or payment_intent.",
    action_sets=["stripe_disputes"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "charge": {
            "type": "string",
            "description": "Filter to a specific charge.",
            "example": "",
        },
        "payment_intent": {
            "type": "string",
            "description": "Filter to a specific PaymentIntent.",
            "example": "",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_disputes(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_disputes",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        charge=input_data.get("charge") or None,
        payment_intent=input_data.get("payment_intent") or None,
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="get_stripe_dispute",
    description="Retrieve a Dispute by ID.",
    action_sets=["stripe_disputes"],
    input_schema={
        "dispute_id": {
            "type": "string",
            "description": "Dispute ID.",
            "example": "di_…",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "charge,payment_intent",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_dispute(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "get_dispute",
        dispute_id=input_data["dispute_id"],
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="update_stripe_dispute",
    description="Save (or submit) dispute evidence. Pass submit=True to finalize and submit to the card network — IRREVERSIBLE. Without submit, saves as draft for further edits.",
    action_sets=["stripe_disputes"],
    input_schema={
        "dispute_id": {
            "type": "string",
            "description": "Dispute ID.",
            "example": "di_…",
        },
        "evidence": {
            "type": "object",
            "description": "Evidence fields (see Stripe docs for the full schema — receipt, shipping_documentation, customer_email_address, etc.).",
            "example": {
                "customer_email_address": "jane@example.com",
                "uncategorized_text": "Customer was refunded immediately.",
            },
        },
        "submit": {
            "type": "boolean",
            "description": "True submits to card network. Omit/False saves as draft.",
            "example": False,
        },
        "metadata": {
            "type": "object",
            "description": "Arbitrary labels.",
            "example": {},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_stripe_dispute(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "update_dispute",
        dispute_id=input_data["dispute_id"],
        evidence=input_data.get("evidence") or None,
        submit=input_data.get("submit"),
        metadata=input_data.get("metadata") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="close_stripe_dispute",
    description="Forfeit a dispute — accept the chargeback as final. Once closed, cannot be reopened.",
    action_sets=["stripe_disputes"],
    input_schema={
        "dispute_id": {
            "type": "string",
            "description": "Dispute ID.",
            "example": "di_…",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def close_stripe_dispute(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "close_dispute",
        dispute_id=input_data["dispute_id"],
        idempotency_key=input_data.get("idempotency_key") or None,
    )


# ==================================================================
# Payouts + balance (stripe_payouts)
# ==================================================================


@action(
    name="list_stripe_payouts",
    description="List Payouts to the merchant's bank account.",
    action_sets=["stripe_payouts", "stripe"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "status": {
            "type": "string",
            "description": "'pending' | 'in_transit' | 'paid' | 'failed' | 'canceled'.",
            "example": "paid",
        },
        "destination": {
            "type": "string",
            "description": "Bank account or card ID.",
            "example": "",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_payouts(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_payouts",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        status=input_data.get("status") or None,
        destination=input_data.get("destination") or None,
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="get_stripe_payout",
    description="Retrieve a Payout by ID.",
    action_sets=["stripe_payouts"],
    input_schema={
        "payout_id": {"type": "string", "description": "Payout ID.", "example": "po_…"},
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "destination,failure_balance_transaction",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_payout(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "get_payout",
        payout_id=input_data["payout_id"],
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="create_stripe_payout",
    description="Trigger a payout from your Stripe balance to your bank. method='standard' (1-2 day) or 'instant' (fee, requires eligibility).",
    action_sets=["stripe_payouts"],
    input_schema={
        "amount": {
            "type": "integer",
            "description": "Amount in smallest currency unit.",
            "example": 10000,
        },
        "currency": {
            "type": "string",
            "description": "ISO 4217 lowercase. Defaults to integration default_currency.",
            "example": "usd",
        },
        "description": {
            "type": "string",
            "description": "Internal description.",
            "example": "Weekly payout",
        },
        "statement_descriptor": {
            "type": "string",
            "description": "Appears on bank statement.",
            "example": "",
        },
        "method": {
            "type": "string",
            "description": "'standard' | 'instant'.",
            "example": "standard",
        },
        "source_type": {
            "type": "string",
            "description": "'bank_account' | 'card'.",
            "example": "bank_account",
        },
        "destination": {
            "type": "string",
            "description": "Specific bank account or card ID. Omit to use the default.",
            "example": "",
        },
        "metadata": {
            "type": "object",
            "description": "Arbitrary labels.",
            "example": {},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_stripe_payout(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "create_payout",
        amount=input_data["amount"],
        currency=input_data.get("currency") or None,
        description=input_data.get("description") or None,
        statement_descriptor=input_data.get("statement_descriptor") or None,
        method=input_data.get("method") or None,
        source_type=input_data.get("source_type") or None,
        destination=input_data.get("destination") or None,
        metadata=input_data.get("metadata") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="cancel_stripe_payout",
    description="Cancel a Payout. Only valid if status is 'pending'.",
    action_sets=["stripe_payouts"],
    input_schema={
        "payout_id": {"type": "string", "description": "Payout ID.", "example": "po_…"},
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def cancel_stripe_payout(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "cancel_payout",
        payout_id=input_data["payout_id"],
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="get_stripe_balance",
    description="Get the current Stripe balance — available (settled) and pending funds per currency.",
    action_sets=["stripe_payouts", "stripe"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_balance(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("stripe", "get_balance")


@action(
    name="list_stripe_balance_transactions",
    description="List Balance Transactions — every money movement (charges, refunds, payouts, fees, etc.). Filter by type, currency, source, or payout.",
    action_sets=["stripe_payouts"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "type": {
            "type": "string",
            "description": "'charge' | 'refund' | 'adjustment' | 'application_fee' | 'payout' | 'transfer' | 'stripe_fee' | etc.",
            "example": "charge",
        },
        "currency": {
            "type": "string",
            "description": "ISO 4217 lowercase filter.",
            "example": "",
        },
        "source": {
            "type": "string",
            "description": "Filter to a specific source ID (charge, refund, etc.).",
            "example": "",
        },
        "payout": {
            "type": "string",
            "description": "Filter to transactions in a specific payout.",
            "example": "",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_balance_transactions(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_balance_transactions",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        type=input_data.get("type") or None,
        currency=input_data.get("currency") or None,
        source=input_data.get("source") or None,
        payout=input_data.get("payout") or None,
        expand=_csv(input_data.get("expand")),
    )


# ==================================================================
# Quotes (stripe_quotes)
# ==================================================================


@action(
    name="list_stripe_quotes",
    description="List Quotes. Filter by customer or status.",
    action_sets=["stripe_quotes"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "customer": {
            "type": "string",
            "description": "Filter to a customer.",
            "example": "",
        },
        "status": {
            "type": "string",
            "description": "'draft' | 'open' | 'accepted' | 'canceled'.",
            "example": "open",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_quotes(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_quotes",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        customer=input_data.get("customer") or None,
        status=input_data.get("status") or None,
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="get_stripe_quote",
    description="Retrieve a Quote by ID.",
    action_sets=["stripe_quotes"],
    input_schema={
        "quote_id": {"type": "string", "description": "Quote ID.", "example": "qt_…"},
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "line_items,customer,invoice",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_quote(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "get_quote",
        quote_id=input_data["quote_id"],
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="create_stripe_quote",
    description="Create a draft Quote for a customer. After creation, call finalize_stripe_quote to lock it, then send the URL or wait for accept_stripe_quote.",
    action_sets=["stripe_quotes"],
    input_schema={
        "customer": {
            "type": "string",
            "description": "Customer ID.",
            "example": "cus_…",
        },
        "line_items": {
            "type": "array",
            "description": "Line items: [{price: 'price_xxx', quantity: 1}].",
            "example": [{"price": "price_xxx", "quantity": 1}],
        },
        "description": {
            "type": "string",
            "description": "Internal description.",
            "example": "",
        },
        "footer": {
            "type": "string",
            "description": "Footer on the rendered quote.",
            "example": "",
        },
        "header": {
            "type": "string",
            "description": "Header on the rendered quote.",
            "example": "",
        },
        "expires_at": {
            "type": "integer",
            "description": "UNIX timestamp expiry.",
            "example": 0,
        },
        "collection_method": {
            "type": "string",
            "description": "'charge_automatically' | 'send_invoice'.",
            "example": "",
        },
        "default_tax_rates": {
            "type": "array",
            "description": "Tax rate IDs applied to all items.",
            "example": [],
        },
        "subscription_data": {
            "type": "object",
            "description": "Defaults applied to the subscription created on accept.",
            "example": {},
        },
        "metadata": {
            "type": "object",
            "description": "Arbitrary labels.",
            "example": {},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_stripe_quote(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "create_quote",
        customer=input_data["customer"],
        line_items=input_data["line_items"],
        description=input_data.get("description") or None,
        footer=input_data.get("footer") or None,
        header=input_data.get("header") or None,
        expires_at=input_data.get("expires_at") or None,
        collection_method=input_data.get("collection_method") or None,
        default_tax_rates=input_data.get("default_tax_rates") or None,
        subscription_data=input_data.get("subscription_data") or None,
        metadata=input_data.get("metadata") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="update_stripe_quote",
    description="Update a draft Quote. Once finalized most fields are locked.",
    action_sets=["stripe_quotes"],
    input_schema={
        "quote_id": {"type": "string", "description": "Quote ID.", "example": "qt_…"},
        "properties": {
            "type": "object",
            "description": "Properties to update.",
            "example": {"description": "Updated"},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_stripe_quote(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "update_quote",
        quote_id=input_data["quote_id"],
        properties=input_data.get("properties") or {},
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="finalize_stripe_quote",
    description="Finalize a draft Quote — it becomes 'open' and is ready for the customer to accept.",
    action_sets=["stripe_quotes"],
    input_schema={
        "quote_id": {
            "type": "string",
            "description": "Quote ID (must be draft).",
            "example": "qt_…",
        },
        "expires_at": {
            "type": "integer",
            "description": "Override expiry at finalize time.",
            "example": 0,
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def finalize_stripe_quote(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "finalize_quote",
        quote_id=input_data["quote_id"],
        expires_at=input_data.get("expires_at") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="accept_stripe_quote",
    description="Accept an open Quote on the customer's behalf — creates the invoice / subscription per the quote terms.",
    action_sets=["stripe_quotes"],
    input_schema={
        "quote_id": {
            "type": "string",
            "description": "Quote ID (must be open).",
            "example": "qt_…",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def accept_stripe_quote(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "accept_quote",
        quote_id=input_data["quote_id"],
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="cancel_stripe_quote",
    description="Cancel a draft or open Quote. Cannot cancel an accepted quote.",
    action_sets=["stripe_quotes"],
    input_schema={
        "quote_id": {"type": "string", "description": "Quote ID.", "example": "qt_…"},
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def cancel_stripe_quote(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "cancel_quote",
        quote_id=input_data["quote_id"],
        idempotency_key=input_data.get("idempotency_key") or None,
    )


# ==================================================================
# Events + webhook endpoints (stripe_webhooks)
# ==================================================================


@action(
    name="list_stripe_events",
    description="List Events from the Stripe event log. Filter by type ('invoice.paid', 'customer.created', etc.) or multiple types.",
    action_sets=["stripe_webhooks"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "type": {
            "type": "string",
            "description": "Single event type filter.",
            "example": "invoice.paid",
        },
        "types": {
            "type": "array",
            "description": "List of event types.",
            "example": ["invoice.paid", "invoice.finalized"],
        },
        "delivery_success": {
            "type": "boolean",
            "description": "Only events delivered (or not delivered) successfully to a webhook.",
            "example": True,
        },
        "created_gte": {
            "type": "integer",
            "description": "Created >= UNIX timestamp.",
            "example": 0,
        },
        "created_lte": {
            "type": "integer",
            "description": "Created <= UNIX timestamp.",
            "example": 0,
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_events(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_events",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        type=input_data.get("type") or None,
        types=input_data.get("types") or None,
        delivery_success=input_data.get("delivery_success"),
        created_gte=input_data.get("created_gte") or None,
        created_lte=input_data.get("created_lte") or None,
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="get_stripe_event",
    description="Retrieve a single Event by ID.",
    action_sets=["stripe_webhooks"],
    input_schema={
        "event_id": {"type": "string", "description": "Event ID.", "example": "evt_…"},
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_event(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "get_event",
        event_id=input_data["event_id"],
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="list_stripe_webhook_endpoints",
    description="List Webhook Endpoints registered on the account.",
    action_sets=["stripe_webhooks"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_webhook_endpoints(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_webhook_endpoints",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="get_stripe_webhook_endpoint",
    description="Retrieve a Webhook Endpoint by ID.",
    action_sets=["stripe_webhooks"],
    input_schema={
        "endpoint_id": {
            "type": "string",
            "description": "Webhook Endpoint ID.",
            "example": "we_…",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_webhook_endpoint(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "get_webhook_endpoint",
        endpoint_id=input_data["endpoint_id"],
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="create_stripe_webhook_endpoint",
    description="Register a Webhook Endpoint. URL must be publicly reachable HTTPS. 'enabled_events' must explicitly list event types or ['*'].",
    action_sets=["stripe_webhooks"],
    input_schema={
        "url": {
            "type": "string",
            "description": "HTTPS URL Stripe will POST events to.",
            "example": "https://example.com/stripe/webhook",
        },
        "enabled_events": {
            "type": "array",
            "description": "Event types to subscribe to, or ['*'] for all.",
            "example": ["invoice.paid", "customer.created"],
        },
        "description": {
            "type": "string",
            "description": "Internal description.",
            "example": "",
        },
        "connect": {
            "type": "boolean",
            "description": "True for Connect events from connected accounts.",
            "example": False,
        },
        "api_version": {
            "type": "string",
            "description": "Pin the event payload version.",
            "example": "",
        },
        "metadata": {
            "type": "object",
            "description": "Arbitrary labels.",
            "example": {},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_stripe_webhook_endpoint(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "create_webhook_endpoint",
        url=input_data["url"],
        enabled_events=input_data["enabled_events"],
        description=input_data.get("description") or None,
        connect=input_data.get("connect"),
        api_version=input_data.get("api_version") or None,
        metadata=input_data.get("metadata") or None,
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="update_stripe_webhook_endpoint",
    description="Update a Webhook Endpoint's URL, enabled_events, description, disabled flag, etc.",
    action_sets=["stripe_webhooks"],
    input_schema={
        "endpoint_id": {
            "type": "string",
            "description": "Webhook Endpoint ID.",
            "example": "we_…",
        },
        "properties": {
            "type": "object",
            "description": "Properties to update.",
            "example": {"enabled_events": ["invoice.paid"], "disabled": False},
        },
        "idempotency_key": {
            "type": "string",
            "description": "Optional idempotency key.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_stripe_webhook_endpoint(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "update_webhook_endpoint",
        endpoint_id=input_data["endpoint_id"],
        properties=input_data.get("properties") or {},
        idempotency_key=input_data.get("idempotency_key") or None,
    )


@action(
    name="delete_stripe_webhook_endpoint",
    description="Delete a Webhook Endpoint. Stripe stops POSTing to its URL immediately.",
    action_sets=["stripe_webhooks"],
    input_schema={
        "endpoint_id": {
            "type": "string",
            "description": "Webhook Endpoint ID.",
            "example": "we_…",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_stripe_webhook_endpoint(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "delete_webhook_endpoint",
        endpoint_id=input_data["endpoint_id"],
    )


# ==================================================================
# Files (stripe_files)
# ==================================================================


@action(
    name="upload_stripe_file",
    description="Upload a file to Stripe (multipart). 'purpose' constrains downstream use — most commonly 'dispute_evidence' (then reference the returned file_id in update_stripe_dispute's evidence object).",
    action_sets=["stripe_files"],
    input_schema={
        "file_path": {
            "type": "string",
            "description": "Absolute path to a local file.",
            "example": "/tmp/receipt.png",
        },
        "purpose": {
            "type": "string",
            "description": "'dispute_evidence' | 'identity_document' | 'business_logo' | 'business_icon' | 'tax_document_user_upload' | 'finance_report_run' | 'pci_document' | 'additional_verification' | 'customer_signature'.",
            "example": "dispute_evidence",
        },
        "link_create": {
            "type": "boolean",
            "description": "Create a public file link alongside the upload.",
            "example": False,
        },
        "link_expires_at": {
            "type": "integer",
            "description": "UNIX timestamp link expiry.",
            "example": 0,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def upload_stripe_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "stripe",
        "upload_file",
        file_path=input_data["file_path"],
        purpose=input_data["purpose"],
        link_create=input_data.get("link_create"),
        link_expires_at=input_data.get("link_expires_at") or None,
    )


@action(
    name="get_stripe_file",
    description="Retrieve a File metadata record by ID.",
    action_sets=["stripe_files"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": "file_…"},
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "get_file",
        file_id=input_data["file_id"],
        expand=_csv(input_data.get("expand")),
    )


@action(
    name="list_stripe_files",
    description="List uploaded Files. Filter by purpose.",
    action_sets=["stripe_files"],
    input_schema={
        "limit": {
            "type": "integer",
            "description": "Max results (1-100).",
            "example": 10,
        },
        "starting_after": {"type": "string", "description": "Cursor.", "example": ""},
        "ending_before": {"type": "string", "description": "Cursor.", "example": ""},
        "purpose": {
            "type": "string",
            "description": "Filter by file purpose.",
            "example": "dispute_evidence",
        },
        "expand": {
            "type": "string",
            "description": "Comma-separated fields to expand.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_stripe_files(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    def _csv(v):
        if not v:
            return None
        return [s.strip() for s in str(v).split(",") if s.strip()] or None

    return await run_client(
        "stripe",
        "list_files",
        limit=input_data.get("limit", 10),
        starting_after=input_data.get("starting_after") or None,
        ending_before=input_data.get("ending_before") or None,
        purpose=input_data.get("purpose") or None,
        expand=_csv(input_data.get("expand")),
    )


# ==================================================================
# Account (umbrella-only — single read action, no fine-grained set)
# ==================================================================


@action(
    name="get_stripe_account",
    description="Retrieve the current Stripe account's profile — business name, country, default_currency, capabilities, payouts_enabled, etc.",
    action_sets=["stripe"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_stripe_account(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("stripe", "get_account")


# ==================================================================
# Intentionally NOT exposed as actions (and why)
# ==================================================================
# These Stripe REST categories are admin / niche / non-user-facing or carry
# enough operational risk that they should be a deliberate later addition,
# not a default surface. Add them when a real use case materializes.
#
# - Stripe Connect platform endpoints (accounts, account_links, transfers,
#   topups, application_fees, login_links, persons, capabilities)
#     The integration is intentionally not a Connect platform — see the auth
#     decision in INTEGRATION.md. Per-call `Stripe-Account` on connected
#     accounts is supported in the client for the rare standalone case.
# - Stripe Tax (registrations, transactions, calculations, settings)
#     Tax product is a distinct compliance surface; mis-application creates
#     real regulatory exposure. Tax codes on products/prices ARE supported,
#     which is the common case.
# - Stripe Issuing (cards, cardholders, authorizations, transactions,
#   personalization_designs, physical_bundles)
#     Card-issuing product is for embedded fintechs; specialized workflows.
# - Stripe Terminal (locations, readers, connection_tokens, configurations)
#     POS hardware; sessions span physical devices, not what an agent drives.
# - Stripe Climate (orders, products, suppliers)
#     Carbon-removal commitments; niche.
# - Stripe Apps (secrets, monitor_event)
#     Marketplace app authoring surface; not a customer surface.
# - Reporting (report_runs, report_types, sigma queries)
#     Admin / data-warehouse surface; ask the user to use the dashboard.
# - Setup intents (full CRUD)
#     Server-side SetupIntent creation is rarely useful — the client SDKs
#     handle the SCA flow. The agent has no way to complete a SetupIntent
#     without browser/mobile help. If a use case emerges, add a single
#     `create_stripe_setup_intent` to `stripe_payment_methods`.
# - Sources (legacy payment object), Tokens (browser-side)
#     Both superseded by PaymentMethods; including them encourages the LLM
#     to pick the wrong primitive.
# - Tax rates / shipping rates CRUD, billing portal configurations CRUD
#     Configuration-as-code surface; users overwhelmingly set these once
#     via the dashboard. Re-add if a concrete request comes in.
# - Credit notes
#     Refund-with-paperwork; useful but adds 6+ endpoints. Hold until a
#     user actually asks. Refunds + invoice voiding + uncollectible cover
#     ~95% of the same ground.
# - Customer Sessions (server SDK helper for Elements)
#     Client-SDK plumbing — not actionable server-side.
# - Tax IDs on customers (CRUD)
#     Niche compliance metadata. Most agents don't write these.
