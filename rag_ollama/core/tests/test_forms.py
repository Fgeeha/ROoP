"""Tests for core forms."""

import pytest
from django.contrib.auth.models import User

from core.forms import ProfileForm, RegistrationForm


@pytest.fixture
def user(db):
    return User.objects.create_user(username='existing', email='existing@example.com', password='testpass123')


class TestRegistrationForm:
    def test_valid_form(self, db):
        data = {
            'username': 'newuser',
            'email': 'new@example.com',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        }
        form = RegistrationForm(data=data)
        assert form.is_valid(), form.errors

    def test_duplicate_email(self, user):
        data = {
            'username': 'another',
            'email': 'existing@example.com',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        }
        form = RegistrationForm(data=data)
        assert not form.is_valid()
        assert 'email' in form.errors

    def test_password_mismatch(self, db):
        data = {
            'username': 'newuser',
            'email': 'new@example.com',
            'password1': 'StrongPass123!',
            'password2': 'DifferentPass123!',
        }
        form = RegistrationForm(data=data)
        assert not form.is_valid()

    def test_missing_email(self, db):
        data = {
            'username': 'newuser',
            'email': '',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        }
        form = RegistrationForm(data=data)
        assert not form.is_valid()
        assert 'email' in form.errors


class TestProfileForm:
    def test_valid_profile_update(self, user):
        data = {
            'first_name': 'Ivan',
            'last_name': 'Ivanov',
            'email': 'existing@example.com',
        }
        form = ProfileForm(data=data, instance=user)
        assert form.is_valid(), form.errors

    def test_change_email(self, user):
        data = {
            'first_name': 'Ivan',
            'last_name': 'Ivanov',
            'email': 'newemail@example.com',
        }
        form = ProfileForm(data=data, instance=user)
        assert form.is_valid()

    def test_duplicate_email_rejected(self, user):
        User.objects.create_user(username='other', email='taken@example.com', password='pass123')
        data = {
            'first_name': 'Ivan',
            'last_name': 'Ivanov',
            'email': 'taken@example.com',
        }
        form = ProfileForm(data=data, instance=user)
        assert not form.is_valid()
        assert 'email' in form.errors

    def test_empty_first_last_name_ok(self, user):
        data = {
            'first_name': '',
            'last_name': '',
            'email': 'existing@example.com',
        }
        form = ProfileForm(data=data, instance=user)
        assert form.is_valid()
