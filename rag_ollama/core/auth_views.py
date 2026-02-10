"""
Authentication views: registration, login, logout, email verification,
password reset, profile.
"""

import logging
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags

from .forms import LoginForm, ProfileForm, RegistrationForm
from .models import UserProfile

logger = logging.getLogger('core')


def register_view(request):
    """User self-registration with email verification."""
    if request.user.is_authenticated:
        return redirect('core:profile')

    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False  # Inactive until email confirmed
            user.save()

            # Create profile and generate verification token
            profile = UserProfile.objects.create(user=user)
            token = profile.generate_verification_token()

            # Send verification email
            _send_verification_email(request, user, token)

            return render(request, 'core/auth/register_done.html', {
                'email': user.email,
            })
    else:
        form = RegistrationForm()

    return render(request, 'core/auth/register.html', {'form': form})


def verify_email_view(request, token):
    """Verify email by token from the confirmation link."""
    try:
        profile = UserProfile.objects.get(email_verification_token=token)
    except UserProfile.DoesNotExist:
        return render(request, 'core/auth/verify_result.html', {
            'success': False,
            'error': 'Ссылка недействительна или уже была использована.',
        })

    if not profile.is_token_valid():
        return render(request, 'core/auth/verify_result.html', {
            'success': False,
            'error': 'Срок действия ссылки истёк (24 часа). Зарегистрируйтесь повторно.',
        })

    # Activate user
    profile.is_email_verified = True
    profile.email_verification_token = ''
    profile.save(update_fields=['is_email_verified', 'email_verification_token'])

    user = profile.user
    user.is_active = True
    user.save(update_fields=['is_active'])

    # Auto-login after verification
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')

    return render(request, 'core/auth/verify_result.html', {
        'success': True,
    })


def login_view(request):
    """User login."""
    if request.user.is_authenticated:
        return redirect('core:index')

    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            next_url = request.GET.get('next', 'core:index')
            # Only redirect to safe internal URLs
            if next_url.startswith('/'):
                return redirect(next_url)
            return redirect('core:index')
    else:
        form = LoginForm()

    return render(request, 'core/auth/login.html', {'form': form})


def logout_view(request):
    """User logout."""
    logout(request)
    return redirect('core:login')


@login_required
def profile_view(request):
    """User profile / personal account."""
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'update_profile':
            form = ProfileForm(request.POST, instance=user)
            if form.is_valid():
                old_email = user.email
                form.save()

                # If email changed, re-verify
                if user.email != old_email:
                    profile.is_email_verified = False
                    profile.save(update_fields=['is_email_verified'])
                    token = profile.generate_verification_token()
                    _send_verification_email(request, user, token)
                    messages.info(
                        request,
                        'Email изменён. Письмо с подтверждением отправлено на новый адрес.'
                    )
                else:
                    messages.success(request, 'Профиль обновлён.')
                return redirect('core:profile')
        elif action == 'generate_api_key':
            api_key = profile.generate_api_key()
            messages.success(
                request,
                f'Новый API ключ сгенерирован. Сохраните его: {api_key}'
            )
            return redirect('core:profile')
        elif action == 'resend_verification':
            if not profile.is_email_verified:
                token = profile.generate_verification_token()
                _send_verification_email(request, user, token)
                messages.info(request, 'Письмо с подтверждением отправлено повторно.')
            return redirect('core:profile')
    else:
        form = ProfileForm(instance=user)

    return render(request, 'core/auth/profile.html', {
        'form': form,
        'profile': profile,
    })


def resend_verification_view(request):
    """Resend verification email for users who didn't receive it."""
    if request.user.is_authenticated:
        return redirect('core:profile')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        if not email:
            return render(request, 'core/auth/resend_verification.html', {
                'error': 'Введите email.',
            })

        try:
            user = User.objects.get(email=email)
            profile, _ = UserProfile.objects.get_or_create(user=user)

            if user.is_active and profile.is_email_verified:
                # Already verified -- redirect to login
                return render(request, 'core/auth/resend_verification.html', {
                    'info': 'Этот email уже подтверждён. Войдите в систему.',
                })

            # Generate new token and send
            token = profile.generate_verification_token()
            _send_verification_email(request, user, token)
        except User.DoesNotExist:
            # Don't reveal whether the email exists
            pass

        # Always show success (to prevent enumeration)
        return render(request, 'core/auth/resend_verification_sent.html', {
            'email': email,
        })

    return render(request, 'core/auth/resend_verification.html')


