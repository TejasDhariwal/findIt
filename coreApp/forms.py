from datetime import datetime, timedelta

from django import forms
from django.core.validators import MaxValueValidator, MinValueValidator
from django.contrib.auth import get_user_model, password_validation

from .models import Facility, FacilityAvailability, SessionRecord

Account = get_user_model()


class SignUpForm(forms.ModelForm):
    city = forms.CharField(
        label="City",
        max_length=100,
        widget=forms.TextInput(
            attrs={"placeholder": "e.g. Bengaluru", "autocomplete": "address-level2"}
        ),
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput,
    )
    confirm_password = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput,
    )

    class Meta:
        model = Account
        fields = ("user_type", "name", "email", "mobile_no", "city")
        widgets = {
            "user_type": forms.Select(),
            "city": forms.TextInput(
                attrs={"placeholder": "e.g. Bengaluru", "autocomplete": "address-level2"}
            ),
        }

    def clean_email(self):
        return Account.objects.normalize_email(self.cleaned_data["email"])

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password and password != confirm_password:
            self.add_error("confirm_password", "The passwords do not match.")

        if password:
            try:
                password_validation.validate_password(password, self.instance)
            except forms.ValidationError as error:
                self.add_error("password", error)

        return cleaned_data

    def save(self, commit=True):
        account = super().save(commit=False)
        account.set_password(self.cleaned_data["password"])
        if commit:
            account.save()
        return account


class LoginForm(forms.Form):
    email = forms.EmailField()
    password = forms.CharField(strip=False, widget=forms.PasswordInput)


class AccountCityForm(forms.ModelForm):
    """Allow existing accounts to set or update their home city."""

    city = forms.CharField(
        label="Home city",
        max_length=100,
        widget=forms.TextInput(
            attrs={"placeholder": "e.g. Bengaluru", "autocomplete": "address-level2"}
        ),
    )

    class Meta:
        model = Account
        fields = ("city",)
        widgets = {
            "city": forms.TextInput(
                attrs={"placeholder": "e.g. Bengaluru", "autocomplete": "address-level2"}
            ),
        }


