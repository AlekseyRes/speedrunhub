"""Account views: registration plus Django's built-in auth flow."""

from django.contrib import messages
from django.db import IntegrityError
from django.shortcuts import redirect, render

from .forms import DUPLICATE_ACCOUNT_MESSAGE, RegistrationForm


def register(request):
    """Create a new account and send the user to the login page."""
    if request.user.is_authenticated:
        return redirect("core:home")

    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            try:
                form.save()
            except IntegrityError:
                # A concurrent request may have claimed the username between
                # validation and save. Keep the response generic.
                form.add_error(None, DUPLICATE_ACCOUNT_MESSAGE)
            else:
                messages.success(
                    request,
                    "Your account was created successfully. You can log in now.",
                )
                return redirect("accounts:login")
    else:
        form = RegistrationForm()

    return render(request, "accounts/register.html", {"form": form})
