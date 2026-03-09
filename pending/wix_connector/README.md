# wix_connector

A Python module for reading and writing to Wix sites via the Wix Headless REST API.

Supports: CMS collections, Blog posts, Store catalog, and Contacts/Members.

---

## What It Does

| Module | Capability |
|--------|-----------|
| `WixCMS` | Query, read, create, and update items in any Wix Data collection |
| `WixBlog` | List, create draft, and publish blog posts programmatically |
| `WixStore` | Read the Wix Store product catalog |
| `WixMembers` | List and search Wix Contacts |

---

## Getting Your API Key

1. Log into your [Wix Dashboard](https://manage.wix.com)
2. Go to **Settings** -> **API Keys** (in the Advanced section)
3. Click **Create API Key**
4. Give it a name (e.g., "Engineer0")
5. Select the **Site APIs** permissions you need:
   - Wix Data (for CMS)
   - Wix Blog (for blog posts)
   - Wix Stores (for product catalog)
   - Wix Contacts (for members/contacts)
6. Copy the generated key — it starts with `IST.eyJ...`
7. Find your **Site ID** in the dashboard URL: `manage.wix.com/dashboard/{SITE_ID}/...`

> Note: API Keys are scoped to a single Wix account. For per-user access across multiple sites, use OAuth instead.

---

## Setup

**Install dependencies:**

```bash
pip install httpx
# or install the package directly:
pip install -e /path/to/wix_connector
```

**Set environment variables** (copy `.env.example` to `.env`):

```bash
cp .env.example .env
# then edit .env with your real credentials
```

```
WIX_SITE_ID=your-wix-site-id-here
WIX_API_KEY=IST.eyJraWQiOiJQb3pIX2FjM...your-api-key
WIX_ACCOUNT_ID=   # optional
```

Load them before running:

```bash
export $(cat .env | xargs)
```

---

## Quick Start

### Check connection

```python
from wix_connector import WixClient

client = WixClient()
print(client.get_status())
# {'configured': True, 'site_id': 'a1b2c3d4...', 'api_key': 'set'}
```

### List blog posts

```python
from wix_connector import WixBlog

blog = WixBlog()
result = blog.list_posts(limit=10, status="PUBLISHED")
for post in result.get("posts", []):
    print(post["title"], post["id"])
```

### Create and publish a blog post

```python
from wix_connector import WixBlog

blog = WixBlog()
result = blog.create_and_publish(
    title="Engineer0 Daily Digest — Feb 17",
    content_html="<p>Today's research summary...</p>",
    excerpt="AI-generated digest of today's key findings.",
)
print(result)
# {'success': True, 'post_id': 'abc123', 'publish_result': {...}}
```

### Query a CMS collection

```python
from wix_connector import WixCMS

cms = WixCMS()

# List all collections
collections = cms.list_collections()

# Query items in a specific collection
items = cms.query(
    collection_id="MyCollection",
    filter={"fieldName": "status", "operator": "eq", "value": "active"},
    limit=25,
)
for item in items.get("dataItems", []):
    print(item["data"])
```

### Create a CMS item

```python
from wix_connector import WixCMS

cms = WixCMS()
result = cms.create_item("Tasks", {
    "title": "New task from Engineer0",
    "status": "pending",
    "assignedTo": "engineer0",
})
print(result)
```

### Read the store catalog

```python
from wix_connector import WixStore

store = WixStore()
products = store.list_products(limit=10, in_stock_only=True)
for p in products.get("products", []):
    print(p["name"], p["price"])
```

### Search contacts

```python
from wix_connector import WixMembers

members = WixMembers()
results = members.search_contacts("darnie")
```

---

## Sharing a Client Across Modules

To avoid creating multiple HTTP sessions, instantiate `WixClient` once and pass it in:

```python
from wix_connector import WixClient, WixBlog, WixCMS

client = WixClient()
blog = WixBlog(client=client)
cms = WixCMS(client=client)
```

---

## Important Limitations

- **Not all Wix sites support full headless write operations.** Only sites with **Wix Headless** or **Wix Studio** enabled support the full write API for CMS and Blog.
- **API Key permissions must match** the endpoints you call — a key without Blog permissions will return 403 on blog endpoints.
- **Rate limits apply.** Wix enforces per-minute and per-day rate limits on REST API calls.
- **Rich content format.** The Blog API uses Wix's `richContent` node format, not raw HTML. The `create_draft` method wraps plain text in a paragraph node — for complex formatting, build the node tree manually.
- **Tag creation is separate.** Blog tags must be created via the Tags API before referencing their IDs in posts.

---

## File Structure

```
wix_connector/
├── wix_connector/
│   ├── __init__.py      # Public exports
│   ├── client.py        # Base HTTP client (auth, GET/POST/PATCH)
│   ├── cms.py           # Wix Data (CMS) collections
│   ├── blog.py          # Blog post management
│   ├── store.py         # Store product catalog
│   └── members.py       # Contacts and members
├── setup.py
├── requirements.txt
├── .env.example
└── README.md
```

---

## API Reference Links

- [Wix REST API overview](https://dev.wix.com/docs/rest)
- [Wix Data (CMS) API](https://dev.wix.com/docs/rest/articles/getting-started/wix-headless/wix-data)
- [Wix Blog API v3](https://dev.wix.com/docs/rest/business-solutions/blog/posts/introduction)
- [Wix Stores API](https://dev.wix.com/docs/rest/business-solutions/stores/catalog/products/introduction)
- [Wix Contacts API](https://dev.wix.com/docs/rest/crm/contacts/introduction)
