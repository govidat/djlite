from django.db import models
from django.core.validators import MaxValueValidator
import json







# Create your models here

#Common component structrue:




"""
Client
  └── ClientGroup  (e.g. "Warehouse Staff", "Billing Team", "Store A Managers")
        ├── module permissions  (what they can do)
        ├── location scope      (which stores/branches)
        └── Users               (many users assigned to one group)

Django User (auth identity — ONE per real person)
    ↓
    ├── ClientUserProfile (Type 1 — staff, ONE client only)
    │       user = OneToOneField(User)
    │       client = FK(Client)
    │       → john is acme's editor, cannot be beta's editor
    │
    └── CustomerProfile (Type 2 — can have MANY per user)
            user = ForeignKey(User)   ← NOT OneToOne
            client = FK(Client)
            → john can be acme's customer AND beta's customer
            → same Django User, different CustomerProfile per client      
        
"""

# models.py
