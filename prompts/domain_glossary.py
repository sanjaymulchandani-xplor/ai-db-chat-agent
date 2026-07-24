from __future__ import annotations

from typing import List, Sequence, Set

"""Curated Mariana-Django domain knowledge for Text-to-SQL.

This is NOT a live schema dump. It teaches the model what tables mean,
how to join them, and which status strings are exact."""

# Allowlists / denylists
CORE_TABLES: frozenset[str] = frozenset(
    {
        # Identity
        "user_core_marianauser",
        "user_core_employee",
        "user_core_taggedmarianauser",
        "user_core_marianausertag",
        # Turf hierarchy
        "reservation_core_site",
        "reservation_core_region",
        "reservation_core_location",
        "reservation_core_classroom",
        "reservation_core_layout",
        "reservation_core_spot",
        "reservation_core_spottype",
        "reservation_core_slottype",
        # Classes & bookings
        "reservation_core_classsession",
        "reservation_core_classsessiontype",
        "reservation_core_classsessiontag",
        "reservation_core_taggedclasssession",
        "reservation_core_reservation",
        "reservation_core_taggedreservation",
        "reservation_core_reservationtag",
        "reservation_core_instructortoclasssessionassignment",
        "reservation_core_recurringclasssession",
        "reservation_core_scheduletemplate",
        "reservation_core_scheduletemplateclasssession",
        "reservation_core_spothold",
        "reservation_core_lastvisit",
        "reservation_core_ding",
        # Memberships & credits
        "reservation_core_membership",
        "reservation_core_membershipinstance",
        "reservation_core_membershiptransaction",
        "reservation_core_membershipslot",
        "reservation_core_membershipfreeze",
        "reservation_core_credit",
        "reservation_core_credittransaction",
        "reservation_core_creditslot",
        "reservation_core_bookingwindow",
        "reservation_core_latecancelwindow",
        "reservation_core_noshowwindow",
        "reservation_core_waitlistcutoffwindow",
        # Commerce (Oscar forks)
        "partner_partner",
        "partner_stockrecord",
        "catalogue_product",
        "catalogue_productclass",
        "catalogue_category",
        "catalogue_productcategory",
        "order_order",
        "order_line",
        "order_orderdiscount",
        "payment_source",
        "payment_sourcetype",
        "payment_transaction",
        "payment_bankcard",
        "payment_bankaccount",
        # Offers / vouchers (common business Qs)
        "offer_conditionaloffer",
        "voucher_voucher",
        "voucher_voucherapplication",
        # Account balances / gifts
        "user_core_accounttransaction",
        "user_core_giftcardinstance",
        "user_core_creditgiftinstance",
        "user_core_accountgiftinstance",
    }
)

REPORTING_VIEWS: frozenset[str] = frozenset(
    {
        "view_reservations_report",
        "view_orders_report",
        "view_customers_report",
        "view_sales_by_location",
        "view_sales_by_product",
        "view_sales_by_product_type",
        "view_payment_transactions",
        "view_payment_transactions_by_location",
        "view_outstanding_credits",
        "view_outstanding_balances",
        "view_membership_instance_facts",
        "view_customer_retention_report",
        "view_customer_frequency",
        "view_utilization_by_location",
        "view_utilization_by_instructor",
        "view_utilization_by_class_type",
        "view_revenue_by_class_session",
        "view_realized_revenue",
        "view_total_daily_sales_by_location",
        "view_employee_report",
        "view_instructor_payroll",
        "view_credit_details",
        "view_credit_usage_details",
        "view_first_timer_facts",
    }
)

EXCLUDE_PREFIXES: tuple[str, ...] = (
    "mbo_migration_",
    "zingfit_migration_",
    "client_migration_",
    "csv_migration_",
    "django_",
    "oauth2_",
    "mt_oauth_",
    "axes_",
    "social_auth_",
    "tests_",
    "guardian_",
    "thumbnail_",
    "constance_",
    "auth_group",
    "auth_permission",
    "admin_core_dummypwr",
)

