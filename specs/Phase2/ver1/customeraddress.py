# In mysite/models/users.py — CustomerAddress additions
class CustomerAddress(models.Model):
    customer     = models.ForeignKey(CustomerProfile, ...)
    # existing fields stay unchanged
    street       = models.CharField(max_length=200)
    city         = models.CharField(max_length=100)
    state        = models.CharField(max_length=100, blank=True)  # add
    zip_code     = models.CharField(max_length=20)
    country_code = models.CharField(max_length=2)
    is_default   = models.BooleanField(default=False)
    # Beckn alignment additions (all optional — no breaking change)
    gps          = models.CharField(
        max_length=50, blank=True,
        help_text="Beckn Location.gps — 'lat,long' e.g. '12.9698,77.7500'"
    )
    area_code    = models.CharField(
        max_length=20, blank=True,
        help_text="Beckn Location.area_code — postal/delivery zone code"
    )
    address_type = models.CharField(
        max_length=20, blank=True,
        choices=[('home','Home'),('work','Work'),('other','Other')],
        help_text="Beckn Location.address type"
    )
    landmark     = models.CharField(max_length=200, blank=True)

    def to_beckn_location(self):
        """Serialise to Beckn Location schema."""
        return {
            "gps": self.gps or "",
            "address": {
                "door": "",
                "name": self.landmark,
                "building": "",
                "street": self.street,
                "locality": "",
                "ward": "",
                "city": self.city,
                "state": self.state,
                "country": self.country_code,
                "area_code": self.area_code or self.zip_code,
            }
        }