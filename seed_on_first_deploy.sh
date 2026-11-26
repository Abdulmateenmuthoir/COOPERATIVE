#!/usr/bin/env bash
# Seed demo data only on first deployment.
# The 'acada' tenant check prevents re-seeding on subsequent deploys.

# 1. Run migrations (required on every start)
python manage.py migrate --noinput

# 2. Check whether the demo tenant already exists.
#    If it does, we skip seed_demo entirely so existing members/loans are never touched.
#    `manage.py shell` is required so Django settings are loaded (a bare
#    `python -c` has no DJANGO_SETTINGS_MODULE and crashes before querying).
#    Exit-code check avoids parsing shell banner output.
python manage.py shell -c "
from apps.core.models import Tenant
import sys
sys.exit(0 if Tenant.objects.filter(code='acada').exists() else 1)
"
HAS_TENANT=$?

if [ "$HAS_TENANT" != "0" ]; then
  # First-time deploy: seed the demo cooperative.
  python manage.py seed_demo || true
fi

# 3. Start the API server
exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:$PORT \
  --workers 3 \
  --timeout 60 \
  --access-logfile - \
  --error-logfile -