REPORTING_QUESTION_HINTS: tuple[str, ...] = (
    "report",
    "reporting",
    "analytics",
    "utilization",
    "retention",
    "revenue",
    "payroll",
    "dashboard",
    "kpi",
    "trend",
    "by location",
    "by product",
    "by instructor",
    "sales by",
    "outstanding",
)


def is_excluded_table(table_name: str) -> bool:
    return any(table_name.startswith(prefix) for prefix in EXCLUDE_PREFIXES)


def question_looks_like_reporting(question: str) -> bool:
    q = question.lower()
    return any(hint in q for hint in REPORTING_QUESTION_HINTS)


def filter_tables_for_question(
    cached_tables: Sequence[str],
    question: str | None = None,
) -> List[str]:
    """Intersect live cache with core allowlist; optionally add reporting views."""
    cached: Set[str] = {t for t in cached_tables if not is_excluded_table(t)}
    selected = sorted(cached & CORE_TABLES)

    include_views = question is None or question_looks_like_reporting(question)
    if include_views:
        views = sorted(cached & REPORTING_VIEWS)
        # Also pick up any other view_* already in cache that matches REPORTING_VIEWS
        # plus unknown view_* only when question is clearly reporting.
        if question is not None and question_looks_like_reporting(question):
            extra_views = sorted(
                t for t in cached if t.startswith("view_") and t not in views
            )
            views = sorted(set(views) | set(extra_views))
        for v in views:
            if v not in selected:
                selected.append(v)

    return selected


