from __future__ import annotations

"""Static schema column dump for evals (no live Postgres required).

Columns are a realistic subset of Mariana tenant tables so the model can
generate joins without hitting information_schema.
"""


SCHEMA_NAME = "cousteau"

# table -> list of "col (type)" fragments
_FIXTURE_COLUMNS: dict[str, list[str]] = {
    "user_core_marianauser": [
        "id (bigint)",
        "email (character varying)",
        "first_name (character varying)",
        "last_name (character varying)",
        "full_name (character varying)",
        "home_location_id (bigint)",
        "is_active (boolean)",
        "archived_at (timestamp with time zone)",
    ],
    "reservation_core_site": ["id (bigint)", "name (character varying)"],
    "reservation_core_region": [
        "id (bigint)",
        "name (character varying)",
        "site_id (bigint)",
    ],
    "reservation_core_location": [
        "id (bigint)",
        "name (character varying)",
        "region_id (bigint)",
        "site_id (bigint)",
        "timezone (character varying)",
        "status (character varying)",
        "partner_id (integer)",
        "archived_at (timestamp with time zone)",
    ],
    "reservation_core_classroom": [
        "id (bigint)",
        "location_id (bigint)",
        "name (character varying)",
    ],
    "reservation_core_layout": [
        "id (bigint)",
        "classroom_id (bigint)",
        "name (character varying)",
    ],
    "reservation_core_classsession": [
        "id (bigint)",
        "layout_id (bigint)",
        "class_session_type_id (bigint)",
        "start_datetime (timestamp with time zone)",
        "end_datetime (timestamp with time zone)",
        "cancellation_datetime (timestamp with time zone)",
        "archived_at (timestamp with time zone)",
        "public (boolean)",
    ],
    "reservation_core_classsessiontype": [
        "id (bigint)",
        "name (character varying)",
    ],
    "reservation_core_reservation": [
        "id (bigint)",
        "user_id (integer)",
        "booked_on_behalf_of_user_id (integer)",
        "broker_id (integer)",
        "class_session_id (bigint)",
        "status (character varying)",
        "reservation_type (character varying)",
        "creation_date (timestamp with time zone)",
        "reserved_for_guest (boolean)",
        "guest_email (character varying)",
    ],
    "reservation_core_instructortoclasssessionassignment": [
        "id (bigint)",
        "class_session_id (bigint)",
        "instructor_id (integer)",
    ],
    "reservation_core_credit": [
        "id (bigint)",
        "name (character varying)",
        "is_active (boolean)",
        "archived_at (timestamp with time zone)",
    ],
    "reservation_core_credittransaction": [
        "id (bigint)",
        "user_id (integer)",
        "credit_id (bigint)",
        "parent_credit_transaction_id (bigint)",
        "remaining_credits_cache (integer)",
        "expiration_datetime (timestamp with time zone)",
        "is_expired (boolean)",
        "transaction_amount (integer)",
    ],
    "reservation_core_membership": [
        "id (bigint)",
        "name (character varying)",
        "is_active (boolean)",
        "archived_at (timestamp with time zone)",
    ],
    "reservation_core_membershipinstance": [
        "id (bigint)",
        "user_id (integer)",
        "membership_id (bigint)",
        "status (character varying)",
        "start_datetime (timestamp with time zone)",
        "end_datetime (timestamp with time zone)",
        "fulfillment_partner_id (integer)",
    ],
    "reservation_core_membershiptransaction": [
        "id (bigint)",
        "membership_instance_id (bigint)",
        "parent_membership_transaction_id (bigint)",
        "payment_interval_start_date (timestamp with time zone)",
        "payment_interval_end_date (timestamp with time zone)",
    ],
    "partner_partner": [
        "id (integer)",
        "name (character varying)",
        "partner_type (character varying)",
    ],
    "catalogue_product": [
        "id (integer)",
        "title (character varying)",
        "structure (character varying)",
    ],
    "order_order": [
        "id (integer)",
        "number (character varying)",
        "user_id (integer)",
        "originating_partner_id (integer)",
        "status (character varying)",
        "currency (character varying)",
        "total_incl_tax (numeric)",
        "date_placed (timestamp with time zone)",
    ],
    "order_line": [
        "id (integer)",
        "order_id (integer)",
        "product_id (integer)",
        "partner_id (integer)",
        "quantity (integer)",
        "line_price_incl_tax (numeric)",
    ],
    "payment_source": [
        "id (integer)",
        "order_id (integer)",
        "source_type_id (integer)",
        "amount_debited (numeric)",
        "currency (character varying)",
    ],
    "payment_transaction": [
        "id (integer)",
        "source_id (integer)",
        "txn_type (character varying)",
        "amount (numeric)",
        "status (character varying)",
    ],
}


def build_fixture_schema_context(schema_name: str = SCHEMA_NAME) -> str:
    lines = []
    for table, cols in _FIXTURE_COLUMNS.items():
        lines.append(f"- {schema_name}.{table}: {', '.join(cols)}")
    return "\n".join(lines)
