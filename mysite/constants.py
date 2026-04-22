# These are Project Level Constants that can be pulled into settings.py and from there into any views


"""

This is achieved through globalval models

DB: GlobalValCat + GlobalVal (keyval_en, keyval_hi, keyval_fr, keyval_ta)
        ↓  single query via .values()
Cache: nested dict { cat: { key: { lang: val } } }   TTL 1hr
        ↓  auto-busted on post_save / post_delete
Context processor: resolves to active language → gv + gvt
        ↓
Template: {{ gv.accounts.logout }}  or  {{ gvt.accounts.logout.hi }}

globalval = {
"accounts": {
    "logout": {"en": "Logout", "fr": "frLogout", "hi": "hiLogout"},
    "signin_up": {"en": "SignIn/SignUp", "fr": "frSignIn/SignUp", "hi": "hiSignIn/SignUp"},
    "signin": {"en": "SignIn", "fr": "frSignIn", "hi": "hiSignIn"},
    "signup": {"en": "SignUp", "fr": "frSignUp", "hi": "hiSignUp"},
},
}
"""