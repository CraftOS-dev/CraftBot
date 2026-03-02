---
name: woocommerce
description: |
  WooCommerce REST API integration with managed OAuth. Access products, orders, customers, coupons, shipping, taxes, reports, and webhooks. Use this skill when users want to manage e-commerce operations, process orders, or integrate with WooCommerce stores. For other third party apps, use the api-gateway skill (https://clawhub.ai/byungkyu/api-gateway).
compatibility: Requires network access and valid Maton API key
metadata:
  author: maton
  version: "1.0"
  clawdbot:
    emoji: 🧠
    requires:
      env:
        - MATON_API_KEY
---

# WooCommerce

Access the WooCommerce REST API with managed OAuth authentication. Manage products, orders, customers, coupons, shipping, taxes, and more for e-commerce operations.

## Quick Start

```bash
# List products
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://gateway.maton.ai/woocommerce/wp-json/wc/v3/products')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

## Base URL

```
https://gateway.maton.ai/woocommerce/{native-api-path}
```

Replace `{native-api-path}` with the actual WooCommerce API endpoint path. The gateway proxies requests to your WooCommerce store and automatically handles authentication.

## Authentication

All requests require the Maton API key in the Authorization header:

```
Authorization: Bearer $MATON_API_KEY
```

**Environment Variable:** Set your API key as `MATON_API_KEY`:

```bash
export MATON_API_KEY="YOUR_API_KEY"
```

### Getting Your API Key

1. Sign in or create an account at [maton.ai](https://maton.ai)
2. Go to [maton.ai/settings](https://maton.ai/settings)
3. Copy your API key

## Connection Management

Manage your WooCommerce OAuth connections at `https://ctrl.maton.ai`.

### List Connections

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://ctrl.maton.ai/connections?app=woocommerce&status=ACTIVE')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

### Create Connection

```bash
python <<'EOF'
import urllib.request, os, json
data = json.dumps({'app': 'woocommerce'}).encode()
req = urllib.request.Request('https://ctrl.maton.ai/connections', data=data, method='POST')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
req.add_header('Content-Type', 'application/json')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

### Get Connection

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://ctrl.maton.ai/connections/{connection_id}')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

**Response:**
```json
{
  "connection": {
    "connection_id": "21fd90f9-5935-43cd-b6c8-bde9d915ca80",
    "status": "ACTIVE",
    "creation_time": "2025-12-08T07:20:53.488460Z",
    "last_updated_time": "2026-01-31T20:03:32.593153Z",
    "url": "https://connect.maton.ai/?session_token=...",
    "app": "woocommerce",
    "metadata": {}
  }
}
```

Open the returned `url` in a browser to complete OAuth authorization.

### Delete Connection

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://ctrl.maton.ai/connections/{connection_id}', method='DELETE')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

### Specifying Connection

If you have multiple WooCommerce connections, specify which one to use with the `Maton-Connection` header:

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://gateway.maton.ai/woocommerce/wp-json/wc/v3/products')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
req.add_header('Maton-Connection', '21fd90f9-5935-43cd-b6c8-bde9d915ca80')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

If omitted, the gateway uses the default (oldest) active connection.

## API Reference

### Products

#### List All Products

```bash
GET /woocommerce/wp-json/wc/v3/products
```

Query parameters:
- `page` - Current page (default: 1)
- `per_page` - Items per page (default: 10, max: 100)
- `search` - Search by product name
- `status` - Filter by status: `draft`, `pending`, `private`, `publish`
- `type` - Filter by type: `simple`, `grouped`, `external`, `variable`
- `sku` - Filter by SKU
- `category` - Filter by category ID
- `tag` - Filter by tag ID
- `featured` - Filter featured products
- `on_sale` - Filter on-sale products
- `min_price` / `max_price` - Filter by price range
- `stock_status` - Filter by stock status: `instock`, `outofstock`, `onbackorder`
- `orderby` - Sort by: `date`, `id`, `include`, `title`, `slug`, `price`, `popularity`, `rating`
- `order` - Sort order: `asc`, `desc`

**Example:**

```bash
curl -s -X GET "https://gateway.maton.ai/woocommerce/wp-json/wc/v3/products?per_page=20&status=publish" -H "Authorization: Bearer $MATON_API_KEY"
```

**Response:**
```json
[
  {
    "id": 123,
    "name": "Premium T-Shirt",
    "slug": "premium-t-shirt",
    "type": "simple",
    "status": "publish",
    "sku": "TSH-001",
    "price": "29.99",
    "regular_price": "34.99",
    "sale_price": "29.99",
    "stock_quantity": 50,
    "stock_status": "instock",
    "categories": [{"id": 15, "name": "Apparel"}],
    "images": [{"id": 456, "src": "https://..."}]
  }
]
```

#### Get a Product

```bash
GET /woocommerce/wp-json/wc/v3/products/{id}
```

**Example:**

```bash
curl -s -X GET "https://gateway.maton.ai/woocommerce/wp-json/wc/v3/products/123" -H "Authorization: Bearer $MATON_API_KEY"
```

#### Create a Product

```bash
POST /woocommerce/wp-json/wc/v3/products
Content-Type: application/json

{
  "name": "New Product",
  "type": "simple",
  "regular_price": "49.99",
  "description": "Full product description",
  "short_description": "Brief description",
  "sku": "PROD-001",
  "manage_stock": true,
  "stock_quantity": 100,
  "categories": [{"id": 15}],
  "images": [{"src": "https://example.com/image.jpg"}]
}
```

**Example:**

```bash
curl -s -X POST "https://gateway.maton.ai/woocommerce/wp-json/wc/v3/products" -H "Content-Type: application/json" -H "Authorization: Bearer $MATON_API_KEY" -d '{"name": "Premium Widget", "type": "simple", "regular_price": "19.99", "sku": "WDG-001"}'
```

#### Update a Product

```bash
PUT /woocommerce/wp-json/wc/v3/products/{id}
```

**Example:**

```bash
curl -s -X PUT "https://gateway.maton.ai/woocommerce/wp-json/wc/v3/products/123" -H "Content-Type: application/json" -H "Authorization: Bearer $MATON_API_KEY" -d '{"regular_price": "24.99", "sale_price": "19.99"}'
```

#### Delete a Product

```bash
DELETE /woocommerce/wp-json/wc/v3/products/{id}
```

Query parameters:
- `force` - Set to `true` to permanently delete (default: `false` moves to trash)

#### Duplicate a Product

```bash
POST /woocommerce/wp-json/wc/v3/products/{id}/duplicate
```

### Product Variations

For variable products, manage individual variations:

#### List Variations

```bash
GET /woocommerce/wp-json/wc/v3/products/{product_id}/variations
```

#### Create Variation

```bash
POST /woocommerce/wp-json/wc/v3/products/{product_id}/variations
Content-Type: application/json

{
  "regular_price": "29.99",
  "sku": "TSH-001-RED-M",
  "attributes": [
    {"id": 1, "option": "Red"},
    {"id": 2, "option": "Medium"}
  ]
}
```

#### Update Variation

```bash
PUT /woocommerce/wp-json/wc/v3/products/{product_id}/variations/{id}
```

#### Delete Variation

```bash
DELETE /woocommerce/wp-json/wc/v3/products/{product_id}/variations/{id}
```

#### Batch Update Variations

```bash
POST /woocommerce/wp-json/wc/v3/products/{product_id}/variations/batch
```

### Product Attributes

#### List Attributes

```bash
GET /woocommerce/wp-json/wc/v3/products/attributes
```

#### Create Attribute

```bash
POST /woocommerce/wp-json/wc/v3/products/attributes
Content-Type: application/json

{
  "name": "Color",
  "slug": "color",
  "type": "select",
  "order_by": "menu_order"
}
```

#### Get/Update/Delete Attribute

```bash
GET /woocommerce/wp-json/wc/v3/products/attributes/{id}
PUT /woocommerce/wp-json/wc/v3/products/attributes/{id}
DELETE /woocommerce/wp-json/wc/v3/products/attributes/{id}
```

### Attribute Terms

```bash
GET /woocommerce/wp-json/wc/v3/products/attributes/{attribute_id}/terms
POST /woocommerce/wp-json/wc/v3/products/attributes/{attribute_id}/terms
GET /woocommerce/wp-json/wc/v3/products/attributes/{attribute_id}/terms/{id}
PUT /woocommerce/wp-json/wc/v3/products/attributes/{attribute_id}/terms/{id}
DELETE /woocommerce/wp-json/wc/v3/products/attributes/{attribute_id}/terms/{id}
```

### Product Categories

#### List Categories

```bash
GET /woocommerce/wp-json/wc/v3/products/categories
```

#### Create Category

```bash
POST /woocommerce/wp-json/wc/v3/products/categories
Content-Type: application/json

{
  "name": "Electronics",
  "parent": 0,
  "description": "Electronic products"
}
```

#### Get/Update/Delete Category

```bash
GET /woocommerce/wp-json/wc/v3/products/categories/{id}
PUT /woocommerce/wp-json/wc/v3/products/categories/{id}
DELETE /woocommerce/wp-json/wc/v3/products/categories/{id}
```

### Product Tags

```bash
GET /woocommerce/wp-json/wc/v3/products/tags
POST /woocommerce/wp-json/wc/v3/products/tags
GET /woocommerce/wp-json/wc/v3/products/tags/{id}
PUT /woocommerce/wp-json/wc/v3/products/tags/{id}
DELETE /woocommerce/wp-json/wc/v3/products/tags/{id}
```

### Product Shipping Classes

```bash
GET /woocommerce/wp-json/wc/v3/products/shipping_classes
POST /woocommerce/wp-json/wc/v3/products/shipping_classes
GET /woocommerce/wp-json/wc/v3/products/shipping_classes/{id}
PUT /woocommerce/wp-json/wc/v3/products/shipping_classes/{id}
DELETE /woocommerce/wp-json/wc/v3/products/shipping_classes/{id}
```

### Product Reviews

#### List Reviews

```bash
GET /woocommerce/wp-json/wc/v3/products/reviews
```

Query parameters:
- `product` - Filter by product ID
- `status` - Filter by status: `approved`, `hold`, `spam`, `trash`

#### Create Review

```bash
POST /woocommerce/wp-json/wc/v3/products/reviews
Content-Type: application/json

{
  "product_id": 123,
  "review": "Great product!",
  "reviewer": "John Doe",
  "reviewer_email": "john@example.com",
  "rating": 5
}
```

#### Get/Update/Delete Review

```bash
GET /woocommerce/wp-json/wc/v3/products/reviews/{id}
PUT /woocommerce/wp-json/wc/v3/products/reviews/{id}
DELETE /woocommerce/wp-json/wc/v3/products/reviews/{id}
```

---

### Orders

#### List All Orders

```bash
GET /woocommerce/wp-json/wc/v3/orders
```

Query parameters:
- `page` - Current page (default: 1)
- `per_page` - Items per page (default: 10)
- `search` - Search orders
- `after` / `before` - Filter by date (ISO8601)
- `status` - Order status (see below)
- `customer` - Filter by customer ID
- `product` - Filter by product ID
- `orderby` - Sort by: `date`, `id`, `include`, `title`, `slug`
- `order` - Sort order: `asc`, `desc`

**Order Statuses:**
- `pending` - Payment pending
- `processing` - Payment received, awaiting fulfillment
- `on-hold` - Awaiting payment confirmation
- `completed` - Order fulfilled
- `cancelled` - Cancelled by admin or customer
- `refunded` - Fully refunded
- `failed` - Payment failed

**Example:**

```bash
curl -s -X GET "https://gateway.maton.ai/woocommerce/wp-json/wc/v3/orders?status=processing&per_page=50" -H "Authorization: Bearer $MATON_API_KEY"
```

**Response:**
```json
[
  {
    "id": 456,
    "status": "processing",
    "currency": "USD",
    "total": "129.99",
    "customer_id": 12,
    "billing": {
      "first_name": "John",
      "last_name": "Doe",
      "email": "john@example.com"
    },
    "line_items": [
      {
        "id": 789,
        "product_id": 123,
        "name": "Premium T-Shirt",
        "quantity": 2,
        "total": "59.98"
      }
    ]
  }
]
```

#### Get an Order

```bash
GET /woocommerce/wp-json/wc/v3/orders/{id}
```

#### Create an Order

```bash
POST /woocommerce/wp-json/wc/v3/orders
Content-Type: application/json

{
  "payment_method": "stripe",
  "payment_method_title": "Credit Card",
  "set_paid": true,
  "billing": {
    "first_name": "John",
    "last_name": "Doe",
    "address_1": "123 Main St",
    "city": "Anytown",
    "state": "CA",
    "postcode": "12345",
    "country": "US",
    "email": "john@example.com",
    "phone": "555-1234"
  },
  "shipping": {
    "first_name": "John",
    "last_name": "Doe",
    "address_1": "123 Main St",
    "city": "Anytown",
    "state": "CA",
    "postcode": "12345",
    "country": "US"
  },
  "line_items": [
    {
      "product_id": 123,
      "quantity": 2
    }
  ]
}
```

#### Update an Order

```bash
PUT /woocommerce/wp-json/wc/v3/orders/{id}
```

**Example - Update order status:**

```bash
curl -s -X PUT "https://gateway.maton.ai/woocommerce/wp-json/wc/v3/orders/456" -H "Content-Type: application/json" -H "Authorization: Bearer $MATON_API_KEY" -d '{"status": "completed"}'
```

#### Delete an Order

```bash
DELETE /woocommerce/wp-json/wc/v3/orders/{id}
```

### Order Notes

#### List Order Notes

```bash
GET /woocommerce/wp-json/wc/v3/orders/{order_id}/notes
```

#### Create Order Note

```bash
POST /woocommerce/wp-json/wc/v3/orders/{order_id}/notes
Content-Type: application/json

{
  "note": "Order shipped via FedEx, tracking #12345",
  "customer_note": true
}
```

- `customer_note`: Set to `true` to make the note visible to the customer

#### Get/Delete Order Note

```bash
GET /woocommerce/wp-json/wc/v3/orders/{order_id}/notes/{id}
DELETE /woocommerce/wp-json/wc/v3/orders/{order_id}/notes/{id}
```

### Order Refunds

#### List Refunds

```bash
GET /woocommerce/wp-json/wc/v3/orders/{order_id}/refunds
```

#### Create Refund

```bash
POST /woocommerce/wp-json/wc/v3/orders/{order_id}/refunds
Content-Type: application/json

{
  "amount": "25.00",
  "reason": "Product damaged during shipping",
  "api_refund": true
}
```

- `api_refund`: Set to `true` to process refund through payment gateway

#### Get/Delete Refund

```bash
GET /woocommerce/wp-json/wc/v3/orders/{order_id}/refunds/{id}
DELETE /woocommerce/wp-json/wc/v3/orders/{order_id}/refunds/{id}
```

---

### Customers

#### List All Customers

```bash
GET /woocommerce/wp-json/wc/v3/customers
```

Query parameters:
- `page` - Current page (default: 1)
- `per_page` - Items per page (default: 10)
- `search` - Search by name or email
- `email` - Filter by exact email
- `role` - Filter by role: `all`, `administrator`, `customer`, `shop_manager`
- `orderby` - Sort by: `id`, `include`, `name`, `registered_date`
- `order` - Sort order: `asc`, `desc`

**Example:**

```bash
curl -s -X GET "https://gateway.maton.ai/woocommerce/wp-json/wc/v3/customers?per_page=25" -H "Authorization: Bearer $MATON_API_KEY"
```

**Response:**
```json
[
  {
    "id": 12,
    "email": "john@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "username": "johndoe",
    "billing": {
      "first_name": "John",
      "last_name": "Doe",
      "address_1": "123 Main St",
      "city": "Anytown",
      "state": "CA",
      "postcode": "12345",
      "country": "US",
      "email": "john@example.com",
      "phone": "555-1234"
    },
    "shipping": {
      "first_name": "John",
      "last_name": "Doe",
      "address_1": "123 Main St",
      "city": "Anytown",
      "state": "CA",
      "postcode": "12345",
      "country": "US"
    }
  }
]
```

#### Get a Customer

```bash
GET /woocommerce/wp-json/wc/v3/customers/{id}
```

#### Create a Customer

```bash
POST /woocommerce/wp-json/wc/v3/customers
Content-Type: application/json

{
  "email": "jane@example.com",
  "first_name": "Jane",
  "last_name": "Smith",
  "username": "janesmith",
  "password": "secure_password",
  "billing": {
    "first_name": "Jane",
    "last_name": "Smith",
    "address_1": "456 Oak Ave",
    "city": "Springfield",
    "state": "IL",
    "postcode": "62701",
    "country": "US",
    "email": "jane@example.com",
    "phone": "555-5678"
  }
}
```

#### Update a Customer

```bash
PUT /woocommerce/wp-json/wc/v3/customers/{id}
```

#### Delete a Customer

```bash
DELETE /woocommerce/wp-json/wc/v3/customers/{id}
```

### Customer Downloads

```bash
GET /woocommerce/wp-json/wc/v3/customers/{customer_id}/downloads
```

Returns downloadable products the customer has access to.

---

### Coupons

#### List All Coupons

```bash
GET /woocommerce/wp-json/wc/v3/coupons
```

Query parameters:
- `page` - Current page (default: 1)
- `per_page` - Items per page (default: 10)
- `search` - Search coupons
- `code` - Filter by coupon code

#### Get a Coupon

```bash
GET /woocommerce/wp-json/wc/v3/coupons/{id}
```

#### Create a Coupon

```bash
POST /woocommerce/wp-json/wc/v3/coupons
Content-Type: application/json

{
  "code": "SUMMER2024",
  "discount_type": "percent",
  "amount": "15",
  "description": "Summer promotion - 15% off",
  "date_expires": "2024-08-31T23:59:59",
  "individual_use": true,
  "usage_limit": 100,
  "usage_limit_per_user": 1,
  "minimum_amount": "50.00",
  "maximum_amount": "500.00",
  "free_shipping": false,
  "exclude_sale_items": true
}
```

**Discount Types:**
- `percent` - Percentage discount
- `fixed_cart` - Fixed amount off entire cart
- `fixed_product` - Fixed amount off per product

**Coupon Properties:**
- `code` - Coupon code (required)
- `amount` - Discount amount
- `discount_type` - Type of discount
- `description` - Coupon description
- `date_expires` - Expiration date (ISO8601)
- `individual_use` - Cannot be combined with other coupons
- `product_ids` - Array of product IDs the coupon applies to
- `excluded_product_ids` - Array of product IDs excluded
- `usage_limit` - Total number of times coupon can be used
- `usage_limit_per_user` - Usage limit per customer
- `limit_usage_to_x_items` - Max items the discount applies to
- `free_shipping` - Enables free shipping
- `product_categories` - Array of category IDs
- `excluded_product_categories` - Array of excluded category IDs
- `exclude_sale_items` - Exclude sale items from discount
- `minimum_amount` - Minimum cart total required
- `maximum_amount` - Maximum cart total allowed
- `email_restrictions` - Array of allowed email addresses

#### Update a Coupon

```bash
PUT /woocommerce/wp-json/wc/v3/coupons/{id}
```

#### Delete a Coupon

```bash
DELETE /woocommerce/wp-json/wc/v3/coupons/{id}
```

---

### Taxes

#### Tax Rates

```bash
GET /woocommerce/wp-json/wc/v3/taxes
POST /woocommerce/wp-json/wc/v3/taxes
GET /woocommerce/wp-json/wc/v3/taxes/{id}
PUT /woocommerce/wp-json/wc/v3/taxes/{id}
DELETE /woocommerce/wp-json/wc/v3/taxes/{id}
POST /woocommerce/wp-json/wc/v3/taxes/batch
```

**Create Tax Rate Example:**

```bash
curl -s -X POST "https://gateway.maton.ai/woocommerce/wp-json/wc/v3/taxes" -H "Content-Type: application/json" -H "Authorization: Bearer $MATON_API_KEY" -d '{"country": "US", "state": "CA", "rate": "7.25", "name": "CA State Tax", "shipping": true}'
```

#### Tax Classes

```bash
GET /woocommerce/wp-json/wc/v3/taxes/classes
POST /woocommerce/wp-json/wc/v3/taxes/classes
DELETE /woocommerce/wp-json/wc/v3/taxes/classes/{slug}
```

---

### Shipping

#### Shipping Zones

```bash
GET /woocommerce/wp-json/wc/v3/shipping/zones
POST /woocommerce/wp-json/wc/v3/shipping/zones
GET /woocommerce/wp-json/wc/v3/shipping/zones/{id}
PUT /woocommerce/wp-json/wc/v3/shipping/zones/{id}
DELETE /woocommerce/wp-json/wc/v3/shipping/zones/{id}
```

**Create Shipping Zone Example:**

```bash
curl -s -X POST "https://gateway.maton.ai/woocommerce/wp-json/wc/v3/shipping/zones" -H "Content-Type: application/json" -H "Authorization: Bearer $MATON_API_KEY" -d '{"name": "US West Coast", "order": 1}'
```

#### Shipping Zone Locations

```bash
GET /woocommerce/wp-json/wc/v3/shipping/zones/{zone_id}/locations
PUT /woocommerce/wp-json/wc/v3/shipping/zones/{zone_id}/locations
```

**Update Zone Locations Example:**

```bash
curl -s -X PUT "https://gateway.maton.ai/woocommerce/wp-json/wc/v3/shipping/zones/1/locations" -H "Content-Type: application/json" -H "Authorization: Bearer $MATON_API_KEY" -d '[{"code": "US:CA", "type": "state"}, {"code": "US:OR", "type": "state"}, {"code": "US:WA", "type": "state"}]'
```

#### Shipping Zone Methods

```bash
GET /woocommerce/wp-json/wc/v3/shipping/zones/{zone_id}/methods
POST /woocommerce/wp-json/wc/v3/shipping/zones/{zone_id}/methods
GET /woocommerce/wp-json/wc/v3/shipping/zones/{zone_id}/methods/{id}
PUT /woocommerce/wp-json/wc/v3/shipping/zones/{zone_id}/methods/{id}
DELETE /woocommerce/wp-json/wc/v3/shipping/zones/{zone_id}/methods/{id}
```

#### Shipping Methods (Global)

```bash
GET /woocommerce/wp-json/wc/v3/shipping_methods
GET /woocommerce/wp-json/wc/v3/shipping_methods/{id}
```

---

### Payment Gateways

```bash
GET /woocommerce/wp-json/wc/v3/payment_gateways
GET /woocommerce/wp-json/wc/v3/payment_gateways/{id}
PUT /woocommerce/wp-json/wc/v3/payment_gateways/{id}
```

**Example - Enable a Payment Gateway:**

```bash
curl -s -X PUT "https://gateway.maton.ai/woocommerce/wp-json/wc/v3/payment_gateways/stripe" -H "Content-Type: application/json" -H "Authorization: Bearer $MATON_API_KEY" -d '{"enabled": true}'
```

---

### Settings

#### List Settings Groups

```bash
GET /woocommerce/wp-json/wc/v3/settings
```

#### List Settings in a Group

```bash
GET /woocommerce/wp-json/wc/v3/settings/{group}
```

Common groups: `general`, `products`, `tax`, `shipping`, `checkout`, `account`, `email`

#### Get/Update a Setting

```bash
GET /woocommerce/wp-json/wc/v3/settings/{group}/{id}
PUT /woocommerce/wp-json/wc/v3/settings/{group}/{id}
```

**Example - Update Store Address:**

```bash
curl -s -X PUT "https://gateway.maton.ai/woocommerce/wp-json/wc/v3/settings/general/woocommerce_store_address" -H "Content-Type: application/json" -H "Authorization: Bearer $MATON_API_KEY" -d '{"value": "123 Commerce St"}'
```

#### Batch Update Settings

```bash
POST /woocommerce/wp-json/wc/v3/settings/{group}/batch
```

---

### Webhooks

#### List All Webhooks

```bash
GET /woocommerce/wp-json/wc/v3/webhooks
```

#### Create a Webhook

```bash
POST /woocommerce/wp-json/wc/v3/webhooks
Content-Type: application/json

{
  "name": "Order Created",
  "topic": "order.created",
  "delivery_url": "https://example.com/webhooks/woocommerce",
  "status": "active"
}
```

**Webhook Topics:**
- `order.created`, `order.updated`, `order.deleted`, `order.restored`
- `product.created`, `product.updated`, `product.deleted`, `product.restored`
- `customer.created`, `customer.updated`, `customer.deleted`
- `coupon.created`, `coupon.updated`, `coupon.deleted`, `coupon.restored`

#### Get/Update/Delete Webhook

```bash
GET /woocommerce/wp-json/wc/v3/webhooks/{id}
PUT /woocommerce/wp-json/wc/v3/webhooks/{id}
DELETE /woocommerce/wp-json/wc/v3/webhooks/{id}
```

---

### Reports

#### List Available Reports

```bash
GET /woocommerce/wp-json/wc/v3/reports
```

#### Sales Report

```bash
GET /woocommerce/wp-json/wc/v3/reports/sales
```

Query parameters:
- `period` - Report period: `week`, `month`, `last_month`, `year`
- `date_min` / `date_max` - Custom date range

#### Top Sellers Report

```bash
GET /woocommerce/wp-json/wc/v3/reports/top_sellers
```

#### Coupons Totals

```bash
GET /woocommerce/wp-json/wc/v3/reports/coupons/totals
```

#### Customers Totals

```bash
GET /woocommerce/wp-json/wc/v3/reports/customers/totals
```

#### Orders Totals

```bash
GET /woocommerce/wp-json/wc/v3/reports/orders/totals
```

#### Products Totals

```bash
GET /woocommerce/wp-json/wc/v3/reports/products/totals
```

#### Reviews Totals

```bash
GET /woocommerce/wp-json/wc/v3/reports/reviews/totals
```

---

### Data

#### List All Data Endpoints

```bash
GET /woocommerce/wp-json/wc/v3/data
```

#### Continents

```bash
GET /woocommerce/wp-json/wc/v3/data/continents
GET /woocommerce/wp-json/wc/v3/data/continents/{code}
```

#### Countries

```bash
GET /woocommerce/wp-json/wc/v3/data/countries
GET /woocommerce/wp-json/wc/v3/data/countries/{code}
```

#### Currencies

```bash
GET /woocommerce/wp-json/wc/v3/data/currencies
GET /woocommerce/wp-json/wc/v3/data/currencies/{code}
GET /woocommerce/wp-json/wc/v3/data/currencies/current
```

---

### System Status

```bash
GET /woocommerce/wp-json/wc/v3/system_status
GET /woocommerce/wp-json/wc/v3/system_status/tools
POST /woocommerce/wp-json/wc/v3/system_status/tools/{id}
```

---

## Batch Operations

Most resources support batch operations for creating, updating, and deleting multiple items:

```bash
POST /woocommerce/wp-json/wc/v3/{resource}/batch
Content-Type: application/json

{
  "create": [
    {"name": "New Product 1", "regular_price": "19.99"},
    {"name": "New Product 2", "regular_price": "29.99"}
  ],
  "update": [
    {"id": 123, "regular_price": "24.99"}
  ],
  "delete": [456, 789]
}
```

**Response:**
```json
{
  "create": [...],
  "update": [...],
  "delete": [...]
}
```

## Pagination

WooCommerce uses page-based pagination with response headers:

**Query Parameters:**
- `page` - Page number (default: 1)
- `per_page` - Items per page (default: 10, max: 100)
- `offset` - Offset to start from

**Response Headers:**
- `X-WP-Total` - Total number of items
- `X-WP-TotalPages` - Total number of pages
- `Link` - Contains `next`, `prev`, `first`, `last` pagination links

**Example:**

```bash
curl -s -I -X GET "https://gateway.maton.ai/woocommerce/wp-json/wc/v3/products?page=2&per_page=25" -H "Authorization: Bearer $MATON_API_KEY"
```

## Code Examples

### JavaScript

```javascript
const response = await fetch(
  'https://gateway.maton.ai/woocommerce/wp-json/wc/v3/orders?status=processing',
  {
    headers: {
      'Authorization': `Bearer ${process.env.MATON_API_KEY}`
    }
  }
);
const orders = await response.json();
```

### Python

```python
import os
import requests

response = requests.get(
    'https://gateway.maton.ai/woocommerce/wp-json/wc/v3/products',
    headers={'Authorization': f'Bearer {os.environ["MATON_API_KEY"]}'},
    params={'per_page': 50, 'status': 'publish'}
)
products = response.json()
```

### Creating an Order with Line Items

```python
import os
import requests

order_data = {
    "payment_method": "stripe",
    "set_paid": True,
    "billing": {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john@example.com",
        "address_1": "123 Main St",
        "city": "Anytown",
        "state": "CA",
        "postcode": "12345",
        "country": "US"
    },
    "line_items": [
        {"product_id": 123, "quantity": 2},
        {"product_id": 456, "quantity": 1}
    ]
}

response = requests.post(
    'https://gateway.maton.ai/woocommerce/wp-json/wc/v3/orders',
    headers={
        'Authorization': f'Bearer {os.environ["MATON_API_KEY"]}',
        'Content-Type': 'application/json'
    },
    json=order_data
)
order = response.json()
```

## Notes

- All monetary amounts are returned as strings with two decimal places
- Dates are in ISO8601 format: `YYYY-MM-DDTHH:MM:SS`
- Resource IDs are integers
- The API requires "pretty permalinks" enabled in WordPress
- Use `context=edit` parameter for additional writable fields
- IMPORTANT: When using curl commands, use `curl -g` when URLs contain brackets (`fields[]`, `sort[]`, `records[]`) to disable glob parsing
- IMPORTANT: When piping curl output to `jq` or other commands, environment variables like `$MATON_API_KEY` may not expand correctly in some shell environments. You may get "Invalid API key" errors when piping.

## Error Handling

| Status | Meaning |
|--------|---------|
| 400 | Bad request or invalid data |
| 401 | Invalid or missing authentication |
| 403 | Forbidden - insufficient permissions |
| 404 | Resource not found |
| 500 | Internal server error |

**Error Response Format:**
```json
{
  "code": "woocommerce_rest_invalid_id",
  "message": "Invalid ID.",
  "data": {
    "status": 404
  }
}
```

### Troubleshooting: API Key Issues

1. Check that the `MATON_API_KEY` environment variable is set:

```bash
echo $MATON_API_KEY
```

2. Verify the API key is valid by listing connections:

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://ctrl.maton.ai/connections')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

### Troubleshooting: Invalid App Name

1. Ensure your URL path starts with `woocommerce`. For example:

- Correct: `https://gateway.maton.ai/woocommerce/wp-json/wc/v3/products`
- Incorrect: `https://gateway.maton.ai/wp-json/wc/v3/products`

## Resources

### General
- [WooCommerce REST API Documentation](https://woocommerce.github.io/woocommerce-rest-api-docs/)
- [API Authentication Guide](https://woocommerce.github.io/woocommerce-rest-api-docs/#authentication)
- [WooCommerce Developer Resources](https://developer.woocommerce.com/)

### Products
- [Products](https://woocommerce.github.io/woocommerce-rest-api-docs/#products)
- [Product Variations](https://woocommerce.github.io/woocommerce-rest-api-docs/#product-variations)
- [Product Attributes](https://woocommerce.github.io/woocommerce-rest-api-docs/#product-attributes)
- [Product Attribute Terms](https://woocommerce.github.io/woocommerce-rest-api-docs/#product-attribute-terms)
- [Product Categories](https://woocommerce.github.io/woocommerce-rest-api-docs/#product-categories)
- [Product Tags](https://woocommerce.github.io/woocommerce-rest-api-docs/#product-tags)
- [Product Shipping Classes](https://woocommerce.github.io/woocommerce-rest-api-docs/#product-shipping-classes)
- [Product Reviews](https://woocommerce.github.io/woocommerce-rest-api-docs/#product-reviews)

### Orders
- [Orders](https://woocommerce.github.io/woocommerce-rest-api-docs/#orders)
- [Order Notes](https://woocommerce.github.io/woocommerce-rest-api-docs/#order-notes)
- [Refunds](https://woocommerce.github.io/woocommerce-rest-api-docs/#refunds)

### Customers
- [Customers](https://woocommerce.github.io/woocommerce-rest-api-docs/#customers)

### Coupons
- [Coupons](https://woocommerce.github.io/woocommerce-rest-api-docs/#coupons)

### Taxes
- [Tax Rates](https://woocommerce.github.io/woocommerce-rest-api-docs/#tax-rates)
- [Tax Classes](https://woocommerce.github.io/woocommerce-rest-api-docs/#tax-classes)

### Shipping
- [Shipping Zones](https://woocommerce.github.io/woocommerce-rest-api-docs/#shipping-zones)
- [Shipping Zone Locations](https://woocommerce.github.io/woocommerce-rest-api-docs/#shipping-zone-locations)
- [Shipping Zone Methods](https://woocommerce.github.io/woocommerce-rest-api-docs/#shipping-zone-methods)
- [Shipping Methods](https://woocommerce.github.io/woocommerce-rest-api-docs/#shipping-methods)

### Payments & Settings
- [Payment Gateways](https://woocommerce.github.io/woocommerce-rest-api-docs/#payment-gateways)
- [Settings](https://woocommerce.github.io/woocommerce-rest-api-docs/#settings)
- [Setting Options](https://woocommerce.github.io/woocommerce-rest-api-docs/#setting-options)

### Webhooks
- [Webhooks](https://woocommerce.github.io/woocommerce-rest-api-docs/#webhooks)

### Reports
- [Reports](https://woocommerce.github.io/woocommerce-rest-api-docs/#reports)
- [Sales Reports](https://woocommerce.github.io/woocommerce-rest-api-docs/#sales-reports)
- [Top Sellers Report](https://woocommerce.github.io/woocommerce-rest-api-docs/#top-sellers-report)
- [Coupons Totals](https://woocommerce.github.io/woocommerce-rest-api-docs/#coupons-totals)
- [Customers Totals](https://woocommerce.github.io/woocommerce-rest-api-docs/#customers-totals)
- [Orders Totals](https://woocommerce.github.io/woocommerce-rest-api-docs/#orders-totals)
- [Products Totals](https://woocommerce.github.io/woocommerce-rest-api-docs/#products-totals)
- [Reviews Totals](https://woocommerce.github.io/woocommerce-rest-api-docs/#reviews-totals)

### Data
- [Data](https://woocommerce.github.io/woocommerce-rest-api-docs/#data)
- [Continents](https://woocommerce.github.io/woocommerce-rest-api-docs/#continents)
- [Countries](https://woocommerce.github.io/woocommerce-rest-api-docs/#countries)
- [Currencies](https://woocommerce.github.io/woocommerce-rest-api-docs/#currencies)

### System
- [System Status](https://woocommerce.github.io/woocommerce-rest-api-docs/#system-status)
- [System Status Tools](https://woocommerce.github.io/woocommerce-rest-api-docs/#system-status-tools)
- [Maton Community](https://discord.com/invite/dBfFAcefs2)
- [Maton Support](mailto:support@maton.ai)