def password_reset_request_view(request):
    """Step 1: User enters email to receive a password reset link."""
    if request.user.is_authenticated:
        return redirect('core:profile')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        if not email:
            return render(request, 'core/auth/password_reset.html', {
                'error': 'Введите ваш email.',
            })

        try:
            user = User.objects.get(email=email)
            profile, _ = UserProfile.objects.get_or_create(user=user)
            token = profile.generate_verification_token()
            _send_password_reset_email(request, user, token)
        except User.DoesNotExist:
            # Don't reveal whether the email exists
            pass

        # Always show success to prevent email enumeration
        return render(request, 'core/auth/password_reset_sent.html', {
            'email': email,
        })

    return render(request, 'core/auth/password_reset.html')


def password_reset_confirm_view(request, token):
    """Step 2: User clicks the link and sets a new password."""
    try:
        profile = UserProfile.objects.get(email_verification_token=token)
    except UserProfile.DoesNotExist:
        return render(request, 'core/auth/password_reset_confirm.html', {
            'invalid': True,
            'error': 'Ссылка недействительна или уже была использована.',
        })

    if not profile.is_token_valid():
        return render(request, 'core/auth/password_reset_confirm.html', {
            'invalid': True,
            'error': 'Срок действия ссылки истёк (24 часа). Запросите новую.',
        })

    if request.method == 'POST':
        password1 = request.POST.get('password1', '')
        password2 = request.POST.get('password2', '')

        if not password1 or len(password1) < 8:
            return render(request, 'core/auth/password_reset_confirm.html', {
                'error': 'Пароль должен быть не менее 8 символов.',
                'token': token,
            })

        if password1 != password2:
            return render(request, 'core/auth/password_reset_confirm.html', {
                'error': 'Пароли не совпадают.',
                'token': token,
            })

        user = profile.user
        user.set_password(password1)

        # Activate user if not yet active (proves email ownership)
        if not user.is_active:
            user.is_active = True
            logger.info(f"User {user.username} activated via password reset")
        user.save()

        # Mark email as verified and invalidate token
        profile.is_email_verified = True
        profile.email_verification_token = ''
        profile.save(update_fields=['is_email_verified', 'email_verification_token'])

        # Auto-login
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')

        return render(request, 'core/auth/password_reset_done.html')

    return render(request, 'core/auth/password_reset_confirm.html', {
        'token': token,
    })


def _send_password_reset_email(request, user, token):
    """Send password reset email via SMTP."""
    scheme = 'https' if request.is_secure() else 'http'
    host = request.get_host()
    reset_url = f"{scheme}://{host}/accounts/password-reset/confirm/{token}/"

    html_message = render_to_string('core/auth/email_password_reset.html', {
        'user': user,
        'reset_url': reset_url,
    })

    _send_email_with_retry(
        subject='ROoP - Сброс пароля',
        html_message=html_message,
        recipient=user.email,
    )


def _send_verification_email(request, user, token):
    """Send email verification letter via SMTP."""
    scheme = 'https' if request.is_secure() else 'http'
    host = request.get_host()
    verify_url = f"{scheme}://{host}/accounts/verify/{token}/"

    html_message = render_to_string('core/auth/email_verify.html', {
        'user': user,
        'verify_url': verify_url,
    })

    _send_email_with_retry(
        subject='ROoP - Подтверждение email',
        html_message=html_message,
        recipient=user.email,
    )


def _send_email_with_retry(subject, html_message, recipient, max_retries=3):
    """Send email with retry logic for transient SMTP errors."""
    plain_message = strip_tags(html_message)

    for attempt in range(1, max_retries + 1):
        try:
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                html_message=html_message,
                fail_silently=False,
            )
            logger.info(f"Email sent to {recipient} (attempt {attempt}): {subject}")
            return True
        except Exception as e:
            logger.warning(
                f"Email send attempt {attempt}/{max_retries} failed "
                f"to {recipient}: {type(e).__name__}: {e}"
            )
            if attempt < max_retries:
                time.sleep(2 * attempt)  # backoff: 2s, 4s

    logger.error(f"All {max_retries} attempts to send email to {recipient} failed: {subject}")
    return False
