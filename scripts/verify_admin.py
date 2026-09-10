"""Check that all Phase 3 models are registered in the Django admin."""

from django.apps import apps
from django.contrib import admin

TARGET_APPS = ["career_intel", "recruiters", "referrals"]

missing = []

for app_label in TARGET_APPS:
    try:
        app_config = apps.get_app_config(app_label)
    except LookupError:
        print(f"App not found: {app_label}")
        continue

    print(f"\n=== {app_label} ===")
    for model in app_config.get_models():
        is_registered = model in admin.site._registry
        print(f"  [{'OK     ' if is_registered else 'MISSING'}] {model.__name__}")
        if not is_registered:
            missing.append(f"{app_label}.{model.__name__}")

print("\n" + "-" * 50)
print(f"Unregistered models: {len(missing)}")
for name in missing:
    print(f"  - {name}")
