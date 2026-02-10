"""
Data migration: assign existing documents and chat messages
to the first admin (superuser), and mark existing documents as shared.
"""

from django.db import migrations


def assign_to_admin(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Document = apps.get_model('core', 'Document')
    ChatMessage = apps.get_model('core', 'ChatMessage')

    # Find first superuser (admin)
    admin = User.objects.filter(is_superuser=True).first()
    if not admin:
        admin = User.objects.first()
    if not admin:
        return  # No users at all -- nothing to migrate

    # Assign orphan documents to admin and mark as shared
    Document.objects.filter(user__isnull=True).update(
        user=admin,
        is_shared=True,
    )

    # Assign orphan chat messages to admin
    ChatMessage.objects.filter(user__isnull=True).update(user=admin)


def reverse(apps, schema_editor):
    # No reverse needed -- data was already unowned
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_user_isolation_and_sharing'),
    ]

    operations = [
        migrations.RunPython(assign_to_admin, reverse),
    ]
