from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group, User


class GoAdminSite(admin.AdminSite):
    site_header = "Go Admin"
    site_title = "Go Admin"
    index_title = "Go Admin Home"
    site_url = "/"
    enable_nav_sidebar = False


admin_site = GoAdminSite()
admin_site.register(Group, GroupAdmin)
admin_site.register(User, UserAdmin)
