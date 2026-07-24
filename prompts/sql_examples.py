from __future__ import annotations

"""Few-shot SQL examples for Mariana Text-to-SQL prompts."""

def build_sql_examples_text(schema_name: str) -> str:
    s = schema_name
    return f"""
## Few-shot examples

### Example 1 — Active reservations for a user by email
Question: How many active reservations does jane@example.com have?
SQL:
```sql
SELECT COUNT(*) AS active_reservation_count
FROM {s}.reservation_core_reservation r
JOIN {s}.user_core_marianauser u
  ON u.id = r.booked_on_behalf_of_user_id
WHERE LOWER(u.email) = LOWER('jane@example.com')
  AND u.archived_at IS NULL
  AND r.status IN ('pending', 'check in');
```

### Example 2 — Upcoming class sessions at a location
Question: What classes are coming up at location id 42?
SQL:
```sql
SELECT
  cs.id,
  cs.start_datetime,
  loc.name AS location_name,
  loc.timezone
FROM {s}.reservation_core_classsession cs
JOIN {s}.reservation_core_layout lay ON lay.id = cs.layout_id
JOIN {s}.reservation_core_classroom room ON room.id = lay.classroom_id
JOIN {s}.reservation_core_location loc ON loc.id = room.location_id
WHERE loc.id = 42
  AND cs.cancellation_datetime IS NULL
  AND cs.archived_at IS NULL
  AND cs.start_datetime >= NOW()
ORDER BY cs.start_datetime
LIMIT 100;
```

### Example 3 — Active memberships for a user
Question: Which memberships are active for user id 1001?
SQL:
```sql
SELECT
  mi.id,
  mi.status,
  mi.start_datetime,
  mi.end_datetime,
  m.name AS membership_name
FROM {s}.reservation_core_membershipinstance mi
JOIN {s}.reservation_core_membership m ON m.id = mi.membership_id
WHERE mi.user_id = 1001
  AND mi.status IN ('active', 'pending_customer_activation', 'pending_start_date')
ORDER BY mi.start_datetime DESC;
```

### Example 4 — Completed sales by location (partner bridge)
Question: Total completed sales last month at location id 7?
SQL:
```sql
SELECT
  loc.id AS location_id,
  loc.name AS location_name,
  SUM(o.total_incl_tax) AS total_sales,
  o.currency
FROM {s}.order_order o
JOIN {s}.partner_partner p ON p.id = o.originating_partner_id
JOIN {s}.reservation_core_location loc ON loc.partner_id = p.id
WHERE loc.id = 7
  AND o.status IN ('Completed', 'Partially Refunded')
  AND o.date_placed >= date_trunc('month', NOW() - INTERVAL '1 month')
  AND o.date_placed < date_trunc('month', NOW())
GROUP BY loc.id, loc.name, o.currency;
```

### Example 5 — Remaining credit balance for a user
Question: How many credits does user id 1001 have left?
SQL:
```sql
SELECT
  COALESCE(SUM(ct.remaining_credits_cache), 0) AS remaining_credits
FROM {s}.reservation_core_credittransaction ct
WHERE ct.user_id = 1001
  AND ct.parent_credit_transaction_id IS NULL
  AND (ct.is_expired IS FALSE OR ct.is_expired IS NULL)
  AND (ct.expiration_datetime IS NULL OR ct.expiration_datetime > NOW());
```

### Example 6 — Users with more than one credit pack
Question: How many users have more than one credit pack?
SQL:
```sql
SELECT COUNT(*) AS user_count
FROM (
  SELECT ct.user_id
  FROM {s}.reservation_core_credittransaction ct
  WHERE ct.parent_credit_transaction_id IS NULL
  GROUP BY ct.user_id
  HAVING COUNT(*) > 1
) multi_pack_users;
```

### Example 7 — Most popular credit pack (use default metric — do NOT clarify)
Question: Which credit pack is the most popular amongst users?
Default: popularity = distinct users who own that pack (parent credit transactions).
Note: join `{s}.reservation_core_credit` for `name` — there is no `reservation_core_payment` table.
SQL:
```sql
SELECT
  ct.credit_id,
  c.name AS credit_pack_name,
  COUNT(DISTINCT ct.user_id) AS user_count,
  COUNT(*) AS pack_purchase_count
FROM {s}.reservation_core_credittransaction ct
JOIN {s}.reservation_core_credit c ON c.id = ct.credit_id
WHERE ct.parent_credit_transaction_id IS NULL
  AND c.archived_at IS NULL
GROUP BY ct.credit_id, c.name
ORDER BY user_count DESC, pack_purchase_count DESC
LIMIT 10;
```

### Example 8 — Most popular membership (use membershipinstance — do NOT use membershiptransaction.membership_id)
Question: Which membership is the most popular amongst users?
Default: popularity = distinct users with a membership instance of that type.
Note: `{s}.reservation_core_membershiptransaction` has `membership_instance_id`, NOT `membership_id` or `user_id`.
SQL:
```sql
SELECT
  mi.membership_id,
  m.name AS membership_name,
  COUNT(DISTINCT mi.user_id) AS user_count,
  COUNT(*) AS instance_count
FROM {s}.reservation_core_membershipinstance mi
JOIN {s}.reservation_core_membership m ON m.id = mi.membership_id
WHERE m.archived_at IS NULL
GROUP BY mi.membership_id, m.name
ORDER BY user_count DESC, instance_count DESC
LIMIT 10;
```

### Example 9 — Top enrolled class sessions (NOT reservations — one reservation = one seat)
Question: Names of top 10 reservations with most users enrolled in them?
Interpretation: user means class sessions with the most active enrollments. Return class **names**, not bare ids.
SQL:
```sql
SELECT
  cst.name AS class_name,
  loc.name AS location_name,
  cs.start_datetime,
  COUNT(*) AS enrolled_users
FROM {s}.reservation_core_reservation r
JOIN {s}.reservation_core_classsession cs ON cs.id = r.class_session_id
JOIN {s}.reservation_core_classsessiontype cst ON cst.id = cs.class_session_type_id
JOIN {s}.reservation_core_layout lay ON lay.id = cs.layout_id
JOIN {s}.reservation_core_classroom room ON room.id = lay.classroom_id
JOIN {s}.reservation_core_location loc ON loc.id = room.location_id
WHERE r.status IN ('pending', 'check in')
  AND cs.cancellation_datetime IS NULL
  AND cs.archived_at IS NULL
GROUP BY cst.name, loc.name, cs.start_datetime, cs.id
ORDER BY enrolled_users DESC, cs.start_datetime DESC
LIMIT 10;
```

### Example 10 — Booking / reservation details (names + datetime, not ids)
Question: What booking is that? / when is that upcoming reservation?
SQL:
```sql
SELECT
  cst.name AS class_name,
  loc.name AS location_name,
  cs.start_datetime,
  cs.end_datetime,
  r.status
FROM {s}.reservation_core_reservation r
JOIN {s}.reservation_core_classsession cs ON cs.id = r.class_session_id
JOIN {s}.reservation_core_classsessiontype cst ON cst.id = cs.class_session_type_id
JOIN {s}.reservation_core_layout lay ON lay.id = cs.layout_id
JOIN {s}.reservation_core_classroom room ON room.id = lay.classroom_id
JOIN {s}.reservation_core_location loc ON loc.id = room.location_id
WHERE r.booked_on_behalf_of_user_id = 35000
  AND r.status IN ('pending', 'check in')
  AND cs.start_datetime >= NOW()
ORDER BY cs.start_datetime
LIMIT 10;
```

### Example 11 — User with most credits (include name, not only user_id)
Question: Which user has the most credits?
SQL:
```sql
SELECT
  u.full_name,
  u.email,
  SUM(ct.remaining_credits_cache) AS total_credits
FROM {s}.reservation_core_credittransaction ct
JOIN {s}.user_core_marianauser u ON u.id = ct.user_id
WHERE ct.parent_credit_transaction_id IS NULL
  AND u.archived_at IS NULL
GROUP BY u.id, u.full_name, u.email
ORDER BY total_credits DESC
LIMIT 1;
```

### Example 12 — Truly ambiguous (clarify only when no default exists)
Question: Who are the top customers?
Response JSON:
{{"reasoning": "No default: top by spend vs visits vs reservations are different. Ask which metric and time range.", "sql": null, "error": "Please clarify the metric (e.g. total spend, class visits) and time range."}}
""".strip()
