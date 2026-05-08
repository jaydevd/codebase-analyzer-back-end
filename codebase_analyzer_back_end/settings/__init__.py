import os
from importlib import import_module

from django.core.exceptions import ImproperlyConfigured


ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()

SETTINGS_MODULES = {
    "development": "codebase_analyzer_back_end.settings.development",
    "staging": "codebase_analyzer_back_end.settings.staging",
    "production": "codebase_analyzer_back_end.settings.production",
}

try:
    settings_module = SETTINGS_MODULES[ENVIRONMENT]
except KeyError as exc:
    supported_environments = ", ".join(sorted(SETTINGS_MODULES))
    raise ImproperlyConfigured(
        f"Unsupported ENVIRONMENT '{ENVIRONMENT}'. Expected one of: {supported_environments}."
    ) from exc

module = import_module(settings_module)

for attribute in dir(module):
    if attribute.isupper():
        globals()[attribute] = getattr(module, attribute)
