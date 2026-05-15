# models/admin_proxies.py

from mysite.models import Client


#class ClientCore(Client):
#    class Meta:
#        proxy = True
#        verbose_name = "00-03A Client Core"
#        verbose_name_plural = "00-03A Client Core"


class ClientContentStructured(Client):
    class Meta:
        proxy = True
        verbose_name = "00-03B Client Content Structured"
        verbose_name_plural = "00-03B Client Content Structured"

class ClientContentHtml(Client):
    class Meta:
        proxy = True
        verbose_name = "00-03C Client Content Html"
        verbose_name_plural = "00-03C Client Content Html"

class ClientTemplatewrapper(Client):
    class Meta:
        proxy = True
        verbose_name = "00-03D Client Template"
        verbose_name_plural = "00-03D Client Template"        

class ClientStaff(Client):
    class Meta:
        proxy = True
        verbose_name = "00-03E Client Staff"
        verbose_name_plural = "00-03E Client Staff"


