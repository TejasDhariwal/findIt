from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
import re

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from PIL import Image

from .forms import (
    AccountCityForm,
    FacilityForm,
    FacilityScheduleForm,
    FindForm,
    LoginForm,
    ProviderSessionDetailsForm,
    ProviderSessionStartPhotoForm,
    RentalRequestForm,
    RenterSessionPhotoForm,
    SignUpForm,
)
from .models import Account, Facility, RentalRequest, SessionRecord


def _facilities_in_city(city):
    """Match the final address component despite spacing and city-name variants."""
    normalized_city = " ".join(city.split()).casefold()
    if not normalized_city:
        return Facility.objects.none()
    city_names = {
        "bangalore": ("Bangalore", "Bengaluru"),
        "bengaluru": ("Bengaluru", "Bangalore"),
    }.get(normalized_city, (normalized_city,))
    address_match = Q()
    for city_name in city_names:
        address_match |= Q(
            institution_location__iregex=rf"(?:^|,)\s*{re.escape(city_name)}\s*$"
        )
    return Facility.objects.filter(address_match)


def home(request):
    institutions = []
    if request.user.is_authenticated and request.user.city.strip():
        institutions = list(
            _facilities_in_city(request.user.city)
            .values(
                "institution_name",
                "institution_location",
                "institution_state",
            )
            .distinct()
            .order_by("institution_name", "institution_location")
        )
    return render(request, "home.html", {"institutions": institutions})


@login_required(login_url="log_in")
def institution_facilities(request):
    """List a selected institution's facilities in the signed-in user's city."""
    institution_name = request.GET.get("name", "").strip()
    institution_location = request.GET.get("location", "").strip()
    institution_state = request.GET.get("state", "").strip()
    facilities = Facility.objects.none()
    if institution_name and institution_location and institution_state:
        facilities = _facilities_in_city(request.user.city).filter(
            institution_name__iexact=institution_name,
            institution_location__iexact=institution_location,
            institution_state__iexact=institution_state,
        ).select_related("provider")
    return render(
        request,
        "institution_facilities.html",
        {
            "facilities": facilities,
            "institution_name": institution_name,
            "institution_location": institution_location,
            "institution_state": institution_state,
            "city": request.user.city,
        },
    )


@login_required(login_url="log_in")
def find(request):
    form = FindForm()
    return render(request, "find.html", {"form": form})


def _distance_km(origin_latitude, origin_longitude, target_latitude, target_longitude):
    """Return great-circle distance using the Haversine formula."""
    origin_latitude, origin_longitude, target_latitude, target_longitude = map(
        radians,
        (origin_latitude, origin_longitude, target_latitude, target_longitude),
    )
    latitude_delta = target_latitude - origin_latitude
    longitude_delta = target_longitude - origin_longitude
    haversine = (
        sin(latitude_delta / 2) ** 2
        + cos(origin_latitude) * cos(target_latitude) * sin(longitude_delta / 2) ** 2
    )
    return 6371 * 2 * asin(sqrt(haversine))


@login_required(login_url="log_in")
@require_POST
def search_results(request):
    form = FindForm(request.POST)
    if not form.is_valid():
        return render(request, "find.html", {"form": form}, status=400)

    search = form.cleaned_data
    # The final comma-separated part is the city in "locality, colony, city".
    city = search["location"].rsplit(",", 1)[-1].strip()
    facilities = Facility.objects.filter(
        institution_location__icontains=city,
        institution_state__iexact=search["state"].strip(),
        facility_name__icontains=search["query"].strip(),
        latitude__isnull=False,
        longitude__isnull=False,
    ).select_related("provider")

    origin_latitude = float(search["latitude"])
    origin_longitude = float(search["longitude"])
    results = []
    for facility in facilities:
        facility.distance_km = _distance_km(
            origin_latitude,
            origin_longitude,
            float(facility.latitude),
            float(facility.longitude),
        )
        results.append(facility)
    results.sort(key=lambda facility: facility.distance_km)

    return render(
        request,
        "search_results.html",
        {
            "facilities": results,
            "query": search["query"],
            "city": city,
            "state": search["state"],
        },
    )


