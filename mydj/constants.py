# These are Project Level Constants that can be pulled into settings.py and from there into any views

PC_NAVBAR_ITEMS = [
    {"level": 0, "parent_id": "", "id": "id1", "order": 3, "is_parent": False, "text": {"en": "Item1-en", "fr": "Item1-fr" }, "url": "url1"},
    {"level": 0, "parent_id": "", "id": "id2", "order": 2, "is_parent": False, "text": {"en": "Item2-en", "fr": "Item2-fr" }, "url": "url2"},
    {"level": 0, "parent_id": "", "id": "id3", "order": 1, "is_parent": True,  "text": {"en": "Item3-en", "fr": "Item3-fr" }, "url": "url3"},
    {"level": 1, "parent_id": "id3", "id": "id4", "order": 2, "is_parent": False, "text": {"en": "Item41-en", "fr": "Item41-fr" }, "url": "url41"},
    {"level": 1, "parent_id": "id3", "id": "id5", "order": 1, "is_parent": True, "text": {"en": "Item42-en", "fr": "Item42-fr" }, "url": "url42"},
    {"level": 2, "parent_id": "id5", "id": "id6", "order": 1, "is_parent": False, "text": {"en": "Item421-en", "fr": "Item421-fr" }, "url": "url421"},                        
    ]   

PC_THEMES = [
    {"id": "id1", "order": 3, "value": "light", "text": {"en": "Light", "fr": "Light-fr" }},
    {"id": "id2", "order": 2, "value": "dark",  "text": {"en": "Dark", "fr": "Dark-fr" }},
    {"id": "id3", "order": 1, "value": "aqua",  "text": {"en": "Aqua", "fr": "Aqua-fr"}},
    {"id": "id4", "order": 1, "value": "mytheme",  "text": {"en": "MyTheme", "fr": "MyTheme-fr"}},                
]

PC_LANGUAGES = [
    {"code": "en", "order": 3, "text": {"en": "English", "fr": "Anglais" }},
    {"code": "fr", "order": 2, "text": {"en": "French", "fr": "Francais" }},
#    {"code": "hi", "order": 1, "text": {"en": "Hindi", "fr": "Fr-Hindi" }},            
]

MY_ERROR_CODES = [
    {"code": "Z001", "text": {"en": "Value is not maintained"}},
    {"code": "Z002", "text": {"en": "Input is not a Dictionary Object"}},
]