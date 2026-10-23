"""
Custom filter backends for the users app.
"""
import operator
from functools import reduce

from django.db.models import Exists, OuterRef, Q
from rest_framework.filters import SearchFilter


class MemberSearchFilter(SearchFilter):
    """
    Search members by name, email *or* the tenant-scoped institutional
    identifiers (employee number, payroll number).

    DRF's SearchFilter expresses a single lookup path per search field, so it
    cannot say "the employee number, but only within my own society" — the
    identifier has to be matched on the same profile row as the tenant.
    This subclass therefore builds the OR group itself and resolves the
    identifiers through a subquery pinned to `request.tenant`.

    A member who belongs to more than one society may hold a different
    employee number in each; the subquery makes sure a number issued by
    another society can never match here.
    """

    def filter_queryset(self, request, queryset, view):
        search_fields = self.get_search_fields(view, request)
        search_terms = self.get_search_terms(request)

        if not search_fields or not search_terms:
            return queryset

        tenant = getattr(request, "tenant", None)

        conditions = []
        for term in search_terms:
            term_query = Q()

            for field in search_fields:
                lookup = self.construct_search(str(field), queryset)
                term_query = term_query | Q(**{lookup: term})

            identifier_match = self._identifier_match(tenant, term)
            if identifier_match is not None:
                term_query = term_query | Q(identifier_match)

            conditions.append(term_query)

        return queryset.filter(reduce(operator.and_, conditions)).distinct()

    def _identifier_match(self, tenant, term):
        """
        A subquery that matches the term against the member profile of the
        current tenant — or None when there is no tenant to scope to.
        """
        if tenant is None:
            return None

        from apps.users.models import MemberProfile

        return Exists(
            MemberProfile.objects.filter(
                user=OuterRef("user"),
                tenant=tenant,
            ).filter(
                Q(employee_no__icontains=term) | Q(payroll_no__icontains=term)
            )
        )