@login_required(login_url="log_in")
def add_facility(request):
    if request.user.user_type != Account.UserType.PROVIDER:
        messages.error(request, "Only provider accounts can add facilities.")
        return redirect("home")

    form = FacilityForm(request.POST or None)
    schedule_form = FacilityScheduleForm(request.POST or None)
    if (
        request.method == "POST"
        and form.is_valid()
        and schedule_form.is_valid()
    ):
        with transaction.atomic():
            facility = form.save(commit=False)
            facility.provider = request.user
            facility.save()
            schedule_form.save(facility)
        messages.success(request, "Your facility and weekly hours have been added.")
        return redirect("home")

    return render(
        request,
        "add_facility.html",
        {"form": form, "schedule_form": schedule_form},
    )


def _calendar_days(facility, start_date):
    """Build seven days of one-hour slots and hide renter details from viewers."""
    end_date = start_date + timedelta(days=6)
    schedules = {
        schedule.day_of_week: schedule
        for schedule in facility.weekly_availability.all()
    }
    requests_by_date = {}
    for rental_request in facility.rental_requests.filter(
        requested_date__range=(start_date, end_date),
        status__in=(RentalRequest.Status.PENDING, RentalRequest.Status.APPROVED),
    ):
        requests_by_date.setdefault(rental_request.requested_date, []).append(
            rental_request
        )

    calendar = []
    current_time = timezone.localtime().replace(tzinfo=None)
    for day_offset in range(7):
        current_date = start_date + timedelta(days=day_offset)
        schedule = schedules.get((current_date.weekday() + 1) % 7)
        day = {
            "date": current_date,
            "schedule": schedule,
            "slots": [],
        }
        if schedule and not schedule.is_closed:
            slot_start = datetime.combine(current_date, schedule.opens_at)
            closing_time = datetime.combine(current_date, schedule.closes_at)
            while slot_start + timedelta(hours=1) <= closing_time:
                slot_end = slot_start + timedelta(hours=1)
                overlapping_requests = [
                    rental_request
                    for rental_request in requests_by_date.get(current_date, [])
                    if rental_request.starts_at < slot_end.time()
                    and rental_request.ends_at > slot_start.time()
                ]
                if any(
                    item.status == RentalRequest.Status.APPROVED
                    for item in overlapping_requests
                ):
                    status = "booked"
                elif overlapping_requests:
                    status = "requested"
                elif (
                    current_date == start_date
                    and slot_start <= current_time
                ):
                    status = "past"
                else:
                    status = "available"
                day["slots"].append(
                    {
                        "starts_at": slot_start.time(),
                        "ends_at": slot_end.time(),
                        "status": status,
                        "value": (
                            f"{current_date.isoformat()}|"
                            f"{slot_start.strftime('%H:%M')}"
                        ),
                    }
                )
                slot_start = slot_end
        calendar.append(day)
    return calendar


