# Phase 3 — eCommerce Project Plan

## Summary

Phase 3 delivers a full commerce lifecycle on top of the existing multi-tenant CMS and item catalogue. The design priority is correctness of the business rules (pricing, delivery split, document promotion) before UI polish.

**Stack additions:** `djmoney`, `celery`, `redis`, `djangorestframework`, `django-filter`, `babel`, Razorpay / Stripe SDKs.

---

## Guiding Architecture Decisions

| Decision | Rationale |
|----------|-----------|
| Document promotion via `promote_document()` service | Single code path for all flow variants (Inquiry→Quotation→Order, Quotation→Order, Order direct); avoids duplicated copy logic |
| `MoneyField` (djmoney) on all monetary columns | Prevents float precision bugs; stores currency alongside amount in DB |
| Pricing engine as a separate `utils/pricing_engine.py` | Testable in isolation; callable from both synchronous views and Celery tasks |
| `PricingResultLine` stored per document | Full audit trail; required for Beckn `Quotation.breakup` serialisation |
| Delivery split resolved at service layer, not model | Business rules (customer override → location flag → client flag) belong in a service function, not a model method |
| Picking/Packing/Transportation are optional and feature-flagged | Many clients will not need warehouse operations; avoids mandatory complexity |
| `InvoiceDelivery` M2M through table | Supports both 1:1 and many-Deliveries-to-one-Invoice patterns |
| Beckn `to_beckn()` on each model | Phase 4 ONDC integration becomes a routing / signature exercise, not a model redesign |

---

## Sprint Plan

### Sprint 3.0 — Foundation and Prerequisites
**Estimated effort:** 3–4 days
**Deliverable:** All prerequisite model changes, flag fields, and infrastructure wired; 0 migration errors.

Tasks:
- Redis production cache + Celery worker wiring
- `requirements.txt` additions
- `Client` currency fields + `ClientCurrencyRule` model
- `ClientLocation` Phase 3 boolean flags
- `CustomerAddress.address_type` enum extension + Beckn geo fields
- `ClientFeatureControl` Phase 3 feature keys
- Migrations + `manage.py check`

Dependencies: None (can begin immediately).

---

### Sprint 3.1 — Pricing Engine
**Estimated effort:** 5–7 days
**Deliverable:** Pricing procedure can be configured in Admin and executed against a document context, producing auditable `PricingResultLine` records.

Tasks:
- All pricing models (`PricingProcedure`, `PricingStep`, `ConditionType`, `ConditionAccessSequence`, `ConditionRecord`, `ConditionScale`, `PricingResultLine`)
- `execute_pricing_procedure()` engine in `utils/pricing_engine.py`
- Signal: copy default procedure on Client create
- Pricing-specific cache keys + invalidation
- Admin: `PricingProcedureAdmin`, `ConditionRecordAdmin`
- Unit tests: all condition calc types (absolute, % of derived), slab/scale, header apportionment, statistical exclusion, access sequence fallthrough

Dependencies: Sprint 3.0.

---

### Sprint 3.2 — Inquiry and Quotation
**Estimated effort:** 4–5 days
**Deliverable:** Customer can submit an Inquiry; staff converts to Quotation with pricing applied; currency dropdown works.

Tasks:
- `Inquiry`, `InquiryLine`, `Quotation`, `QuotationLine` models
- `promote_document()` service (Inquiry → Quotation path)
- Currency dropdown on header (populated from `Client.allowed_currencies`)
- `ClientCurrencyRule` resolution on document creation
- Views + templates (DaisyUI): inquiry form, quotation form, status flow
- HTMX inline line editing on Quotation
- Admin
- Unit tests: promotion copies lines; pricing applied; currency default/override

Dependencies: Sprint 3.1.

---

### Sprint 3.3 — Order
**Estimated effort:** 5–6 days
**Deliverable:** Orders can be created from Quotation or directly; Cart can be promoted to Order; OrderLine `open_qty` tracking works; short-close flag respected.

Tasks:
- `Order`, `OrderLine` models (with `open_qty`, `closed_qty`, `ship_to_address` override, `bill_to_address` override)
- `Cart`, `CartItem` (session + DB); `Cart.promote_to_order()`
- `promote_document()` extended for Quotation → Order
- `open_qty` decrement on DeliveryLine save (signal)
- Short-close: `open_qty=0` + `OrderLine.status=SHORT_CLOSED` on flag
- Customer-facing: cart view, checkout, order history
- Views + templates
- Admin
- Unit tests: all entry points; open_qty tracking; short-close

Dependencies: Sprint 3.2.

---

### Sprint 3.4 — Delivery
**Estimated effort:** 5–7 days
**Deliverable:** Deliveries can be planned and created from Orders with correct split and partial-shipment behaviour.

