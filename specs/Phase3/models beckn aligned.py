# mysite/models/commerce.py

class Cart(models.Model):
    """Beckn: pre-order state. Maps to Beckn 'select' stage."""
    customer    = models.ForeignKey(CustomerProfile, on_delete=models.CASCADE)
    client      = models.ForeignKey(Client, on_delete=models.CASCADE)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
    # Beckn context fields for future network participation
    beckn_transaction_id = models.CharField(max_length=100, blank=True)


class CartItem(models.Model):
    cart        = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    item        = models.ForeignKey('catalogue.Item', on_delete=models.CASCADE)
    variant     = models.ForeignKey('catalogue.ItemVariant', null=True, blank=True,
                                    on_delete=models.SET_NULL)
    quantity    = models.PositiveIntegerField(default=1)
    # Snapshot price at time of adding to cart
    unit_price  = models.DecimalField(max_digits=12, decimal_places=2)
    currency    = models.CharField(max_length=3, default='INR')


class BecknFulfillment(models.Model):
    """
    Beckn Fulfillment object — how the order is delivered.
    Stored separately so one order can have multiple fulfillments
    (partial shipments, split delivery).
    """
    FULFILLMENT_TYPES = [
        ('delivery',    'Home Delivery'),
        ('self-pickup', 'Store Pickup'),
        ('digital',     'Digital / Download'),
    ]
    STATUS_CHOICES = [
        ('pending',         'Pending'),
        ('packed',          'Packed'),
        ('agent-assigned',  'Agent Assigned'),
        ('out-for-delivery','Out for Delivery'),
        ('delivered',       'Delivered'),
        ('cancelled',       'Cancelled'),
        ('returned',        'Returned'),
    ]
    fulfillment_id   = models.UUIDField(default=uuid.uuid4, unique=True)
    fulfillment_type = models.CharField(max_length=20, choices=FULFILLMENT_TYPES,
                                        default='delivery')
    status           = models.CharField(max_length=30, choices=STATUS_CHOICES,
                                        default='pending')
    # Beckn: start location (pickup from provider)
    start_location   = models.ForeignKey(
        'ClientLocation', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+'
    )
    # Beckn: end location (deliver to customer)
    end_address      = models.ForeignKey(
        'CustomerAddress', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+'
    )
    # Beckn: agent (delivery person) — optional
    agent_name       = models.CharField(max_length=100, blank=True)
    agent_phone      = models.CharField(max_length=20, blank=True)
    tracking_url     = models.URLField(blank=True)
    # Tracking enabled flag (Beckn: Fulfillment.tracking)
    tracking_enabled = models.BooleanField(default=False)
    estimated_delivery_at = models.DateTimeField(null=True, blank=True)
    delivered_at     = models.DateTimeField(null=True, blank=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Beckn Fulfillment'

    def to_beckn(self):
        return {
            "id": str(self.fulfillment_id),
            "type": self.fulfillment_type,
            "tracking": self.tracking_enabled,
            "state": {"descriptor": {"code": self.status}},
            "end": {
                "location": self.end_address.to_beckn_location()
                            if self.end_address else {},
                "contact": {},
            },
        }


class BecknBilling(models.Model):
    """
    Beckn Billing object — billing details for an order.
    Snapshot at time of order — not linked live to CustomerProfile.
    """
    # Snapshot of customer billing info at order time
    name         = models.CharField(max_length=200)
    email        = models.EmailField()
    phone        = models.CharField(max_length=20)
    # Beckn Address fields
    street       = models.CharField(max_length=200, blank=True)
    city         = models.CharField(max_length=100, blank=True)
    state        = models.CharField(max_length=100, blank=True)
    zip_code     = models.CharField(max_length=20, blank=True)
    country_code = models.CharField(max_length=2, default='IN')
    area_code    = models.CharField(max_length=20, blank=True)
    # GST / tax fields (India-specific, Beckn domain extension)
    tax_number   = models.CharField(max_length=20, blank=True,
                                    help_text="GSTIN for B2B orders")
    created_at   = models.DateTimeField(auto_now_add=True)

    def to_beckn(self):
        return {
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "address": {
                "street": self.street,
                "city": self.city,
                "state": self.state,
                "area_code": self.area_code or self.zip_code,
                "country": self.country_code,
            },
            "tax_number": self.tax_number,
        }


class BecknQuotation(models.Model):
    """
    Beckn Quotation — the price breakdown for an order.
    Stores the computed quote at time of init/confirm.
    """
    subtotal     = models.DecimalField(max_digits=12, decimal_places=2)
    tax          = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delivery_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount     = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total        = models.DecimalField(max_digits=12, decimal_places=2)
    currency     = models.CharField(max_length=3, default='INR')
    # Beckn: breakup as JSON for arbitrary line items
    breakup      = models.JSONField(default=list, blank=True,
                                    help_text='[{"title":"Item total","price":{"value":"999","currency":"INR"}}]')

    def to_beckn(self):
        return {
            "price": {
                "currency": self.currency,
                "value": str(self.total),
            },
            "breakup": self.breakup or [
                {"title": "Subtotal",  "price": {"value": str(self.subtotal),     "currency": self.currency}},
                {"title": "Tax",       "price": {"value": str(self.tax),          "currency": self.currency}},
                {"title": "Delivery",  "price": {"value": str(self.delivery_fee), "currency": self.currency}},
                {"title": "Discount",  "price": {"value": str(-self.discount),    "currency": self.currency}},
            ],
        }


class Order(models.Model):
    """
    Beckn Order — the central commerce object.
    Maps to Beckn's Order schema exactly.
    Lifecycle: cart → select → init → confirm → fulfillment → post-fulfillment
    """
    STATUS_CHOICES = [
        # Beckn order lifecycle states
        ('created',    'Created'),       # cart confirmed
        ('accepted',   'Accepted'),      # provider accepted
        ('in-progress','In Progress'),   # being fulfilled
        ('completed',  'Completed'),     # delivered
        ('cancelled',  'Cancelled'),
        ('returned',   'Returned'),
    ]
    PAYMENT_STATUS = [
        ('not-paid', 'Not Paid'),
        ('paid',     'Paid'),
        ('refunded', 'Refunded'),
    ]

    # Beckn: Order.id
    order_id     = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)

    # Beckn: Order.provider — our Client
    client       = models.ForeignKey(Client, on_delete=models.PROTECT,
                                     related_name='orders')

    # Beckn: Order consumer — our CustomerProfile
    customer     = models.ForeignKey(CustomerProfile, on_delete=models.PROTECT,
                                     related_name='orders')

    # Beckn: Order.state
    status       = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                    default='created', db_index=True)

    # Beckn: Order.fulfillments (one-to-one for Phase 3, M2M later)
    fulfillment  = models.OneToOneField(
        BecknFulfillment, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='order'
    )

    # Beckn: Order.billing
    billing      = models.OneToOneField(
        BecknBilling, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='order'
    )

    # Beckn: Order.quote
    quotation    = models.OneToOneField(
        BecknQuotation, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='order'
    )

    # Beckn: Order.payment
    payment_status    = models.CharField(max_length=20, choices=PAYMENT_STATUS,
                                         default='not-paid')
    payment_method    = models.CharField(max_length=50, blank=True)  # UPI, COD, Card
    payment_reference = models.CharField(max_length=200, blank=True) # transaction ID
    paid_at           = models.DateTimeField(null=True, blank=True)

    # Beckn: Order.cancellation_reason_id (for cancel flow)
    cancellation_reason = models.CharField(max_length=200, blank=True)

    # Timestamps
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    # Beckn: transaction_id for future network participation
    beckn_transaction_id = models.CharField(max_length=100, blank=True, db_index=True)

    class Meta:
        ordering     = ['-created_at']
        verbose_name = 'Order'
        indexes      = [
            models.Index(fields=['client', 'status']),
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['created_at']),
        ]

    def to_beckn(self):
        """Serialise to Beckn Order schema — ready for API adapter."""
        return {
            "id":          str(self.order_id),
            "state":       self.status,
            "provider":    {"id": self.client.client_id},
            "items":       [item.to_beckn() for item in self.items.all()],
            "billing":     self.billing.to_beckn() if self.billing else {},
            "fulfillments":[self.fulfillment.to_beckn()] if self.fulfillment else [],
            "quote":       self.quotation.to_beckn() if self.quotation else {},
            "payment": {
                "status": self.payment_status,
                "type":   self.payment_method,
            },
        }


class OrderItem(models.Model):
    """
    Beckn: Order.items — snapshot of item at time of order.
    Price is snapshotted so historical orders remain correct even if item price changes.
    """
    order       = models.ForeignKey(Order, on_delete=models.CASCADE,
                                    related_name='items')
    item        = models.ForeignKey('catalogue.Item', on_delete=models.PROTECT)
    variant     = models.ForeignKey('catalogue.ItemVariant', null=True, blank=True,
                                    on_delete=models.SET_NULL)
    quantity    = models.PositiveIntegerField(default=1)
    # Price snapshot
    unit_price  = models.DecimalField(max_digits=12, decimal_places=2)
    currency    = models.CharField(max_length=3, default='INR')
    # Beckn: per-item fulfillment state (for partial shipments)
    fulfillment_state = models.CharField(max_length=30, blank=True)

    def to_beckn(self):
        return {
            "id":       self.item.item_id,
            "quantity": {"count": self.quantity},
            "price":    {
                "currency": self.currency,
                "value":    str(self.unit_price),
            },
        }