@login_required(login_url="log_in")
def facility_availability(request, facility_id):
    """Show the next seven days and accept requests for available hourly slots."""
    facility = get_object_or_404(
        Facility.objects.select_related("provider"),
        pk=facility_id,
    )
    start_date = timezone.localdate()
    calendar = _calendar_days(facility, start_date)
    slot_choices = [
        (
            slot["value"],
            f'{day["date"].strftime("%a, %b %d")} · '
            f'{slot["starts_at"]:%H:%M}',
        )
        for day in calendar
        for slot in day["slots"]
        if slot["status"] == "available"
    ]
    if request.method == "POST":
        if request.user.user_type != Account.UserType.USER:
            messages.error(request, "Only renter accounts can request a facility.")
            return redirect("facility_availability", facility_id=facility.pk)
        if request.user == facility.provider:
            messages.error(request, "You cannot request your own facility.")
            return redirect("facility_availability", facility_id=facility.pk)

        form = RentalRequestForm(request.POST, choices=slot_choices)
        if form.is_valid():
            selected_slots = form.selected_slot_times()
            grouped_slots = []
            for requested_date, starts_at, ends_at in selected_slots:
                if (
                    grouped_slots
                    and grouped_slots[-1][0] == requested_date
                    and grouped_slots[-1][2] == starts_at
                ):
                    grouped_slots[-1] = (
                        requested_date,
                        grouped_slots[-1][1],
                        ends_at,
                    )
                else:
                    grouped_slots.append((requested_date, starts_at, ends_at))
            with transaction.atomic():
                for requested_date, starts_at, ends_at in grouped_slots:
                    slot_is_taken = RentalRequest.objects.filter(
                        facility=facility,
                        requested_date=requested_date,
                        status__in=(
                            RentalRequest.Status.PENDING,
                            RentalRequest.Status.APPROVED,
                        ),
                        starts_at__lt=ends_at,
                        ends_at__gt=starts_at,
                    ).exists()
                    if slot_is_taken:
                        messages.error(
                            request,
                            "One or more selected slots have just been requested or booked. Please choose again.",
                        )
                        return redirect(
                            "facility_availability",
                            facility_id=facility.pk,
                        )
                RentalRequest.objects.bulk_create(
                    [
                        RentalRequest(
                            facility=facility,
                            renter=request.user,
                            requested_date=requested_date,
                            starts_at=starts_at,
                            ends_at=ends_at,
                        )
                        for requested_date, starts_at, ends_at in grouped_slots
                    ]
                )
            messages.success(request, "Your selected rental slots have been sent to the provider.")
            return redirect("account")
    else:
        form = RentalRequestForm(choices=slot_choices)

    return render(
        request,
        "facility_availability.html",
        {
            "facility": facility,
            "calendar": calendar,
            "start_date": start_date,
            "request_form": form,
            "selected_slots": set(request.POST.getlist("selected_slots")),
        },
        status=400 if request.method == "POST" and not form.is_valid() else 200,
    )


@login_required(login_url="log_in")
@require_POST
def update_rental_request(request, request_id, action):
    """Let the owning provider approve or decline a pending request."""
    if request.user.user_type != Account.UserType.PROVIDER:
        messages.error(request, "Only providers can update rental requests.")
        return redirect("account")
    rental_request = get_object_or_404(
        RentalRequest.objects.select_related("facility"),
        pk=request_id,
        facility__provider=request.user,
        status=RentalRequest.Status.PENDING,
    )
    if action == "approve":
        with transaction.atomic():
            conflicting_requests = RentalRequest.objects.filter(
                facility=rental_request.facility,
                requested_date=rental_request.requested_date,
                status=RentalRequest.Status.PENDING,
                starts_at__lt=rental_request.ends_at,
                ends_at__gt=rental_request.starts_at,
            ).exclude(pk=rental_request.pk)
            conflicting_requests.update(status=RentalRequest.Status.REJECTED)
            rental_request.status = RentalRequest.Status.APPROVED
            rental_request.save(update_fields=("status",))
        messages.success(request, "The rental request has been approved.")
    elif action == "reject":
        rental_request.status = RentalRequest.Status.REJECTED
        rental_request.save(update_fields=("status",))
        messages.success(request, "The rental request has been declined.")
    else:
        messages.error(request, "That request action is not supported.")
    return redirect("account")


