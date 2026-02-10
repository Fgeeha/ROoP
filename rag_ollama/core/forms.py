"""
Django forms for user authentication and profile management.
"""

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User


class RegistrationForm(UserCreationForm):
    """User registration form with email (required)."""

    email = forms.EmailField(
        required=True,
        label='Email',
        widget=forms.EmailInput(attrs={
            'class': 'form-input',
            'placeholder': 'your@email.com',
            'autocomplete': 'email',
        }),
    )
    username = forms.CharField(
        label='Имя пользователя',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'Имя пользователя',
            'autocomplete': 'username',
        }),
    )
    password1 = forms.CharField(
        label='Пароль',
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Пароль',
            'autocomplete': 'new-password',
        }),
    )
    password2 = forms.CharField(
        label='Подтверждение пароля',
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Повторите пароль',
            'autocomplete': 'new-password',
        }),
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('Пользователь с таким email уже зарегистрирован.')
        return email


class LoginForm(AuthenticationForm):
    """Styled login form."""

    error_messages = {
        'invalid_login': 'Неверное имя пользователя или пароль.',
        'inactive': 'Этот аккаунт неактивен. Проверьте почту для подтверждения.',
    }

    username = forms.CharField(
        label='Имя пользователя',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'Имя пользователя',
            'autocomplete': 'username',
        }),
    )
    password = forms.CharField(
        label='Пароль',
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Пароль',
            'autocomplete': 'current-password',
        }),
    )


class ProfileForm(forms.ModelForm):
    """User profile edit form."""

    first_name = forms.CharField(
        required=False,
        label='Имя',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'Иван',
        }),
    )
    last_name = forms.CharField(
        required=False,
        label='Фамилия',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'Иванов',
        }),
    )
    email = forms.EmailField(
        required=True,
        label='Email',
        widget=forms.EmailInput(attrs={
            'class': 'form-input',
        }),
    )

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email')

    def clean_email(self):
        email = self.cleaned_data.get('email')
        qs = User.objects.filter(email=email).exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('Этот email уже используется другим пользователем.')
        return email