Tasks:
- `Delivery`, `DeliveryLine` models
- `plan_deliveries(order)` service: reads split rules (customer override → ClientLocation → Client); groups lines by `ship_to_address` + dispatch location
- `create_delivery_from_plan()` service
- `create_backorder(delivery)` service (partial shipment)
- Admin: `DeliveryAdmin`; dispatch location filter
- Unit tests:
  - Split allowed → multiple Deliveries created
  - Split disallowed at location → error raised
  - Split disallowed at client → error raised
  - Customer override takes priority
  - Partial: backorder Delivery created for remaining `open_qty`
  - Partial disallowed → short-close applied
  - Multi-location dispatch enabled → lines from different locations

Dependencies: Sprint 3.3.

---

### Sprint 3.5 — Picking and Packing (Optional)
**Estimated effort:** 3–4 days
**Deliverable:** Warehouse staff can process picking and packing tasks; feature-flagged so clients without warehouse ops are unaffected.

Tasks:
- `Picking`, `PickingLine`, `Packing`, `PackingLine` models
- Feature gate: `ClientFeatureControl('picking')` / `('packing')` checked in status flow
- Admin + basic staff views
- Unit tests: feature disabled → step skipped in status machine

Dependencies: Sprint 3.4.

---

### Sprint 3.6 — Transportation (Optional)
**Estimated effort:** 2–3 days
**Deliverable:** Multiple Deliveries can be consolidated onto a single Transportation record; Beckn serialisation works.

Tasks:
- `Transportation`, `TransportationDelivery` models
- Constraint: Delivery → at most one Transportation
- Feature gate: `ClientFeatureControl('transportation')`
- Admin action: select Deliveries → create Transportation
- `to_beckn()` → `BecknFulfillment`
- Unit tests: duplicate assignment → error

Dependencies: Sprint 3.4.

---

### Sprint 3.7 — Billing / Invoice
**Estimated effort:** 4–5 days
**Deliverable:** Client staff can generate invoices consolidating one or more Deliveries; PDF is generated asynchronously.

Tasks:
- `Invoice`, `InvoiceLine`, `InvoiceDelivery` models
- Constraint: Delivery → at most one Invoice
- Consolidation feature gate (`ClientFeatureControl('billing_consolidation')`)
- Admin action: select Deliveries → create Invoice
- PDF Celery task (`generate_invoice_pdf`) — `weasyprint` or `reportlab`
- `to_beckn()` → `BecknBilling`
- Unit tests: multi-Delivery; single-Delivery fallback; PDF task enqueued on ISSUED

Dependencies: Sprint 3.4.

---

### Sprint 3.8 — Payment
**Estimated effort:** 4–5 days
**Deliverable:** Customers can pay via Razorpay (INR) or Stripe (multi-currency); order confirmation email sent on payment.

Tasks:
- `Payment`, `PaymentAllocation` models
- Razorpay SDK integration + webhook handler (`razorpay_webhook`)
- Stripe SDK integration + webhook handler (`stripe_webhook`)
- `PaymentAllocation` — partial payment support
- Celery tasks: `send_order_confirmation`, `send_quotation_email`
- Email templates (DaisyUI-styled)
- `to_beckn()` → `BecknPayment`
- Unit tests: full payment; partial payment; over-payment; webhook idempotency

Dependencies: Sprint 3.7.

---

### Sprint 3.9 — Returns and Refunds
**Estimated effort:** 3–4 days
**Deliverable:** Customer can request return; staff processes; refund allocated against original payment.

Tasks:
- `Return`, `ReturnLine`, `Refund` models
- Return → `open_qty` restoration (or write-off)
- Refund → gateway reversal call (Razorpay / Stripe)
- Customer-facing return request form
- Admin
- Unit tests: return restores open_qty; refund allocated against original payment

Dependencies: Sprint 3.8.

---

### Sprint 3.10 — REST API Layer
**Estimated effort:** 3–4 days
**Deliverable:** Commerce documents are accessible via a versioned REST API; `?format=beckn` returns Beckn schema-compliant JSON.

Tasks:
- DRF router under `mysite/api/`
- ViewSets: Inquiry, Quotation, Order, Delivery, Invoice
- DRF Token Auth
- `?format=beckn` → `to_beckn()` serialiser branch
- OpenAPI schema via `drf-spectacular`

Dependencies: Sprint 3.3, 3.7.

---

### Sprint 3.11 — Client Dashboard and Reporting
**Estimated effort:** 3–4 days
**Deliverable:** Client staff can manage and monitor orders, deliveries, and invoices from a single dashboard.