@login_required(login_url="log_in")
def session_workspace(request, request_id):
    """Provide one session page for the renter and provider on an approved booking."""
    rental_request = get_object_or_404(
        RentalRequest.objects.select_related("facility", "renter", "facility__provider"),
        pk=request_id,
        status=RentalRequest.Status.APPROVED,
    )
    if request.user not in (rental_request.renter, rental_request.facility.provider):
        messages.error(request, "You do not have access to this booked session.")
        return redirect("account")

    session_record = SessionRecord.objects.filter(
        rental_request=rental_request,
    ).first()
    is_provider = request.user == rental_request.facility.provider
    context = {
        "rental_request": rental_request,
        "session_record": session_record,
        "is_provider": is_provider,
        "start_photo_form": (
            ProviderSessionStartPhotoForm()
            if is_provider and not session_record
            else None
        ),
        "provider_details_form": (
            ProviderSessionDetailsForm(instance=session_record)
            if (
                is_provider
                and session_record
                and session_record.ending_photo
                and not session_record.finalized_at
            )
            else None
        ),
        "renter_photo_form": (
            RenterSessionPhotoForm()
            if (
                not is_provider
                and session_record
                and not session_record.ending_photo
            )
            else None
        ),
    }
    return render(request, "session_workspace.html", context)


@login_required(login_url="log_in")
@require_POST
def submit_provider_session_start_photo(request, request_id):
    """Let the provider upload the starting photo at any time before the renter's photo."""
    rental_request = get_object_or_404(
        RentalRequest.objects.select_related("facility"),
        pk=request_id,
        facility__provider=request.user,
        status=RentalRequest.Status.APPROVED,
    )
    if SessionRecord.objects.filter(rental_request=rental_request).exists():
        messages.error(request, "The starting photo has already been submitted.")
        return redirect("session_workspace", request_id=rental_request.pk)

    form = ProviderSessionStartPhotoForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(
            request,
            " ".join(
                f"{field}: {', '.join(errors)}"
                for field, errors in form.errors.items()
            ),
        )
        return redirect("session_workspace", request_id=rental_request.pk)
    SessionRecord.objects.create(
        rental_request=rental_request,
        starting_photo=form.cleaned_data["starting_photo"],
    )
    messages.success(request, "The starting photo has been saved.")
    return redirect("session_workspace", request_id=rental_request.pk)


@login_required(login_url="log_in")
@require_POST
def submit_provider_session_record(request, request_id):
    """Save provider-owned details after the renter submits the ending photo."""
    rental_request = get_object_or_404(
        RentalRequest.objects.select_related("facility"),
        pk=request_id,
        facility__provider=request.user,
        status=RentalRequest.Status.APPROVED,
    )
    session_record = get_object_or_404(
        SessionRecord,
        rental_request=rental_request,
        ending_photo__gt="",
        finalized_at__isnull=True,
    )

    form = ProviderSessionDetailsForm(request.POST, instance=session_record)
    if not form.is_valid():
        messages.error(
            request,
            " ".join(
                f"{field}: {', '.join(errors)}"
                for field, errors in form.errors.items()
            ),
        )
        return redirect("session_workspace", request_id=rental_request.pk)

    session_record = form.save(commit=False)
    session_record.finalized_at = timezone.now()
    session_record.save()
    messages.success(request, "The completed session has been added to History.")
    return redirect("session_workspace", request_id=rental_request.pk)


@login_required(login_url="log_in")
@require_POST
def submit_renter_session_photo(request, request_id):
    """Allow the renter to add an ending photo only after the provider's start photo."""
    rental_request = get_object_or_404(
        RentalRequest.objects.select_related("facility"),
        pk=request_id,
        renter=request.user,
        status=RentalRequest.Status.APPROVED,
    )
    session_record = get_object_or_404(
        SessionRecord,
        rental_request=rental_request,
        finalized_at__isnull=True,
    )
    if session_record.ending_photo:
        messages.error(request, "The ending photo has already been submitted.")
        return redirect("session_workspace", request_id=rental_request.pk)

    form = RenterSessionPhotoForm(request.POST, request.FILES)
    if not form.is_valid():
        errors = " ".join(
            f"{field}: {', '.join(field_errors)}"
            for field, field_errors in form.errors.items()
        )
        messages.error(request, errors)
        return redirect("session_workspace", request_id=rental_request.pk)

    session_record.ending_photo = form.cleaned_data["ending_photo"]
    session_record.save(update_fields=("ending_photo",))
    messages.success(
        request,
        "The ending photo is saved. The provider can now enter the final details.",
    )
    return redirect("session_workspace", request_id=rental_request.pk)


