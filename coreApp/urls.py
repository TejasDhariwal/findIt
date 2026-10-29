from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("find/", views.find, name="find"),
    path("find/results/", views.search_results, name="search_results"),
    path("institutions/", views.institution_facilities, name="institution_facilities"),
    path("facilities/add/", views.add_facility, name="add_facility"),
    path(
        "facilities/<int:facility_id>/availability/",
        views.facility_availability,
        name="facility_availability",
    ),
    path(
        "rental-requests/<int:request_id>/session/",
        views.session_workspace,
        name="session_workspace",
    ),
    path(
        "rental-requests/<int:request_id>/<str:action>/",
        views.update_rental_request,
        name="update_rental_request",
    ),
    path(
        "rental-requests/<int:request_id>/session/start-photo/",
        views.submit_provider_session_start_photo,
        name="submit_provider_session_start_photo",
    ),
    path(
        "rental-requests/<int:request_id>/session/provider/",
        views.submit_provider_session_record,
        name="provider_session_record",
    ),
    path(
        "rental-requests/<int:request_id>/session/renter-photo/",
        views.submit_renter_session_photo,
        name="submit_renter_session_photo",
    ),
    path(
        "session-records/<int:record_id>/",
        views.session_record_detail,
        name="session_record_detail",
    ),
    path(
        "session-records/<int:record_id>/photos/<str:photo_type>/",
        views.session_record_photo,
        name="session_record_photo",
    ),
    path("signin/", views.sign_in, name="sign_in"),
    path("login/", views.log_in, name="log_in"),
    path("account/", views.account, name="account"),
    path("logout/", views.log_out, name="log_out"),
]