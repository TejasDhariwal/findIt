from pathlib import PurePath
from uuid import uuid4

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.conf import settings
from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from django.core.exceptions import ValidationError


def session_photo_upload_path(instance, filename):
    """Keep session photos grouped by booking and never retain user filenames."""
    photo_type = "end" if instance.ending_photo else "start"
    extension = PurePath(filename).suffix.lower()
    if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        extension = ".jpg"
    return f"session-records/{instance.rental_request_id}/{photo_type}/{uuid4().hex}{extension}"


class AccountManager(BaseUserManager):
    """Create accounts with Django's secure password hashing."""

    use_in_migrations = True

    def create_user(self, email, name, mobile_no, user_type, password=None):
        if not email:
            raise ValueError("An email address is required.")

        account = self.model(
            email=self.normalize_email(email),
            name=name,
            mobile_no=mobile_no,
            user_type=user_type,
        )
        account.set_password(password)
        account.save(using=self._db)
        return account

    def create_superuser(self, email, name, mobile_no, user_type, password=None):
        account = self.create_user(email, name, mobile_no, user_type, password)
        account.is_staff = True
        account.is_superuser = True
        account.save(using=self._db)
        return account


class Account(AbstractBaseUser, PermissionsMixin):
    """Login details shared by renters and sports-facility providers."""

    class UserType(models.TextChoices):
        USER = "user", "User"
        PROVIDER = "provider", "Provider"

    user_type = models.CharField(max_length=8, choices=UserType.choices)
    name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    mobile_no = models.CharField(max_length=20)
    city = models.CharField(max_length=100, blank=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    objects = AccountManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name", "mobile_no", "user_type"]

    def __str__(self):
        return self.email


class Facility(models.Model):
    """A sports facility or equipment item listed by a provider."""

    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="facilities",
        limit_choices_to={"user_type": Account.UserType.PROVIDER},
    )
    facility_name = models.CharField(max_length=150)
    institution_name = models.CharField(max_length=200)
    institution_location = models.CharField(max_length=255)
    institution_state = models.CharField(max_length=100)
    price_per_hour = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    contact_no = models.CharField(max_length=20)
    contact_person_name = models.CharField(max_length=150)
    latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )

    def __str__(self):
        return f"{self.facility_name} - {self.institution_name}"


class FacilityAvailability(models.Model):
    """Weekly opening hours for a facility; weekday values are Sunday-first."""

    class DayOfWeek(models.IntegerChoices):
        SUNDAY = 0, "Sunday"
        MONDAY = 1, "Monday"
        TUESDAY = 2, "Tuesday"
        WEDNESDAY = 3, "Wednesday"
        THURSDAY = 4, "Thursday"
        FRIDAY = 5, "Friday"
        SATURDAY = 6, "Saturday"

    facility = models.ForeignKey(
        Facility,
        on_delete=models.CASCADE,
        related_name="weekly_availability",
    )
    day_of_week = models.PositiveSmallIntegerField(choices=DayOfWeek.choices)
    opens_at = models.TimeField(null=True, blank=True)
    closes_at = models.TimeField(null=True, blank=True)
    is_closed = models.BooleanField(default=False)

    class Meta:
        ordering = ("day_of_week",)
        constraints = [
            models.UniqueConstraint(
                fields=("facility", "day_of_week"),
                name="unique_facility_availability_day",
            ),
        ]

    def __str__(self):
        if self.is_closed:
            return f"{self.get_day_of_week_display()}: closed"
        return f"{self.get_day_of_week_display()}: {self.opens_at}–{self.closes_at}"


class RentalRequest(models.Model):
    """A renter's one-hour request for a facility slot."""

    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting provider"
        APPROVED = "approved", "Booked"
        REJECTED = "rejected", "Declined"

    facility = models.ForeignKey(
        Facility,
        on_delete=models.CASCADE,
        related_name="rental_requests",
    )
    renter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="rental_requests",
    )
    requested_date = models.DateField()
    starts_at = models.TimeField()
    ends_at = models.TimeField()
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("requested_date", "starts_at")
        indexes = [
            models.Index(
                fields=("facility", "requested_date", "status"),
                name="rental_facility_date_status",
            ),
        ]

    def __str__(self):
        return (
            f"{self.facility.facility_name} on {self.requested_date} "
            f"at {self.starts_at}"
        )


class SessionRecord(models.Model):
    """Provider-owned session details and start photo with a renter end photo."""

    rental_request = models.OneToOneField(
        RentalRequest,
        on_delete=models.CASCADE,
        related_name="session_record",
    )
    starting_photo = models.ImageField(upload_to=session_photo_upload_path)
    ending_photo = models.ImageField(
        upload_to=session_photo_upload_path,
        blank=True,
    )
    damage_reported = models.BooleanField(null=True, blank=True)
    damage_description = models.TextField(blank=True)
    damage_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    payment_received = models.BooleanField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-finalized_at",)

    def save(self, *args, **kwargs):
        """Prevent either participant from changing a finalized session record."""
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            if previous.finalized_at:
                changed_fields = [
                    field.name
                    for field in self._meta.concrete_fields
                    if getattr(previous, field.attname) != getattr(self, field.attname)
                ]
                if changed_fields:
                    raise ValidationError(
                        "A finalized session record cannot be changed."
                    )
        if self.finalized_at and (
            not self.starting_photo
            or not self.ending_photo
            or self.damage_reported is None
            or self.payment_received is None
        ):
            raise ValidationError(
                "A finalized session record requires all provider details and both photos."
            )
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Session record for {self.rental_request}"
