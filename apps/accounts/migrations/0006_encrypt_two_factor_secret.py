"""
Encrypt 2FA secrets at rest.

Existing rows are encrypted with raw SQL rather than through the model, so the
conversion does not depend on how any field class reads or writes. Reversible:
rolling back decrypts and restores the original 32-character column.
"""

from django.db import migrations

import apps.accounts.fields


def _table_and_pk(apps, schema_editor):
    model = apps.get_model("accounts", "TwoFactorAuth")
    quote = schema_editor.connection.ops.quote_name
    return quote(model._meta.db_table), quote(model._meta.pk.column)


def encrypt_existing_secrets(apps, schema_editor):
    from apps.accounts.fields import encrypt_str, looks_encrypted

    table, pk = _table_and_pk(apps, schema_editor)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"SELECT {pk}, secret FROM {table}")
        for row_id, secret in cursor.fetchall():
            if secret and not looks_encrypted(secret):
                cursor.execute(
                    f"UPDATE {table} SET secret = %s WHERE {pk} = %s",
                    [encrypt_str(secret), row_id],
                )


def decrypt_existing_secrets(apps, schema_editor):
    from apps.accounts.fields import decrypt_str, looks_encrypted

    table, pk = _table_and_pk(apps, schema_editor)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"SELECT {pk}, secret FROM {table}")
        for row_id, secret in cursor.fetchall():
            if looks_encrypted(secret):
                cursor.execute(
                    f"UPDATE {table} SET secret = %s WHERE {pk} = %s",
                    [decrypt_str(secret), row_id],
                )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_user_deactivation_reason"),
    ]

    operations = [
        migrations.AlterField(
            model_name="twofactorauth",
            name="secret",
            field=apps.accounts.fields.EncryptedTextField(),
        ),
        migrations.RunPython(encrypt_existing_secrets, decrypt_existing_secrets),
    ]
