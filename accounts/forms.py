"""Registration form with case-insensitive, non-enumerating uniqueness checks."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

User = get_user_model()

DUPLICATE_ACCOUNT_MESSAGE = (
    "An account with that username or email already exists."
)


class RegistrationForm(UserCreationForm):
    """Extend the built-in form with a required, unique email address."""

    email = forms.EmailField(
        required=True,
        label="Email address",
        help_text="Required. Must be unique (case-insensitive).",
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "password1", "password2")

    def clean_username(self):
        return self.cleaned_data["username"].strip()

    def clean_email(self):
        return self.cleaned_data["email"].strip()

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get("username")
        email = cleaned_data.get("email")

        # One generic non-field message avoids revealing whether a username or
        # an email address is already registered. Password mismatch and weak
        # password errors stay attached to their fields.
        if username and User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(DUPLICATE_ACCOUNT_MESSAGE)
        if email and User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(DUPLICATE_ACCOUNT_MESSAGE)
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user
