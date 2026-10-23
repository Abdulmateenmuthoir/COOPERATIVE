#!/usr/bin/env bash
# Seed demo data only on first deployment.
# The 'acada' tenant check prevents re-seeding on subsequent deploys.

# 1. Run migrations (required on every start)
python manage.py migrate --noinput

# 2. Check whether the demo tenant already exists.
#    If it does, we skip seed_demo entirely so existing members/loans are never touched.
HAS_TENANT=$(python -c "
from apps.core.models import Tenant
print('1' if Tenant.objects.filter(code='acada').exists() else '0')
")

if [ "$HAS_TENANT" != "1" ]; then
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