@login_required(login_url="log_in")
def session_record_detail(request, record_id):
    """Show finalized session details only to the booking's renter and provider."""
    session_record = get_object_or_404(
        SessionRecord.objects.select_related(
            "rental_request__facility",
            "rental_request__renter",
        ),
        pk=record_id,
        finalized_at__isnull=False,
    )
    rental_request = session_record.rental_request
    if request.user not in (rental_request.renter, rental_request.facility.provider):
        messages.error(request, "You do not have access to this session history.")
        return redirect("account")
    return render(
        request,
        "session_record_detail.html",
        {"session_record": session_record},
    )


@login_required(login_url="log_in")
def session_record_photo(request, record_id, photo_type):
    """Serve finalized photos only to the renter and provider involved."""
    if photo_type not in {"start", "end"}:
        raise Http404

    session_record = get_object_or_404(
        SessionRecord.objects.select_related(
            "rental_request__facility",
            "rental_request__renter",
        ),
        pk=record_id,
        finalized_at__isnull=False,
    )
    rental_request = session_record.rental_request
    if request.user not in (rental_request.renter, rental_request.facility.provider):
        messages.error(request, "You do not have access to this session photo.")
        return redirect("account")

    photo = (
        session_record.starting_photo
        if photo_type == "start"
        else session_record.ending_photo
    )
    if not photo:
        raise Http404
    photo.open("rb")
    with Image.open(photo) as image:
        content_type = Image.MIME[image.format]
    photo.seek(0)
    response = FileResponse(photo, content_type=content_type)
    response["Content-Disposition"] = f'inline; filename="{Path(photo.name).name}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


def sign_in(request):
    if request.user.is_authenticated:
        return redirect("home")

    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        account = form.save()
        login(request, account)
        messages.success(request, "Your account has been created.")
        return redirect("home")

    return render(request, "sign_in.html", {"form": form})


def log_in(request):
    if request.user.is_authenticated:
        return redirect("home")

    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        account = authenticate(
            request,
            email=form.cleaned_data["email"],
            password=form.cleaned_data["password"],
        )
        if account is not None:
            login(request, account)
            return redirect("home")
        form.add_error(None, "Email or password is incorrect.")

    return render(request, "log_in.html", {"form": form})


@login_required
def account(request):
    city_form = AccountCityForm(request.POST or None, instance=request.user)
    if request.method == "POST":
        if city_form.is_valid():
            city_form.save()
            messages.success(request, "Your home city has been updated.")
            return redirect("account")

    if request.user.user_type == Account.UserType.PROVIDER:
        rental_requests = RentalRequest.objects.filter(
            facility__provider=request.user,
        )
    else:
        rental_requests = RentalRequest.objects.filter(
            renter=request.user,
        )
    rental_requests = rental_requests.exclude(
        status=RentalRequest.Status.APPROVED,
        session_record__finalized_at__isnull=False,
    ).select_related("facility", "facility__provider", "renter", "session_record")
    session_history = SessionRecord.objects.filter(
        finalized_at__isnull=False,
    ).filter(
        Q(rental_request__renter=request.user)
        | Q(rental_request__facility__provider=request.user)
    ).select_related("rental_request__facility")
    return render(
        request,
        "account.html",
        {
            "rental_requests": rental_requests,
            "city_form": city_form,
            "session_history": session_history,
        },
    )


@require_POST
def log_out(request):
    logout(request)
    return redirect("home")