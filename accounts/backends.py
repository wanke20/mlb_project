from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    """Authenticate using email (case-insensitive) instead of username.

    Users are created with ``username == email`` (see ``forms.SignupForm``),
    but we look up by the ``email`` field explicitly so logins keep working
    even if a username ever diverges from the email.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        email = (username or kwargs.get("email") or "").strip()
        if not email or password is None:
            return None
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # Run the default hasher once to mitigate timing-based user enumeration.
            User().set_password(password)
            return None
        except User.MultipleObjectsReturned:
            user = User.objects.filter(email__iexact=email).order_by("id").first()

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
