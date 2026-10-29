from io import BytesIO
from datetime import time, timedelta
from decimal import Decimal
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .models import Facility, FacilityAvailability, RentalRequest, SessionRecord

Account = get_user_model()


def default_schedule_payload():
    """Provide weekday business hours and close both weekend days."""
    data = {}
    for day in ("sunday", "saturday"):
        data[f"{day}_closed"] = "on"
    for day in ("monday", "tuesday", "wednesday", "thursday", "friday"):
        data[f"{day}_opens_at"] = "08:00"
        data[f"{day}_closes_at"] = "18:00"
    return data


class AccountFlowTests(TestCase):
    def setUp(self):
        self.account_data = {
            "user_type": Account.UserType.USER,
            "name": "Sam Player",
            "email": "sam@example.com",
            "mobile_no": "+15551234567",
            "city": "Bengaluru",
            "password": "Skyline!Racket_4829",
            "confirm_password": "Skyline!Racket_4829",
        }

    def test_sign_up_saves_account_and_updates_navigation(self):
        response = self.client.post(reverse("sign_in"), self.account_data)

        self.assertRedirects(response, reverse("home"))
        account = Account.objects.get(email="sam@example.com")
        self.assertTrue(account.check_password(self.account_data["password"]))
        self.assertNotEqual(account.password, self.account_data["password"])
        self.assertEqual(account.city, "Bengaluru")

        response = self.client.get(reverse("home"))
        self.assertContains(response, "Sam Player")
        self.assertContains(response, reverse("account"))
        self.assertNotContains(response, reverse("sign_in"))
        self.assertNotContains(response, reverse("log_in"))

    def test_account_page_shows_profile_details(self):
        account = Account.objects.create_user(
            email=self.account_data["email"],
            name=self.account_data["name"],
            mobile_no=self.account_data["mobile_no"],
            user_type=self.account_data["user_type"],
            password=self.account_data["password"],
        )
        self.client.force_login(account)

        response = self.client.get(reverse("account"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "sam@example.com")
        self.assertContains(response, "+15551234567")
        self.assertContains(response, "Home city")

    def test_existing_account_can_update_its_home_city(self):
        account = Account.objects.create_user(
            email=self.account_data["email"],
            name=self.account_data["name"],
            mobile_no=self.account_data["mobile_no"],
            user_type=self.account_data["user_type"],
            password=self.account_data["password"],
        )
        self.client.force_login(account)

        response = self.client.post(reverse("account"), {"city": "Bengaluru"})

        self.assertRedirects(response, reverse("account"))
        account.refresh_from_db()
        self.assertEqual(account.city, "Bengaluru")

    def test_invalid_password_confirmation_does_not_create_account(self):
        form_data = {**self.account_data, "confirm_password": "Different!Password4829"}

        response = self.client.post(reverse("sign_in"), form_data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The passwords do not match.")
        self.assertFalse(Account.objects.filter(email="sam@example.com").exists())

    def test_login_and_post_logout(self):
        Account.objects.create_user(
            email=self.account_data["email"],
            name=self.account_data["name"],
            mobile_no=self.account_data["mobile_no"],
            user_type=self.account_data["user_type"],
            password=self.account_data["password"],
        )
        response = self.client.post(
            reverse("log_in"),
            {
                "email": self.account_data["email"],
                "password": self.account_data["password"],
            },
        )

        self.assertRedirects(response, reverse("home"))
        self.assertContains(self.client.get(reverse("home")), "Sam Player")

        response = self.client.post(reverse("log_out"))

        self.assertRedirects(response, reverse("home"))
        self.assertContains(self.client.get(reverse("home")), "Sign in")

    def test_find_button_is_only_shown_to_signed_in_users(self):
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, "See how FindIt works")
        self.assertNotContains(response, "Let's find it")

        account = Account.objects.create_user(
            email=self.account_data["email"],
            name=self.account_data["name"],
            mobile_no=self.account_data["mobile_no"],
            user_type=self.account_data["user_type"],
            password=self.account_data["password"],
        )
        self.client.force_login(account)
        response = self.client.get(reverse("home"))

        self.assertContains(response, "Let's find it")
        self.assertContains(response, reverse("find"))

    def test_home_lists_institutions_in_signed_in_account_city(self):
        provider = Account.objects.create_user(
            email="provider-directory@example.com",
            name="Local School",
            mobile_no="5551234567",
            user_type=Account.UserType.PROVIDER,
            password="Provider!Password4829",
        )
        Facility.objects.create(
            provider=provider,
            facility_name="Football Ground",
            institution_name="BMS College of Engineering",
            institution_location="Basavanagudi,  Bengaluru",
            institution_state="Karnataka",
            price_per_hour="500.00",
            contact_no="5551111111",
            contact_person_name="Asha",
        )
        Facility.objects.create(
            provider=provider,
            facility_name="Tennis Court",
            institution_name="Mysuru School",
            institution_location="Mysuru",
            institution_state="Karnataka",
            price_per_hour="300.00",
            contact_no="5552222222",
            contact_person_name="Ravi",
        )
        renter = Account.objects.create_user(
            email="directory-renter@example.com",
            name="City Renter",
            mobile_no="5553333333",
            user_type=Account.UserType.USER,
            password="Renter!Password4829",
        )
        renter.city = "Bangalore"
        renter.save(update_fields=("city",))
        self.client.force_login(renter)

        response = self.client.get(reverse("home"))

        self.assertContains(response, "BMS College of Engineering")
        self.assertNotContains(response, "Mysuru School")
        self.assertContains(
            response,
            reverse("institution_facilities"),
        )

    def test_institution_page_lists_facilities_and_preserves_rental_link(self):
        provider = Account.objects.create_user(
            email="provider-institution@example.com",
            name="Local School",
            mobile_no="5551234567",
            user_type=Account.UserType.PROVIDER,
            password="Provider!Password4829",
        )
        renter = Account.objects.create_user(
            email="institution-renter@example.com",
            name="City Renter",
            mobile_no="5553333333",
            user_type=Account.UserType.USER,
            password="Renter!Password4829",
        )
        renter.city = "Bangalore"
        renter.save(update_fields=("city",))
        facility = Facility.objects.create(
            provider=provider,
            facility_name="Football Ground",
            institution_name="Bengaluru School",
            institution_location="Central,  Bengaluru",
            institution_state="Karnataka",
            price_per_hour="500.00",
            contact_no="5551111111",
            contact_person_name="Asha",
        )
        self.client.force_login(renter)

        response = self.client.get(
            reverse("institution_facilities"),
            {
                "name": "Bengaluru School",
                "location": "Central,  Bengaluru",
                "state": "Karnataka",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Football Ground")
        self.assertContains(
            response,
            reverse("facility_availability", args=(facility.pk,)),
        )

    def test_find_page_requires_login(self):
        response = self.client.get(reverse("find"))

        self.assertRedirects(
            response,
            f"{reverse('log_in')}?next={reverse('find')}",
        )

    def test_find_form_accepts_search_and_location(self):
        account = Account.objects.create_user(
            email=self.account_data["email"],
            name=self.account_data["name"],
            mobile_no=self.account_data["mobile_no"],
            user_type=self.account_data["user_type"],
            password=self.account_data["password"],
        )
        self.client.force_login(account)

        response = self.client.get(reverse("find"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "What do you want to find?")
        self.assertContains(response, "Your current location")
        self.assertContains(response, "State")
        self.assertContains(response, "Use my current location")
        self.assertContains(response, "OpenStreetMap")

        response = self.client.post(
            reverse("search_results"),
            {
                "query": "football ground",
                "location": "Indiranagar, Bengaluru",
                "state": "Karnataka",
                "latitude": "12.9716000",
                "longitude": "77.5946000",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No matching facilities found")

    def test_search_requires_state_and_coordinates(self):
        account = Account.objects.create_user(
            email=self.account_data["email"],
            name=self.account_data["name"],
            mobile_no=self.account_data["mobile_no"],
            user_type=self.account_data["user_type"],
            password=self.account_data["password"],
        )
        self.client.force_login(account)

        response = self.client.post(
            reverse("search_results"),
            {
                "query": "football ground",
                "location": "Indiranagar, Bengaluru",
                "latitude": "12.9716000",
                "longitude": "77.5946000",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "This field is required.", status_code=400)
        self.assertNotContains(response, "No matching facilities found", status_code=400)

    def test_search_filters_by_facility_city_and_orders_by_distance(self):
        provider = Account.objects.create_user(
            email="provider@example.com",
            name="Local School",
            mobile_no="5551234567",
            user_type=Account.UserType.PROVIDER,
            password="Secure!ProviderPass893",
        )
        closest = Facility.objects.create(
            provider=provider,
            facility_name="Football Ground",
            institution_name="Nearby School",
            institution_location="Koramangala, Bengaluru",
            institution_state="Karnataka",
            price_per_hour="500.00",
            contact_no="5551111111",
            contact_person_name="Asha",
            latitude="12.9720000",
            longitude="77.5946000",
        )
        farther = Facility.objects.create(
            provider=provider,
            facility_name="Football Ground",
            institution_name="Farther College",
            institution_location="Whitefield, Bengaluru",
            institution_state="Karnataka",
            price_per_hour="750.00",
            contact_no="5552222222",
            contact_person_name="Ravi",
            latitude="13.0200000",
            longitude="77.7500000",
        )
        Facility.objects.create(
            provider=provider,
            facility_name="Football Ground",
            institution_name="Different City School",
            institution_location="Mysuru",
            institution_state="Karnataka",
            price_per_hour="400.00",
            contact_no="5553333333",
            contact_person_name="Dev",
            latitude="12.2958000",
            longitude="76.6394000",
        )
        self.client.force_login(provider)

        response = self.client.post(
            reverse("search_results"),
            {
                "query": "football ground",
                "location": "Indiranagar, Bengaluru",
                "state": "Karnataka",
                "latitude": "12.9716000",
                "longitude": "77.5946000",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["facilities"]),
            [closest, farther],
        )
        self.assertContains(response, "Nearby School")
        self.assertContains(response, "Farther College")
        self.assertNotContains(response, "Different City School")

    def test_provider_can_add_facility_with_saved_coordinates(self):
        provider = Account.objects.create_user(
            email="provider@example.com",
            name="Local School",
            mobile_no="5551234567",
            user_type=Account.UserType.PROVIDER,
            password="Secure!ProviderPass893",
        )
        self.client.force_login(provider)

        response = self.client.post(
            reverse("add_facility"),
            {
                "facility_name": "Tennis Court",
                "institution_name": "Local School",
                "institution_location": "Central, Bengaluru",
                "institution_state": "Karnataka",
                "price_per_hour": "350.00",
                "contact_no": "5551234567",
                "contact_person_name": "Sam",
                "latitude": "12.9716000",
                "longitude": "77.5946000",
                **default_schedule_payload(),
            },
        )

        self.assertRedirects(response, reverse("home"))
        facility = Facility.objects.get(facility_name="Tennis Court")
        self.assertEqual(facility.provider, provider)
        self.assertEqual(str(facility.latitude), "12.9716000")
        self.assertEqual(facility.weekly_availability.count(), 7)
        monday = facility.weekly_availability.get(
            day_of_week=FacilityAvailability.DayOfWeek.MONDAY,
        )
        self.assertEqual(monday.opens_at.strftime("%H:%M"), "08:00")
        self.assertEqual(monday.closes_at.strftime("%H:%M"), "18:00")
        self.assertTrue(
            facility.weekly_availability.get(
                day_of_week=FacilityAvailability.DayOfWeek.SUNDAY,
            ).is_closed
        )

    def test_non_provider_cannot_add_facility(self):
        account = Account.objects.create_user(
            email=self.account_data["email"],
            name=self.account_data["name"],
            mobile_no=self.account_data["mobile_no"],
            user_type=self.account_data["user_type"],
            password=self.account_data["password"],
        )
        self.client.force_login(account)

        response = self.client.get(reverse("add_facility"))

        self.assertRedirects(response, reverse("home"))


class FacilityRentalFlowTests(TestCase):
    def setUp(self):
        self.provider = Account.objects.create_user(
            email="provider-rental@example.com",
            name="Local Provider",
            mobile_no="5551234567",
            user_type=Account.UserType.PROVIDER,
            password="Provider!Password4829",
        )
        self.renter = Account.objects.create_user(
            email="renter@example.com",
            name="Local Renter",
            mobile_no="5557654321",
            user_type=Account.UserType.USER,
            password="Renter!Password4829",
        )
        self.facility = Facility.objects.create(
            provider=self.provider,
            facility_name="Football Ground",
            institution_name="Local School",
            institution_location="Central, Bengaluru",
            institution_state="Karnataka",
            price_per_hour="500.00",
            contact_no="5551234567",
            contact_person_name="Asha",
            latitude="12.9716000",
            longitude="77.5946000",
        )
        for day in range(7):
            is_weekday = 1 <= day <= 5
            FacilityAvailability.objects.create(
                facility=self.facility,
                day_of_week=day,
                opens_at="08:00" if is_weekday else None,
                closes_at="18:00" if is_weekday else None,
                is_closed=not is_weekday,
            )

    def next_open_date(self):
        requested_date = timezone.localdate() + timedelta(days=1)
        while requested_date.weekday() > 4:
            requested_date += timedelta(days=1)
        return requested_date

    def test_calendar_shows_seven_days_with_open_and_closed_days(self):
        self.client.force_login(self.renter)

        response = self.client.get(
            reverse("facility_availability", args=(self.facility.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["calendar"]), 7)
        self.assertContains(response, "Select")
        self.assertContains(response, "Request selected slots")
        self.assertContains(response, "Closed")

    def test_renter_request_is_persisted_and_visible_to_provider(self):
        self.client.force_login(self.renter)
        requested_date = self.next_open_date()

        response = self.client.post(
            reverse("facility_availability", args=(self.facility.pk,)),
            {
                "selected_slots": f"{requested_date.isoformat()}|09:00",
            },
        )

        self.assertRedirects(response, reverse("account"))
        rental_request = RentalRequest.objects.get()
        self.assertEqual(rental_request.renter, self.renter)
        self.assertEqual(rental_request.status, RentalRequest.Status.PENDING)

        self.client.force_login(self.provider)
        response = self.client.get(reverse("account"))
        self.assertContains(response, "Local Renter")
        self.assertContains(response, "Approve")

    def test_requested_slot_cannot_be_requested_again_and_provider_can_approve(self):
        requested_date = self.next_open_date()
        rental_request = RentalRequest.objects.create(
            facility=self.facility,
            renter=self.renter,
            requested_date=requested_date,
            starts_at="09:00",
            ends_at="10:00",
        )

        self.client.force_login(self.renter)
        response = self.client.post(
            reverse("facility_availability", args=(self.facility.pk,)),
            {
                "selected_slots": f"{requested_date.isoformat()}|09:00",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(RentalRequest.objects.count(), 1)

        self.client.force_login(self.provider)
        response = self.client.post(
            reverse(
                "update_rental_request",
                args=(rental_request.pk, "approve"),
            )
        )
        self.assertRedirects(response, reverse("account"))
        rental_request.refresh_from_db()
        self.assertEqual(rental_request.status, RentalRequest.Status.APPROVED)

        response = self.client.get(
            reverse("facility_availability", args=(self.facility.pk,))
        )
        self.assertContains(response, "Booked")

    def test_closed_day_cannot_be_requested(self):
        today = timezone.localdate()
        days_until_saturday = (5 - today.weekday()) % 7
        requested_date = today + timedelta(days=days_until_saturday)
        self.client.force_login(self.renter)

        response = self.client.post(
            reverse("facility_availability", args=(self.facility.pk,)),
            {
                "selected_slots": f"{requested_date.isoformat()}|09:00",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(RentalRequest.objects.exists())

    def test_multiple_contiguous_slots_create_one_multi_hour_request(self):
        self.client.force_login(self.renter)
        requested_date = self.next_open_date()

        response = self.client.post(
            reverse("facility_availability", args=(self.facility.pk,)),
            {
                "selected_slots": [
                    f"{requested_date.isoformat()}|09:00",
                    f"{requested_date.isoformat()}|10:00",
                    f"{requested_date.isoformat()}|11:00",
                ],
            },
        )

        self.assertRedirects(response, reverse("account"))
        rental_request = RentalRequest.objects.get()
        self.assertEqual(rental_request.starts_at.strftime("%H:%M"), "09:00")
        self.assertEqual(rental_request.ends_at.strftime("%H:%M"), "12:00")


class SessionRecordFlowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_directory = TemporaryDirectory()
        cls.media_settings = override_settings(MEDIA_ROOT=cls.media_directory.name)
        cls.media_settings.enable()

    @classmethod
    def tearDownClass(cls):
        cls.media_settings.disable()
        cls.media_directory.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.provider = Account.objects.create_user(
            email="session-provider@example.com",
            name="Session Provider",
            mobile_no="5551234567",
            user_type=Account.UserType.PROVIDER,
            password="Provider!Password4829",
        )
        self.renter = Account.objects.create_user(
            email="session-renter@example.com",
            name="Session Renter",
            mobile_no="5557654321",
            user_type=Account.UserType.USER,
            password="Renter!Password4829",
        )
        self.outsider = Account.objects.create_user(
            email="session-outsider@example.com",
            name="Session Outsider",
            mobile_no="5551111111",
            user_type=Account.UserType.USER,
            password="Outsider!Password4829",
        )
        self.facility = Facility.objects.create(
            provider=self.provider,
            facility_name="Football Ground",
            institution_name="Local School",
            institution_location="Central, Bengaluru",
            institution_state="Karnataka",
            price_per_hour="500.00",
            contact_no="5551234567",
            contact_person_name="Asha",
        )
        self.rental_request = RentalRequest.objects.create(
            facility=self.facility,
            renter=self.renter,
            requested_date=timezone.localdate() - timedelta(days=1),
            starts_at=time(9),
            ends_at=time(10),
            status=RentalRequest.Status.APPROVED,
        )
        self.provider_start_photo_url = reverse(
            "submit_provider_session_start_photo",
            args=(self.rental_request.pk,),
        )
        self.provider_url = reverse(
            "provider_session_record",
            args=(self.rental_request.pk,),
        )
        self.renter_photo_url = reverse(
            "submit_renter_session_photo",
            args=(self.rental_request.pk,),
        )
    def uploaded_photo(self, filename):
        image_buffer = BytesIO()
        Image.new("RGB", (2, 2), color="green").save(image_buffer, format="PNG")
        return SimpleUploadedFile(
            filename,
            image_buffer.getvalue(),
            content_type="image/png",
        )

    def test_provider_details_and_renter_photo_finalize_immutable_history(self):
        self.client.force_login(self.provider)

        response = self.client.post(
            self.provider_start_photo_url,
            {"starting_photo": self.uploaded_photo("starting.png")},
        )
        self.assertRedirects(
            response,
            reverse("session_workspace", args=(self.rental_request.pk,)),
        )
        session_record = SessionRecord.objects.get()
        self.assertTrue(session_record.starting_photo)
        self.assertIsNone(session_record.damage_reported)

        self.client.force_login(self.renter)
        response = self.client.post(
            self.renter_photo_url,
            {"ending_photo": self.uploaded_photo("ending.png")},
        )
        self.assertRedirects(
            response,
            reverse("session_workspace", args=(self.rental_request.pk,)),
        )

        self.client.force_login(self.provider)
        response = self.client.post(
            self.provider_url,
            {
                "damage_reported": "yes",
                "damage_description": "Broken sideline marker",
                "damage_cost": "125.00",
                "payment_received": "yes",
            },
        )
        self.assertRedirects(
            response,
            reverse("session_workspace", args=(self.rental_request.pk,)),
        )
        session_record.refresh_from_db()
        self.assertTrue(session_record.damage_reported)
        self.assertEqual(session_record.damage_cost, Decimal("125.00"))
        self.assertTrue(session_record.payment_received)
        self.assertTrue(session_record.finalized_at)
        self.assertTrue(session_record.ending_photo)

        response = self.client.get(reverse("account"))
        self.assertContains(response, "Football Ground")
        self.assertContains(response, reverse("session_record_detail", args=(session_record.pk,)))
        self.assertEqual(list(response.context["rental_requests"]), [])
        self.assertEqual(
            list(response.context["session_history"]),
            [session_record],
        )

        response = self.client.get(
            reverse("session_record_detail", args=(session_record.pk,))
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Broken sideline marker")
        self.assertContains(response, reverse("session_record_photo", args=(session_record.pk, "start")))
        self.assertContains(response, reverse("session_record_photo", args=(session_record.pk, "end")))
        response = self.client.get(
            reverse("session_record_photo", args=(session_record.pk, "start"))
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        response.close()

        session_record.damage_description = "Changed after completion"
        with self.assertRaises(ValidationError):
            session_record.save()

    def test_end_photo_can_arrive_before_provider_details(self):
        session_record = SessionRecord.objects.create(
            rental_request=self.rental_request,
            starting_photo=self.uploaded_photo("starting.png"),
        )
        self.client.force_login(self.renter)

        response = self.client.post(
            self.renter_photo_url,
            {"ending_photo": self.uploaded_photo("ending.png")},
        )
        self.assertRedirects(
            response,
            reverse("session_workspace", args=(self.rental_request.pk,)),
        )
        session_record.refresh_from_db()
        self.assertTrue(session_record.ending_photo)
        self.assertIsNone(session_record.finalized_at)

        self.client.force_login(self.provider)
        response = self.client.post(
            self.provider_url,
            {
                "damage_reported": "no",
                "payment_received": "no",
            },
        )
        self.assertRedirects(
            response,
            reverse("session_workspace", args=(self.rental_request.pk,)),
        )
        session_record.refresh_from_db()
        self.assertTrue(session_record.finalized_at)
        self.assertFalse(session_record.damage_reported)
        self.assertIsNone(session_record.damage_cost)

    def test_renter_cannot_add_end_photo_before_provider_record_exists(self):
        self.client.force_login(self.provider)

        response = self.client.post(
            self.provider_url,
            {
                "damage_reported": "no",
                "payment_received": "yes",
            },
        )
        self.assertEqual(response.status_code, 404)

        self.client.force_login(self.renter)

        response = self.client.post(
            self.renter_photo_url,
            {"ending_photo": self.uploaded_photo("ending.png")},
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(SessionRecord.objects.exists())

    def test_only_booking_participants_can_view_session_details_and_photos(self):
        record = SessionRecord.objects.create(
            rental_request=self.rental_request,
            starting_photo=self.uploaded_photo("starting.png"),
            ending_photo=self.uploaded_photo("ending.png"),
            damage_reported=False,
            payment_received=True,
            finalized_at=timezone.now(),
        )
        self.client.force_login(self.outsider)

        response = self.client.get(
            reverse("session_record_detail", args=(record.pk,))
        )
        self.assertRedirects(response, reverse("account"))
        response = self.client.get(
            reverse("session_record_photo", args=(record.pk, "start"))
        )
        self.assertRedirects(response, reverse("account"))

    def test_booked_session_opens_workspace_from_both_accounts(self):
        workspace_url = reverse("session_workspace", args=(self.rental_request.pk,))

        self.client.force_login(self.provider)
        response = self.client.get(reverse("account"))
        self.assertContains(response, workspace_url)
        response = self.client.get(workspace_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PROVIDER SESSION")
        self.assertContains(response, "Save starting photo")

        self.client.force_login(self.renter)
        response = self.client.get(reverse("account"))
        self.assertContains(response, workspace_url)
        response = self.client.get(workspace_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "YOUR BOOKED SESSION")

    def test_outsider_cannot_open_session_workspace(self):
        self.client.force_login(self.outsider)

        response = self.client.get(
            reverse("session_workspace", args=(self.rental_request.pk,))
        )

        self.assertRedirects(response, reverse("account"))
