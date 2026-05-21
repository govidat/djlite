A clean production-style approach is:

```text
project_root/
│
├── data/
│   ├── globalvalcat.csv
│   ├── globalval.csv
│   ├── taxonomy.csv
│   ├── themes.csv
│   └── products.csv
│
├── scripts/
│   ├── __init__.py
│   ├── load_globalvals.py
│   ├── load_taxonomies.py
│   ├── load_themes.py
│   └── load_products.py
│
├── manage.py
└── mysite/
```

This gives you:

* Excel-friendly master data maintenance
* Git-versioned scripts data
* Repeatable DEV setup
* Easy migration from SQLite → PostgreSQL
* Easy onboarding of demo datasets

---

# 1. Create CSV files

## `data/globalvalcat.csv`

```csv
globalvalcat_id
account
language
testcat
```

---

## `data/globalval.csv`

```csv
globalvalcat_id,key,keyval_en,keyval_hi,keyval_fr
account,logout,Logout,hiLogout,frLogout
account,signIn,SignIn,hiSignIn,frSignIn
account,signin_up,Signin/Signup,hiSignin/Signup,frSignin/Signup
account,signup,Signup,hiSignup,frSignup
language,en,English,hiEnglish,frEnglish
language,hi,Hindi,hiHindi,frHindi
language,fr,French,hiFrench,frFrench
testcat,testkey,test_en,test_hi,test_fr
```

You can:

* maintain in Excel
* export as CSV UTF-8
* commit into Git

This is exactly how many ERP systems maintain reference/master data.

---

# 2. Create scripts loader

## `scripts/load_globalvals.py`

```python
import csv
from pathlib import Path

from mysite.models import GlobalValCat, GlobalVal


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_globalvalcats():

    file_path = DATA_DIR / "globalvalcat.csv"

    with open(file_path, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)

        for row in reader:

            GlobalValCat.objects.update_or_create(
                globalvalcat_id=row["globalvalcat_id"]
            )

    print("Loaded GlobalValCat")


def load_globalvals():

    file_path = DATA_DIR / "globalval.csv"

    globalvalcats = {
        c.globalvalcat_id: c
        for c in GlobalValCat.objects.all()
    }

    with open(file_path, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)

        for row in reader:

            GlobalVal.objects.update_or_create(
                globalvalcat=globalvalcats[row["globalvalcat_id"]],
                key=row["key"],

                defaults={
                    "keyval_en": row.get("keyval_en", ""),
                    "keyval_hi": row.get("keyval_hi", ""),
                    "keyval_fr": row.get("keyval_fr", ""),
                }
            )

    print("Loaded GlobalVal")


def run():

    load_globalvalcats()
    load_globalvals()

    print("Done")
```

---

# 3. Run it

If using [django-extensions](https://django-extensions.readthedocs.io/en/latest/runscript.html?utm_source=chatgpt.com):

Install:

```bash
pip install django-extensions
```

Add to `INSTALLED_APPS`:

```python
'django_extensions',
```

Run:

```bash
python manage.py runscript load_globalvals
```

---

# 4. Recommended approach for ALL scripts data

Create separate loaders:

```text
scripts/
    load_globalvals.py
    load_taxonomies.py
    load_client.py
    load_themes.py
    load_catalogue.py
    load_demo_orders.py
```

This scales beautifully.

---

# 5. Better pattern for large datasets

For larger imports:

```python
bulk_create()
bulk_update()
```

instead of `update_or_create()`.

But for:

* DEV setup
* idempotent seeding
* repeatable demo data

`update_or_create()` is PERFECT.

---

# 6. Add a master orchestrator

## `scripts/load_all.py`

```python
from scripts.load_globalvals import run as load_globalvals
from scripts.load_taxonomies import run as load_taxonomies
from scripts.load_themes import run as load_themes


def run():

    load_globalvals()
    load_taxonomies()
    load_themes()

    print("All seed data loaded")
```

Run:

```bash
python manage.py runscript load_all
```

---

# 7. Why this is superior to fixtures

Django fixtures (`dumpdata/loaddata`) are not ideal for your ERP/catalogue system because:

| Fixtures              | CSV Seed Approach         |
| --------------------- | ------------------------- |
| difficult to edit     | business users can edit   |
| PK dependent          | natural-key driven        |
| huge JSON files       | modular                   |
| bad Git diffs         | clean Git diffs           |
| poor for multilingual | easy multilingual columns |
| poor for demos        | excellent for demos       |

For your architecture:

* catalogue
* themes
* multilingual
* taxonomies
* ERP reference masters

CSV + loaders is the better long-term strategy.

---

# 8. Future upgrade (important)

Later, you can evolve this into:

| Current          | Future           |
| ---------------- | ---------------- |
| CSV              | Excel            |
| csv.DictReader   | pandas           |
| local files      | S3               |
| manual runscript | Admin import UI  |
| sync all         | incremental sync |

Your future Phase 3B demand-planning stack already includes pandas and openpyxl, so eventually you can directly load `.xlsx`.

But right now:

* CSV
* small scripts loaders
* Git-controlled data

is the correct architecture.
