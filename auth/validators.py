from django.core.validators import RegexValidator


INDIA_COUNTRY_CODE = "+91"

phone_number_validator = RegexValidator(
    regex=r"^\d{10}$",
    message="Phone number must contain exactly 10 digits.",
)

pincode_validator = RegexValidator(
    regex=r"^[1-9][0-9]{5}$",
    message="Pincode must be a valid 6-digit Indian postal code.",
)
