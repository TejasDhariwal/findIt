from django.contrib import admin
from .models import Account, Facility, FacilityAvailability, RentalRequest


admin.site.register(Account)
admin.site.register(Facility)
admin.site.register(FacilityAvailability)
admin.site.register(RentalRequest)