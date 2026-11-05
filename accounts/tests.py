"""Tests for registration and authentication flows."""

from unittest.mock import patch
from urllib.parse import urlparse

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

User = get_user_model()

VALID_PASSWORD = "Str0ngPass!2026"
DUPLICATE_MESSAGE = "An account with that username or email already exists."


class RegistrationTests(TestCase):
    def setUp(self):
        self.url = reverse("accounts:register")

    def test_registration_success_redirects_to_login_and_creates_user(self):
        response = self.client.post(
            self.url,
            {
                "username": "newrunner",
                "email": "newrunner@example.com",
                "password1": VALID_PASSWORD,
                "password2": VALID_PASSWORD,
            },
        )

        self.assertRedirects(response, reverse("accounts:login"))
        user = User.objects.get(username="newrunner")
        self.assertEqual(user.email, "newrunner@example.com")

    def test_registration_success_shows_message_after_redirect(self):
        response = self.client.post(
            self.url,
            {
                "username": "newrunner",
                "email": "newrunner@example.com",
                "password1": VALID_PASSWORD,
                "password2": VALID_PASSWORD,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "account was created successfully")

    def test_duplicate_username_is_rejected_case_insensitively(self):
        User.objects.create_user(
            username="Runner",
            email="runner@example.com",
            password=VALID_PASSWORD,
        )

        response = self.client.post(
            self.url,
            {
                "username": "runner",
                "email": "another@example.com",
                "password1": VALID_PASSWORD,
                "password2": VALID_PASSWORD,
            },
        )

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertIn(DUPLICATE_MESSAGE, form.non_field_errors())
        self.assertNotIn("username", form.errors)
        self.assertEqual(User.objects.count(), 1)

    def test_duplicate_email_is_rejected_case_insensitively(self):
        User.objects.create_user(
            username="runner",
            email="Runner@Example.com",
            password=VALID_PASSWORD,
        )

        response = self.client.post(
            self.url,
            {
                "username": "anotherrunner",
                "email": "runner@example.com",
                "password1": VALID_PASSWORD,
                "password2": VALID_PASSWORD,
            },
        )

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertIn(DUPLICATE_MESSAGE, form.non_field_errors())
        self.assertNotIn("email", form.errors)
        self.assertEqual(User.objects.count(), 1)

    def test_password_mismatch_is_rejected(self):
        response = self.client.post(
            self.url,
            {
                "username": "newrunner",
                "email": "newrunner@example.com",
                "password1": VALID_PASSWORD,
                "password2": "DifferentPass!2026",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("password2", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="newrunner").exists())

    def test_weak_password_is_rejected_by_validators(self):
        response = self.client.post(
            self.url,
            {
                "username": "newrunner",
                "email": "newrunner@example.com",
                "password1": "91827364550",
                "password2": "91827364550",
            },
        )

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertIn("password2", form.errors)
        self.assertIn("entirely numeric", form.errors["password2"][0].lower())
        self.assertFalse(User.objects.filter(username="newrunner").exists())

    def test_invalid_email_is_rejected(self):
        response = self.client.post(
            self.url,
            {
                "username": "newrunner",
                "email": "not-an-email",
                "password1": VALID_PASSWORD,
                "password2": VALID_PASSWORD,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="newrunner").exists())

    @patch("core.views.get_client")
    def test_authenticated_user_is_redirected_home(self, mock_get_client):
        mock_get_client.return_value.get_games.return_value = {
            "ok": True,
            "data": [],
            "error": None,
            "total": 0,
        }
        User.objects.create_user(
            username="runner",
            email="runner@example.com",
            password=VALID_PASSWORD,
        )
        self.client.login(username="runner", password=VALID_PASSWORD)

        response = self.client.get(self.url)

        self.assertRedirects(response, reverse("core:home"))


class RegistrationCsrfTests(TestCase):
    def test_registration_post_without_csrf_token_is_forbidden(self):
        client = Client(enforce_csrf_checks=True)

        response = client.post(
            reverse("accounts:register"),
            {
                "username": "newrunner",
                "email": "newrunner@example.com",
                "password1": VALID_PASSWORD,
                "password2": VALID_PASSWORD,
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="newrunner").exists())


class AuthenticationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="runner",
            email="runner@example.com",
            password=VALID_PASSWORD,
        )

    def test_login_page_renders(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Log in to your hub")

    @patch("core.views.get_client")
    def test_login_success_redirects_home(self, mock_get_client):
        mock_get_client.return_value.get_games.return_value = {
            "ok": True,
            "data": [],
            "error": None,
            "total": 0,
        }
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "runner", "password": VALID_PASSWORD},
        )
        self.assertRedirects(response, reverse("core:home"))

    def test_external_next_is_ignored_after_login(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "runner",
                "password": VALID_PASSWORD,
                "next": "https://evil.example/phish",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("core:home"))
        self.assertEqual(urlparse(response.url).netloc, "")

    def test_safe_internal_next_is_honoured_after_login(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "runner",
                "password": VALID_PASSWORD,
                "next": reverse("core:explorer"),
            },
        )

        self.assertRedirects(
            response, reverse("core:explorer"), fetch_redirect_response=False
        )

    @patch("core.views.get_client")
    def test_logout_requires_post_and_redirects_home(self, mock_get_client):
        mock_get_client.return_value.get_games.return_value = {
            "ok": True,
            "data": [],
            "error": None,
            "total": 0,
        }
        self.client.login(username="runner", password=VALID_PASSWORD)

        response = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(response, reverse("core:home"))
        self.assertNotIn("_auth_user_id", self.client.session)