Tasks:
- Order management: filter by status, date, customer, location
- Delivery performance summary
- Revenue report (confirmed + paid orders per period)
- `ClientGroupPermission` modules activated: `inquiry`, `quotation`, `cart`, `order`, `delivery`, `shipment`, `billing`, `payment`
- PostgreSQL full-text search on Item name / description (deferred from Phase 2)

Dependencies: Sprint 3.9.

---

### Sprint 3.12 — Production Hardening
**Estimated effort:** 3–4 days
**Deliverable:** Phase 3 is deployed, tested end-to-end, and load-tested.

Tasks:
- Deploy PostgreSQL + Redis + Celery worker to Railway / Render (`Procfile` update)
- `ACCOUNT_EMAIL_VERIFICATION = "mandatory"` in production settings
- Wire `django-guardian` permissions to all commerce views and API endpoints
- End-to-end test: `Inquiry → Quotation → Order → Delivery → Invoice → Payment`
- End-to-end test: `Order → split Delivery → consolidated Invoice`
- End-to-end test: partial shipment → back-order Delivery
- End-to-end test: Returns + Refund
- Load test: 500 concurrent checkout sessions
- `EXPLAIN ANALYZE` on pricing engine queries; add indexes as needed

Dependencies: All prior sprints.

---

## Sprint Dependencies (DAG)

```
3.0 (Foundation)
  └─▶ 3.1 (Pricing Engine)
        └─▶ 3.2 (Inquiry / Quotation)
              └─▶ 3.3 (Order)
                    └─▶ 3.4 (Delivery)
                          ├─▶ 3.5 (Picking / Packing)  ─────────┐
                          ├─▶ 3.6 (Transportation)     ─────────┤
                          └─▶ 3.7 (Invoice / Billing)            │
                                └─▶ 3.8 (Payment)                │
                                      └─▶ 3.9 (Returns)          │
                                                                  │
3.3 + 3.7 ─▶ 3.10 (REST API)                                     │
3.9 ──────▶ 3.11 (Dashboard)                                      │
All ───────▶ 3.12 (Production Hardening) ◀────────────────────────┘
```

---

## Estimated Total Effort

| Sprint | Effort |
|--------|--------|
| 3.0 Foundation | 3–4 days |
| 3.1 Pricing Engine | 5–7 days |
| 3.2 Inquiry / Quotation | 4–5 days |
| 3.3 Order | 5–6 days |
| 3.4 Delivery | 5–7 days |
| 3.5 Picking / Packing | 3–4 days |
| 3.6 Transportation | 2–3 days |
| 3.7 Billing / Invoice | 4–5 days |
| 3.8 Payment | 4–5 days |
| 3.9 Returns / Refunds | 3–4 days |
| 3.10 REST API | 3–4 days |
| 3.11 Dashboard | 3–4 days |
| 3.12 Production Hardening | 3–4 days |
| **Total** | **47–62 days (solo developer)** |

Sprints 3.5, 3.6, and 3.7/3.8/3.9 can run in parallel once Sprint 3.4 is complete if a second developer is available.

---

## Key Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Pricing engine complexity slips schedule | Build and test engine in complete isolation (Sprint 3.1) before any document model depends on it |
| Delivery split rules have edge cases | Exhaustive unit tests in Sprint 3.4; explicit flag priority documented and codified in service layer |
| Payment gateway webhook reliability | Idempotency key on webhook handlers; retry logic in Celery tasks |
| Multi-currency rounding errors | Use `djmoney` + `decimal.ROUND_HALF_UP` consistently; never use float for monetary arithmetic |
| `ClientFeatureControl` flag proliferation | Define all Phase 3 flags in Sprint 3.0; document in tech-stack.md; use a single utility `feature_enabled(client, location, feature_key)` helper |
| Beckn schema drift | Pin Beckn spec version; `to_beckn()` methods tested with snapshot tests against Beckn schema JSON |

---

## Definition of Done (Phase 3)

- [ ] All 12 sprints merged and deployed to production PaaS
- [ ] Full commerce flow (Inquiry → Payment) works end-to-end for at least one real client
- [ ] Delivery split, partial shipment, and back-order all work per flag configuration
- [ ] Pricing engine produces auditable `PricingResultLine` records matching manual calculation
- [ ] Invoice PDF generated and emailed to Customer on Invoice ISSUED
- [ ] Order confirmation email sent to Customer on Payment confirmed
- [ ] REST API returns valid Beckn v2.0 JSON on `?format=beckn`
- [ ] All commerce views and API endpoints enforce `django-guardian` permissions
- [ ] 0 open migration errors; `manage.py check` clean
- [ ] Load test passes: 500 concurrent checkout sessions without degradation