def build_domain_glossary_text(schema_name: str) -> str:
    """Static domain glossary with schema name substituted for examples."""
    s = schema_name
    return f"""
## Mariana domain (tenant schema: {s})

Multi-tenant: each studio brand lives in its own Postgres schema (e.g. `{s}`).
Always qualify tables as `{s}.<table>`. Do not query other schemas.

### Conventions
- Soft-delete: many entities use `archived_at`. Active rows → `archived_at IS NULL`.
- Reservations are NOT soft-deleted; they use `status` instead.
- Timestamps (`start_datetime`, `date_placed`, etc.) are stored in **UTC**.
- Studio local time: use `{s}.reservation_core_location.timezone`.
- Most models have `id`, `created_at`, `updated_at`.

### Turf hierarchy (physical space)
Site → Region → Location → Classroom → Layout → Spot → ClassSession

| Table | Meaning | Key join / filter tips |
|---|---|---|
| `{s}.reservation_core_site` | Brand / top turf | `id`, `name` |
| `{s}.reservation_core_region` | Region under a site | `site_id` → site |
| `{s}.reservation_core_location` | Studio location | `region_id`, `site_id`, `timezone`, `status`, `partner_id` (1:1 to partner), `listed` |
| `{s}.reservation_core_classroom` | Room in a location | `location_id` |
| `{s}.reservation_core_layout` | Seat map for a classroom | `classroom_id` |
| `{s}.reservation_core_spot` | Individual seat | layout FK |

Location.status values: `onboarding` | `live` | `frozen` | `closed`.
"Live studio" usually means `status = 'live'` (and often `archived_at IS NULL` if present).

### Users
| Table | Meaning | Tips |
|---|---|---|
| `{s}.user_core_marianauser` | Customer / staff user | `email` (lowercased), `first_name`, `last_name`, `full_name`, `phone_number`, `home_location_id`, `is_active`, `is_staff`, `archived_at`, `merged_into_id` |

Filter out archived users with `archived_at IS NULL` unless the question asks for deleted/merged accounts.

### Classes & reservations
| Table | Meaning | Tips |
|---|---|---|
| `{s}.reservation_core_classsession` | A scheduled class | `layout_id` → layout → classroom → location; `start_datetime` (UTC); `class_session_type_id`; cancelled if `cancellation_datetime IS NOT NULL`; also filter `archived_at IS NULL` |
| `{s}.reservation_core_classsessiontype` | Class type / format | name, duration-related attrs |
| `{s}.reservation_core_reservation` | A booking / seat hold | See critical FKs below |
| `{s}.reservation_core_instructortoclasssessionassignment` | Instructor on a class | `class_session_id`, instructor user FK |

**CRITICAL — reservation user FKs:**
- `booked_on_behalf_of_user_id` = the **customer who owns/attends** the seat. Use this for "user's reservations / bookings / check-ins".
- `user_id` = who placed the booking (may be staff booking on behalf of someone).
- `broker_id` = staff who booked (when applicable).
- Guest bookings: `reserved_for_guest = true` with `guest_email` / `guest_name`.

**Reservation.status** (lowercase; some values contain SPACES — copy exactly):
`pending`, `check in`, `standard cancel`, `penalty cancel`, `graced cancel`,
`penalty no show`, `no fee no show`, `graced no show`, `removed`,
`class cancelled`, `penalty removed`

- Active / upcoming attendance: `status IN ('pending', 'check in')`
- reservation_type: `standard` | `waitlist` | `standby`

Join path — class sessions at a location:
`classsession` → `layout` → `classroom` → `location`

### Memberships & credits
Catalog types vs owned instances vs ledger transactions:

| Table | Meaning | Tips |
|---|---|---|
| `{s}.reservation_core_membership` | Membership product type (catalog) | Soft-deletable; has `name` directly (Payment base is **abstract** — no payment table) |
| `{s}.reservation_core_membershipinstance` | A user's membership | `user_id`, `membership_id` → membership, `status`, `start_datetime`, `end_datetime`, `fulfillment_partner_id` → partner |
| `{s}.reservation_core_membershiptransaction` | Interval (parent) or usage (child) | Has `membership_instance_id` (NOT `membership_id` / `user_id`). Parent: `parent_membership_transaction_id IS NULL` |
| `{s}.reservation_core_credit` | Credit pack type (catalog) | Soft-deletable; has `name` directly on this table |
| `{s}.reservation_core_credittransaction` | Pack (parent) or burn (child) | Parent: `parent_credit_transaction_id IS NULL`; `credit_id` → `reservation_core_credit.id`; `user_id` on this table; `remaining_credits_cache`, `expiration_datetime`, `is_expired`, `transaction_amount` (negative = use) |

**Important:** `Payment` is an abstract Django model. There is **no** `{s}.reservation_core_payment` table. Read pack/membership names from `{s}.reservation_core_credit.name` / `{s}.reservation_core_membership.name`.

**Membership vs credit ownership paths (do not mix them up):**
- Popular / owned **credits** → `{s}.reservation_core_credittransaction` (parent rows) via `credit_id` + `user_id`
- Popular / owned **memberships** → `{s}.reservation_core_membershipinstance` via `membership_id` + `user_id`
  (join transactions only when you need interval/usage ledger data, via `membership_instance_id`)

**MembershipInstance.status:**
`active`, `frozen`, `cancelled`, `terminated`, `payment_failure`, `ding_failure`,
`done`, `pending_customer_activation`, `pending_start_date`, `converted`

"Active memberships" usually:
`status IN ('active', 'pending_customer_activation', 'pending_start_date')`

Credit balance for a user → parent credit transactions only:
`parent_credit_transaction_id IS NULL` and sum/`remaining_credits_cache`.

### Commerce (orders / payments)
Sales hang off **Partner**, not Location directly.
`location.partner_id` ↔ `partner_partner.id` (OneToOne).
Orders use `originating_partner_id` for where sold.

| Table | Meaning | Tips |
|---|---|---|
| `{s}.partner_partner` | Fulfillment / sell-from partner | Bridge to location |
| `{s}.catalogue_product` | Sellable SKU | Oscar polymorphism (`structure` parent/child) |
| `{s}.order_order` | Checkout order | `user_id`, `originating_partner_id`, `status`, `date_placed`, `total_incl_tax`, `currency` |
| `{s}.order_line` | Line item | `order_id`, `product_id`, `partner_id`, quantities & prices |
| `{s}.payment_source` | Payment source on an order | `order_id`, amounts allocated/debited/refunded |
| `{s}.payment_transaction` | Debit/Refund/Capture/Void | `source_id`, `txn_type`, `amount`, `status` |

**Order.status** (Title Case strings):
`Pending`, `Completed`, `Deferred`, `Cancelled`, `Refunded`,
`Partially Refunded`, `Payment Failure`, `Disputed`, `Dispute Closed`, `Out of Stock`

Typical completed sales:
`status IN ('Completed', 'Partially Refunded')` (adjust if question includes refunds/failures).

Join path — sales by location:
`order_order` → `partner_partner` ON `originating_partner_id` → `reservation_core_location` ON `partner_id`

Note: Class attendance paid with credits/memberships may leave **no** order row; ledger is credit/membership transactions. Retail packs, memberships purchased, dings, etc. appear on orders.

### Reporting views
Prefer `{s}.view_*` tables when the question is analytics-shaped and the view exists in the live column list (e.g. `view_sales_by_location`, `view_reservations_report`). Otherwise build from core tables.

### Default metrics (use these — do NOT ask to clarify)
When the user says "most popular", "top", "busiest", etc. and a standard studio metric exists, **pick the default**, state it in `reasoning`, and write SQL:

| Phrase | Default metric |
|---|---|
| Most popular **credit pack** | Distinct users on **parent** `{s}.reservation_core_credittransaction` rows per `credit_id` |
| Users with the **most credits** / max credit balance | Rank **users** by `SUM(remaining_credits_cache)` on **parent** credit transactions; SELECT `full_name` (join marianauser), not bare `user_id` |
| Most popular **membership** | Distinct users on `{s}.reservation_core_membershipinstance` per `membership_id` (NOT membershiptransaction) |
| Top / most enrolled **classes** / "reservations with most users" | Count active reservations **per class session** (`class_session_id`), NOT per reservation id. One reservation ≈ one seat. |
| Most popular / top **product** | Completed order lines by quantity or distinct buyers |
| Busiest **location** / most classes | Class session count (non-cancelled) or reservation count |
| Top **instructor** | Class sessions taught or checked-in reservations |
| Top **customers** with no metric | Still ask — spend vs visits vs reservations are different businesses |

**Readable labels (privacy):** Prefer names over internal ids in the SELECT list.
Use ids only in JOIN/WHERE (including from session memory). Do not return
`user_id` / `reservation_id` / `class_session_id` / `class_session_type_id` unless
the user explicitly asks for ids.

Only return `sql: null` when **no** reasonable default exists (or required filters like email/id are missing).

### Gotchas (do not ignore)
1. Always schema-qualify: `{s}.table_name`.
2. Prefer `booked_on_behalf_of_user_id` for customer reservation history.
3. Reservation statuses include spaces (`'check in'`, `'standard cancel'`).
4. Filter `archived_at IS NULL` on users, class sessions, catalog types when asking about current/active data.
5. Class cancelled → `cancellation_datetime IS NOT NULL` (also often archived).
6. Location sales go through `partner`, not a direct order.location_id.
7. Parent vs child credit/membership transactions — balances live on parents.
8. Credit/Membership `name` is on `{s}.reservation_core_credit` / `{s}.reservation_core_membership`. Never join `reservation_core_payment` (that table does not exist — Payment is abstract).
9. `{s}.reservation_core_membershiptransaction` has `membership_instance_id` only — never `membership_id` or `user_id`. For membership popularity/ownership use `{s}.reservation_core_membershipinstance`.
10. A **reservation** is one booking/seat. "Most enrolled class" → group reservations by `class_session_id` and join class session type / location for **names**. Never `GROUP BY reservation.id` for enrollment counts.
11. Never invent columns; if the live column list conflicts with this glossary, trust the live column list for names, keep join semantics from this glossary.
""".strip()