class FindForm(forms.Form):
    query = forms.CharField(
        label="What do you want to find?",
        max_length=150,
        widget=forms.TextInput(
            attrs={"placeholder": "e.g. football ground, sports equipment"}
        ),
    )
    location = forms.CharField(
        label="Your current location",
        max_length=255,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Locality, colony, city",
                "autocomplete": "address-level2",
            }
        ),
    )
    state = forms.CharField(
        label="State",
        max_length=100,
        widget=forms.TextInput(
            attrs={"placeholder": "Enter your state", "autocomplete": "address-level1"}
        ),
    )
    latitude = forms.DecimalField(
        max_digits=10,
        decimal_places=7,
        widget=forms.HiddenInput,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = forms.DecimalField(
        max_digits=10,
        decimal_places=7,
        widget=forms.HiddenInput,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )


class FacilityForm(forms.ModelForm):
    class Meta:
        model = Facility
        fields = (
            "facility_name",
            "institution_name",
            "institution_location",
            "institution_state",
            "price_per_hour",
            "contact_no",
            "contact_person_name",
            "latitude",
            "longitude",
        )
        widgets = {
            "institution_location": forms.TextInput(
                attrs={"placeholder": "Locality, colony, city"}
            ),
            "institution_state": forms.TextInput(attrs={"placeholder": "State"}),
            "latitude": forms.HiddenInput,
            "longitude": forms.HiddenInput,
        }

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("latitude") is None or cleaned_data.get("longitude") is None:
            raise forms.ValidationError(
                "Enter a valid institution location so we can place it on the map."
            )
        return cleaned_data


class FacilityScheduleForm(forms.Form):
    """Collect opening hours in a compact Sunday-through-Saturday grid."""

    DAYS = FacilityAvailability.DayOfWeek.choices

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for day, label in self.DAYS:
            prefix = label.lower()
            self.fields[f"{prefix}_closed"] = forms.BooleanField(
                label="Closed",
                required=False,
            )
            self.fields[f"{prefix}_opens_at"] = forms.TimeField(
                label="Opens",
                required=False,
                widget=forms.TimeInput(attrs={"type": "time"}),
            )
            self.fields[f"{prefix}_closes_at"] = forms.TimeField(
                label="Closes",
                required=False,
                widget=forms.TimeInput(attrs={"type": "time"}),
            )

    @property
    def schedule_rows(self):
        return [
            (
                label,
                self[f"{label.lower()}_closed"],
                self[f"{label.lower()}_opens_at"],
                self[f"{label.lower()}_closes_at"],
            )
            for _, label in self.DAYS
        ]

    def clean(self):
        cleaned_data = super().clean()
        for _, label in self.DAYS:
            prefix = label.lower()
            if cleaned_data.get(f"{prefix}_closed"):
                cleaned_data[f"{prefix}_opens_at"] = None
                cleaned_data[f"{prefix}_closes_at"] = None
                continue

            opens_at = cleaned_data.get(f"{prefix}_opens_at")
            closes_at = cleaned_data.get(f"{prefix}_closes_at")
            if not opens_at or not closes_at:
                self.add_error(
                    None,
                    f"Choose opening and closing times for {label}, or mark it closed.",
                )
            elif closes_at <= opens_at:
                self.add_error(
                    None,
                    f"{label} closing time must be later than its opening time.",
                )
        return cleaned_data

    def save(self, facility):
        """Persist a complete seven-day schedule once the facility exists."""
        FacilityAvailability.objects.bulk_create(
            [
                FacilityAvailability(
                    facility=facility,
                    day_of_week=day,
                    is_closed=self.cleaned_data[f"{label.lower()}_closed"],
                    opens_at=self.cleaned_data[f"{label.lower()}_opens_at"],
                    closes_at=self.cleaned_data[f"{label.lower()}_closes_at"],
                )
                for day, label in self.DAYS
            ]
        )


class RentalRequestForm(forms.Form):
    """Validate selected hourly slots against the live calendar choices."""

    selected_slots = forms.MultipleChoiceField(
        choices=(),
        required=True,
        error_messages={"required": "Select at least one available time slot."},
    )

    def __init__(self, *args, choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["selected_slots"].choices = choices

    def clean_selected_slots(self):
        selected_slots = self.cleaned_data["selected_slots"]
        if len(selected_slots) != len(set(selected_slots)):
            raise forms.ValidationError("Each available slot can only be selected once.")
        return selected_slots

    def selected_slot_times(self):
        """Parse already-validated values into (date, start, end) tuples."""
        selected = []
        for value in self.cleaned_data["selected_slots"]:
            date_value, start_value = value.split("|", 1)
            requested_date = forms.fields.DateField().to_python(date_value)
            starts_at = forms.fields.TimeField().to_python(start_value)
            ends_at = (
                datetime.combine(requested_date, starts_at) + timedelta(hours=1)
            ).time()
            selected.append((requested_date, starts_at, ends_at))
        return sorted(selected)


class ProviderSessionDetailsForm(forms.ModelForm):
    """Capture provider-owned damage and payment details after a session."""

    damage_reported = forms.ChoiceField(
        choices=(("no", "No damage"), ("yes", "Damage reported")),
        label="Was there any damage?",
    )
    payment_received = forms.ChoiceField(
        choices=(("yes", "Payment received"), ("no", "Payment not received")),
        label="Was payment made?",
    )

    class Meta:
        model = SessionRecord
        fields = (
            "damage_reported",
            "damage_description",
            "damage_cost",
            "payment_received",
        )
        widgets = {
            "damage_description": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "damage_description": "Describe the damage",
            "damage_cost": "Estimated damage cost",
        }

    def clean_starting_photo(self):
        return validate_session_photo(self.cleaned_data["starting_photo"])

    def clean(self):
        cleaned_data = super().clean()
        damage_reported = cleaned_data.get("damage_reported") == "yes"
        cleaned_data["damage_reported"] = damage_reported
        cleaned_data["payment_received"] = (
            cleaned_data.get("payment_received") == "yes"
        )

        if damage_reported:
            if not cleaned_data.get("damage_description"):
                self.add_error("damage_description", "Describe the reported damage.")
            if cleaned_data.get("damage_cost") is None:
                self.add_error("damage_cost", "Enter the estimated damage cost.")
        else:
            cleaned_data["damage_description"] = ""
            cleaned_data["damage_cost"] = None
        return cleaned_data


class ProviderSessionStartPhotoForm(forms.Form):
    """Collect the provider's starting-condition photo during the booking."""

    starting_photo = forms.ImageField(
        label="Photo of the facility at the start",
        widget=forms.ClearableFileInput(
            attrs={"accept": "image/jpeg,image/png,image/webp"}
        ),
    )

    def clean_starting_photo(self):
        return validate_session_photo(self.cleaned_data["starting_photo"])


class RenterSessionPhotoForm(forms.Form):
    """Collect the renter-owned photo showing the facility at session end."""

    ending_photo = forms.ImageField(
        label="Photo of the facility at the end",
        widget=forms.ClearableFileInput(
            attrs={"accept": "image/jpeg,image/png,image/webp"}
        ),
    )

    def clean_ending_photo(self):
        return validate_session_photo(self.cleaned_data["ending_photo"])


def validate_session_photo(photo):
    """Limit uploaded session images to common web photo formats and 5 MB."""
    if photo.size > 5 * 1024 * 1024:
        raise forms.ValidationError("Each photo must be 5 MB or smaller.")
    if getattr(photo, "image", None) is None or photo.image.format not in {
        "JPEG",
        "PNG",
        "WEBP",
    }:
        raise forms.ValidationError("Upload a valid JPEG, PNG, or WebP image.")
    return photo
