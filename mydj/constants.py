# These are Project Level Constants that can be pulled into settings.py and from there into any views

# THIS IS DROPPED. THIS IS MAINTAINED AT CLIENT LEVEL AND PULLED DDIRECTLY INTO VIEWS
ZPC_NAVBAR_ITEMS = [
    {"id": "id1", "text": {"en": "Item1-en", "fr": "Item1-fr" }, "url": "url1"},
    {"id": "id2", "text": {"en": "Item2-en", "fr": "Item2-fr" }, "url": "url2"},
    {"id": "id3", "text": {"en": "Item3-en", "fr": "Item3-fr" }, "url": "url3"},
    {"id": "id4", "text": {"en": "Item41-en", "fr": "Item41-fr" }, "url": "url41"},
    {"id": "id5", "text": {"en": "Item42-en", "fr": "Item42-fr" }, "url": "url42"},
    {"id": "id6", "text": {"en": "Item421-en", "fr": "Item421-fr" }, "url": "url421"},                        
    {'id': 'home', 'text': {'en': 'Home', 'fr': 'frHome', 'hi': 'hiHome'}},
    {'id': 'about', 'text': {'en': 'About', 'fr': 'frAbout', 'hi': 'hiAbout'}},
    {'id': 'products', 'text': {'en': 'Products', 'fr': 'frProducts', 'hi': 'hiProducts'}},
    {'id': 'projects', 'text': {'en': 'Projects', 'fr': 'frProjects', 'hi': 'hiProjects'}},
    {'id': 'features', 'text': {'en': 'Features', 'fr': 'frFeatures', 'hi': 'hiFeatures'}},
    {'id': 'company', 'text': {'en': 'Company', 'fr': 'frCompany', 'hi': 'hiCompany'}},
    {'id': 'contact', 'text': {'en': 'Contact', 'fr': 'frContact', 'hi': 'hiContact'}},
    {'id': 'tob', 'text': {'en': 'ToB', 'fr': 'frToB', 'hi': 'hiToB'}},
    {'id': 'team', 'text': {'en': 'Team', 'fr': 'frTeam', 'hi': 'hiTeam'}},
    {'id': 'clients', 'text': {'en': 'Clients', 'fr': 'frClients', 'hi': 'hiClients'}},
    {'id': 'pricing', 'text': {'en': 'Pricing', 'fr': 'frPricing', 'hi': 'hiPricing'}},

    ]   


PC_THEMES = [
    {"id": "light",     "order": 3, "text": {"en": "Light", "fr": "Light-fr" }},
    {"id": "dark",      "order": 2, "text": {"en": "Dark", "fr": "Dark-fr" }},
    {"id": "aqua",      "order": 1, "text": {"en": "Aqua", "fr": "Aqua-fr"}},
    {"id": "mytheme",   "order": 1, "text": {"en": "MyTheme", "fr": "MyTheme-fr"}},                
]

PC_LANGUAGES = [
    {"id": "en", "order": 3, "text": {"en": "English", "fr": "Anglais" }},
    {"id": "fr", "order": 2, "text": {"en": "French", "fr": "Francais" }},
#    {"code": "hi", "order": 1, "text": {"en": "Hindi", "fr": "Fr-Hindi" }},            
]

PC_ERROR_CODES = [
    {"code": "Z001", "text": {"en": "Value is not maintained"}},
    {"code": "Z002", "text": {"en": "Input is not a Dictionary Object"}},
]

